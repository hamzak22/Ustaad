from fastapi import APIRouter, Depends, HTTPException
import psycopg
from database import get_db_connection
from modules.auth.routes import get_current_user_id
from modules.notifications.models import NotificationCreate
from modules.notifications.service import persist_notification, broadcast_notification
from modules.bids_bookings.modules import CreateBidRequest, BidResponse, ProposalResponse, DirectJobResponseModel, CompleteBookingWithReviewRequest
from modules.bids_bookings.modules import BookingResponse
from modules.reviews.models import ReviewResponse
from uuid import UUID
from typing import List

router = APIRouter(tags=["Bidding & Contracts"])

# ==========================================
# Endpoint 1: Placing a bid
# ==========================================
@router.post("/bid")
async def place_bid(
    bid_data: CreateBidRequest,
    user_id: str = Depends(get_current_user_id),
    conn: psycopg.AsyncConnection = Depends(get_db_connection)
):
    try:
        # Transaction begins immediately
        async with conn.transaction():
            notification = None
            async with conn.cursor() as cur:
                await cur.execute("SELECT role AS role FROM Users WHERE user_id = %s", (user_id,))
                role_row = await cur.fetchone()
                
                if not role_row or role_row["role"] != 'Worker':
                    raise HTTPException(status_code=403, detail="Only workers can place bids.")

                await cur.execute("SELECT client_id AS client_id, title AS title, status AS status, job_type, target_worker FROM Jobs WHERE job_id = %s", (str(bid_data.job_id),))
                job_row = await cur.fetchone()
                
                if not job_row:
                    raise HTTPException(status_code=404, detail="Job not found.")
                if job_row["status"] != 'Open':
                    raise HTTPException(status_code=400, detail="This job is no longer accepting bids.")
                if str(job_row["client_id"]) == user_id: 
                    raise HTTPException(status_code=403, detail="You cannot bid on your own job.")

                # Enforce direct job rules: only the target worker can propose on a direct job
                if job_row["job_type"] == "Direct":
                    if job_row["target_worker"] is None or str(job_row["target_worker"]) != user_id:
                        raise HTTPException(status_code=403, detail="Only the assigned worker can submit a proposal for this direct job.")

                await cur.execute("""
                    INSERT INTO Bids (job_id, worker_id, proposed_price, fee_type, eta, description)
                    VALUES (%s, %s, %s, %s, %s, %s) RETURNING bid_id AS bid_id;
                """, (str(bid_data.job_id), user_id, bid_data.proposed_price, bid_data.fee_type, bid_data.eta, bid_data.cover_letter))

                result = await cur.fetchone()
                new_bid_id = result["bid_id"]

                # If worker attached previous review IDs, validate and insert them
                if bid_data.attached_review_ids:
                    for rev_id in bid_data.attached_review_ids:
                        await cur.execute("SELECT worker_id FROM Reviews WHERE review_id = %s", (str(rev_id),))
                        rev_row = await cur.fetchone()
                        if not rev_row:
                            raise HTTPException(status_code=400, detail=f"Attached review {rev_id} not found")
                        if str(rev_row["worker_id"]) != user_id:
                            raise HTTPException(status_code=400, detail="You can only attach your own past reviews")

                        await cur.execute("INSERT INTO Bid_Attached_Reviews (bid_id, review_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (new_bid_id, str(rev_id)))

                notification = await persist_notification(
                    conn,
                    NotificationCreate(
                        recipient_id=job_row["client_id"],
                        actor_id=UUID(user_id),
                        notification_type="bid_placed",
                        title="New bid received",
                        body=f"A worker placed a bid on your job '{job_row['title']}'.",
                        entity_type="bid",
                        entity_id=new_bid_id,
                        metadata={
                            "job_id": str(bid_data.job_id),
                            "worker_id": user_id,
                            "price": bid_data.proposed_price,
                        },
                    ),
                )

        if notification:
            await broadcast_notification(notification)

        return {"message": "Bid placed successfully!", "bid_id": new_bid_id}
                
    except psycopg.errors.UniqueViolation:
        # If the worker already bid, the transaction automatically rolls back before hitting this block
        raise HTTPException(status_code=409, detail="You have already bid on this job.")



# ==========================================
# Endpoint 2: Get all bids for a job
# ==========================================
@router.get("/jobs/{job_id}/bids", response_model=List[BidResponse])
async def get_job_bids(
    job_id: UUID,
    user_id: str = Depends(get_current_user_id),
    conn: psycopg.AsyncConnection = Depends(get_db_connection)
):
    # Even for read-only endpoints, a transaction guarantees a "consistent snapshot" of the data
    async with conn.transaction():
        async with conn.cursor() as cur:
            
            await cur.execute("SELECT client_id AS client_id FROM Jobs WHERE job_id = %s", (str(job_id),))
            job_row = await cur.fetchone()
            
            if not job_row:
                raise HTTPException(status_code=404, detail="Job not found.")
            if str(job_row["client_id"]) != user_id:
                raise HTTPException(status_code=403, detail="Only the job creator can view its bids.")

            await cur.execute("""
                SELECT b.bid_id AS bid_id,
                       b.worker_id AS worker_id,
                       u.full_name AS worker_name,
                       u.city AS worker_city,
                       COALESCE(wp.average_rating, 0) AS worker_rating,
                       b.proposed_price AS proposed_price,
                       b.fee_type AS fee_type,
                       b.eta AS eta,
                       b.description AS description,
                       b.status AS status
                FROM Bids b
                JOIN Users u ON b.worker_id = u.user_id
                LEFT JOIN worker_profile wp ON b.worker_id = wp.worker_id
                WHERE b.job_id = %s
                ORDER BY b.proposed_price ASC;
            """, (str(job_id),))
            
            rows = await cur.fetchall()
            
            bids = []
            for row in rows:
                # fetch attached reviews for this bid
                await cur.execute(
                    """
                    SELECT r.review_id AS review_id, r.booking_id AS booking_id, r.job_id AS job_id, r.customer_id AS customer_id, u.full_name AS customer_name, r.rating AS rating, r.comment AS comment, r.created_at AS created_at, r.worker_id AS worker_id
                    FROM Bid_Attached_Reviews bar
                    JOIN Reviews r ON bar.review_id = r.review_id
                    LEFT JOIN Users u ON r.customer_id = u.user_id
                    WHERE bar.bid_id = %s
                    ORDER BY r.created_at DESC
                    """,
                    (str(row["bid_id"]),),
                )

                rev_rows = await cur.fetchall()
                attached_reviews = []
                for r in rev_rows:
                    attached_reviews.append({
                        "review_id": r["review_id"],
                        "booking_id": r["booking_id"],
                        "job_id": r["job_id"],
                        "worker_id": r["worker_id"],
                        "customer_id": r["customer_id"],
                        "customer_name": r["customer_name"],
                        "rating": r["rating"],
                        "comment": r["comment"],
                        "created_at": r["created_at"],
                    })

                bids.append({
                    "bid_id": row["bid_id"],
                    "worker_id": row["worker_id"],
                    "worker_name": row["worker_name"],
                    "worker_city": row.get("worker_city"),
                    "worker_rating": float(row["worker_rating"]),
                    "proposed_price": float(row["proposed_price"]),
                    "fee_type": row["fee_type"],
                    "eta": row["eta"],
                    "cover_letter": row["description"],
                    "attached_reviews": attached_reviews,
                    "status": row["status"],
                })
                
            return bids


# ==========================================
# Endpoint: Get my proposals (worker view)
# ==========================================
@router.get("/my-proposals", response_model=List[ProposalResponse])
async def get_my_proposals(
    user_id: str = Depends(get_current_user_id),
    conn: psycopg.AsyncConnection = Depends(get_db_connection),
):
    async with conn.transaction():
        async with conn.cursor() as cur:
            # Ensure role is Worker
            await cur.execute("SELECT role FROM Users WHERE user_id = %s", (user_id,))
            row_role = await cur.fetchone()
            if not row_role or row_role["role"] != 'Worker':
                raise HTTPException(status_code=403, detail="Only workers can view their proposals")

            await cur.execute(
                """
                SELECT b.bid_id, b.job_id, j.title AS job_title, j.description AS job_description,
                       j.client_id AS client_id, c.full_name AS client_name,
                       b.proposed_price, b.fee_type, b.eta, b.description AS cover_letter,
                       b.status, b.created_at
                FROM Bids b
                JOIN Jobs j ON b.job_id = j.job_id
                JOIN Users c ON j.client_id = c.user_id
                                WHERE b.worker_id = %s
                                    AND LOWER(b.status) IN ('pending', 'accepted', 'rejected')
                ORDER BY b.created_at DESC
                """,
                (user_id,)
            )

            rows = await cur.fetchall()

            proposals = []
            for row in rows:
                # fetch attached reviews
                await cur.execute(
                    """
                    SELECT r.review_id AS review_id, r.booking_id AS booking_id, r.job_id AS job_id, r.customer_id AS customer_id, u.full_name AS customer_name, r.rating AS rating, r.comment AS comment, r.created_at AS created_at, r.worker_id AS worker_id
                    FROM Bid_Attached_Reviews bar
                    JOIN Reviews r ON bar.review_id = r.review_id
                    LEFT JOIN Users u ON r.customer_id = u.user_id
                    WHERE bar.bid_id = %s
                    ORDER BY r.created_at DESC
                    """,
                    (str(row["bid_id"]),),
                )
                rev_rows = await cur.fetchall()
                attached_reviews = []
                for r in rev_rows:
                    attached_reviews.append({
                        "review_id": r["review_id"],
                        "booking_id": r["booking_id"],
                        "job_id": r["job_id"],
                        "worker_id": r["worker_id"],
                        "customer_id": r["customer_id"],
                        "customer_name": r["customer_name"],
                        "rating": r["rating"],
                        "comment": r["comment"],
                        "created_at": r["created_at"],
                    })

                proposals.append({
                    "bid_id": row["bid_id"],
                    "job_id": row["job_id"],
                    "job_title": row["job_title"],
                    "job_description": row["job_description"],
                    "client_id": row["client_id"],
                    "client_name": row["client_name"],
                    "proposed_price": float(row["proposed_price"]),
                    "fee_type": row["fee_type"],
                    "eta": row["eta"],
                    "cover_letter": row["cover_letter"],
                    "attached_reviews": attached_reviews,
                    "status": row["status"],
                    "created_at": row["created_at"],
                })

            return proposals


# ==========================================
# Endpoint: Decline a direct job invitation
# ==========================================
@router.post("/jobs/{job_id}/decline-direct-invite")
async def decline_direct_invite(
    job_id: UUID,
    user_id: str = Depends(get_current_user_id),
    conn: psycopg.AsyncConnection = Depends(get_db_connection),
):
    try:
        async with conn.transaction():
            async with conn.cursor() as cur:
                # Verify job is direct and assigned to this worker
                await cur.execute(
                    "SELECT job_type, target_worker, client_id, title FROM Jobs WHERE job_id = %s",
                    (str(job_id),),
                )
                job_row = await cur.fetchone()

                if not job_row:
                    raise HTTPException(status_code=404, detail="Job not found.")
                
                if job_row["job_type"] != "Direct":
                    raise HTTPException(status_code=400, detail="Only direct jobs can be declined.")
                
                if job_row["target_worker"] is None or str(job_row["target_worker"]) != user_id:
                    raise HTTPException(status_code=403, detail="Only the assigned worker can decline this job.")

                # Record the decline in Direct_Job_Responses table
                await cur.execute(
                    """
                    INSERT INTO Direct_Job_Responses (job_id, worker_id, response_status)
                    VALUES (%s, %s, 'Declined')
                    ON CONFLICT (job_id, worker_id) DO UPDATE SET response_status = 'Declined', responded_at = CURRENT_TIMESTAMP
                    RETURNING id
                    """,
                    (str(job_id), user_id),
                )
                
                result = await cur.fetchone()
                if not result:
                    raise HTTPException(status_code=500, detail="Failed to record decline.")

                notification = await persist_notification(
                    conn,
                    NotificationCreate(
                        recipient_id=job_row["client_id"],
                        actor_id=UUID(user_id),
                        notification_type="direct_invite_declined",
                        title="Direct job invitation declined",
                        body=f"The worker declined your direct job invitation for '{job_row['title']}'.",
                        entity_type="job",
                        entity_id=job_id,
                        metadata={"job_id": str(job_id), "worker_id": user_id},
                    ),
                )

        await broadcast_notification(notification)
        return {"message": "Direct job invitation declined successfully."}

    except HTTPException:
        raise
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail="An error occurred while declining the job invitation")


