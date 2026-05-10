from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import EmailStr
from psycopg import AsyncConnection
from uuid import UUID

from .models import (
    CreateJobResponseModel,
    CreateJobModel,
    JobFeedData,
    JobType,
    JobData,
    ClientJobResponseData,
    SaveJobRequestModel,
    SaveJobResponeModel,
    UnsaveJobResponseModel,
    SavedJobsResponseModel,
    SavedJobData,
    WorkerActiveJobData,
)
from database import get_db_connection

from modules.auth.routes import get_current_user_id
from modules.notifications.models import NotificationCreate
from modules.notifications.service import persist_notification, broadcast_notification


router = APIRouter(
    prefix="/jobs",
    tags=["jobs"]
)


async def _ensure_worker_profile(conn: AsyncConnection, user_id: str) -> None:
    async with conn.cursor() as cur:
        await cur.execute("SELECT 1 FROM worker_profile WHERE worker_id = %s", (user_id,))
        worker = await cur.fetchone()

        if not worker:
            raise HTTPException(status_code=403, detail="Only workers can use saved jobs")


@router.post("/save", response_model=SaveJobResponeModel, status_code=status.HTTP_201_CREATED)
async def save_job(
    data: SaveJobRequestModel,
    conn: AsyncConnection = Depends(get_db_connection),
    user_id: str = Depends(get_current_user_id),
):
    try:
        async with conn.transaction():
            await _ensure_worker_profile(conn, user_id)

            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT j.job_id
                    FROM Jobs j
                    WHERE j.job_id = %s
                      AND (j.job_type = 'Public' OR j.target_worker = %s)
                    """,
                    (str(data.job_id), user_id),
                )
                job = await cur.fetchone()

                if not job:
                    raise HTTPException(status_code=404, detail="Job not found or not accessible")

                await cur.execute(
                    "SELECT 1 FROM Saved_Jobs WHERE job_id = %s AND worker_id = %s",
                    (str(data.job_id), user_id),
                )
                already_saved = await cur.fetchone()

                if already_saved:
                    raise HTTPException(status_code=409, detail="Job already saved")

                await cur.execute(
                    "INSERT INTO Saved_Jobs(job_id, worker_id) VALUES(%s, %s)",
                    (str(data.job_id), user_id),
                )

        return SaveJobResponeModel(message="Job saved successfully", job_id=data.job_id)
    except HTTPException:
        raise
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail="An error occurred while saving the job")


@router.delete("/saved/{job_id}", response_model=UnsaveJobResponseModel)
async def unsave_job(
    job_id: UUID,
    conn: AsyncConnection = Depends(get_db_connection),
    user_id: str = Depends(get_current_user_id),
):
    try:
        async with conn.transaction():
            await _ensure_worker_profile(conn, user_id)

            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    DELETE FROM Saved_Jobs
                    WHERE job_id = %s AND worker_id = %s
                    RETURNING job_id
                    """,
                    (str(job_id), user_id),
                )
                deleted = await cur.fetchone()

                if not deleted:
                    raise HTTPException(status_code=404, detail="Saved job not found")

        return UnsaveJobResponseModel(message="Job unsaved successfully", job_id=job_id)
    except HTTPException:
        raise
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail="An error occurred while unsaving the job")


@router.get("/saved", response_model=SavedJobsResponseModel)
async def get_saved_jobs(
    conn: AsyncConnection = Depends(get_db_connection),
    user_id: str = Depends(get_current_user_id),
):
    query = """
        SELECT
            j.job_id,
            c.full_name AS client_name,
            j.title AS job_title,
            j.description AS job_description,
            j.location_address AS job_location,
            COALESCE(j.estimated_budget, 0) AS job_budget,
            j.job_type,
            j.status AS job_status,
            s.service_name
        FROM Saved_Jobs sj
        JOIN Jobs j ON j.job_id = sj.job_id
        JOIN Users c ON c.user_id = j.client_id
        JOIN Services s ON s.service_id = j.service_id
        WHERE sj.worker_id = %s
        ORDER BY j.created_at DESC
    """

    try:
        await _ensure_worker_profile(conn, user_id)

        async with conn.cursor() as cur:
            await cur.execute(query, (user_id,))
            rows = await cur.fetchall()

            jobs = [
                SavedJobData(
                    job_id=row["job_id"],
                    client_name=row["client_name"],
                    job_title=row["job_title"],
                    job_description=row["job_description"],
                    job_location=row["job_location"],
                    job_budget=float(row["job_budget"]),
                    job_type=row["job_type"],
                    job_status=row["job_status"],
                    service_name=row["service_name"],
                )
                for row in rows
            ]

            return SavedJobsResponseModel(job_data=jobs)
    except HTTPException:
        raise
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail="An error occurred while fetching saved jobs")



