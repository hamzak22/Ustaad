from fastapi import APIRouter, Depends, HTTPException, status
import psycopg
import jwt
from typing import Annotated

from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from modules.auth.token_generator import SECRET_KEY, ALGORITHM
from database import get_db_connection

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
            SELECT u.user_id, u.full_name, u.email, u.phone_number, u.role, u.is_active, wp.bio
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
            async with conn.cursor() as cur:
                
                # Update Phone Number in Users table
                if update_data.phone_number is not None:
                    await cur.execute(
                        "UPDATE Users SET phone_number = %s WHERE user_id = %s",
                        (update_data.phone_number, user_id)
                    )

                # Update Bio in worker_profile table
                if update_data.bio is not None:
                    # FIX: We use a simple UPDATE now. The profile MUST exist already.
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

        return {"message": "Worker profile updated successfully!"}
        
    except psycopg.errors.UniqueViolation:
        raise HTTPException(status_code=400, detail="That phone number is already in use.")
    except psycopg.errors.ForeignKeyViolation:
        raise HTTPException(status_code=400, detail="One of the provided service IDs does not exist.")
    except Exception as e:
        # Catch other random DB errors
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


# ============================================================================
# WORKER SEARCH ENDPOINTS (For Customers)
# ============================================================================

@router.post("/workers/search", response_model=WorkerSearchResponse)
async def search_workers(
    search_params: WorkerSearchRequest,
    conn: psycopg.AsyncConnection = Depends(get_db_connection)
):
    """
    Search for available workers based on various criteria.
    
    This endpoint allows customers to search for workers by:
    - Service/skill (service_id)
    - City/location
    - Minimum rating
    - Availability status
    - Text search (name or bio)
    
    Supports pagination via limit and offset parameters.
    """
    async with conn.cursor() as cur:
        try:
            # Build dynamic SQL based on provided filters
            if search_params.search_query:
                # Use text search query
                query = """
                    SELECT 
                        u.user_id,
                        u.full_name,
                        u.email,
                        u.phone_number,
                        u.city,
                        wp.worker_id,
                        wp.experience,
                        wp.availability_status,
                        wp.bio,
                        wp.average_rating,
                        wp.total_reviews,
                        ws.service_id,
                        s.service_name,
                        ws.hourly_rate,
                        CASE 
                            WHEN LOWER(u.full_name) = LOWER(%s) THEN 3
                            WHEN LOWER(u.full_name) LIKE LOWER(%s || '%%') THEN 2
                            WHEN LOWER(u.full_name) ILIKE %s THEN 1
                            ELSE 0
                        END AS relevance_score
                    FROM Users u
                    JOIN worker_profile wp ON u.user_id = wp.worker_id
                    JOIN worker_skills ws ON wp.worker_id = ws.worker_id
                    JOIN Services s ON ws.service_id = s.service_id
                    WHERE 
                        u.is_active = true
                        AND (LOWER(u.full_name) ILIKE %s OR LOWER(wp.bio) ILIKE %s)
                        AND (ws.service_id = %s OR %s IS NULL)
                    ORDER BY relevance_score DESC, wp.average_rating DESC
                    LIMIT %s OFFSET %s
                """
                search_pattern = '%' + search_params.search_query + '%'
                await cur.execute(
                    query,
                    (
                        search_params.search_query,
                        search_params.search_query,
                        search_params.search_query,
                        search_pattern,
                        search_pattern,
                        search_params.service_id,
                        search_params.service_id,
                        search_params.limit,
                        search_params.offset
                    )
                )
            else:
                # Use structured filters search
                query = """
                    SELECT DISTINCT ON (wp.worker_id)
                        u.user_id,
                        u.full_name,
                        u.email,
                        u.phone_number,
                        u.city,
                        wp.worker_id,
                        wp.experience,
                        wp.availability_status,
                        wp.bio,
                        wp.average_rating,
                        wp.total_reviews,
                        ws.service_id,
                        s.service_name,
                        ws.hourly_rate
                    FROM Users u
                    JOIN worker_profile wp ON u.user_id = wp.worker_id
                    JOIN worker_skills ws ON wp.worker_id = ws.worker_id
                    JOIN Services s ON ws.service_id = s.service_id
                    WHERE 
                        u.is_active = true
                        AND (ws.service_id = %s OR %s IS NULL)
                        AND (u.city = %s OR %s IS NULL)
                        AND wp.average_rating >= %s
                        AND (wp.availability_status = %s OR %s IS NULL)
                    ORDER BY wp.worker_id, wp.average_rating DESC
                    LIMIT %s OFFSET %s
                """
                await cur.execute(
                    query,
                    (
                        search_params.service_id,
                        search_params.service_id,
                        search_params.city,
                        search_params.city,
                        search_params.min_rating or 0,
                        search_params.availability_status,
                        search_params.availability_status,
                        search_params.limit,
                        search_params.offset
                    )
                )

            rows = await cur.fetchall()
            
            # Transform rows to WorkerSearchResultItem objects
            workers = [
                WorkerSearchResultItem(
                    user_id=row["user_id"],
                    full_name=row["full_name"],
                    email=row["email"],
                    phone_number=row["phone_number"],
                    city=row["city"],
                    worker_id=row["worker_id"],
                    experience=row["experience"],
                    availability_status=row["availability_status"],
                    bio=row["bio"],
                    average_rating=float(row["average_rating"]),
                    total_reviews=row["total_reviews"],
                    service_id=row["service_id"],
                    service_name=row["service_name"],
                    hourly_rate=float(row["hourly_rate"])
                )
                for row in rows
            ]
            
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
    """
    Get detailed profile of a specific worker.
    
    This endpoint returns:
    - Complete worker profile information
    - All skills with hourly rates
    - Recent reviews and ratings
    - Work history summary
    
    Accessible to all authenticated customers (no auth required for view).
    """
    async with conn.cursor() as cur:
        try:
            # Fetch worker profile with skills
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
                    wp.availability_status,
                    wp.bio,
                    wp.average_rating,
                    wp.total_reviews
                FROM Users u
                JOIN worker_profile wp ON u.user_id = wp.worker_id
                WHERE 
                    wp.worker_id = %s
                    AND u.is_active = true
            """, (worker_id,))
            
            worker_row = await cur.fetchone()
            if not worker_row:
                raise HTTPException(status_code=404, detail="Worker not found or is inactive")
            
            # Fetch worker skills
            await cur.execute("""
                SELECT 
                    s.service_id,
                    s.service_name,
                    ws.hourly_rate
                FROM worker_skills ws
                JOIN Services s ON ws.service_id = s.service_id
                WHERE ws.worker_id = %s
                ORDER BY s.service_name ASC
            """, (worker_id,))
            
            skills_rows = await cur.fetchall()
            skills = [
                WorkerSkillInfo(
                    service_id=skill["service_id"],
                    service_name=skill["service_name"],
                    hourly_rate=float(skill["hourly_rate"])
                )
                for skill in skills_rows
            ]
            
            # Fetch recent reviews
            await cur.execute("""
                SELECT 
                    r.review_id,
                    r.rating,
                    r.comment,
                    r.created_at,
                    u.full_name AS customer_name,
                    j.title AS job_title
                FROM Reviews r
                JOIN Jobs j ON r.job_id = j.job_id
                JOIN Users u ON r.customer_id = u.user_id
                WHERE r.worker_id = %s
                ORDER BY r.created_at DESC
                LIMIT 10
            """, (worker_id,))
            
            reviews_rows = await cur.fetchall()
            recent_reviews = [
                WorkerReviewItem(
                    review_id=review["review_id"],
                    rating=review["rating"],
                    comment=review["comment"],
                    created_at=str(review["created_at"]),
                    customer_name=review["customer_name"],
                    job_title=review["job_title"]
                )
                for review in reviews_rows
            ]
            
            return WorkerDetailedProfile(
                user_id=worker_row["user_id"],
                full_name=worker_row["full_name"],
                email=worker_row["email"],
                phone_number=worker_row["phone_number"],
                city=worker_row["city"],
                created_at=str(worker_row["created_at"]),
                worker_id=worker_row["worker_id"],
                experience=worker_row["experience"],
                availability_status=worker_row["availability_status"],
                bio=worker_row["bio"],
                average_rating=float(worker_row["average_rating"]),
                total_reviews=worker_row["total_reviews"],
                skills=skills,
                recent_reviews=recent_reviews
            )
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error fetching worker details: {str(e)}")


@router.get("/workers/{worker_id}/reviews", response_model=list[WorkerReviewItem])
async def get_worker_reviews(
    worker_id: str,
    limit: int = 20,
    offset: int = 0,
    conn: psycopg.AsyncConnection = Depends(get_db_connection)
):
    """
    Get paginated reviews for a specific worker.
    
    Returns the most recent reviews with pagination support.
    """
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 100")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be >= 0")
    
    async with conn.cursor() as cur:
        try:
            # Verify worker exists
            await cur.execute(
                "SELECT worker_id FROM worker_profile WHERE worker_id = %s",
                (worker_id,)
            )
            if not await cur.fetchone():
                raise HTTPException(status_code=404, detail="Worker not found")
            
            # Fetch reviews
            await cur.execute("""
                SELECT 
                    r.review_id,
                    r.rating,
                    r.comment,
                    r.created_at,
                    u.full_name AS customer_name,
                    j.title AS job_title
                FROM Reviews r
                JOIN Jobs j ON r.job_id = j.job_id
                JOIN Users u ON r.customer_id = u.user_id
                WHERE r.worker_id = %s
                ORDER BY r.created_at DESC
                LIMIT %s OFFSET %s
            """, (worker_id, limit, offset))
            
            reviews_rows = await cur.fetchall()
            return [
                WorkerReviewItem(
                    review_id=review["review_id"],
                    rating=review["rating"],
                    comment=review["comment"],
                    created_at=str(review["created_at"]),
                    customer_name=review["customer_name"],
                    job_title=review["job_title"]
                )
                for review in reviews_rows
            ]
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error fetching reviews: {str(e)}")