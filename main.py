from fastapi import FastAPI, Depends
from contextlib import asynccontextmanager
from psycopg_pool import AsyncConnectionPool

import database
from database import get_db_connection



import asyncio

DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/ustaad_db"

@asynccontextmanager
async def Lifespan(app:FastAPI) :
    print("Initializing Database pool....")

    database.pool = AsyncConnectionPool(conninfo=DATABASE_URL, open=True)

    yield

    print("Shutting down database pool...")
    if database.pool :
        await database.pool.close()


app = FastAPI(lifespan=Lifespan)




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