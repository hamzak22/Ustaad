from pydantic import BaseModel, Field
from uuid import UUID
from typing import Optional, List
from datetime import datetime
from modules.reviews.models import ReviewResponse


class CreateBidRequest(BaseModel):
    job_id: UUID
    proposed_price: float
    fee_type: str = Field(..., pattern='^(Hourly|Flat)$')
    eta: str
    cover_letter: Optional[str] = None
    attached_review_ids: Optional[List[UUID]] = None


class BidResponse(BaseModel):
    bid_id: UUID
    worker_id: UUID
    worker_name: str
    worker_city: Optional[str]
    worker_rating: float
    proposed_price: float
    fee_type: str
    eta: str
    cover_letter: Optional[str] = None
    attached_reviews: List[ReviewResponse] = []
    status: str


class ProposalResponse(BaseModel):
    bid_id: UUID
    job_id: UUID
    job_title: str
    job_description: str
    client_id: UUID
    client_name: str
    proposed_price: float
    fee_type: str
    eta: str
    cover_letter: Optional[str] = None
    attached_reviews: List[ReviewResponse] = []
    status: str
    created_at: datetime


class BookingResponse(BaseModel):
    booking_id: UUID
    job_id: UUID
    job_title: str
    job_description: str
    service_name: str
    worker_id: UUID
    worker_name: str
    worker_city: Optional[str]
    worker_rating: float
    agreed_price: float
    eta: str
    booking_status: str
    job_status: str
    created_at: datetime


class DirectJobResponseModel(BaseModel):
    response_status: str = Field(..., pattern='^(Accepted|Declined)$')


class CompleteBookingWithReviewRequest(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = None


