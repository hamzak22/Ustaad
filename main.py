from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row

import database
from database import get_db_connection

#routers
from modules.auth.routes import router as auth_router
from modules.services.routes import router as services_router
from modules.profilemgmt import routes as profile_routes
from modules.locations import routes as locations_routes
from modules.jobs.routes import router as jobs_router
from modules.bids_bookings.routers import router as bids_bookings_router
from modules.reviews.routes import router as reviews_router
from modules.notifications.routes import router as notifications_router



import asyncio

from core.config import get_settings

settings = get_settings() 


DATABASE_URL = settings.DB_URL


@asynccontextmanager
async def Lifespan(app:FastAPI) :
    print("Initializing Database pool....")

    database.pool = AsyncConnectionPool(
    conninfo=DATABASE_URL,
    open=True,
    min_size=1,
    max_size=10,
    max_idle=300,                          # ✅ close idle connections after 5 mins
    reconnect_timeout=30,                  # ✅ auto reconnect if connection drops
    kwargs={
        "row_factory": dict_row,
        # Disable server-side prepared statements (PgBouncer/transaction pooling safe).
        "prepare_threshold": None,
        "keepalives": 1,                   # ✅ enable TCP keepalives
        "keepalives_idle": 60,             # ✅ send keepalive after 60s idle
        "keepalives_interval": 10,         # ✅ retry every 10s
        "keepalives_count": 5,             # ✅ drop after 5 failed keepalives
    }
)
    app.state.db_pool = database.pool

    yield

    print("Shutting down database pool...")
    if database.pool :
        await database.pool.close()


app = FastAPI(lifespan=Lifespan)

allowed_origins = [
    "http://localhost:5173",
    "https://ustaad-frontend.vercel.app"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(auth_router, prefix="/api")
app.include_router(services_router, prefix="/api")
app.include_router(profile_routes.router, prefix="/api")
app.include_router(locations_routes.router, prefix="/api")
app.include_router(jobs_router, prefix="/api")
app.include_router(bids_bookings_router, prefix="/api")
app.include_router(reviews_router, prefix="/api")
app.include_router(notifications_router, prefix="/api")







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