# ==========================================
# Endpoint 3: Accept a bid and generate contract 
# ==========================================
@router.post("/bids/{bid_id}/accept")
async def accept_bid(
    bid_id: UUID,
    user_id: str = Depends(get_current_user_id),
    conn: psycopg.AsyncConnection = Depends(get_db_connection)
):
    try:
        async with conn.transaction():
            async with conn.cursor() as cur:
                # Call stored procedure in create_functions.sql
                await cur.execute("CALL assign_worker_to_request(%s, %s, NULL)", (str(bid_id), user_id))
                result = await cur.fetchone()

                await cur.execute(
                    """
                    SELECT b.booking_id, b.worker_id, b.job_id, j.client_id, j.title
                    FROM Bookings b
                    JOIN Jobs j ON j.job_id = b.job_id
                    WHERE b.booking_id = %s
                    """,
                    (str(result["p_booking_id"]),),
                )
                booking_row = await cur.fetchone()

                worker_notification = await persist_notification(
                    conn,
                    NotificationCreate(
                        recipient_id=booking_row["worker_id"],
                        actor_id=UUID(user_id),
                        notification_type="booking_scheduled",
                        title="You have a new booking",
                        body=f"Your bid was accepted for '{booking_row['title']}'.",
                        entity_type="booking",
                        entity_id=booking_row["booking_id"],
                        metadata={"job_id": str(booking_row["job_id"]), "bid_id": str(bid_id)},
                    ),
                )

                client_notification = await persist_notification(
                    conn,
                    NotificationCreate(
                        recipient_id=booking_row["client_id"],
                        actor_id=UUID(user_id),
                        notification_type="booking_scheduled",
                        title="Booking created",
                        body=f"Your booking for '{booking_row['title']}' has been scheduled.",
                        entity_type="booking",
                        entity_id=booking_row["booking_id"],
                        metadata={"job_id": str(booking_row["job_id"]), "bid_id": str(bid_id)},
                    ),
                )

        await broadcast_notification(worker_notification)
        await broadcast_notification(client_notification)

        return {
            "message": "Bid accepted and Contract created successfully!",
            "booking_id": result["p_booking_id"]
        }
            
    except psycopg.errors.RaiseException as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==========================================
