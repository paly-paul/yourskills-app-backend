from datetime import datetime
import os
from typing import Optional, Dict, Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.utils.hash import hash_password, generate_temp_password, generate_tenant_id

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
