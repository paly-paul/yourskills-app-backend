from pydantic import BaseModel, EmailStr
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

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
