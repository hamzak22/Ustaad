from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from uuid import UUID

class WorkerServiceRateItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    service_id: UUID = Field(alias="id")
    hourly_rate: float

class UpdateWorkerProfileRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    bio: Optional[str] = None
    phone_number: Optional[str] = None
    services: Optional[List[WorkerServiceRateItem]] = None
    hourly_rate: Optional[float] = Field(
        default=None,
        description="Optional shortcut for updating a single hourly rate when the worker handles only one service"
    )

class UserProfileResponse(BaseModel):
    user_id: UUID
    full_name: str
    email: str
    phone_number: Optional[str] = None
    role: str
    bio: Optional[str] = None
    skills: List[dict] = [] 

    