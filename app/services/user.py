from datetime import datetime
import os
from typing import Optional, Dict, Any, List

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import HTTPException
import app.db.database as database

from pymongo import DESCENDING


from app.utils.hash import hash_password, generate_temp_password, generate_tenant_id
from app.schemas.user import AnswerCreate
from app.models.user import generate_uuid, AnswerModel, AnswerWithoutCvModel

async def create_user(db: AsyncIOMotorDatabase, user: Dict[str, Any]) -> Dict[str, Any]:
    tenant_id = generate_tenant_id()
    new_user = {
        "first_name": user.first_name,
        "last_name": user.last_name,
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
        answer_type = ans.get("answer_type", "Short text + Edit view")
        value = ans.get("value")
        limit = ans.get("limit")  
        if answer_type == "Multi-select + limit":
            if limit is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"Parameter '{ans['parameter']}' requires a 'limit' value"
                )
            if isinstance(value, list) and len(value) > limit:
                raise HTTPException(
                    status_code=400,
                    detail=f"Too many selections for parameter '{ans['parameter']}'. "
                           f"Allowed: {limit}, Provided: {len(value)}"
                )

        answer_docs.append(
            AnswerModel(
                user_id=str(user_id),
                tenant_id=str(current_user.get("tenant_id")),
                cv_id=cv_id,
                section=section,
                parameter=ans["parameter"],
                answer_type=answer_type,
                value=value,
                limit=limit,   
                created_at=datetime.utcnow()
            ).dict(by_alias=True)
        )

    if answer_docs:
        await db["answers"].insert_many(answer_docs)

    return {"message": "Answers saved successfully", "doc_id": cv_id}



async def save_answers_without_cv(
    db, current_user: dict, section: str, answers: list, document_id: ObjectId
):
    """
    Save answers that are not linked to any CV.
    Stored in 'answers_without_cv' collection with document_id reference.
    """
    user_id = current_user.get("id") or current_user.get("_id")

    try:
        user_id = ObjectId(str(user_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid user_id")

    answer_docs = []
    for ans in answers:
        answer_type = ans.get("answer_type", "Short text + Edit view")
        value = ans.get("value")
        limit = ans.get("limit")

        if answer_type == "Multi-select + limit":
            if limit is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"Parameter '{ans['parameter']}' requires a 'limit' value"
                )
            if isinstance(value, list) and len(value) > limit:
                raise HTTPException(
                    status_code=400,
                    detail=f"Too many selections for parameter '{ans['parameter']}'. "
                           f"Allowed: {limit}, Provided: {len(value)}"
                )

        answer_docs.append(
    AnswerWithoutCvModel(
        user_id=str(user_id),
        tenant_id=str(current_user.get("tenant_id")),
        section=section,
        parameter=ans["parameter"],
        answer_type=answer_type,
        value=value,
        limit=limit,
        created_at=datetime.utcnow(),
        document_id=str(document_id) 
    ).dict(by_alias=True)
)


    if answer_docs:
        await db["answers_without_cv"].insert_many(answer_docs)

    return {"message": "Answers saved successfully (without CV)", "document_id": str(document_id)}

# async def get_user_management_summary(user_id: str, reference_id: str):
#     if database.db is None:
#         raise RuntimeError("MongoDB not initialized")

#     # ---------------------------
#     # USER DETAILS
#     # ---------------------------
#     user_query = (
#         {"_id": ObjectId(user_id)}
#         if ObjectId.is_valid(user_id)
#         else {"_id": user_id}
#     )

#     user = await database.db["users"].find_one(
#         user_query,
#         {"password": 0}
#     )

#     if not user:
#         raise HTTPException(status_code=404, detail="User not found")

#     user_data = {
#         "id": str(user["_id"]),
#         "username": user.get("username"),
#         "email": user.get("email"),
#         "tenant_id": user.get("tenant_id"),
#         "created_at": user.get("created_at"),
#     }

#     # ---------------------------
#     # FINAL SNAPSHOT
#     # ---------------------------
#     final_snapshot_doc = await database.db["final_skill_snapshot"].find_one(
#         {
#             "user_id": user_id,
#             "reference_id": reference_id,
#         },
#         sort=[("created_at", DESCENDING)]
#     )

#     final_snapshot = None
#     if final_snapshot_doc:
#         final_snapshot = {
#             "snapshot_version": final_snapshot_doc.get("snapshot_version"),
#             "result": final_snapshot_doc.get("result"),
#             "created_at": final_snapshot_doc.get("created_at"),
#         }

#     # ---------------------------
#     # MODEL RESULTS
#     # ---------------------------
#     cursor = database.db["model_results"].find(
#         {
#             "user_id": user_id,
#             "reference_id": reference_id,
#         }
#     ).sort("created_at", DESCENDING)

#     models = {}

#     async for doc in cursor:
#         model_name = doc.get("model_name", "unknown")
#         models[model_name] = {
#             "created_at": doc.get("created_at"),
#             "result": doc.get("result"),
#         }

#     return {
#         "user": user_data,
#         "final_snapshot": final_snapshot,
#         "models": models,
#     }

from bson import ObjectId
from fastapi import HTTPException
from pymongo import DESCENDING
import app.db.database as database


async def get_user_management_summary(user_id: str):
    if database.db is None:
        raise RuntimeError("MongoDB not initialized")

    # 1️⃣ USER DETAILS
    user = await database.db["users"].find_one(
        {"_id": ObjectId(user_id)},
        {"password": 0}
    )

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user_data = {
        "id": str(user["_id"]),
        "username": user.get("username"),
        "email": user.get("email"),
        "tenant_id": user.get("tenant_id"),
        "created_at": user.get("created_at"),
    }

    # 2️⃣ FETCH ALL RESUMES (UPLOADS)
    uploads_cursor = database.db["uploads"].find(
        {"user_id": ObjectId(user_id)}
    ).sort("uploaded_at", DESCENDING)

    resumes = []

    async for upload in uploads_cursor:
        reference_id = upload.get("reference_id") or str(upload["_id"])

        # 3️⃣ FINAL SNAPSHOT (LATEST)
        final_snapshot_doc = await database.db["final_skill_snapshot"].find_one(
            {
                "user_id": user_id,
                "reference_id": reference_id,
            },
            sort=[("created_at", DESCENDING)]
        )

        final_snapshot = None
        if final_snapshot_doc:
            final_snapshot = {
                "snapshot_version": final_snapshot_doc.get("snapshot_version"),
                "result": final_snapshot_doc.get("result"),
                "created_at": final_snapshot_doc.get("created_at"),
            }

        # 4️⃣ MODEL RESULTS (LATEST PER MODEL)
        cursor = database.db["model_results"].find(
            {
                "user_id": user_id,
                "reference_id": reference_id,
            }
        ).sort("created_at", DESCENDING)

        models = {}
        async for doc in cursor:
            model_name = doc.get("model_name", "unknown")
            if model_name not in models:
                models[model_name] = {
                    "created_at": doc.get("created_at"),
                    "result": doc.get("result"),
                }

        resumes.append({
            "reference_id": reference_id,
            "uploaded_at": upload.get("uploaded_at"),
            "final_snapshot": final_snapshot,
            "models": models,
        })

    return {
        "user": user_data,
        "resumes": resumes,
    }
