from fastapi import APIRouter, Depends, HTTPException
import psycopg
from database import get_db_connection
from modules.auth.routes import get_current_user_id
from modules.bids_bookings.modules import CreateBidRequest, BidResponse
from uuid import UUID

router = APIRouter(prefix="/api", tags=["Bidding & Contracts"])

# ==========================================
# Endpoint 1: Placing a bid
# ==========================================
@router.post("/bids")
async def place_bid(
    bid_data: CreateBidRequest,
    user_id: str = Depends(get_current_user_id), 
    conn: psycopg.AsyncConnection = Depends(get_db_connection)
):
    try:
        # Transaction begins immediately
        async with conn.transaction():
            async with conn.cursor() as cur:
                await cur.execute("SELECT role AS role FROM Users WHERE user_id = %s", (user_id,))
                role_row = await cur.fetchone()
                
                if not role_row or role_row["role"] != 'Worker':
                    raise HTTPException(status_code=403, detail="Only workers can place bids.")

                await cur.execute("SELECT client_id AS client_id, status AS status FROM Jobs WHERE job_id = %s", (str(bid_data.job_id),))
                job_row = await cur.fetchone()
                
                if not job_row:
                    raise HTTPException(status_code=404, detail="Job not found.")
                if job_row["status"] != 'Open':
                    raise HTTPException(status_code=400, detail="This job is no longer accepting bids.")
                if str(job_row["client_id"]) == user_id: 
                    raise HTTPException(status_code=403, detail="You cannot bid on your own job.")

                await cur.execute("""
                    INSERT INTO Bids (job_id, worker_id, proposed_price, eta, description)
                    VALUES (%s, %s, %s, %s, %s) RETURNING bid_id AS bid_id;
                """, (str(bid_data.job_id), user_id, bid_data.proposed_price, bid_data.eta, bid_data.description))
                
                result = await cur.fetchone()
                new_bid_id = result["bid_id"]
                
                return {"message": "Bid placed successfully!", "bid_id": new_bid_id}
                
    except psycopg.errors.UniqueViolation:
        # If the worker already bid, the transaction automatically rolls back before hitting this block
        raise HTTPException(status_code=409, detail="You have already bid on this job.")


# ==========================================
# Endpoint 2: Get all bids for a job
# ==========================================
@router.get("/jobs/{job_id}/bids", response_model=list[BidResponse])
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
                       COALESCE(wp.average_rating, 0) AS worker_rating,
                       b.proposed_price AS proposed_price,
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
                bids.append({
                    "bid_id": row["bid_id"],
                    "worker_id": row["worker_id"],
                    "worker_name": row["worker_name"],
                    "worker_rating": float(row["worker_rating"]),
                    "proposed_price": float(row["proposed_price"]),
                    "eta": row["eta"],
                    "description": row["description"],
                    "status": row["status"]
                })
                
            return bids


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
        # Wrap the ENTIRE process (including the initial SELECT) in a transaction to prevent race conditions
        async with conn.transaction():
            async with conn.cursor() as cur:
                # 1. Fetch all required data from the Bid
                await cur.execute("""
                    SELECT b.job_id AS job_id, 
                           b.worker_id AS worker_id, 
                           b.proposed_price AS proposed_price, 
                           b.eta AS eta, 
                           j.client_id AS client_id, 
                           j.status AS status
                    FROM Bids b
                    JOIN Jobs j ON b.job_id = j.job_id
                    WHERE b.bid_id = %s
                """, (str(bid_id),))
                
                row = await cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Bid not found.")
                    
                job_id = row["job_id"]
                worker_id = row["worker_id"]
                agreed_price = row["proposed_price"]
                eta = row["eta"]
                client_id = row["client_id"]
                job_status = row["status"]
                
                # 2. Security Checks
                if str(client_id) != user_id:
                    raise HTTPException(status_code=403, detail="Only the job creator can accept this bid.")
                if job_status != 'Open':
                    raise HTTPException(status_code=400, detail="This job has already been assigned.")

                # 3. Write Operations
                # A. Accept this bid
                await cur.execute("UPDATE Bids SET status = 'Accepted' WHERE bid_id = %s", (str(bid_id),))
                
                # B. Reject all competing bids
                await cur.execute("UPDATE Bids SET status = 'Rejected' WHERE job_id = %s AND bid_id != %s", (job_id, str(bid_id)))
                
                # C. Close the Job
                await cur.execute("UPDATE Jobs SET status = 'In Progress' WHERE job_id = %s", (job_id,))
                
                # D. Generate the Contract
                await cur.execute("""
                    INSERT INTO Bookings (job_id, worker_id, agreed_price, eta, status)
                    VALUES (%s, %s, %s, %s, 'Scheduled')
                    RETURNING booking_id AS booking_id;
                """, (job_id, worker_id, agreed_price, eta))
                
                booking_row = await cur.fetchone()
                new_booking_id = booking_row["booking_id"] 
                
            return {
                "message": "Bid accepted and Contract created successfully!",
                "booking_id": new_booking_id
            }
            
    except HTTPException:
        # Re-raise standard HTTP Exceptions (like 404 or 403) so FastAPI can handle them normally
        raise
    except Exception as e:
        # Catch unexpected database crashes and return a 500
        raise HTTPException(status_code=500, detail=f"Transaction failed: {str(e)}")