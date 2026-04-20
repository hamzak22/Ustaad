from pydantic import BaseModel
from uuid import UUID
from typing import Optional


class CreateBidRequest(BaseModel):
    job_id: UUID
    proposed_price: float
    eta: str
    description: Optional[str] = None

class BidResponse(BaseModel):
    bid_id: UUID
    worker_id: UUID
    worker_name: str
    worker_rating: float
    proposed_price: float
    eta: str
    description: Optional[str] = None
    status: str


