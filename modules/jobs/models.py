from pydantic import BaseModel, Field
from uuid import UUID
from enum import Enum
from typing import Optional


class JobType(Enum):
    PUBLIC="Public"
    DIRECT="Direct"

class JOB_STATUS(Enum):
    OPEN="Open"
    IN_PROGRESS="In Progress"
    COMPLETED="Completed"
    CANCELLED="Cancelled"

class CreateJobModel(BaseModel) :
    service_id : UUID = Field(..., description="The ID of the service associated with the job")
    title : str = Field(..., description="The title of the job")
    description : str = Field(..., description="The description of the job")
    location : str = Field(..., description="The location of the job")
    city : str = Field(..., description="The city where the job will be performed")
    budget : float = Field(..., description="The budget offered for the job")
    job_type : JobType = Field(..., description="The type of the job (public or direct)")
    target_worker : UUID = Field(None, description="The ID of the target worker for direct jobs (optional)")


class CreateJobResponseModel(BaseModel) :
    job_id : UUID = Field(..., description="The ID of the created job")

class JobData(BaseModel) :
    job_id : str
    client_name : str
    job_title : str 
    job_description : str
    job_location : str
    job_budget : float
    service_name : str

class ClientJobResponse(BaseModel) :
    job_title : str 
    job_description : str
    job_location : str
    job_budget : float
    job_type : str
    job_status : str
    city: str
    service_name : str

class JobFeedData(BaseModel) :
    job_data : list[JobData]

class ClientJobResponseData(BaseModel) :
    message : str = "Jobs fetched successfully"
    job_data : list[ClientJobResponse]

class SaveJobRequestModel(BaseModel) :
    job_id : UUID 

class SaveJobResponeModel(BaseModel) : 
    message : str
    job_id : str
    
