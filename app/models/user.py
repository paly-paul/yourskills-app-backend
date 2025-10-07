
from datetime import datetime
from typing import Optional, Dict, Any, List, Union
from pydantic import BaseModel, EmailStr, Field
import uuid

def generate_uuid() -> str:
    return str(uuid.uuid4())

class UserModel(BaseModel):
    id: str = Field(default_factory=generate_uuid, alias="_id")  
    tenant_id: str = Field(default_factory=generate_uuid)
    name: str
    email: EmailStr
    password_hash: str
    stage: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True

class SkillModel(BaseModel):
    id: str = Field(default_factory=generate_uuid, alias="_id")
    name: str
    type: Optional[str] = None

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True


class UserSkillModel(BaseModel):
    id: str = Field(default_factory=generate_uuid, alias="_id")
    user_id: str
    skill_id: str
    tenant_id: str
    source: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True

class UserProfileModel(BaseModel):
    id: str = Field(default_factory=generate_uuid, alias="_id")
    user_id: str
    tenant_id: str
    bio: Optional[str] = None
    photo_url: Optional[str] = None
    education_summary: Optional[str] = None
    years_experience: Optional[int] = None

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True


class UploadModel(BaseModel):
    id: str = Field(default_factory=generate_uuid, alias="_id")
    user_id: str
    tenant_id: str
    file_url: str
    source: Optional[str] = None
    parsed_data: Dict[str, Any]
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True


class SkillSuggestionModel(BaseModel):
    id: str = Field(default_factory=generate_uuid, alias="_id")
    user_id: str
    cv_id: str
    softskills_suggestions: List[str] = Field(default_factory=list)
    technical_skills_suggestions: List[str] = Field(default_factory=list)
    certifications_suggestions: List[str] = Field(default_factory=list)  
    created_at: datetime = Field(default_factory=datetime.utcnow)

class AnswerModel(BaseModel):
    id: str = Field(default_factory=generate_uuid, alias="_id")
    user_id: str
    tenant_id: str
    cv_id: str
    section: str
    parameter: str
    answer_type: str
    value: Optional[Union[str, List[str], Dict[str, str]]] = None
    limit: Optional[int] = None  
    created_at: datetime = Field(default_factory=datetime.utcnow)

class AnswerWithoutCvModel(BaseModel):
    id: str = Field(default_factory=generate_uuid, alias="_id")
    user_id: str
    tenant_id: str
    section: str
    parameter: str
    answer_type: str
    value: Optional[Union[str, List[str], Dict[str, str]]] = None
    limit: Optional[int] = None  
    document_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)







