from fastapi import APIRouter, Depends, HTTPException, status
import psycopg
import jwt
from typing import Annotated

from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from modules.auth.token_generator import SECRET_KEY, ALGORITHM
from database import get_db_connection

from modules.profilemgmt.models import UpdateWorkerProfileRequest, UserProfileResponse

router = APIRouter(prefix="/api", tags=["Profile Management"])
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