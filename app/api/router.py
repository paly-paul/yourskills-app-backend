from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from app.db.database import get_database
from app.schemas import UserCreate, UserLogin, ForgotPasswordRequest, AnswersSubmit
from app.services.user import create_user, get_user_by_username, forgot_password, save_extracted_cv_data, save_latest_cv_answers
from app.utils import verify_password
from app.utils.cv_extractor import extract_cv_data_from_file, predict_audience_type, generate_missing_field_suggestions
from app.utils.token import create_access_token, get_current_user
from app.services.cv_comparison import get_cv_summary
from motor.motor_asyncio import AsyncIOMotorDatabase
import tempfile
from bson import ObjectId
import os
import google.generativeai as genai
import asyncio
import json
from datetime import datetime
from pymongo import DESCENDING
from app.services.skill_suggestions import save_skill_suggestions
from app.services.profile import (
    get_profile_summary_service,
    get_missing_field_questions_service,
    get_audience_questions_service,
    get_questions_by_audience
)

router = APIRouter()


@router.post("/register")
async def register(user: UserCreate, db=Depends(get_database)):
    existing = await get_user_by_username(db, user.username)
    if existing:
        return {"success": False, "reason": "Username already exists."}

    created_user = await create_user(db, user)
    token_data = {"user_id": str(created_user["_id"]), "username": created_user["username"]}
    access_token = create_access_token(token_data)

    return {
        "success": True,
        "token": access_token,
        "tenant_id": created_user["tenant_id"]
    }


@router.post("/login")
async def login(user: UserLogin, db=Depends(get_database)):
    db_user = None
    if user.username:
        db_user = await get_user_by_username(db, user.username)
    elif user.email:
        db_user = await db["users"].find_one({"email": user.email})

    if not db_user:
        return {"success": False, "reason": "User not found."}

    if not verify_password(user.password, db_user["password"]):
        return {"success": False, "reason": "Invalid password."}

    token_data = {"user_id": str(db_user["_id"]), "username": db_user["username"]}
    access_token = create_access_token(token_data)

    return {
        "success": True,
        "token": access_token,
        "tenant_id": db_user["tenant_id"]
    }


@router.get("/profile")
def get_profile(current_user=Depends(get_current_user)):
    if not current_user:
        return {"success": False, "reason": "Unauthorized access or token invalid."}

    profile_data = {
        "id": str(current_user["_id"]),
        "username": current_user["username"],
        "email": current_user["email"]
    }
    return {"success": True, "profile": profile_data}


@router.post("/forgot-password")
def forgot_password_route(payload: ForgotPasswordRequest, db=Depends(get_database)):
    temp_password = forgot_password(db, payload.email)
    if not temp_password:
        raise HTTPException(status_code=404, detail="User not found")

    return {"temp_password": temp_password, "message": "Use this to log in and reset your password"}


@router.post("/extract-cv")
async def extract_cv(
    file: UploadFile = File(...),
    db=Depends(get_database),
    current_user=Depends(get_current_user)
):
    import tempfile
    from app.utils.cv_extractor import (
        extract_cv_data_from_file,
        generate_missing_field_suggestions,
        predict_audience_type,
        generate_job_attribute_options,
        generate_anchor_attribute_options
    )

    with tempfile.NamedTemporaryFile(delete=False, suffix="." + file.filename.split('.')[-1]) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    data = extract_cv_data_from_file(tmp_path, file.content_type)
    if "error" in data:
        return {"message": "CV extraction failed", "error": data["error"]}

    saved_cv = await save_extracted_cv_data(
        user_id=current_user["id"],
        parsed_data=data,
        file_path=tmp_path,
        db=db
    )
    cv_id_str = str(saved_cv.get("_id"))

    softskills_suggestions, technical_skills_suggestions = [], []
    if not data.get("Skills", {}).get("SoftSkills") or not data.get("Skills", {}).get("HardSkills"):
        try:
            suggestions = await generate_missing_field_suggestions(data)
        except Exception:
            suggestions = {"softskills_suggestions": [], "technical_skills_suggestions": []}

        softskills_suggestions = suggestions.get("softskills_suggestions", [])
        technical_skills_suggestions = suggestions.get("technical_skills_suggestions", [])

    await save_skill_suggestions(
        user_id=current_user["id"],
        cv_id=cv_id_str,
        softskills=softskills_suggestions,
        technical_skills=technical_skills_suggestions,
        db=db
    )

    questions_collection = db["questions"]
    questions_doc = await questions_collection.find_one({})
    audience_type = predict_audience_type(data)

    job_questions_with_options = []
    anchor_questions_with_options = []  

    if questions_doc:

        job_attributes = questions_doc.get("Job attributes", [])
        matching_job = next((item for item in job_attributes if item.get("audienceType") == audience_type), None)

        if matching_job:
            job_questions = matching_job.get("questions", [])
            job_options = await generate_job_attribute_options(data, job_questions)
            job_questions_with_options = job_options["suggestions"]

        anchor_attributes = questions_doc.get("Anchor attributes", [])
        matching_anchor = next((item for item in anchor_attributes if item.get("audienceType") == audience_type), None)

        if matching_anchor:
            anchor_questions = matching_anchor.get("questions", [])
            anchor_options = await generate_anchor_attribute_options(data, anchor_questions)
            anchor_questions_with_options = anchor_options["suggestions"]


        uploads_collection = db["uploads"]
        await uploads_collection.update_one(
            {"_id": saved_cv["_id"]},
            {"$set": {
                "audienceType": audience_type,
                "job_questions_with_options": job_questions_with_options,
                "anchor_questions_with_options": anchor_questions_with_options
            }}
        )

    summary = await get_cv_summary(data)

    return {
        "parsed_data": data,
        "summary": summary,
        "audienceType": audience_type,

        "message": "CV data extracted and saved successfully"
    }


@router.get("/profile/summary")
async def get_my_profile_summary(db=Depends(get_database), current_user=Depends(get_current_user)):
    return await get_profile_summary_service(db, current_user)


@router.get("/missing_questions")
async def get_missing_field_questions(
    section: str = "Cv Missing",
    db=Depends(get_database),
    current_user=Depends(get_current_user),
):
    return await get_missing_field_questions_service(section, db, current_user)


@router.get("/job-questions")
async def get_audience_questions(
    db=Depends(get_database),
    current_user=Depends(get_current_user)
):
    return await get_audience_questions_service(db, current_user)

@router.get("/anchor-questions")
async def get_anchor_questions(
    db=Depends(get_database),
    current_user=Depends(get_current_user)
):
    return await get_questions_by_audience(db, current_user, "Anchor attributes")


@router.post("/missing_questions/answers")
async def submit_cv_missing_answers(
    payload: dict,  # Ideally use a Pydantic schema
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_user: dict = Depends(get_current_user)
):
    return await save_latest_cv_answers(
        db=db,
        current_user=current_user,
        section="Cv Missing",
        answers=payload["answers"]
    )


@router.post("/job-questions/answers")
async def submit_job_attr_answers(
    payload: dict,
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_user: dict = Depends(get_current_user)
):
    return await save_latest_cv_answers(
        db=db,
        current_user=current_user,
        section="Job Attributes",
        answers=payload["answers"]
    )


@router.post("/anchor-questions/answers")
async def submit_anchor_attr_answers(
    payload: dict,
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_user: dict = Depends(get_current_user)
):
    return await save_latest_cv_answers(
        db=db,
        current_user=current_user,
        section="Anchor Attributes",
        answers=payload["answers"]
    )



