from pydantic import BaseModel
from uuid import UUID

class LocationResponse(BaseModel):
    location_id: UUID
    location_name: str