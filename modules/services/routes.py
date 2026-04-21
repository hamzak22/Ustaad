from fastapi import APIRouter, Depends, HTTPException, status
import psycopg

from uuid import UUID  

from database import get_db_connection
from .models import ServiceResponse

router = APIRouter(prefix="/services", tags=["Services"])


# ENDPOINT 1: Get All Services
@router.get("/", response_model=list[ServiceResponse])
async def get_all_services(conn: psycopg.AsyncConnection = Depends(get_db_connection)):
    print("hello")
    async with conn.cursor() as cur:
        
        await cur.execute("SELECT service_id, service_name, description FROM Services;")
        
        rows = await cur.fetchall()

        
            
        return rows



# ENDPOINT 2: Get a Single Service
@router.get("/{service_id}", response_model=ServiceResponse)
async def get_single_service(
    service_id: UUID, 
    conn: psycopg.AsyncConnection = Depends(get_db_connection)
):
    
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT service_id, service_name, description FROM Services WHERE service_id = %s;", 
            (service_id,) 
        )
        
        row = await cur.fetchone()
        
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail="Service not found"
            )
            
        return row