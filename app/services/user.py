from sqlalchemy.orm import Session
from app.models import User
from app.schemas import UserCreate
from app.utils import hash_password
from app.models import User
from app.utils.hash import hash_password, generate_temp_password
from sqlalchemy.orm import Session
from app.models import Upload, UserProfile, Skill, UserSkill
from sqlalchemy.orm import Session
from datetime import datetime
import os
from app.utils.hash import generate_tenant_id


def create_user(db: Session, user: UserCreate):
    tenant_id = generate_tenant_id()
    db_user = User(
        username=user.username,
        email=user.email,
        password=hash_password(user.password),
        tenant_id=tenant_id
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def get_user_by_username(db: Session, username: str):
    return db.query(User).filter(User.username == username).first()

def forgot_password(db: Session, email: str) -> str | None:
    user = db.query(User).filter(User.email == email).first()
    if not user:
        return None

    temp_pass = generate_temp_password()
    user.password = hash_password(temp_pass)
    user.is_temp_password = True
    db.commit()
    return temp_pass

def save_extracted_cv_data(user_id: int, parsed_data: dict, file_path: str, db: Session):
    file_url = f"/uploads/{os.path.basename(file_path)}"
    
    upload = Upload(
        user_id=user_id,
        file_url=file_url,
        source="cv",
        parsed_data=parsed_data,
        uploaded_at=datetime.utcnow()
    )
    db.add(upload)

    existing = db.query(UserProfile).filter_by(user_id=user_id).first()
    if not existing:
        profile = UserProfile(
            user_id=user_id,
            bio=parsed_data.get("Summary", ""),
            education_summary=", ".join([edu.get("Degree", "") for edu in parsed_data.get("Education", [])]),
            years_experience=parsed_data.get("YearsExperience", 0)
        )
        db.add(profile)
    else:
        existing.bio = parsed_data.get("Summary", "")
        existing.education_summary = ", ".join([edu.get("Degree", "") for edu in parsed_data.get("Education", [])])
        existing.years_experience = parsed_data.get("YearsExperience", 0)

    for skill_type in ["HardSkills", "SoftSkills"]:
        skill_list = parsed_data.get("Skills", {}).get(skill_type, [])
        for skill_name in skill_list:
            skill = db.query(Skill).filter_by(name=skill_name).first()
            if not skill:
                skill = Skill(name=skill_name, type="hard" if skill_type == "HardSkills" else "soft")
                db.add(skill)
                db.flush()
            
            if not db.query(UserSkill).filter_by(user_id=user_id, skill_id=skill.id).first():
                user_skill = UserSkill(user_id=user_id, skill_id=skill.id)
                db.add(user_skill)

    db.commit()
    return {"message": "CV data extracted and saved successfully"}