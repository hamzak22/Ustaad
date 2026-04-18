from fastapi import FastAPI, Depends
from contextlib import asynccontextmanager
from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row

import database
from database import get_db_connection

#routers
from modules.auth.routes import router as auth_router
from modules.services.routes import router as services_router
from modules.jobs.routes import router as jobs_router

import asyncio

from core.config import get_settings

settings = get_settings() 


DATABASE_URL = f"postgresql://{settings.DB_USERNAME}:{settings.DB_PASSWORD}@{settings.DB_HOST}:5432/ustaad_db"


@asynccontextmanager
async def Lifespan(app:FastAPI) :
    print("Initializing Database pool....")

    database.pool = AsyncConnectionPool(conninfo=DATABASE_URL, open=True, kwargs={"row_factory" : dict_row})

    yield

    print("Shutting down database pool...")
    if database.pool :
        await database.pool.close()


app = FastAPI(lifespan=Lifespan)

app.include_router(auth_router)
app.include_router(services_router)
app.include_router(jobs_router)


@app.get("/")
async def root():
    return {"message": "Javed Javed"}

@app.get("/db-test")
async def test_db(conn = Depends(get_db_connection)) :
    async with conn.cursor() as cur :
        await cur.execute('SELECT version()')
        record = await cur.fetchone()

    return {
        "status" : "Completed",
        "version" : record[0]
    }