#Create Job
@router.post("/create", response_model=CreateJobResponseModel)
async def create_job(data : CreateJobModel, conn : AsyncConnection = Depends(get_db_connection), user_id : str = Depends(get_current_user_id)) :
    try :
        async with conn.transaction() :
            notifications = []
            async with conn.cursor() as cur :
                query_public = """INSERT INTO Jobs(service_id, title,description,job_type,status, location_address, city, estimated_budget, client_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING job_id"""

                query_direct = """INSERT INTO Jobs(service_id, title,description,job_type,status, location_address, city, estimated_budget, client_id, target_worker) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING job_id"""

                print(data)

                if data.job_type == JobType.PUBLIC :
                    await cur.execute(query_public, (data.service_id, data.title, data.description, data.job_type.value, "Open", data.location, data.city, data.budget, user_id,))

                    print("Public Job Created")

                elif data.job_type == JobType.DIRECT :
                    if not data.target_worker :
                        raise HTTPException(status_code=400, detail="Target worker must be specified for direct jobs")
                    
                    # NEW: Validate that target_worker exists and has Worker role
                    await cur.execute(
                        "SELECT u.user_id FROM Users u JOIN worker_profile wp ON wp.worker_id = u.user_id WHERE u.user_id = %s AND u.role = 'Worker'",
                        (str(data.target_worker),)
                    )
                    worker_check = await cur.fetchone()
                    if not worker_check:
                        raise HTTPException(status_code=400, detail="Target worker does not exist or is not a valid worker.")
                    
                    await cur.execute(query_direct, (data.service_id, data.title, data.description, data.job_type.value, "Open", data.location, data.city, data.budget, user_id, data.target_worker,))

                job_row = await cur.fetchone()
                print(job_row)
                if not job_row :
                    raise HTTPException(status_code=500, detail="Job created but no job_id returned")

                job_id = job_row["job_id"]
                print(job_id)

                if data.job_type == JobType.PUBLIC:
                    await cur.execute(
                        """
                        SELECT DISTINCT u.user_id
                        FROM worker_skills ws
                        JOIN Users u ON u.user_id = ws.worker_id
                        WHERE ws.service_id = %s
                          AND u.city = %s
                          AND u.is_active = true
                          AND u.role = 'Worker'
                        """,
                        (str(data.service_id), data.city),
                    )
                    workers = await cur.fetchall()
                    for worker in workers:
                        notifications.append(
                            await persist_notification(
                                conn,
                                NotificationCreate(
                                    recipient_id=worker["user_id"],
                                    actor_id=UUID(user_id),
                                    notification_type="job_created",
                                    title="New job available",
                                    body=f"A new job '{data.title}' was posted in {data.city}.",
                                    entity_type="job",
                                    entity_id=job_id,
                                    metadata={
                                        "service_id": str(data.service_id),
                                        "city": data.city,
                                    },
                                ),
                            )
                        )
                else:
                    notifications.append(
                        await persist_notification(
                            conn,
                            NotificationCreate(
                                recipient_id=UUID(str(data.target_worker)),
                                actor_id=UUID(user_id),
                                notification_type="job_created",
                                title="You have a direct job invitation",
                                body=f"You were invited to a direct job: '{data.title}'.",
                                entity_type="job",
                                entity_id=job_id,
                                metadata={
                                    "service_id": str(data.service_id),
                                    "city": data.city,
                                },
                            ),
                        )
                    )

        for notification in notifications:
            await broadcast_notification(notification)

        return CreateJobResponseModel(
            job_id=job_id
        )
    except HTTPException:
        raise
    except Exception as e :
        print(e)
        raise HTTPException(status_code=500, detail="An error occurred while creating the job")


