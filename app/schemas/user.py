
from pydantic import BaseModel, EmailStr, field_validator, model_validator, constr
from typing import Optional, List, Dict, Union, Any
from datetime import datetime
import uuid


class UserCreate(BaseModel):
    first_name: constr(strip_whitespace=True, min_length=1)
    last_name: constr(strip_whitespace=True, min_length=1)
    username: constr(strip_whitespace=True, min_length=1)
    email: EmailStr
    password: constr(min_length=4)

from typing import Optional, Union
from pydantic import BaseModel, EmailStr, field_validator

class UserLogin(BaseModel):
    email: Optional[Union[EmailStr, str]] = None
    password: str

    @field_validator("email", mode="before")
    @classmethod
    def empty_string_to_none(cls, v):
        return v or None
    @classmethod
    def model_validate(cls, values):
        if not values.get("email"):
            raise ValueError("Email must be provided")
        return values


class UserUpdate(BaseModel):
    name: Optional[str] = None
    stage: Optional[str] = None
    updated_at: datetime = datetime.utcnow()

class UserResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    email: EmailStr
    stage: Optional[str]
    created_at: datetime
    updated_at: datetime

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class SkillCreate(BaseModel):
    name: str
    type: Optional[str] = None

class SkillResponse(BaseModel):
    id: str
    name: str
    type: Optional[str] = None

class UserSkillCreate(BaseModel):
    user_id: str
    skill_id: str
    tenant_id: str
    source: Optional[str] = None

class UserSkillResponse(BaseModel):
    id: str
    user_id: str
    skill_id: str
    tenant_id: str
    source: Optional[str]
    created_at: datetime


class UserProfileCreate(BaseModel):
    user_id: str
    tenant_id: str
    bio: Optional[str] = None
    photo_url: Optional[str] = None
    education_summary: Optional[str] = None
    years_experience: Optional[int] = None

class UserProfileResponse(BaseModel):
    id: str
    user_id: str
    tenant_id: str
    bio: Optional[str]
    photo_url: Optional[str]
    education_summary: Optional[str]
    years_experience: Optional[int]

class UploadCreate(BaseModel):
    user_id: str
    tenant_id: str
    file_url: str
    source: Optional[str] = None
    parsed_data: Dict

class UploadResponse(BaseModel):
    id: str
    user_id: str
    tenant_id: str
    file_url: str
    source: Optional[str]
    parsed_data: Dict
    uploaded_at: datetime

class SkillIn(BaseModel):
    name: str
    type: str

class ResumeExtractResponse(BaseModel):
    bio: Optional[str]
    education_summary: Optional[str]
    years_experience: Optional[int]
    skills: List[SkillIn]




class AnswerCreate(BaseModel):
    parameter: str
    answer_type: str
    value: Optional[Union[str, List[str], Dict[str, str]]] = None
    limit: Optional[int] = None 


class AnswersSubmit(BaseModel):
    answers: List[AnswerCreate]

class UserInfo(BaseModel):
    id: str
    username: Optional[str]
    email: Optional[str]
    tenant_id: Optional[str]
    created_at: Optional[datetime]


class FinalSnapshot(BaseModel):
    snapshot_version: Optional[str]
    result: Optional[Dict[str, Any]]
    created_at: Optional[datetime]


class ModelResult(BaseModel):
    created_at: Optional[datetime]
    result: Optional[Dict[str, Any]]


class UserManagementResponse(BaseModel):
    user: UserInfo
    final_snapshot: Optional[FinalSnapshot]
    models: Dict[str, ModelResult]
    

class EditProfileRequest(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[EmailStr] = None
    current_password: Optional[str] = None
    new_password: Optional[str] = None

    class Config:
        orm_mode = True