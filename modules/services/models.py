from pydantic import BaseModel
from uuid import UUID

class ServiceResponse(BaseModel) :
    service_id : UUID
    service_name : str
    description : str | None = None

