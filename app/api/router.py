from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from app.db.database import get_database
from app.schemas import UserCreate, UserLogin, ForgotPasswordRequest
from app.services.user import create_user, get_user_by_username, forgot_password, save_extracted_cv_data
from app.utils import verify_password
from app.utils.cv_extractor import extract_cv_data_from_file
from app.utils.token import create_access_token, get_current_user
from app.services.cv_comparison import get_cv_summary
import tempfile
from bson import ObjectId
import os
import google.generativeai as genai
import asyncio
import json
from datetime import datetime

router = APIRouter()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError("Missing GEMINI_API_KEY environment variable")

genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel("gemini-1.5-flash")


async def generate_missing_field_suggestions(cv_context: dict, field_types: list[str]) -> dict[str, list[str]]:
    context_str = "\n".join(f"{k}: {v}" for k, v in cv_context.items() if v)

    cv_type = cv_context.get("Summary", "") or cv_context.get("WorkExperience", [])
    if isinstance(cv_type, list):
        cv_type_text = " ".join(str(job.get("Role", "")) for job in cv_type)
    else:
        cv_type_text = str(cv_type)

    prompt = (
        "You are an AI helping complete missing CV fields.\n"
        "For each field type provided, suggest a relevant and comprehensive comma-separated list "
        "based on the candidate's CV context. Include domain-specific items plus a few general extras.\n\n"
        f"CV Context:\n{context_str}\n\n"
        f"CV Type (for context): {cv_type_text}\n\n"
        "Field types to generate:\n"
        + "\n".join(f"- {ftype}" for ftype in field_types) +
        "\n\nInstructions:\n"
        "1. Provide domain-specific and relevant items for each field.\n"
        "2. For Certifications, include both domain-specific and common certifications.\n"
        "Respond ONLY in JSON format with keys as the field type "
        "and values as comma-separated strings. Do not include extra text."
    )

    response = await gemini_model.generate_content_async(prompt)

    try:
        parsed = json.loads(response.text)
    except Exception:
        parsed = {ftype: [] for ftype in field_types}
        lines = (response.text or "").split("\n")
        for line in lines:
            for ftype in field_types:
                if ftype.lower() in line.lower():
                    values_str = line.split(":", 1)[-1] if ":" in line else line
                    items = [s.strip() for s in values_str.split(",") if s.strip()]
                    parsed[ftype] = items
                    break

    for key, val in parsed.items():
        seen = set()
        cleaned = []
        for opt in val:
            if opt.lower() not in seen:
                seen.add(opt.lower())
                cleaned.append(opt)
        parsed[key] = cleaned

    return parsed


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
    mime_type = file.content_type

    with tempfile.NamedTemporaryFile(delete=False, suffix="." + file.filename.split('.')[-1]) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    data = extract_cv_data_from_file(tmp_path, mime_type)

    save_result = await save_extracted_cv_data(
        user_id=current_user["_id"],
        parsed_data=data,
        file_path=tmp_path,
        db=db
    )

    summary = await get_cv_summary(data)

    return {
        "parsed_data": data,
        "summary": summary,
        **save_result,
        "message": "CV data extracted and saved successfully"
    }


@router.get("/questions")
async def get_missing_field_questions(
    db=Depends(get_database),
    current_user=Depends(get_current_user)
):
    param_to_parsed_key = {
        "Education": "Education",
        "Experience": "WorkExperience",
        "Technical Skills": "Skills.HardSkills",  
        "Soft Skills": "Skills.SoftSkills",
        "Certifications": "Certifications",
        "Projects": "Projects",
        "Languages Known": "Languages",
        "Career Objective": "Summary",
        "Awards": "Awards",
        "Volunteer Experience": "VolunteerExperience",
        "Hobbies": "Hobbies",
        "Salary Grades": None
    }

    latest_cv = await db["uploads"].find_one(
        {"user_id": ObjectId(current_user["_id"])},
        sort=[("_id", -1)]
    )

    questions_docs = [q async for q in db["questions"].find({})]

    missing_parameters = [q for q in questions_docs if "parameter" not in q]

    all_parameters = [
        q.get("parameter")
        for q in questions_docs
        if q.get("parameter") and q["parameter"] != "Tools"
    ]

    missing_fields = []

    parsed_data = latest_cv.get("parsed_data", {}) if latest_cv else {}

    hard_skills = parsed_data.get("Skills", {}).get("HardSkills", [])
    tools = parsed_data.get("Tools", [])
    hard_skills_missing = not hard_skills or (isinstance(hard_skills, list) and len(hard_skills) == 0)
    tools_missing = not tools or (isinstance(tools, list) and len(tools) == 0)
    if hard_skills_missing or tools_missing:
        missing_fields.append("Technical Skills")

    for param in all_parameters:
        if param == "Technical Skills":
            continue 

        parsed_key_path = param_to_parsed_key.get(param)
        if not parsed_key_path:
            missing_fields.append(param)
            continue

        keys = parsed_key_path.split(".")
        value = parsed_data
        for k in keys:
            value = value.get(k) if isinstance(value, dict) else None
            if value is None:
                break

        if not value or (isinstance(value, list) and len(value) == 0):
            missing_fields.append(param)
        elif isinstance(value, dict):
            if all(not v or (isinstance(v, list) and len(v) == 0) for v in value.values()):
                missing_fields.append(param)

    llm_fields_needed = [
        q.get("parameter")
        for q in questions_docs
        if q.get("parameter") in ("Technical Skills", "Soft Skills", "Certifications")
        and q.get("parameter") in missing_fields
    ]

    suggestions_data = {}
    if llm_fields_needed:
        suggestions_data = await generate_missing_field_suggestions(parsed_data, llm_fields_needed)

    missing_questions = []
    for q in questions_docs:
        param = q.get("parameter")
        if param in missing_fields:
            q_entry = {**q, "_id": str(q["_id"])}
            if param in suggestions_data:
                q_entry["options"] = suggestions_data[param]
            missing_questions.append(q_entry)

    return {
        "success": True,
        "count": len(missing_questions),
        "questions": missing_questions,
        "missing_fields": missing_fields
    }


