from fastapi import APIRouter, Depends, HTTPException, status
import psycopg

# ADJUST THIS IMPORT based on your project structure!
from database import get_db_connection
from modules.locations.models import LocationResponse

# Set up the router
router = APIRouter(prefix="/locations", tags=["Locations Catalog"])

# ==========================================
# ENDPOINT: Get All Locations
# URL: GET /api/locations
# ==========================================
@router.get("/", response_model=list[LocationResponse])
async def get_all_locations(conn: psycopg.AsyncConnection = Depends(get_db_connection)):
    """Fetches all supported cities/regions where Ustaad operates."""
    
    async with conn.cursor() as cur:
        # 1. Ask the database for all locations
        await cur.execute("SELECT location_id, location_name FROM Locations ORDER BY location_name ASC;")
        
        # 2. Fetch the rows (dict-style rows from psycopg dict_row)
        rows = await cur.fetchall()
        
        # 3. Format them into Python dictionaries
        locations_list = []
        for row in rows:
            locations_list.append({
                "location_id": row["location_id"],
                "location_name": row["location_name"]
            })
            
        # 4. Return the list to the Waiter!
        return locations_list