# Endpoint 4: Mark a booking as completed
# ==========================================
@router.post("/bookings/{booking_id}/complete")
async def complete_booking(
    booking_id: UUID,
    user_id: str = Depends(get_current_user_id),
    conn: psycopg.AsyncConnection = Depends(get_db_connection),
):
    try:
        async with conn.transaction():
            notification = None
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT b.booking_id AS booking_id,
                           b.worker_id AS worker_id,
                           b.status AS booking_status,
                           j.job_id AS job_id,
                           j.status AS job_status,
                           j.client_id AS client_id,
                           j.title AS job_title
                    FROM Bookings b
                    JOIN Jobs j ON j.job_id = b.job_id
                    WHERE b.booking_id = %s
                    """,
                    (str(booking_id),),
                )
                booking_row = await cur.fetchone()

                if not booking_row:
                    raise HTTPException(status_code=404, detail="Booking not found")

                if str(booking_row["client_id"]) != user_id:
                    raise HTTPException(status_code=403, detail="Only the job owner (customer) can complete this booking")

                if booking_row["booking_status"] == "Completed":
                    raise HTTPException(status_code=400, detail="Booking is already completed")

                if booking_row["booking_status"] == "Cancelled":
                    raise HTTPException(status_code=400, detail="Cancelled bookings cannot be completed")

                if booking_row["job_status"] == "Completed":
                    raise HTTPException(status_code=400, detail="Job is already completed")

                # NEW: Require booking to be In Progress before allowing completion
                if booking_row["booking_status"] != "In Progress":
                    raise HTTPException(status_code=400, detail="Only bookings marked as 'In Progress' can be completed. The worker must start the booking first.")

                await cur.execute(
                    """
                    UPDATE Bookings
                    SET status = 'Completed'
                    WHERE booking_id = %s
                    RETURNING booking_id AS booking_id, status AS status
                    """,
                    (str(booking_id),),
                )
                updated_booking = await cur.fetchone()

                notification = await persist_notification(
                    conn,
                    NotificationCreate(
                        recipient_id=booking_row["worker_id"],
                        actor_id=UUID(user_id),
                        notification_type="booking_completed",
                        title="Booking completed",
                        body=f"The customer marked the booking for '{booking_row['job_title']}' as completed.",
                        entity_type="booking",
                        entity_id=updated_booking["booking_id"],
                        metadata={"job_id": str(booking_row["job_id"])},
                    ),
                )

        if notification:
            await broadcast_notification(notification)

        return {
            "message": "Booking marked as completed successfully",
            "booking_id": updated_booking["booking_id"],
            "status": updated_booking["status"],
        }

    except HTTPException:
        raise
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail="An error occurred while completing the booking")


# ==========================================
# Endpoint 4b: Complete a booking and submit review (combined endpoint)
# ==========================================
@router.post("/bookings/{booking_id}/complete-with-review")
async def complete_booking_with_review(
    booking_id: UUID,
    review_data: CompleteBookingWithReviewRequest,
    user_id: str = Depends(get_current_user_id),
    conn: psycopg.AsyncConnection = Depends(get_db_connection),
):
    try:
        async with conn.transaction():
            completion_notification = None
            review_notification = None
            async with conn.cursor() as cur:
                # Fetch booking and job details
                await cur.execute(
                    """
                    SELECT b.booking_id AS booking_id,
                           b.worker_id AS worker_id,
                           b.status AS booking_status,
                           j.job_id AS job_id,
                           j.status AS job_status,
                           j.client_id AS client_id,
                           j.title AS job_title
                    FROM Bookings b
                    JOIN Jobs j ON j.job_id = b.job_id
                    WHERE b.booking_id = %s
                    """,
                    (str(booking_id),),
                )
                booking_row = await cur.fetchone()

                if not booking_row:
                    raise HTTPException(status_code=404, detail="Booking not found")

                if str(booking_row["client_id"]) != user_id:
                    raise HTTPException(status_code=403, detail="Only the job owner (customer) can complete this booking")

                if booking_row["booking_status"] == "Completed":
                    raise HTTPException(status_code=400, detail="Booking is already completed")

                if booking_row["booking_status"] == "Cancelled":
                    raise HTTPException(status_code=400, detail="Cancelled bookings cannot be completed")

                if booking_row["job_status"] == "Completed":
                    raise HTTPException(status_code=400, detail="Job is already completed")

                # Require booking to be In Progress
                if booking_row["booking_status"] != "In Progress":
                    raise HTTPException(status_code=400, detail="Only bookings marked as 'In Progress' can be completed. The worker must start the booking first.")

                # Mark booking as completed
                await cur.execute(
                    """
                    UPDATE Bookings
                    SET status = 'Completed'
                    WHERE booking_id = %s
                    RETURNING booking_id AS booking_id, status AS status
                    """,
                    (str(booking_id),),
                )
                updated_booking = await cur.fetchone()

                # Insert the review
                await cur.execute(
                    """
                    INSERT INTO Reviews (booking_id, job_id, customer_id, worker_id, rating, comment)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING review_id AS review_id
                    """,
                    (
                        str(booking_id),
                        str(booking_row["job_id"]),
                        user_id,
                        str(booking_row["worker_id"]),
                        review_data.rating,
                        review_data.comment,
                    ),
                )

                result = await cur.fetchone()
                new_review_id = result["review_id"]

                completion_notification = await persist_notification(
                    conn,
                    NotificationCreate(
                        recipient_id=booking_row["worker_id"],
                        actor_id=UUID(user_id),
                        notification_type="booking_completed",
                        title="Booking completed",
                        body=f"The customer completed the booking for '{booking_row['job_title']}'.",
                        entity_type="booking",
                        entity_id=updated_booking["booking_id"],
                        metadata={"job_id": str(booking_row["job_id"])},
                    ),
                )

                review_notification = await persist_notification(
                    conn,
                    NotificationCreate(
                        recipient_id=booking_row["worker_id"],
                        actor_id=UUID(user_id),
                        notification_type="review_left",
                        title="New review received",
                        body=f"A customer left a review for '{booking_row['job_title']}'.",
                        entity_type="review",
                        entity_id=new_review_id,
                        metadata={"booking_id": str(booking_id), "job_id": str(booking_row["job_id"])},
                    ),
                )

        await broadcast_notification(completion_notification)
        await broadcast_notification(review_notification)

        return {
            "message": "Booking completed and review submitted successfully",
            "booking_id": updated_booking["booking_id"],
            "booking_status": updated_booking["status"],
            "review_id": new_review_id,
        }

    except psycopg.errors.UniqueViolation:
        raise HTTPException(status_code=409, detail="You have already reviewed this booking.")
    except HTTPException:
        raise
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail="An error occurred while completing the booking and submitting the review")


# ==========================================
# Endpoint: Worker starts a scheduled booking (mark In Progress)
# ==========================================
@router.post("/bookings/{booking_id}/start")
async def start_booking(
    booking_id: UUID,
    user_id: str = Depends(get_current_user_id),
    conn: psycopg.AsyncConnection = Depends(get_db_connection),
):
    try:
        async with conn.transaction():
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT b.booking_id AS booking_id,
                           b.worker_id AS worker_id,
                           b.status AS booking_status,
                           j.job_id AS job_id,
                           j.status AS job_status
                           ,j.client_id AS client_id,
                           j.title AS job_title
                    FROM Bookings b
                    JOIN Jobs j ON j.job_id = b.job_id
                    WHERE b.booking_id = %s
                    """,
                    (str(booking_id),),
                )
                booking_row = await cur.fetchone()

                if not booking_row:
                    raise HTTPException(status_code=404, detail="Booking not found")

                if str(booking_row["worker_id"]) != user_id:
                    raise HTTPException(status_code=403, detail="Only the assigned worker can start this booking")

                if booking_row["booking_status"] != "Scheduled":
                    raise HTTPException(status_code=400, detail="Only scheduled bookings can be started")

                if booking_row["job_status"] == "Completed":
                    raise HTTPException(status_code=400, detail="Job is already completed")

                await cur.execute(
                    """
                    UPDATE Bookings
                    SET status = 'In Progress'
                    WHERE booking_id = %s
                    RETURNING booking_id AS booking_id, status AS status
                    """,
                    (str(booking_id),),
                )
                updated_booking = await cur.fetchone()

                # Ensure job status is also In Progress
                await cur.execute(
                    "UPDATE Jobs SET status = 'In Progress' WHERE job_id = %s RETURNING job_id, status",
                    (str(booking_row["job_id"]),),
                )

                notification = await persist_notification(
                    conn,
                    NotificationCreate(
                        recipient_id=booking_row["client_id"],
                        actor_id=UUID(user_id),
                        notification_type="booking_started",
                        title="Booking started",
                        body=f"Your worker has started the booking for '{booking_row['job_title']}'.",
                        entity_type="booking",
                        entity_id=updated_booking["booking_id"],
                        metadata={"job_id": str(booking_row["job_id"])},
                    ),
                )

        await broadcast_notification(notification)

        return {
                    "message": "Booking started (In Progress)",
                    "booking_id": updated_booking["booking_id"],
                    "status": updated_booking["status"],
                }

    except HTTPException:
        raise
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail="An error occurred while starting the booking")