@router.get("/worker-by-email")
async def get_worker_by_email(
    email: EmailStr,
    conn: AsyncConnection = Depends(get_db_connection),
    user_id: str = Depends(get_current_user_id),
):
    try:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT wp.worker_id, u.full_name
                FROM Users u
                JOIN worker_profile wp ON wp.worker_id = u.user_id
                WHERE u.email = %s AND u.role = 'Worker'
                """,
                (email,),
            )
            worker = await cur.fetchone()

            if not worker:
                raise HTTPException(status_code=404, detail="Worker does not exist")

            return {"worker_id": worker["worker_id"], "full_name" : worker["full_name"]}
    except HTTPException:
        raise
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail="An error occurred while fetching worker")

#Get Job by iD
@router.get("/by-id/{job_id}")
async def get_job_by_id(job_id: str, conn: AsyncConnection = Depends(get_db_connection), user_id : str = Depends(get_current_user_id)) :
    try :
        async with conn.cursor() as cur :
            query = """
            SELECT j.job_id,
            j.title as job_title,
            j.description as job_description,
            COALESCE(j.estimated_budget, 0) AS job_budget,
            j.location_address as job_location,
            c.full_name as client_name,
            s.service_name 
            FROM Jobs j JOIN services s ON s.service_id = j.service_id
            JOIN users c ON c.user_id = j.client_id
            WHERE j.job_id = %s AND 
            (j.job_type = 'Public' OR j.target_worker=%s OR j.client_id=%s)
            """

            print(user_id)
            await cur.execute(query, (job_id, user_id, user_id,))
            job = await cur.fetchone()

            if not job:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

            return {
                "message" : "Job found succesfully",
                "job" : job
            }
    except Exception as e :
        print(e)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not get job details")

#Get All Jobs
@router.get("/feed", response_model=JobFeedData)
async def get_job_feed(
    conn : AsyncConnection = Depends(get_db_connection),
    user_id : str = Depends(get_current_user_id),
    page : int = Query(1, ge=1),
    page_size : int = Query(20, ge=1, le=100),
    min_budget : float | None = Query(None, ge=0),
    max_budget : float | None = Query(None, ge=0),
    search : str | None = Query(None, min_length=1),
) :
    # To Do : Take out city of the user from the table, find out all jobs that match that workers skills and are in the same city, order them by most recent and return them as feed with pagination and filtering options

    user_city_query = """SELECT city FROM Users WHERE user_id = %s"""

    feed_query = """
        SELECT
            j.job_id,
            j.title AS job_title,
            j.description AS job_description,
            COALESCE(j.estimated_budget, 0) AS job_budget,
            j.location_address AS job_location,
            s.service_name,
            c.full_name AS client_name
        FROM Jobs j
        JOIN Users c ON c.user_id = j.client_id
        JOIN Services s ON j.service_id = s.service_id
        WHERE j.status = 'Open'
          AND (
              (
                  j.job_type = 'Public'
                  AND j.city = %s
                  AND j.service_id IN (
                      SELECT ws.service_id
                      FROM worker_skills ws
                      WHERE ws.worker_id = %s
                  )
              )
              OR
              (
                  j.job_type = 'Direct'
                  AND j.target_worker = %s
              )
          )
        ORDER BY j.created_at DESC
                LIMIT %s OFFSET %s
    """

    try :
        async with conn.cursor() as cur :
            await cur.execute(user_city_query, (user_id,))
            user_row = await cur.fetchone()

            if not user_row :
                raise HTTPException(status_code=404, detail="User not found")

            user_city = user_row["city"]

            if min_budget is not None and max_budget is not None and min_budget > max_budget:
                raise HTTPException(status_code=400, detail="min_budget cannot be greater than max_budget")

            offset = (page - 1) * page_size

            await cur.execute(
                feed_query,
                (
                    user_city,
                    user_id,
                    user_id,
                    page_size,
                    offset,
                ),
            )
            rows = await cur.fetchall()

            job_data = [
                JobData(
                    job_id=row["job_id"],
                    client_name=row["client_name"],
                    job_title=row["job_title"],
                    job_description=row["job_description"],
                    job_location=row["job_location"],
                    job_budget=float(row["job_budget"]),
                    service_name=row["service_name"],
                )
                for row in rows
            ]

            return JobFeedData(job_data=job_data)
    except HTTPException:
        raise
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail="An error occurred while fetching the job feed")


@router.get("/working", response_model=list[WorkerActiveJobData])
async def get_worker_active_jobs(
    conn: AsyncConnection = Depends(get_db_connection),
    user_id: str = Depends(get_current_user_id),
):
    try:
        # ensure worker profile exists
        await _ensure_worker_profile(conn, user_id)

        query = """
            SELECT
                b.booking_id,
                j.job_id,
                j.title AS job_title,
                j.description AS job_description,
                j.location_address AS job_location,
                j.city,
                COALESCE(b.agreed_price, j.estimated_budget, 0) AS price,
                s.service_name,
                j.client_id,
                c.full_name AS client_name,
                b.status AS booking_status,
                j.status AS job_status,
                b.eta,
                b.created_at
            FROM Bookings b
            JOIN Jobs j ON b.job_id = j.job_id
            JOIN Users c ON j.client_id = c.user_id
            JOIN Services s ON j.service_id = s.service_id
            WHERE b.worker_id = %s
              AND (b.status = 'Scheduled' OR j.status = 'In Progress')
            ORDER BY b.created_at DESC
        """

        async with conn.cursor() as cur:
            await cur.execute(query, (user_id,))
            rows = await cur.fetchall()

            results = [
                WorkerActiveJobData(
                    booking_id=row["booking_id"],
                    job_id=row["job_id"],
                    job_title=row["job_title"],
                    job_description=row["job_description"],
                    job_location=row["job_location"],
                    city=row["city"],
                    price=float(row["price"]),
                    service_name=row["service_name"],
                    client_id=row["client_id"],
                    client_name=row["client_name"],
                    booking_status=row["booking_status"],
                    job_status=row["job_status"],
                    eta=row["eta"],
                    created_at=row["created_at"],
                )
                for row in rows
            ]

            return results
    except HTTPException:
        raise
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail="An error occurred while fetching active jobs for worker")
    
#Get all jobs created by authenticated client
@router.get("/my-jobs", response_model=ClientJobResponseData)
async def get_all_jobs_created_by_me(
    client_id: str = Depends(get_current_user_id),
    conn: AsyncConnection = Depends(get_db_connection),
):
    query = """
        SELECT
        j.job_id,
            j.title AS job_title,
            j.description AS job_description,
            COALESCE(j.estimated_budget, 0) AS job_budget,
            j.location_address AS job_location,
            j.job_type,
            j.city,
            j.status AS job_status,
            s.service_name
        FROM Jobs j
        JOIN Services s ON s.service_id = j.service_id
        WHERE j.client_id = %s
        ORDER BY j.created_at DESC
    """

    try:
        async with conn.cursor() as cur:
            await cur.execute(query, (client_id,))
            rows = await cur.fetchall()

            jobs = [
                {
                    "job_id":row["job_id"],
                    "job_title": row["job_title"],
                    "job_description": row["job_description"],
                    "job_budget": float(row["job_budget"]),
                    "job_location": row["job_location"],
                    "job_type": row["job_type"],
                    "job_status": row["job_status"],
                    "city" : row["city"], 
                    "service_name": row["service_name"],
                }
                for row in rows
            ]

            return {
                "message": "Jobs fetched successfully",
                "job_data": jobs,
            }
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail="An error occurred while fetching jobs")

