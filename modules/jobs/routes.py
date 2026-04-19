from fastapi import APIRouter, Depends, HTTPException, Query, status
from psycopg import AsyncConnection

from .models import CreateJobResponseModel, CreateJobModel, JobFeedData, JobType, JobData
from database import get_db_connection

from modules.auth.routes import get_current_user_id


router = APIRouter(
    prefix="/jobs",
    tags=["jobs"]
)



#Create Job
@router.post("/create", response_model=CreateJobResponseModel)
async def create_job(data : CreateJobModel, conn : AsyncConnection = Depends(get_db_connection), user_id : str = Depends(get_current_user_id)) :
    try :
        async with conn.transaction() :
            async with conn.cursor() as cur :
                query_public = """INSERT INTO Jobs(service_id, title,description,job_type,status, location_address, estimated_budget, client_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING job_id"""

                query_direct = """INSERT INTO Jobs(service_id, title,description,job_type,status, location_address, estimated_budget, client_id, target_worker) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING job_id"""

                print(data)

                if data.job_type == JobType.PUBLIC :
                    await cur.execute(query_public, (data.service_id, data.title, data.description, data.job_type.value, "Open", data.location, data.budget, user_id,))

                    print("Public Job Created")

                elif data.job_type == JobType.DIRECT :
                    if not data.target_worker :
                        raise HTTPException(status_code=400, detail="Target worker must be specified for direct jobs")
                    
                    await cur.execute(query_direct, (data.service_id, data.title, data.description, data.job_type.value, "Open", data.location, data.budget, user_id, data.target_worker,))

                job_row = await cur.fetchone()
                print(job_row)
                if not job_row :
                    raise HTTPException(status_code=500, detail="Job created but no job_id returned")

                job_id = job_row["job_id"]
                print(job_id)

                return CreateJobResponseModel(
                    job_id=job_id
                )
    except HTTPException:
        raise
    except Exception as e :
        print(e)
        raise HTTPException(status_code=500, detail="An error occurred while creating the job")
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
        WHERE j.job_type = 'Public'
          AND j.status = 'Open'
          AND j.city = %s
          AND j.service_id IN (
              SELECT ws.service_id
              FROM worker_skills ws
              WHERE ws.worker_id = %s
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
                    page_size,
                    offset,
                ),
            )
            rows = await cur.fetchall()

            job_data = [
                JobData(
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
    
#Get all jobs created by authenticated client
@router.get("/my-jobs")
async def get_all_jobs_created_by_me(
    client_id: str = Depends(get_current_user_id),
    conn: AsyncConnection = Depends(get_db_connection),
):
    query = """
        SELECT
            j.title AS job_title,
            j.description AS job_description,
            COALESCE(j.estimated_budget, 0) AS job_budget,
            j.location_address AS job_location,
            j.job_type,
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
                    "job_title": row["job_title"],
                    "job_description": row["job_description"],
                    "job_budget": float(row["job_budget"]),
                    "job_location": row["job_location"],
                    "job_type": row["job_type"],
                    "job_status": row["job_status"],
                    "service_name": row["service_name"],
                }
                for row in rows
            ]

            return {
                "message": "Jobs fetched successfully",
                "jobs": jobs,
            }
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail="An error occurred while fetching jobs")










#Delete job by id
