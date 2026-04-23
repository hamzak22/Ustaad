from pydantic import BaseModel, Field
from uuid import UUID
from typing import Optional
from datetime import datetime

class CreateReviewRequest(BaseModel):
    booking_id: UUID
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = None

class ReviewResponse(BaseModel):
    review_id: UUID
    customer_name: str
    rating: int
    comment: Optional[str] = None
    created_at: datetime




    