# ==========================================
# Endpoint 5: Cancel a booking
# ==========================================
@router.post("/bookings/{booking_id}/cancel")
async def cancel_booking(
    booking_id: UUID,
    user_id: str = Depends(get_current_user_id),
    conn: psycopg.AsyncConnection = Depends(get_db_connection),
):
    try:
        async with conn.transaction():
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT b.booking_id AS booking_id,
                           b.worker_id AS worker_id,
                           b.status AS booking_status,
                           j.client_id AS client_id,
                           j.status AS job_status,
                           j.title AS job_title
                    FROM Bookings b
                    JOIN Jobs j ON j.job_id = b.job_id
                    WHERE b.booking_id = %s
                    """,
                    (str(booking_id),),
                )
                booking_row = await cur.fetchone()

                if not booking_row:
                    raise HTTPException(status_code=404, detail="Booking not found")

                if str(booking_row["client_id"]) != user_id and str(booking_row["worker_id"]) != user_id:
                    raise HTTPException(status_code=403, detail="Only the job owner or assigned worker can cancel this booking")

                if booking_row["booking_status"] == "Cancelled":
                    raise HTTPException(status_code=400, detail="Booking is already cancelled")

                if booking_row["booking_status"] == "Completed":
                    raise HTTPException(status_code=400, detail="Completed bookings cannot be cancelled")

                if booking_row["job_status"] == "Completed":
                    raise HTTPException(status_code=400, detail="Completed jobs cannot be cancelled")

                await cur.execute(
                    """
                    UPDATE Bookings
                    SET status = 'Cancelled'
                    WHERE booking_id = %s
                    RETURNING booking_id AS booking_id, status AS status
                    """,
                    (str(booking_id),),
                )
                updated_booking = await cur.fetchone()

                recipient_id = booking_row["client_id"] if str(booking_row["worker_id"]) == user_id else booking_row["worker_id"]
                notification = await persist_notification(
                    conn,
                    NotificationCreate(
                        recipient_id=recipient_id,
                        actor_id=UUID(user_id),
                        notification_type="booking_cancelled",
                        title="Booking cancelled",
                        body=f"A booking for '{booking_row['job_title']}' was cancelled.",
                        entity_type="booking",
                        entity_id=updated_booking["booking_id"],
                        metadata={"job_id": str(booking_row.get("job_id", booking_id))},
                    ),
                )

        await broadcast_notification(notification)

        return {
                    "message": "Booking cancelled successfully",
                    "booking_id": updated_booking["booking_id"],
                    "status": updated_booking["status"],
                }

    except HTTPException:
        raise
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail="An error occurred while cancelling the booking")


# ==========================================
# Customer: Get all active bookings
# ==========================================
@router.get("/customer/bookings", response_model=list[BookingResponse])
async def get_customer_active_bookings(
    user_id: str = Depends(get_current_user_id),
    conn: psycopg.AsyncConnection = Depends(get_db_connection),
):
    async with conn.transaction():
        async with conn.cursor() as cur:
            # Fetch bookings for jobs owned by this customer that are active
            await cur.execute(
                """
                SELECT b.booking_id, b.job_id, j.title AS job_title, j.description AS job_description,
                       s.service_name, b.worker_id, u.full_name AS worker_name, u.city AS worker_city,
                       COALESCE(wp.average_rating, 0) AS worker_rating, b.agreed_price, b.eta,
                       b.status AS booking_status, j.status AS job_status, b.created_at
                FROM Bookings b
                JOIN Jobs j ON b.job_id = j.job_id
                JOIN Users u ON b.worker_id = u.user_id
                LEFT JOIN worker_profile wp ON b.worker_id = wp.worker_id
                JOIN Services s ON j.service_id = s.service_id
                WHERE j.client_id = %s
                  AND (b.status = 'Scheduled' OR j.status = 'In Progress')
                ORDER BY b.created_at DESC
                """,
                (user_id,)
            )

            rows = await cur.fetchall()
            bookings = []
            for row in rows:
                bookings.append({
                    "booking_id": row["booking_id"],
                    "job_id": row["job_id"],
                    "job_title": row["job_title"],
                    "job_description": row["job_description"],
                    "service_name": row["service_name"],
                    "worker_id": row["worker_id"],
                    "worker_name": row["worker_name"],
                    "worker_city": row.get("worker_city"),
                    "worker_rating": float(row["worker_rating"]),
                    "agreed_price": float(row["agreed_price"]),
                    "eta": row["eta"],
                    "booking_status": row["booking_status"],
                    "job_status": row["job_status"],
                    "created_at": row["created_at"],
                })

            return bookings


# ==========================================
# Customer: Get a single active booking detail
# ==========================================
@router.get("/customer/bookings/{booking_id}", response_model=BookingResponse)
async def get_customer_booking_detail(
    booking_id: UUID,
    user_id: str = Depends(get_current_user_id),
    conn: psycopg.AsyncConnection = Depends(get_db_connection),
):
    async with conn.transaction():
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT b.booking_id, b.job_id, j.title AS job_title, j.description AS job_description,
                       s.service_name, b.worker_id, u.full_name AS worker_name, u.city AS worker_city,
                       COALESCE(wp.average_rating, 0) AS worker_rating, b.agreed_price, b.eta,
                       b.status AS booking_status, j.status AS job_status, b.created_at, j.client_id
                FROM Bookings b
                JOIN Jobs j ON b.job_id = j.job_id
                JOIN Users u ON b.worker_id = u.user_id
                LEFT JOIN worker_profile wp ON b.worker_id = wp.worker_id
                JOIN Services s ON j.service_id = s.service_id
                WHERE b.booking_id = %s
                """,
                (str(booking_id),),
            )

            row = await cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Booking not found")

            # ensure requesting user is the customer who owns the job
            if str(row["client_id"]) != user_id:
                raise HTTPException(status_code=403, detail="Only the job owner can view this booking")

            return {
                "booking_id": row["booking_id"],
                "job_id": row["job_id"],
                "job_title": row["job_title"],
                "job_description": row["job_description"],
                "service_name": row["service_name"],
                "worker_id": row["worker_id"],
                "worker_name": row["worker_name"],
                "worker_city": row.get("worker_city"),
                "worker_rating": float(row["worker_rating"]),
                "agreed_price": float(row["agreed_price"]),
                "eta": row["eta"],
                "booking_status": row["booking_status"],
                "job_status": row["job_status"],
                "created_at": row["created_at"],
            }


