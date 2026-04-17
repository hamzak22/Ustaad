from psycopg_pool import AsyncConnectionPool
from typing import AsyncGenerator
import psycopg

pool : AsyncConnectionPool | None = None


async def get_db_connection() -> AsyncGenerator[psycopg.AsyncConnection, None] :
    if pool is None :
        raise Exception("Database is not initialized")
    
    async with pool.connection() as conn :
        yield conn 
        
    