def determine_audience_type(parsed_data: dict) -> str:
    audience_type = None

    education_list = parsed_data.get("Education", [])
    student_keywords = ["ongoing", "present", "currently pursuing", "in progress", "pursuing"]

    for ed in education_list:
        combined_fields = " ".join(str(v).lower() for v in ed.values() if v)
        if any(keyword in combined_fields for keyword in student_keywords):
            audience_type = "Student"
            break

    work_exp_list = parsed_data.get("WorkExperience", [])

    has_current_job = any(
        str(w.get("isCurrent", "")).strip().lower() in ["true", "yes", "1"] or
        str(w.get("endDate", "")).strip().lower() in ["present", "current", "ongoing", ""]
        for w in work_exp_list
    )

    if "YearsOfExperience" in parsed_data and isinstance(parsed_data["YearsOfExperience"], (int, float)):
        total_years = float(parsed_data["YearsOfExperience"])
    else:
        total_years = 0
        for w in work_exp_list:
            try:
                start_raw = w.get("startDate")
                end_raw = w.get("endDate")

                start = datetime.strptime(str(start_raw), "%Y-%m-%d")
                if not end_raw or str(end_raw).strip().lower() in ["present", "current", "ongoing"]:
                    end = datetime.today()
                else:
                    end = datetime.strptime(str(end_raw), "%Y-%m-%d")

                total_years += (end - start).days / 365
            except Exception:
                continue

    if not audience_type:
        if not has_current_job and total_years < 0.5:
            audience_type = "Job Seeker"
        elif total_years <= 3:
            audience_type = "Early Professional (2-3 years of experience)"
        else:
            audience_type = "Mid - Career Pivot"

    return audience_type


@router.get("/job-questions")
async def get_audience_questions(
    db=Depends(get_database),
    current_user=Depends(get_current_user)
):
    latest_cv = await db["uploads"].find_one(
        {"user_id": ObjectId(current_user["_id"])},
        sort=[("_id", -1)]
    )

    if not latest_cv or "parsed_data" not in latest_cv:
        raise HTTPException(status_code=404, detail="No CV data found for this user")

    audience_type = determine_audience_type(latest_cv["parsed_data"])

    questions_doc = await db["questions"].find_one({"audienceType": audience_type})
    if not questions_doc:
        raise HTTPException(status_code=404, detail=f"No questions found for audience type: {audience_type}")

    return {
        "success": True,
        "audienceType": audience_type,
        "questions": questions_doc.get("questions", [])
    }


@router.get("/anchor-attributes-questions")
async def get_anchor_attributes_questions(
    db=Depends(get_database),
    current_user=Depends(get_current_user)
):
    latest_cv = await db["uploads"].find_one(
        {"user_id": ObjectId(current_user["_id"])},
        sort=[("_id", -1)]
    )

    if not latest_cv or "parsed_data" not in latest_cv:
        raise HTTPException(status_code=404, detail="No CV data found for this user")

    audience_type = determine_audience_type(latest_cv["parsed_data"])

    anchor_doc = await db["anchor_attributes"].find_one({"audienceType": audience_type})
    if not anchor_doc:
        raise HTTPException(status_code=404, detail=f"No anchor attributes found for audience type: {audience_type}")

    return {
        "success": True,
        "audienceType": audience_type,
        "questions": anchor_doc.get("questions", [])
    }