# ==========================================
# Worker: Get my bookings (Scheduled, In Progress, Completed)
# ==========================================
@router.get("/worker/bookings/my-bookings", response_model=list[BookingResponse])
async def get_worker_my_bookings(
    user_id: str = Depends(get_current_user_id),
    conn: psycopg.AsyncConnection = Depends(get_db_connection),
):
    try:
        async with conn.transaction():
            async with conn.cursor() as cur:
                # Verify the user is a worker
                await cur.execute("SELECT role FROM Users WHERE user_id = %s", (user_id,))
                role_row = await cur.fetchone()
                if not role_row or role_row["role"] != "Worker":
                    raise HTTPException(status_code=403, detail="Only workers can view their bookings")

                # Fetch all bookings assigned to this worker, showing all statuses
                await cur.execute(
                    """
                    SELECT b.booking_id, b.job_id, j.title AS job_title, j.description AS job_description,
                           s.service_name, b.worker_id, u.full_name AS client_name, u.city AS client_city,
                           b.agreed_price, b.eta, b.status AS booking_status, j.status AS job_status, 
                           b.created_at
                    FROM Bookings b
                    JOIN Jobs j ON b.job_id = j.job_id
                    JOIN Users u ON j.client_id = u.user_id
                    JOIN Services s ON j.service_id = s.service_id
                    WHERE b.worker_id = %s
                    ORDER BY b.created_at DESC
                    """,
                    (user_id,)
                )

                rows = await cur.fetchall()
                bookings = []
                for row in rows:
                    # For this endpoint we return the client info instead of worker info
                    bookings.append({
                        "booking_id": row["booking_id"],
                        "job_id": row["job_id"],
                        "job_title": row["job_title"],
                        "job_description": row["job_description"],
                        "service_name": row["service_name"],
                        "worker_id": row["worker_id"],
                        "worker_name": row["client_name"],  # Client name for worker view
                        "worker_city": row.get("client_city"),  # Client city for worker view
                        "worker_rating": 0.0,  # Not applicable in worker view
                        "agreed_price": float(row["agreed_price"]),
                        "eta": row["eta"],
                        "booking_status": row["booking_status"],
                        "job_status": row["job_status"],
                        "created_at": row["created_at"],
                    })

                return bookings

    except HTTPException:
        raise
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail="An error occurred while fetching your bookings")