from pydantic import BaseModel, EmailStr
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from typing import Optional, Union
from pydantic import BaseModel, EmailStr, field_validator, model_validator

class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str

class UserLogin(BaseModel):
    username: Optional[str] = None
    email: Optional[Union[EmailStr, str]] = None
    password: str
    @field_validator("email", mode="before")
    @classmethod
    def empty_string_to_none(cls, v):
        return v or None

    @model_validator(mode="after")
    def check_identifier(cls, values):
        if not values.username and not values.email:
            raise ValueError("Either username or email must be provided")
        return values

class UserResponse(BaseModel):
    id: int
    username: str
    email: EmailStr
    
class ForgotPasswordRequest(BaseModel):
    email: EmailStr
    
class UploadResponse(BaseModel):
    id: int
    file_url: str
    source: str
    parsed_data: dict
    uploaded_at: datetime

class SkillIn(BaseModel):
    name: str
    type: str 

class ResumeExtractResponse(BaseModel):
    bio: Optional[str]
    education_summary: Optional[str]
    years_experience: Optional[int]
    skills: List[SkillIn]



    class Config:
        orm_mode = True
