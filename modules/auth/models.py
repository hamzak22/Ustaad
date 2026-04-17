from pydantic import BaseModel, Field, EmailStr, model_validator
from typing import Annotated

from .enums import UserRoleEnum, AvailabilityEnum

class RegisterUserModel(BaseModel) :
    full_name : str = Field(max_length=100, title="Full name of the user")
    email : EmailStr
    password : str = Field(min_length=8, description="Password must be greater than or equals to 8 characters")
    confirm_password : str = Field(min_length=8, description="Password must be greater than or equals to 8 characters")
    phone_number : str = Field(max_length=20)
    role : UserRoleEnum

    @model_validator(mode='after')
    def validate_password(self) :
        if self.password != self.confirm_password :
            raise ValueError("passwords do not match")
        
        return self
    
class RegisterAsWorkerModel(BaseModel) :
    worker_id : int 
    experience : int
    hourly_rate : float
    availability : AvailabilityEnum
    bio : str 

