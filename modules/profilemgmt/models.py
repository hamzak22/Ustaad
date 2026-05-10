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


# Worker Search Models
class WorkerSkillInfo(BaseModel):
    """Skill info for worker search results"""
    service_id: UUID
    service_name: str
    hourly_rate: float


class WorkerSearchResultItem(BaseModel):
    """Single worker in search results"""
    user_id: UUID
    full_name: str
    email: str
    phone_number: Optional[str] = None
    city: str
    worker_id: UUID
    experience: int
    availability: str
    bio: Optional[str] = None
    average_rating: float
    total_reviews: int
    skills: List[WorkerSkillInfo] = []


class WorkerSearchRequest(BaseModel):
    """Request model for searching workers"""
    service_id: Optional[UUID] = Field(None, description="Filter by service/skill UUID")
    city: Optional[str] = Field(None, description="Filter by city name")
    min_rating: Optional[float] = Field(None, ge=0, le=5, description="Minimum average rating (0-5)")
    availability: Optional[str] = Field(None, description="Filter by availability (Available, Busy, Offline)")
    search_query: Optional[str] = Field(None, description="Search by worker name or bio")
    limit: int = Field(10, ge=1, le=100, description="Number of results to return")
    offset: int = Field(0, ge=0, description="Pagination offset")


class WorkerReviewItem(BaseModel):
    """Single review for a worker"""
    review_id: UUID
    rating: int
    comment: Optional[str] = None
    created_at: str
    customer_name: str
    job_title: str


class WorkerDetailedProfile(BaseModel):
    """Detailed worker profile for customer view"""
    user_id: UUID
    full_name: str
    email: str
    phone_number: Optional[str] = None
    city: str
    created_at: str
    worker_id: UUID
    experience: int
    availability: str
    bio: Optional[str] = None
    average_rating: float
    total_reviews: int
    skills: List[WorkerSkillInfo] = []
    recent_reviews: List[WorkerReviewItem] = []


class WorkerSearchResponse(BaseModel):
    """Response model for worker search"""
    total_count: Optional[int] = None
    limit: int
    offset: int
    workers: List[WorkerSearchResultItem]
    