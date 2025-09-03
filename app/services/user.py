from datetime import datetime
import os
from typing import Optional, Dict, Any, List

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import HTTPException

from app.utils.hash import hash_password, generate_temp_password, generate_tenant_id
from app.schemas.user import AnswerCreate
from app.models.user import generate_uuid, AnswerModel 

async def create_user(db: AsyncIOMotorDatabase, user: Dict[str, Any]) -> Dict[str, Any]:
    tenant_id = generate_tenant_id()
    new_user = {
        "username": user.username,
        "email": user.email,
        "password": hash_password(user.password),
        "tenant_id": tenant_id,
        "created_at": datetime.utcnow(),
        "is_temp_password": False
    }
    result = await db.users.insert_one(new_user)
    new_user["_id"] = result.inserted_id
    return new_user

async def get_user_by_username(db: AsyncIOMotorDatabase, username: str) -> Optional[Dict[str, Any]]:
    return await db.users.find_one({"username": username})
async def get_user_by_email(db: AsyncIOMotorDatabase, email: str) -> Optional[Dict[str, Any]]:
    return await db.users.find_one({"email": email})

async def forgot_password(db: AsyncIOMotorDatabase, email: str) -> Optional[str]:
    user = await db.users.find_one({"email": email})
    if not user:
        return None

    temp_pass = generate_temp_password()
    await db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {
            "password": hash_password(temp_pass),
            "is_temp_password": True
        }}
    )
    return temp_pass

async def save_extracted_cv_data(db: AsyncIOMotorDatabase, user_id: str, parsed_data: dict, file_path: str) -> Dict[str, Any]:
    file_url = f"/uploads/{os.path.basename(file_path)}"

    upload_doc = {
        "user_id": ObjectId(user_id),
        "file_url": file_url,
        "source": "cv",
        "parsed_data": parsed_data,
        "uploaded_at": datetime.utcnow()
    }
    result = await db.uploads.insert_one(upload_doc)
    upload_doc["_id"] = result.inserted_id 

    profile_update = {
        "bio": parsed_data.get("Summary", ""),
        "education_summary": ", ".join([edu.get("Degree", "") for edu in parsed_data.get("Education", [])]),
        "years_experience": parsed_data.get("YearsOfExperience", 0)
    }
    await db.user_profiles.update_one(
        {"user_id": ObjectId(user_id)},
        {"$set": profile_update},
        upsert=True
    )

    for skill_type in ["HardSkills", "SoftSkills"]:
        skill_list = parsed_data.get("Skills", {}).get(skill_type, [])
        for skill_name in skill_list:
            skill_doc = await db.skills.find_one({"name": skill_name})
            if not skill_doc:
                skill_doc = {
                    "name": skill_name,
                    "type": "hard" if skill_type == "HardSkills" else "soft"
                }
                result = await db.skills.insert_one(skill_doc)
                skill_id = result.inserted_id
            else:
                skill_id = skill_doc["_id"]

            existing_link = await db.user_skills.find_one({
                "user_id": ObjectId(user_id),
                "skill_id": skill_id
            })
            if not existing_link:
                await db.user_skills.insert_one({
                    "user_id": ObjectId(user_id),
                    "skill_id": skill_id
                })

    return upload_doc

async def save_latest_cv_answers(db, current_user: dict, section: str, answers: list):
    """
    Save answers for the latest uploaded CV.
    """
    user_id = current_user.get("id") or current_user.get("_id")

    try:
        user_id = ObjectId(str(user_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid user_id")

    latest_cv = await db["uploads"].find_one(
        {"user_id": user_id},
        sort=[("uploaded_at", -1)]
    )

    if not latest_cv:
        raise HTTPException(status_code=404, detail="No CV uploaded yet")

    cv_id = str(latest_cv["_id"])

    answer_docs = []
    for ans in answers:
        answer_docs.append(
            AnswerModel(
                user_id=str(user_id),
                tenant_id=str(current_user.get("tenant_id")),
                cv_id=cv_id,
                section=section,
                parameter=ans["parameter"],
                answer_type=ans.get("answer_type", "Short text + Edit view"),
                selected_options=ans.get("selected_options", []),
                free_text=ans.get("free_text"),
                created_at=datetime.utcnow()
            ).dict(by_alias=True)
        )

    if answer_docs:
        await db["answers"].insert_many(answer_docs)

    return {"message": "Answers saved successfully", "cv_id": cv_id}

