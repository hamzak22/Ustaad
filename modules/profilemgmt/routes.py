from fastapi import APIRouter, Depends, HTTPException, status
import psycopg
import jwt
from typing import Annotated

from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from modules.auth.token_generator import SECRET_KEY, ALGORITHM
from database import get_db_connection
from modules.notifications.models import NotificationCreate
from modules.notifications.service import persist_notification, broadcast_notification

from modules.profilemgmt.models import (
    UpdateWorkerProfileRequest, 
    UserProfileResponse,
    WorkerSearchRequest,
    WorkerSearchResponse,
    WorkerSearchResultItem,
    WorkerDetailedProfile,
    WorkerSkillInfo,
    WorkerReviewItem
)

router = APIRouter(tags=["Profile Management"])
oauth2_scheme = OAuth2PasswordBearer("/auth/token")

# --- AUTH HELPER FUNCTION ---
def get_current_user_id(token: Annotated[str, Depends(oauth2_scheme)]) -> str:
    """Decodes the JWT token and extracts the 'sub' (user_id)."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id_str = payload.get("sub")
        if not user_id_str:
            raise HTTPException(status_code=401, detail="Invalid token: missing subject")
        return user_id_str
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


@router.get("/users/me", response_model=UserProfileResponse)
async def get_my_profile(
    user_id: str = Depends(get_current_user_id),
    conn: psycopg.AsyncConnection = Depends(get_db_connection)
):
    async with conn.cursor() as cur:
        # 1. Fetch base user info & worker bio using a LEFT JOIN
        await cur.execute("""
            SELECT u.user_id, u.full_name, u.email, u.phone_number, u.role, u.is_active, wp.bio, wp.average_rating, wp.total_reviews
            FROM Users u
            LEFT JOIN worker_profile wp ON u.user_id = wp.worker_id
            WHERE u.user_id = %s
        """, (user_id,))
        
        user_row = await cur.fetchone()
        if not user_row:
            raise HTTPException(status_code=404, detail="User not found")
            
        # Check if active
        if not user_row["is_active"]:
            raise HTTPException(status_code=403, detail="Account is deactivated")

        # 2. Fetch worker skills (if they are a worker)
        skills_list = []
        if user_row["role"] == 'Worker':
            await cur.execute("""
                SELECT s.service_id, s.service_name, ws.hourly_rate
                FROM worker_skills ws
                JOIN Services s ON ws.service_id = s.service_id
                WHERE ws.worker_id = %s
            """, (user_id,))
            
            skills_rows = await cur.fetchall()
            for skill in skills_rows:
                skills_list.append({
                    "service_id": skill["service_id"],
                    "service_name": skill["service_name"],
                    "hourly_rate": skill["hourly_rate"]
                })

        # 3. Assemble and return the data
        return {
            "user_id": user_row["user_id"],
            "full_name": user_row["full_name"],
            "email": user_row["email"],
            "phone_number": user_row["phone_number"],
            "role": user_row["role"],
            "bio": user_row["bio"],
            "total_reviews" : user_row["total_reviews"],
            "avg_rating" : user_row["average_rating"],
            "skills": skills_list
        }


@router.put("/workers/me")
async def update_worker_profile(
    update_data: UpdateWorkerProfileRequest,
    user_id: str = Depends(get_current_user_id),
    conn: psycopg.AsyncConnection = Depends(get_db_connection)
):
    async with conn.cursor() as cur:
        # 1. Verify user is actually a Worker and is active
        await cur.execute("SELECT role, is_active FROM Users WHERE user_id = %s", (user_id,))
        user_status = await cur.fetchone()
        
        if not user_status:
            raise HTTPException(status_code=404, detail="User not found")
        if not user_status["is_active"]:
            raise HTTPException(status_code=403, detail="Account is deactivated")
        if user_status["role"] != 'Worker':
            raise HTTPException(status_code=403, detail="Only workers can update this profile")

    # 2. Begin Transaction for Updates
    try:
        async with conn.transaction():
            notification = None
            async with conn.cursor() as cur:
                
                # Update Phone Number in Users table
                if update_data.phone_number is not None:
                    await cur.execute(
                        "UPDATE Users SET phone_number = %s WHERE user_id = %s",
                        (update_data.phone_number, user_id)
                    )

                # Update Bio in worker_profile table
                if update_data.bio is not None:
                    await cur.execute("""
                        UPDATE worker_profile 
                        SET bio = %s 
                        WHERE worker_id = %s
                    """, (update_data.bio, user_id))

                # Update Skills/Rates (Merge Strategy)
                if update_data.services is not None:
                    for service in update_data.services:
                        if service.hourly_rate <= 0:
                            raise HTTPException(status_code=400, detail="Hourly rate must be > 0")
                            
                        # UPSERT for worker_skills
                        await cur.execute("""
                            INSERT INTO worker_skills (worker_id, service_id, hourly_rate)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (worker_id, service_id)
                            DO UPDATE SET hourly_rate = EXCLUDED.hourly_rate
                        """, (user_id, str(service.service_id), service.hourly_rate))

                notification = await persist_notification(
                    conn,
                    NotificationCreate(
                        recipient_id=user_id,
                        actor_id=user_id,
                        notification_type="profile_updated",
                        title="Worker profile updated",
                        body="Your worker profile details were updated successfully.",
                        entity_type="worker_profile",
                        entity_id=None,
                        metadata={
                            "bio_updated": update_data.bio is not None,
                            "phone_updated": update_data.phone_number is not None,
                            "services_updated": update_data.services is not None,
                        },
                    ),
                )

        if notification:
            await broadcast_notification(notification)

        return {"message": "Worker profile updated successfully!"}
        
    except psycopg.errors.UniqueViolation:
        raise HTTPException(status_code=400, detail="That phone number is already in use.")
    except psycopg.errors.ForeignKeyViolation:
        raise HTTPException(status_code=400, detail="One of the provided service IDs does not exist.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


# ============================================================================
# WORKER SEARCH ENDPOINTS (For Customers) - CLEAN IMPLEMENTATION
# ============================================================================

@router.post("/workers/search", response_model=WorkerSearchResponse)
async def search_workers(
    search_params: WorkerSearchRequest,
    conn: psycopg.AsyncConnection = Depends(get_db_connection)
):
    """
    Search for available workers with optional filters.
    Returns one worker profile per worker with aggregated skills in a list.
    """
    async with conn.cursor() as cur:
        try:
            # Build params list in the order they appear in the query
            params = []
            
            # Relevance params come FIRST (they appear in SELECT clause)
            if search_params.search_query:
                params.extend([
                    search_params.search_query,
                    search_params.search_query,
                    search_params.search_query
                ])
            
            # Build WHERE conditions
            conditions = ["u.is_active = true"]
            
            # Text search
            if search_params.search_query:
                pattern = f"%{search_params.search_query}%"
                conditions.append("(LOWER(u.full_name) ILIKE %s OR LOWER(wp.bio) ILIKE %s)")
                params.extend([pattern, pattern])
            
            # Service filter
            if search_params.service_id:
                conditions.append("ws.service_id = %s::uuid")
                params.append(search_params.service_id)
            
            # City filter
            if search_params.city:
                conditions.append("u.city = %s")
                params.append(search_params.city)
            
            # Availability filter
            if search_params.availability:
                conditions.append("wp.availability::text = %s")
                params.append(search_params.availability)
            
            # Rating filter (always included)
            conditions.append("wp.average_rating >= %s")
            params.append(search_params.min_rating or 0.0)
            
            where_clause = " AND ".join(conditions)
            
            # Build relevance score clause if doing text search
            relevance_clause = ""
            if search_params.search_query:
                relevance_clause = """,
                    CASE 
                        WHEN LOWER(u.full_name) = LOWER(%s) THEN 3
                        WHEN LOWER(u.full_name) LIKE LOWER(%s || '%%') THEN 2
                        WHEN LOWER(u.full_name) ILIKE %s THEN 1
                        ELSE 0
                    END AS relevance_score"""
            
            # Add pagination (at the end)
            params.extend([search_params.limit, search_params.offset])
            
            # Build query with optional relevance score
            order_by = "relevance_score DESC, wp.average_rating DESC" if search_params.search_query else "wp.average_rating DESC"
            
            query = f"""
                SELECT 
                    u.user_id,
                    u.full_name,
                    u.email,
                    u.phone_number,
                    u.city,
                    wp.worker_id,
                    wp.experience,
                    wp.availability,
                    wp.bio,
                    wp.average_rating,
                    (SELECT COALESCE(COUNT(*), 0) FROM reviews WHERE worker_id = wp.worker_id) AS total_reviews,
                    COALESCE(
                        json_agg(
                            json_build_object(
                                'service_id', ws.service_id,
                                'service_name', s.service_name,
                                'hourly_rate', ws.hourly_rate
                            ) ORDER BY s.service_name
                        ) FILTER (WHERE ws.service_id IS NOT NULL),
                        '[]'::json
                    ) AS skills
                    {relevance_clause}
                FROM users u
                JOIN worker_profile wp ON u.user_id = wp.worker_id
                LEFT JOIN worker_skills ws ON wp.worker_id = ws.worker_id
                LEFT JOIN services s ON ws.service_id = s.service_id
                WHERE {where_clause}
                GROUP BY u.user_id, u.full_name, u.email, u.phone_number, u.city,
                         wp.worker_id, wp.experience, wp.availability, wp.bio, wp.average_rating
                ORDER BY {order_by}
                LIMIT %s OFFSET %s
            """
            
            await cur.execute(query, params)
            rows = await cur.fetchall()
            
            workers = []
            for row in rows:
                # Parse aggregated skills from JSON array
                skills_json = row["skills"] or []
                skills = [
                    WorkerSkillInfo(
                        service_id=skill["service_id"],
                        service_name=skill["service_name"],
                        hourly_rate=float(skill["hourly_rate"])
                    )
                    for skill in skills_json
                ]
                
                workers.append(WorkerSearchResultItem(
                    user_id=row["user_id"],
                    full_name=row["full_name"],
                    email=row["email"],
                    phone_number=row["phone_number"],
                    city=row["city"],
                    worker_id=row["worker_id"],
                    experience=row["experience"],
                    availability=row["availability"],
                    bio=row["bio"],
                    average_rating=float(row["average_rating"]),
                    total_reviews=row["total_reviews"],
                    skills=skills
                ))
            
            return WorkerSearchResponse(
                limit=search_params.limit,
                offset=search_params.offset,
                workers=workers
            )
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Search error: {str(e)}")


@router.get("/workers/{worker_id}", response_model=WorkerDetailedProfile)
async def get_worker_detail(
    worker_id: str,
    conn: psycopg.AsyncConnection = Depends(get_db_connection)
):
    """Get complete profile for a specific worker including skills and recent reviews."""
    async with conn.cursor() as cur:
        try:
            # Get worker profile with aggregated skills
            await cur.execute("""
                SELECT 
                    u.user_id,
                    u.full_name,
                    u.email,
                    u.phone_number,
                    u.city,
                    u.created_at,
                    wp.worker_id,
                    wp.experience,
                    wp.availability,
                    wp.bio,
                    wp.average_rating,
                    (SELECT COALESCE(COUNT(*), 0) FROM reviews WHERE worker_id = wp.worker_id) AS total_reviews,
                    COALESCE(
                        json_agg(
                            json_build_object(
                                'service_id', ws.service_id,
                                'service_name', s.service_name,
                                'hourly_rate', ws.hourly_rate
                            ) ORDER BY s.service_name
                        ) FILTER (WHERE ws.service_id IS NOT NULL),
                        '[]'::json
                    ) AS skills
                FROM users u
                JOIN worker_profile wp ON u.user_id = wp.worker_id
                LEFT JOIN worker_skills ws ON wp.worker_id = ws.worker_id
                LEFT JOIN services s ON ws.service_id = s.service_id
                WHERE wp.worker_id = %s::uuid AND u.is_active = true
                GROUP BY u.user_id, u.full_name, u.email, u.phone_number, u.city, u.created_at,
                         wp.worker_id, wp.experience, wp.availability, wp.bio, wp.average_rating
            """, (worker_id,))
            
            profile_row = await cur.fetchone()
            if not profile_row:
                raise HTTPException(status_code=404, detail="Worker not found")
            
            # Get recent reviews
            await cur.execute("""
                SELECT 
                    r.review_id,
                    r.rating,
                    r.comment,
                    r.created_at,
                    u.full_name AS customer_name,
                    j.title AS job_title
                FROM reviews r
                JOIN jobs j ON r.job_id = j.job_id
                JOIN users u ON r.customer_id = u.user_id
                WHERE r.worker_id = %s::uuid
                ORDER BY r.created_at DESC
                LIMIT 10
            """, (worker_id,))
            
            review_rows = await cur.fetchall()
            reviews = [
                WorkerReviewItem(
                    review_id=row["review_id"],
                    rating=row["rating"],
                    comment=row["comment"],
                    created_at=str(row["created_at"]),
                    customer_name=row["customer_name"],
                    job_title=row["job_title"]
                )
                for row in review_rows
            ]
            
            # Parse skills
            skills_json = profile_row["skills"] or []
            skills = [
                WorkerSkillInfo(
                    service_id=skill["service_id"],
                    service_name=skill["service_name"],
                    hourly_rate=float(skill["hourly_rate"])
                )
                for skill in skills_json
            ]
            
            return WorkerDetailedProfile(
                user_id=profile_row["user_id"],
                full_name=profile_row["full_name"],
                email=profile_row["email"],
                phone_number=profile_row["phone_number"],
                city=profile_row["city"],
                created_at=str(profile_row["created_at"]),
                worker_id=profile_row["worker_id"],
                experience=profile_row["experience"],
                availability=profile_row["availability"],
                bio=profile_row["bio"],
                average_rating=float(profile_row["average_rating"]),
                total_reviews=profile_row["total_reviews"],
                skills=skills,
                recent_reviews=reviews
            )
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Profile error: {str(e)}")


@router.get("/workers/{worker_id}/reviews")
async def get_worker_reviews(
    worker_id: str,
    limit: int = 20,
    offset: int = 0,
    conn: psycopg.AsyncConnection = Depends(get_db_connection)
):
    """Get paginated reviews for a specific worker."""
    async with conn.cursor() as cur:
        try:
            # Validate parameters
            if limit < 1 or limit > 100:
                raise HTTPException(status_code=400, detail="Limit must be between 1 and 100")
            if offset < 0:
                raise HTTPException(status_code=400, detail="Offset must be >= 0")
            
            # Verify worker exists
            await cur.execute(
                "SELECT worker_id FROM worker_profile WHERE worker_id = %s::uuid",
                (worker_id,)
            )
            if not await cur.fetchone():
                raise HTTPException(status_code=404, detail="Worker not found")
            
            # Get reviews
            await cur.execute("""
                SELECT 
                    r.review_id,
                    r.rating,
                    r.comment,
                    r.created_at,
                    u.full_name AS customer_name,
                    j.title AS job_title
                FROM reviews r
                JOIN jobs j ON r.job_id = j.job_id
                JOIN users u ON r.customer_id = u.user_id
                WHERE r.worker_id = %s::uuid
                ORDER BY r.created_at DESC
                LIMIT %s OFFSET %s
            """, (worker_id, limit, offset))
            
            rows = await cur.fetchall()
            return [
                WorkerReviewItem(
                    review_id=row["review_id"],
                    rating=row["rating"],
                    comment=row["comment"],
                    created_at=str(row["created_at"]),
                    customer_name=row["customer_name"],
                    job_title=row["job_title"]
                )
                for row in rows
            ]
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Reviews error: {str(e)}")
