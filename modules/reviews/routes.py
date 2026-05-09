from fastapi import APIRouter, Depends, HTTPException
import psycopg
from database import get_db_connection
from modules.auth.routes import get_current_user_id 
from modules.reviews.models import CreateReviewRequest, ReviewResponse
from uuid import UUID

router = APIRouter(tags=["Reviews"])

# ==========================================
# Endpoint 1: Submit a Review (POST /bookings/{booking_id}/reviews)
# ==========================================
@router.post("/bookings/{booking_id}/reviews")
async def submit_review(
    booking_id: UUID,
    review_data: CreateReviewRequest,
    user_id: str = Depends(get_current_user_id),
    conn: psycopg.AsyncConnection = Depends(get_db_connection)
):
    try:
        async with conn.transaction():
            async with conn.cursor() as cur:
                # 1. Fetch the Booking and Job details to verify ownership and status
                await cur.execute("""
                    SELECT j.client_id AS client_id,
                           b.worker_id AS worker_id,
                           b.status AS booking_status,
                           b.job_id AS job_id
                    FROM Bookings b
                    JOIN Jobs j ON b.job_id = j.job_id
                    WHERE b.booking_id = %s
                """, (str(booking_id),))

                booking_row = await cur.fetchone()
                
                if not booking_row:
                    raise HTTPException(status_code=404, detail="Booking not found.")
                    
                # 2. Strict Business Logic Checks
                if str(booking_row["client_id"]) != user_id:
                    raise HTTPException(status_code=403, detail="Only the customer who booked this job can leave a review.")
                
                if booking_row["booking_status"] != 'Completed':
                    raise HTTPException(status_code=400, detail="You can only review a completed job.")

                # 3. Insert the Review (Database TRIGGER will automatically update the worker's profile!)
                await cur.execute("""
                    INSERT INTO Reviews (booking_id, job_id, customer_id, worker_id, rating, comment)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING review_id AS review_id;
                """, (
                    str(booking_id),
                    str(booking_row["job_id"]),
                    user_id,
                    str(booking_row["worker_id"]),
                    review_data.rating,
                    review_data.comment,
                ))
                
                result = await cur.fetchone()
                new_review_id = result["review_id"]

                # Rating aggregation is handled by the trigger in create_triggers.sql - no need to duplicate it here

                return {"message": "Review submitted successfully!", "review_id": new_review_id}

    except psycopg.errors.UniqueViolation:
        # The database catches if they try to review the same booking twice!
        raise HTTPException(status_code=409, detail="You have already reviewed this booking.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database execution failed: {str(e)}")


# ==========================================
# Endpoint 2: Get a Worker's Reviews
# ==========================================
@router.get("/workers/{worker_id}/reviews", response_model=list[ReviewResponse])
async def get_worker_reviews(
    worker_id: UUID,
    conn: psycopg.AsyncConnection = Depends(get_db_connection)
):
    # This is a public endpoint, so we don't need the user_id dependency.
    # Anyone can see a worker's reviews!
    async with conn.transaction():
        async with conn.cursor() as cur:
            
            # Verify the worker exists
            await cur.execute("SELECT user_id FROM Users WHERE user_id = %s AND role = 'Worker'", (str(worker_id),))
            if not await cur.fetchone():
                raise HTTPException(status_code=404, detail="Worker not found.")

            # Fetch all reviews, joining with Users to get the Customer's name
            await cur.execute("""
                SELECT r.review_id AS review_id,
                       r.booking_id AS booking_id,
                       r.job_id AS job_id,
                       r.customer_id AS customer_id,
                       u.full_name AS customer_name,
                       r.rating AS rating,
                       r.comment AS comment,
                       r.created_at AS created_at,
                       r.worker_id AS worker_id
                FROM Reviews r
                JOIN Users u ON r.customer_id = u.user_id
                WHERE r.worker_id = %s
                ORDER BY r.created_at DESC;
            """, (str(worker_id),))

            rows = await cur.fetchall()

            reviews = []
            for row in rows:
                reviews.append({
                    "review_id": row["review_id"],
                    "booking_id": row["booking_id"],
                    "job_id": row["job_id"],
                    "worker_id": row["worker_id"],
                    "customer_id": row["customer_id"],
                    "customer_name": row["customer_name"],
                    "rating": row["rating"],
                    "comment": row["comment"],
                    "created_at": row["created_at"],
                })

            return reviews