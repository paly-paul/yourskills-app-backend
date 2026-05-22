from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from app.db.database import get_database
from app.schemas import UserCreate, UserLogin, ForgotPasswordRequest, AnswersSubmit
from app.services.user import create_user, get_user_by_email, forgot_password, save_extracted_cv_data, save_latest_cv_answers, save_answers_without_cv
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
from dateutil import parser as date_parser
from pymongo import DESCENDING
from app.services.skill_suggestions import save_skill_suggestions
from app.services.profile import (
    get_missing_field_questions_service,
    get_audience_questions_service,
    get_audience_questions_service_without_cv,
    get_questions_excluding_parameters, get_questions_by_parameters,get_questions_by_parameters_withoutcv,
    get_remaining_anchor_questions_without_cv
)
from app.utils.cv_extractor import generate_job_attribute_options
import re
from app.schemas.user import EditProfileRequest
from app.utils import verify_password, hash_password

import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

gemini_model = genai.GenerativeModel("gemini-2.5-flash-lite")

def get_llm_model():
    return gemini_model


router = APIRouter()


# ------------------------------------Routers for With cv ----------------------------------------------------------------


@router.post("/register")
async def register(user: UserCreate, db=Depends(get_database)):
   
    existing = await get_user_by_email(db, user.email)
    if existing:
        return {"success": False, "reason": "Email already exists."}

    created_user = await create_user(db, user)
    # token_data = {"user_id": str(created_user["_id"]), "username": created_user["username"]}
    token_data = {
        "user_id": str(created_user["_id"]),
        "username": created_user["username"],
        "first_name": created_user["first_name"],
        "last_name": created_user["last_name"]
    }
    access_token = create_access_token(token_data)

    return {
        "success": True,
        "token": access_token,
        "tenant_id": created_user["tenant_id"]
    }


@router.post("/login")
async def login(user: UserLogin, db=Depends(get_database)):
  
    db_user = await db["users"].find_one({"email": user.email})

    if not db_user:
        return {"success": False, "reason": "User not found."}

    if not verify_password(user.password, db_user["password"]):
        return {"success": False, "reason": "Invalid password."}

    token_data = {
        "user_id": str(db_user["_id"]),
        "email": db_user["email"]  
    }
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
        "email": current_user["email"],
        "first_name": current_user.get("first_name"),
        "last_name": current_user.get("last_name"),
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
    # ---------------- SAVE TEMP FILE ----------------
    with tempfile.NamedTemporaryFile(delete=False, suffix="." + file.filename.split('.')[-1]) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    # ---------------- EXTRACT RESUME DATA ----------------
    data = extract_cv_data_from_file(tmp_path, file.content_type)

    if "error" in data:
        return {"message": "CV extraction failed", "error": data["error"]}

    # ---------------- SAVE PARSED CV ----------------
    saved_cv = await save_extracted_cv_data(
        user_id=current_user["id"],
        parsed_data=data,
        file_path=tmp_path,
        db=db
    )

    cv_id_str = str(saved_cv.get("_id"))

    # -------------------------------------------------------
    # 🔥 NEW: DIRECTLY READ LLM-GENERATED FIELDS (NO LLM CALL)
    # -------------------------------------------------------

    softskills_suggestions = data.get("LLM_Generated_Soft_Skills", [])
    technical_skills_suggestions = data.get("LLM_Generated_Technical_Skills", [])
    certifications_suggestions = data.get("LLM_Generated_Certificates", [])
    certifications_suggestions = [cert.get("Name") for cert in certifications_suggestions]


    # ---------------- SAVE SUGGESTIONS TO DB ----------------
    await save_skill_suggestions(
        user_id=current_user["id"],
        cv_id=cv_id_str,
        softskills=softskills_suggestions,
        technical_skills=technical_skills_suggestions,
        certifications=certifications_suggestions,
        db=db
    )

    # ---------------- LOAD QUESTIONS FROM DB ----------------
    questions_collection = db["questions"]
    questions_doc = await questions_collection.find_one({})

    audience_type = predict_audience_type(data)
    job_questions_with_options = []

    if questions_doc:
        job_attributes = questions_doc.get("Job attributes", [])
        matching_job = next(
            (item for item in job_attributes if item.get("audienceType") == audience_type),
            None
        )

        if matching_job:
            job_questions = matching_job.get("questions", [])
            job_options = await generate_job_attribute_options(data, job_questions)
            job_questions_with_options = job_options["suggestions"]

        # Save audience type + questions in uploads
        uploads_collection = db["uploads"]
        await uploads_collection.update_one(
            {"_id": saved_cv["_id"]},
            {"$set": {
                "audienceType": audience_type,
                "job_questions_with_options": job_questions_with_options
            }}
        )

    # ---------------- SUMMARY OF KNOWN & UNKNOWN FIELDS ----------------
    summary = await get_cv_summary(data)

    def parse_duration(duration_str: str):
        from dateutil import parser as date_parser
        try:
            parts = re.split(r"\s*(?:-|–|—|to)\s*", duration_str or "", flags=re.IGNORECASE)
            if len(parts) != 2:
                return None

            start_str, end_str = parts[0].strip(), parts[1].strip().lower()
            start_date = date_parser.parse(start_str, fuzzy=True)

            if any(x in end_str for x in ("present", "current", "ongoing")):
                end_date = datetime.today()
            else:
                end_date = date_parser.parse(end_str, fuzzy=True)

            return start_date, end_date
        except Exception:
            return None

    # ---------------- DETECT LATEST JOB ROLE ----------------
    job_role = None
    latest_end = datetime.min

    for job in data.get("WorkExperience", []) or []:
        parsed = parse_duration(job.get("Duration", ""))
        if parsed:
            _, end = parsed
            if end > latest_end:
                latest_end = end
                job_role = job.get("Role")

    if not job_role and data.get("WorkExperience"):
        raw_role = data["WorkExperience"][0].get("Role", "")
        if raw_role:
            job_role = raw_role.split("/")[0].split(",")[0].strip()

    if not job_role and data.get("Summary"):
        match = re.search(r"(?i)([A-Z][a-zA-Z\s\/\-]+)\s+with\s+\d+\s+years", data["Summary"])
        if match:
            job_role = match.group(1).strip()

    # ---------------- CALCULATE KNOWN % ----------------
    known_fields = len(summary.get("known", []))
    unknown_fields = len(summary.get("unknown", []))
    total_fields = known_fields + unknown_fields

    known_percentage = round((known_fields / total_fields) * 100, 2) if total_fields else 0.0

    # ---------------- FINAL RESPONSE ----------------
    return {
        "parsed_data": data,
        "summary": summary,
        "audienceType": audience_type,
        "candidate": {
            "name": data.get("Name"),
            "job_role": job_role,
            "known_percentage": known_percentage
        },
        "message": "CV data extracted and saved successfully"
    }

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
    response = await get_audience_questions_service(db, current_user)

    if "questions" in response and isinstance(response["questions"], list):
        for q in response["questions"]:
            if "parameter" in q and isinstance(q["parameter"], list):
                q["parameter"] = "+".join(str(p) for p in q["parameter"])

    return response

@router.post("/update-audience-type")
async def update_audience_type(
    payload: dict,
    db=Depends(get_database),
    current_user=Depends(get_current_user)
):

    selected_audience_type = payload.get("audienceType")

    uploads_collection = db["uploads"]

    latest_cv = await uploads_collection.find_one(
        {"user_id": ObjectId(current_user["_id"])},
        sort=[("_id", -1)]
    )

    if not latest_cv:
        raise HTTPException(
            status_code=404,
            detail="No CV found"
        )

    await uploads_collection.update_one(
        {"_id": latest_cv["_id"]},
        {
            "$set": {
                "selectedAudienceType": selected_audience_type
            }
        }
    )

    return {
        "success": True,
        "selectedAudienceType": selected_audience_type
    }

@router.get("/anchor-questions/parameters")
async def get_anchor_questions_by_parameters(
    db=Depends(get_database),
    current_user=Depends(get_current_user)
):
    """
    Fetch specific Anchor Attribute questions for:
      - Personal Interests + Hobbies + Exploration Interest + Motivation Drivers + Motivating Activities
      - Achievements
    """
    return await get_questions_by_parameters(
        db, current_user,
        "Anchor attributes",
        [
            "Personal Interests + Hobbies + Exploration Interest + Motivation Drivers + Motivating Activities",
            "Achievements"
        ]
    )

@router.get("/anchor-questions/remaining")
async def get_remaining_anchor_questions(
    db=Depends(get_database),
    current_user=Depends(get_current_user),
    model=Depends(get_llm_model)  
):
    """Fetch anchor attribute questions excluding base params,
    generating and merging options if needed.
    """
    exclude_params = [
        "Personal Interests + Hobbies + Exploration Interest + Motivation Drivers + Motivating Activities",
        "Achievements"
    ]

    return await get_questions_excluding_parameters(
        db=db,
        current_user=current_user,
        attribute_type="Anchor attributes",
        exclude_params=exclude_params,
        model=model,
        get_database=get_database
    )


@router.post("/missing_questions/answers")
async def submit_cv_missing_answers(
    payload: dict,  
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
    answers = payload.get("answers", [])

    for ans in answers:
        parameter = ans.get("parameter")
        selected_values = ans.get("value", [])

        if parameter == "Work Styles + Work Activities + Abilities" and len(selected_values) > 5:
            raise HTTPException(
                status_code=400,
                detail="You can select a maximum of 5 options for 'Work Styles + Work Activities + Abilities'."
            )

        if parameter == "Work Values" and len(selected_values) > 3:
            raise HTTPException(
                status_code=400,
                detail="You can select a maximum of 3 options for 'Work Values'."
            )

    return await save_latest_cv_answers(
        db=db,
        current_user=current_user,
        section="Job Attributes",
        answers=answers
    )


@router.post("/anchor-questions/answers")
async def submit_anchor_attr_answers(
    payload: dict,
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_user: dict = Depends(get_current_user)
):
    answers = payload.get("answers", [])

    for ans in answers:
        parameter = ans.get("parameter")
        selected_values = ans.get("value", [])

        if parameter == "Interests - RIASEC" and len(selected_values) > 3:
            raise HTTPException(
                status_code=400,
                detail="You can select a maximum of 3 options for 'Interests - RIASEC'."
            )

    return await save_latest_cv_answers(
        db=db,
        current_user=current_user,
        section="Anchor Attributes",
        answers=answers
    )


@router.get("/cv/latest/details")
async def get_latest_cv_details(
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_user: dict = Depends(get_current_user)
):
    uploads_collection = db["uploads"]
    answers_collection = db["answers"]

    user_id = str(current_user.get("_id"))

    query = {"user_id": {"$in": [user_id, ObjectId(user_id)]}}
    cv_doc = await uploads_collection.find_one(
        query,
        sort=[("uploaded_at", DESCENDING)]
    )

    if not cv_doc:
        raise HTTPException(status_code=404, detail="No CV uploaded yet")

    parsed_data = cv_doc.get("parsed_data", {}) or {}
    work_experiences = parsed_data.get("WorkExperience", []) or []

    def parse_duration(duration_str: str):
        try:
            parts = re.split(r"\s*(?:-|–|—|to)\s*", duration_str or "", flags=re.IGNORECASE)
            if len(parts) != 2:
                return None
            start_str, end_str = parts[0].strip(), parts[1].strip().lower()
            start_date = date_parser.parse(start_str, fuzzy=True)
            if any(x in end_str for x in ("present", "current", "ongoing")):
                end_date = datetime.today()
            else:
                end_date = date_parser.parse(end_str, fuzzy=True)
            return start_date, end_date
        except Exception:
            return None

    job_role = None
    latest_end = datetime.min

    if parsed_data.get("YearsOfExperience", 0) == 0:
        job_role = "Fresher"
    else:
        for job in work_experiences:
            parsed = parse_duration(job.get("Duration", ""))
            if parsed:
                _, end = parsed
                if end > latest_end:
                    latest_end = end
                    job_role = job.get("Role")

    education_list = parsed_data.get("Education", []) or []

    def get_year(education_entry):
        try:
            year_str = education_entry.get("Year", "")
            if '-' in year_str or '–' in year_str:
                end_year = year_str.split('-')[-1].strip()
                return int(end_year)
            return int(re.search(r'\d{4}', year_str).group())
        except (AttributeError, ValueError):
            return 0

    if education_list:
        education_list.sort(key=get_year, reverse=True)
        latest_education = [education_list[0]]
    else:
        latest_education = []

    def transform_certifications(certs):
        formatted = []
        if not certs:
            return formatted

        for cert in certs:
            if isinstance(cert, str):
                parts = [p.strip() for p in re.split(r"\s*[-–]\s*", cert, maxsplit=1)]
                name = parts[0] if parts else ""
                issuer = parts[1] if len(parts) > 1 else ""
                formatted.append({
                    "Name": name,
                    "Issuer": issuer,
                    "Year": ""
                })
            elif isinstance(cert, dict):
                formatted.append({
                    "Name": cert.get("Name", ""),
                    "Issuer": cert.get("Issuer", ""),
                    "Year": cert.get("Year", "")
                })
        return formatted

    formatted_data = {
        "name": parsed_data.get("Name"),
        "role": parsed_data.get("JobRole"),
        "Summary": parsed_data.get("Summary") or "",
        "hard_skills": parsed_data.get("Skills", {}).get("HardSkills", []),
        "soft_skills": parsed_data.get("Skills", {}).get("SoftSkills", []),
        "tools": parsed_data.get("Skills", {}).get("Tools", []),
        "education": latest_education,
        "career_overview": parsed_data.get("YearsOfExperience"),
        "certifications": transform_certifications(parsed_data.get("Certifications", []))
    }

    async def fetch_answer(parameter: str, section="Cv Missing"):
        ans_doc = await answers_collection.find_one(
            {
                "user_id": user_id,
                "cv_id": str(cv_doc.get("_id")),
                "section": section,
                "parameter": parameter
            },
            sort=[("created_at", DESCENDING)]
        )
        if ans_doc:
            return ans_doc.get("value") or ans_doc.get("selected_options") or ans_doc.get("free_text")
        return None

    if not formatted_data["certifications"]:
        raw_certs = await fetch_answer("Certifications")
        formatted_data["certifications"] = transform_certifications(raw_certs)

    if not formatted_data["hard_skills"]:
        formatted_data["hard_skills"] = await fetch_answer("Technical Skills")

    if not formatted_data["soft_skills"]:
        formatted_data["soft_skills"] = await fetch_answer("Soft Skills")

    if not formatted_data["tools"]:
        formatted_data["tools"] = await fetch_answer("Hot Technologies", section="Job Attributes")

    if not formatted_data["role"]:
        formatted_data["role"] = await fetch_answer("Experience")

    if not formatted_data["education"]:
        edu_answer = await fetch_answer("Education")
        if edu_answer:
            if isinstance(edu_answer, list):
                formatted_data["education"] = []
                for entry in edu_answer:
                    formatted_data["education"].append({
                        "Degree": entry.get("selectedField") or entry.get("selected") or "",
                        "Institution": "", 
                        "Grade": "",
                        "Year": ""
                    })
            elif isinstance(edu_answer, dict):
                formatted_data["education"] = [{
                    "Degree": edu_answer.get("selectedField") or edu_answer.get("selected") or "",
                    "Institution": "",
                    "Grade": "",
                    "Year": ""
                }]


    if not formatted_data["Summary"]:
        formatted_data["Summary"] = await fetch_answer("Career Objective")

    return {"success": True, "cv_details": formatted_data}

#_______________________________________________________________________________________________________________________________________________________
#____________________________________________________________________________________________________________________________________________________________________________
# ------------------------------------------ Second Flow Endpints( Without cv/) -----------------------------------------------------------


@router.post("/proceed-without-cv")
async def proceed_without_cv(
    payload: dict,
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_user: dict = Depends(get_current_user)
):
    """
    Store the selected audience_type when user proceeds without uploading a CV
    in a separate collection.
    """
    audience_type = payload.get("audienceType")
    if not audience_type:
        raise HTTPException(status_code=400, detail="audienceType is required")

    user_id = str(current_user.get("_id"))
    proceed_collection = db["proceed_without_cv"]  

    doc = {
        "user_id": user_id,
        "audienceType": audience_type,
        "created_at": datetime.utcnow(),
        "source": "without_cv"
    }

    result = await proceed_collection.insert_one(doc)

    return {
        "success": True,
        "message": "Audience type stored successfully (without CV)",
        "data": {
            "audienceType": audience_type,
            "user_id": user_id,
            "doc_id": str(result.inserted_id)
        }
    }

@router.get("/cv-missing-questions")
async def get_cv_missing_questions(
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_user: dict = Depends(get_current_user)
):
    """
    Fetch all questions from the 'Cv Missing' section of the questions collection
    """
    questions_collection = db["questions"]

    questions_doc = await questions_collection.find_one({}, {"Cv Missing": 1, "_id": 0})

    if not questions_doc:
        raise HTTPException(status_code=404, detail="No questions found")

    return {"questions": questions_doc.get("Cv Missing", [])}


@router.post("/missing-answers/without-cv")
async def submit_answers_without_cv(
    payload: dict,
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_user: dict = Depends(get_current_user)
):
    """
    Endpoint to save missing answers without CV.
    Gets latest document_id from proceed_without_cv for this user.
    """
    answers = payload.get("answers", [])

    user_id = current_user.get("id") or current_user.get("_id")
    try:
        user_id = ObjectId(str(user_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid user_id")

    latest_doc = await db["proceed_without_cv"].find_one(
        {"user_id": str(user_id)},
        sort=[("_id", -1)]
    )

    if not latest_doc:
        raise HTTPException(status_code=404, detail="No proceed_without_cv document found")

    document_id = latest_doc["_id"]

    return await save_answers_without_cv(db, current_user, "Cv Missing", answers, document_id)


@router.get("/job-questions-without-cv")
async def get_audience_questions_without_cv(
    db=Depends(get_database),
    current_user=Depends(get_current_user)
):
    """
    API endpoint to fetch audience-specific job questions with options
    for users who proceed without uploading a CV.
    """
    response = await get_audience_questions_service_without_cv(db, current_user)

    if "questions" in response and isinstance(response["questions"], list):
        for q in response["questions"]:
            if "parameter" in q and isinstance(q["parameter"], list):
                q["parameter"] = "+".join(str(p) for p in q["parameter"])

    return response


@router.post("/job-questions/answers/without-cv")
async def submit_job_attr_answers_without_cv(
    payload: dict,
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_user: dict = Depends(get_current_user)
):
    """
    Endpoint to save Job Attributes answers without CV.
    Validates answer limits and stores them under proceed_without_cv document.
    """
    answers = payload.get("answers", [])

    for ans in answers:
        parameter = ans.get("parameter")
        selected_values = ans.get("value", [])

        if parameter == "Work Styles + Work Activities + Abilities" and len(selected_values) > 5:
            raise HTTPException(
                status_code=400,
                detail="You can select a maximum of 5 options for 'Work Styles + Work Activities + Abilities'."
            )

        if parameter == "Work Values" and len(selected_values) > 3:
            raise HTTPException(
                status_code=400,
                detail="You can select a maximum of 3 options for 'Work Values'."
            )

    user_id = current_user.get("id") or current_user.get("_id")
    try:
        user_id = ObjectId(str(user_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid user_id")

    latest_doc = await db["proceed_without_cv"].find_one(
        {"user_id": str(user_id)},
        sort=[("_id", -1)]
    )

    if not latest_doc:
        raise HTTPException(status_code=404, detail="No proceed_without_cv document found")

    document_id = latest_doc["_id"]

    return await save_answers_without_cv(
        db=db,
        current_user=current_user,
        section="Job Attributes",
        answers=answers,
        document_id=document_id
    )


@router.get("/anchor-questions/parameters-without-cv")
async def get_anchor_questions_by_user_parameters(
    db=Depends(get_database),
    current_user=Depends(get_current_user)
):
    """
    Fetch specific Anchor Attribute questions for the current user based on their audienceType
    stored in the `proceed_without_cv` collection, specifically for:
      - Personal Interests + Hobbies + Exploration Interest + Motivation Drivers + Motivating Activities
      - Achievements
    """

    record = await db["proceed_without_cv"].find_one(
        {"user_id": str(current_user["_id"])},
        sort=[("_id", -1)]
    )

    if not record or "audienceType" not in record:
        raise HTTPException(status_code=404, detail="Audience type not found for user")

    audience_type = record["audienceType"]

    return await get_questions_by_parameters_withoutcv(
        db,
        current_user,
        "Anchor attributes",
        [
            "Personal Interests + Hobbies + Exploration Interest + Motivation Drivers + Motivating Activities",
            "Achievements"
        ],
        audience_type=audience_type  
    )

@router.get("/anchor-questions/remaining-without-cv")
async def get_remaining_anchor_questions(
    db=Depends(get_database),
    current_user=Depends(get_current_user),
    model=Depends(get_llm_model)
):
    """
    Fetch remaining anchor attribute questions for the current user.
    - Exclude base parameters.
    - If user has no CV, fallback to latest proceed_without_cv and generate options if needed.
    - Merge with system questions, avoiding duplicates.
    """
    exclude_params = [
        "Personal Interests + Hobbies + Exploration Interest + Motivation Drivers + Motivating Activities",
        "Achievements"
    ]
    attribute_type = "Anchor attributes"

    
    return await get_remaining_anchor_questions_without_cv(
        db=db,
        current_user=current_user,
        model=model,
        exclude_params=exclude_params,
        attribute_type=attribute_type
    )


@router.post("/anchor-questions/answers-without-cv")
async def submit_anchor_attr_answers(
    payload: dict,
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_user: dict = Depends(get_current_user)
):
    """
    Save Anchor Attribute answers for the current user in 'answers_without_cv'
    using the common save_answers_without_cv function.
    """
    record = await db["proceed_without_cv"].find_one(
        {"user_id": str(current_user["_id"])},
        sort=[("_id", -1)]
    )

    if not record or "audienceType" not in record:
        raise HTTPException(status_code=404, detail="Audience type not found for user")

    audience_type = record["audienceType"]
    document_id = record["_id"] 

    answers = payload.get("answers", [])

    for ans in answers:
        parameter = ans.get("parameter")
        selected_values = ans.get("value", [])

        if parameter == "Interests - RIASEC" and isinstance(selected_values, list) and len(selected_values) > 3:
            raise HTTPException(
                status_code=400,
                detail="You can select a maximum of 3 options for 'Interests - RIASEC'."
            )
    result = await save_answers_without_cv(
        db=db,
        current_user=current_user,
        section="Anchor Attributes",
        answers=answers,
        document_id=document_id
    )

    return {
        "success": True,
        "message": "Anchor Attribute answers saved successfully (without CV)",
        "audienceType": audience_type,
        "doc_id": str(document_id),
        "details": result
    }


def parse_duration(duration_str):
    """
    Parses a duration string into start and end datetime objects.
    Handles 'X years', 'X months', and 'March 2022 - May 2023' formats.
    """
    try:
        duration_str = duration_str.replace("’", "'").replace("‘", "'").strip()
        duration_str = re.sub(r"\s+", " ", duration_str)
        duration_str = re.sub(r"\(|\)", "", duration_str)

        match = re.search(r"(\d+)\s*(year|month)", duration_str, re.IGNORECASE)
        if match:
            num, unit = match.groups()
            num = int(num)
            end_date = datetime.today()
            if "year" in unit.lower():
                start_date = datetime(end_date.year - num, end_date.month, end_date.day)
            else: 
                months_back = num
                year = end_date.year - (months_back // 12)
                month = end_date.month - (months_back % 12)
                if month <= 0:
                    year -= 1
                    month += 12
                start_date = datetime(year, month, 1)
            return start_date, end_date

        parts = re.split(r"\s*(?:-|–|—|to)\s*", duration_str, flags=re.IGNORECASE)
        if len(parts) != 2:
            return None
        start_str, end_str = parts[0].strip(), parts[1].strip().lower()

        try:
            start_date = date_parser.parse(start_str, fuzzy=True)
        except Exception:
            return None

        if any(word in end_str for word in ["present", "current", "now"]):
            end_date = datetime.today()
        else:
            try:
                end_date = date_parser.parse(end_str, fuzzy=True)
            except Exception:
                return None

        return start_date, end_date
    except Exception:
        return None

def parse_experience_string(exp_string: str):
    """
    Parses a comma-separated experience string into a list of job dictionaries.
    Handles free text like 'Intern for 6 months' or 'Internship from March 2022 to May 2023'.
    """
    work_experiences = []
    roles = [r.strip() for r in re.split(r",(?![^()]*\))", exp_string)]

    for role_str in roles:
        role = re.sub(r"\b(for|with|at)\b.*", "", role_str, flags=re.IGNORECASE).strip()

        date_match = re.search(r"([A-Za-z]+\s+\d{4})\s*(?:-|to)\s*([A-Za-z]+\s+\d{4})", role_str, re.IGNORECASE)
        if date_match:
            duration = f"{date_match.group(1)} - {date_match.group(2)}"
        else:
            dur_match = re.search(r"(\d+)\s*(year|month)", role_str, re.IGNORECASE)
            duration = dur_match.group(0) if dur_match else ""

        work_experiences.append({
            "Title": role,
            "Duration": duration
        })

    return work_experiences


def extract_years_from_summary(summary_text: str) -> float:
    if not summary_text:
        return 0.0
    match = re.search(r"(?i)(over|more than|about)?\s*(\d+)\s*(\+)?\s*years? of experience", summary_text)
    if match:
        return float(match.group(2))
    return 0.0

def calculate_years_of_experience(work_experiences):
    total_months = 0
    for job in work_experiences:
        duration_str = job.get("Duration", "")
        if not duration_str:
            continue
        match = re.search(r"(\d+)\s*(year|month)", duration_str, re.IGNORECASE)
        if match:
            num, unit = match.groups()
            num = int(num)
            if "year" in unit.lower():
                total_months += num * 12
            elif "month" in unit.lower():
                total_months += num
            continue
        parsed = parse_duration(duration_str)
        if parsed:
            start, end = parsed
            months = (end.year - start.year) * 12 + (end.month - start.month)
            total_months += max(0, months)

    return round(total_months / 12, 2)

@router.get("/cv/summary/without")
async def get_cv_summary_without(
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_user: dict = Depends(get_current_user)
):
    answers_collection = db["answers_without_cv"]
    users_collection = db["users"]
    proceed_collection = db["proceed_without_cv"]

    user_id = str(current_user.get("_id"))
    username = current_user.get("username")

    user_doc = await users_collection.find_one({"username": username})
    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found")
    name = user_doc.get("username")

    latest_proceed = await proceed_collection.find_one(
        {"user_id": user_id},
        sort=[("created_at", DESCENDING)]
    )
    if not latest_proceed:
        raise HTTPException(status_code=404, detail="No proceed_without_cv found")

    document_id = str(latest_proceed["_id"])
    parameters_map = {
        "Technical Skills": "hard_skills",
        "Career Objective": "summary",
        "Soft Skills": "soft_skills",
        "Education": "education",
        "Certifications": "certifications"
    }

    formatted_data = {
        "name": name,
        "role": None,
        "career_overview": 0.0,
        "hard_skills": [],
        "summary": "",   
        "soft_skills": [],
        "education": [],
        "certifications": [],
        "tools": []
    }

    async def fetch_answers(parameter: str):
        query = {"user_id": user_id, "document_id": document_id, "parameter": parameter}
        cursor = answers_collection.find(query).sort("created_at", DESCENDING)
        results = []
        async for ans_doc in cursor:
            answer = (
                ans_doc.get("value")
                or ans_doc.get("selected_options")
                or ans_doc.get("free_text")
            )
            if answer:
                if isinstance(answer, list):
                    results.extend(answer)
                else:
                    results.append(answer)
        return results

    def transform_certifications(certs):
        formatted = []
        if not certs:
            return formatted
        for cert in certs:
            if isinstance(cert, str):
                parts = [p.strip() for p in re.split(r"\s*[-–]\s*", cert, maxsplit=1)]
                name = parts[0] if parts else ""
                issuer = parts[1] if len(parts) > 1 else ""
                formatted.append({
                    "Name": name,
                    "Issuer": issuer,
                    "Year": ""
                })
            elif isinstance(cert, dict):
                formatted.append({
                    "Name": cert.get("Name", ""),
                    "Issuer": cert.get("Issuer", ""),
                    "Year": cert.get("Year", "")
                })
        return formatted

    for param, field in parameters_map.items():
        answers = await fetch_answers(param)
        if answers:
            if field == "summary":
                formatted_data[field] = answers[0]
            elif field == "certifications":
                formatted_data[field] = transform_certifications(answers)
            elif field == "education":
                normalized_education = []
                for ans in answers:
                    if isinstance(ans, dict):
                        normalized_education.append({
                            "Degree": ans.get("selectedField") or ans.get("selected") or "",
                            "Institution": "",
                            "Grade": "",
                            "Year": ""
                        })
                    else:
                        normalized_education.append({
                            "Degree": str(ans),
                            "Institution": "",
                            "Grade": "",
                            "Year": ""
                        })

                seen_degrees = set()
                deduped_edu = []
                for edu in normalized_education:
                    degree = edu["Degree"]
                    if degree not in seen_degrees and degree:
                        seen_degrees.add(degree)
                        deduped_edu.append(edu)
                formatted_data[field] = deduped_edu
            else:
                seen = set()
                deduped = []
                for ans in answers:
                    key = tuple(sorted(ans.items())) if isinstance(ans, dict) else ans
                    if key not in seen:
                        seen.add(key)
                        deduped.append(ans)
                formatted_data[field] = deduped

    work_experiences = []
    exp_doc = await answers_collection.find_one(
        {"user_id": user_id, "document_id": document_id, "parameter": "Experience"},
        sort=[("created_at", DESCENDING)]
    )

    if exp_doc and isinstance(exp_doc.get("value"), str):
        experience_string = exp_doc["value"]
        work_experiences = parse_experience_string(experience_string)
        if work_experiences:
            formatted_data["role"] = work_experiences[-1].get("Title")

    elif exp_doc and isinstance(exp_doc.get("value"), list):
        work_experiences = exp_doc["value"]
        if work_experiences:
            formatted_data["role"] = work_experiences[-1].get("Title")

    years = calculate_years_of_experience(work_experiences)
    if years == 0.0:
        years = extract_years_from_summary(formatted_data["summary"])
    formatted_data["career_overview"] = years

    hot_tech_doc = await answers_collection.find_one(
        {"user_id": user_id, "document_id": document_id, "parameter": "Hot Technologies"},
        sort=[("created_at", DESCENDING)]
    )
    if hot_tech_doc:
        tools_value = hot_tech_doc.get("value", [])
        formatted_data["tools"] = tools_value

    response_data = formatted_data.copy()
    response_data["Summary"] = response_data.pop("summary")

    return {"success": True, "cv_details": response_data}

#____________________________________________________________________________________________________________________________________________________

#-------------------------------------Api for Model prediction Data ------------------------------------------------------------------------------

@router.get("/cv/profile-data")
async def get_cv_profile_data(
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_user: dict = Depends(get_current_user)
):
    uploads_collection = db["uploads"]
    answers_collection = db["answers"]
    answers_without_cv_collection = db["answers_without_cv"]
    proceed_without_cv_collection = db["proceed_without_cv"]

    user_id = str(current_user.get("_id"))
    query = {"user_id": {"$in": [user_id, ObjectId(user_id)]}}

    latest_cv_doc = await uploads_collection.find_one(
        query, sort=[("uploaded_at", DESCENDING)]
    )
    latest_no_cv_doc = await proceed_without_cv_collection.find_one(
        {"user_id": user_id}, sort=[("created_at", DESCENDING)]
    )
    latest_cv_time = latest_cv_doc.get("uploaded_at") if latest_cv_doc else None
    latest_no_cv_time = latest_no_cv_doc.get("created_at") if latest_no_cv_doc else None

    active_flow = "without_cv"
    has_cv = False
    parsed_data = {}
    active_answers_collection = answers_without_cv_collection
    reference_id = None

    if latest_cv_time and (not latest_no_cv_time or latest_cv_time > latest_no_cv_time):
        active_flow = "with_cv"
        has_cv = True
        parsed_data = latest_cv_doc.get("parsed_data", {})
        active_answers_collection = answers_collection
        reference_id = str(latest_cv_doc.get("_id"))
    else:
        reference_id = str(latest_no_cv_doc.get("_id")) if latest_no_cv_doc else None

    talent_info = {
        "Education": parsed_data.get("Education", []),
        "Internships": parsed_data.get("Internships", []),
        "Projects": parsed_data.get("Projects", []),
        "Experience": parsed_data.get("WorkExperience", []),
        "Core Tasks": "",
        "Supplementary Tasks": "",
        "Emerging Tasks": "",
        "Knowledge": "",
        "Skills": "",
        "Core Tasks": "",
        "Supplementary Tasks": "",
        "Emerging Tasks": "",
        "Knowledge": "",
        "Skills": "",
        "Work activities": "",
        "Work styles": "",
        "Work values": "",
        "Technical Skills": parsed_data.get("Skills", {}).get("HardSkills", []),
        "Hot Technologies": "",
        "Soft Skills": parsed_data.get("Skills", {}).get("SoftSkills", []),
        "Functional Skills": "",
        "Certifications": parsed_data.get("Certifications", []),
        "Salary grades": "",
        "Career Objective": parsed_data.get("Summary") if has_cv else "",
        "Career Interest Areas": ""
    }

    anchor_attrs = {
        "Achievements": "",
        "Behavioral Skills": "",
        "Interests": "",
        "Competency": "",
        "Cognitive Preferences": "",
        "Creative Inclinations": "",
        "Exploration Interest": "",
        "Future study intent": "",
        "Cultural Exposure": "",
        "Emerging Tech Awareness": "",
        "Hobbies": "",
        "Learning Agility": "",
        "Life Skills": "",
        "Motivation Drivers": "",
        "Motivating Activities": "",
        "Newly Acquired Skills": "",
        "Organizational Skills": "",
        "Personal Interests": "",
        "Social Causes": "",
        "Volunteering": "",
        "Personality Traits": ""
    }

    async def fetch_answer(parameter: str, section: str):
        query_filter = {
            "user_id": user_id,
            "section": section,
            "parameter": {"$regex": f".*{parameter}.*", "$options": "i"},
        }
        if has_cv:
            query_filter["cv_id"] = reference_id
        else:
            query_filter["document_id"] = reference_id

        ans_doc = await active_answers_collection.find_one(
            query_filter, sort=[("created_at", DESCENDING)]
        )
        if not ans_doc:
            return None
        VALUE_ONLY_FIELDS = [
            "Core Tasks",
            "Supplementary Tasks",
            "Emerging Tasks",
            "Knowledge",
            "Skills",
        ]

        if parameter.lower() == "achievements":
            value_obj = ans_doc.get("value", {})
            if isinstance(value_obj, dict):
                return value_obj.get("text") or value_obj.get("selected")
            return None

        if parameter in VALUE_ONLY_FIELDS:
            return ans_doc.get("value")
        return (
            ans_doc.get("free_text")
            or ans_doc.get("selected_options")
            or ans_doc.get("value")
        )

    for field, value in talent_info.items():
        db_field_name = "Career Interests" if field == "Career Interest Areas" else field

        needs_fetch = (
            field == "Career Interest Areas"
            or not value
            or value in ["", [], None]
        )

        if needs_fetch:
            if has_cv:
                answer_val = await fetch_answer(db_field_name, "Cv Missing")
                if not answer_val:
                    answer_val = await fetch_answer(db_field_name, "Job Attributes")
            else:
                answer_val = await fetch_answer(db_field_name, "Cv Missing")
                if not answer_val:
                    answer_val = await fetch_answer(db_field_name, "Job Attributes")

            if answer_val:
                talent_info[field] = answer_val

    for field in anchor_attrs:
        answer_val = await fetch_answer(field, "Anchor Attributes")
        if answer_val:
            anchor_attrs[field] = answer_val

    return {
        "success": True,
        "flow": active_flow,
        "cv_id_or_document_id": reference_id,
        "latest_cv_uploaded_at": latest_cv_time,
        "latest_without_cv_created_at": latest_no_cv_time,
        "Talent Information": talent_info,
        "Anchor Attributes": anchor_attrs,
    }


# ---------------------------------------- Extraction without auth ---------------------------------------
#-----------------------------------------------------------------------------------------------------------------
#--------------------------------------------------------------------------------------------------------------------


def generate_dummy_user_id():
    return ObjectId()

@router.post("/extract-cv-no-auth")
async def extract_cv_no_auth(
    file: UploadFile = File(...),
    db=Depends(get_database),
):
    with tempfile.NamedTemporaryFile(delete=False, suffix="." + file.filename.split('.')[-1]) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    data = extract_cv_data_from_file(tmp_path, file.content_type)
    if "error" in data:
        return {"message": "CV extraction failed", "error": data["error"]}

    dummy_user_id = generate_dummy_user_id()

    saved_cv = await save_extracted_cv_data(
        user_id=str(dummy_user_id),
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
        user_id=str(dummy_user_id),
        cv_id=cv_id_str,
        softskills=softskills_suggestions,
        technical_skills=technical_skills_suggestions,
        db=db
    )
    questions_collection = db["questions"]
    questions_doc = await questions_collection.find_one({})
    audience_type = predict_audience_type(data)

    job_questions_with_options = []

    if questions_doc:
        job_attributes = questions_doc.get("Job attributes", [])
        matching_job = next((item for item in job_attributes if item.get("audienceType") == audience_type), None)

        if matching_job:
            job_questions = matching_job.get("questions", [])
            job_options = await generate_job_attribute_options(data, job_questions)
            job_questions_with_options = job_options["suggestions"]

        uploads_collection = db["uploads"]
        await uploads_collection.update_one(
            {"_id": saved_cv["_id"]},
            {"$set": {
                "audienceType": audience_type,
                "job_questions_with_options": job_questions_with_options
            }}
        )

    summary = await get_cv_summary(data)

    def parse_duration(duration_str: str):
        from dateutil import parser as date_parser
        try:
            parts = re.split(r"\s*(?:-|–|—|to)\s*", duration_str or "", flags=re.IGNORECASE)
            if len(parts) != 2:
                return None
            start_str, end_str = parts[0].strip(), parts[1].strip().lower()
            start_date = date_parser.parse(start_str, fuzzy=True)
            if any(x in end_str for x in ("present", "current", "ongoing")):
                end_date = datetime.today()
            else:
                end_date = date_parser.parse(end_str, fuzzy=True)
            return start_date, end_date
        except Exception:
            return None

    job_role = None
    latest_end = datetime.min
    for job in data.get("WorkExperience", []) or []:
        parsed = parse_duration(job.get("Duration", ""))
        if parsed:
            _, end = parsed
            if end > latest_end:
                latest_end = end
                job_role = job.get("Role")

    if not job_role and data.get("WorkExperience"):
        raw_role = data["WorkExperience"][0].get("Role", "")
        if raw_role:
            job_role = raw_role.split("/")[0].split(",")[0].strip()

    if not job_role and data.get("Summary"):
        match = re.search(r"(?i)([A-Z][a-zA-Z\s\/\-]+)\s+with\s+\d+\s+years", data["Summary"])
        if match:
            job_role = match.group(1).strip()

    known_fields = len(summary.get("known", []))
    unknown_fields = len(summary.get("unknown", []))
    total_fields = known_fields + unknown_fields
    known_percentage = round((known_fields / total_fields) * 100, 2) if total_fields else 0.0

    return {
        "parsed_data": data,
        "summary": summary,
        "audienceType": audience_type,
        "candidate": {
            "name": data.get("Name"),
            "job_role": job_role,
            "known_percentage": known_percentage
        },
        "dummy_user_id": str(dummy_user_id),
        "message": "CV data extracted and saved successfully (no-auth)"
    }


async def get_cv_profile_data(
    db: AsyncIOMotorDatabase,
    current_user: dict
):
    uploads_collection = db["uploads"]
    answers_collection = db["answers"]
    answers_without_cv_collection = db["answers_without_cv"]
    proceed_without_cv_collection = db["proceed_without_cv"]

    user_id = str(current_user.get("_id"))
    query = {"user_id": {"$in": [user_id, ObjectId(user_id)]}}

    latest_cv_doc = await uploads_collection.find_one(
        query, sort=[("uploaded_at", DESCENDING)]
    )

    latest_no_cv_doc = await proceed_without_cv_collection.find_one(
        {"user_id": user_id}, sort=[("created_at", DESCENDING)]
    )

    latest_cv_time = latest_cv_doc.get("uploaded_at") if latest_cv_doc else None
    latest_no_cv_time = latest_no_cv_doc.get("created_at") if latest_no_cv_doc else None

    active_flow = "without_cv"
    has_cv = False
    parsed_data = {}
    active_answers_collection = answers_without_cv_collection
    reference_id = None

    if latest_cv_time and (not latest_no_cv_time or latest_cv_time > latest_no_cv_time):
        active_flow = "with_cv"
        has_cv = True
        parsed_data = latest_cv_doc.get("parsed_data", {})
        active_answers_collection = answers_collection
        reference_id = str(latest_cv_doc.get("_id"))
    else:
        reference_id = str(latest_no_cv_doc.get("_id")) if latest_no_cv_doc else None

    talent_info = {
        "Education": parsed_data.get("Education", []),
        "Internships": parsed_data.get("Internships", []),
        "Projects": parsed_data.get("Projects", []),
        "Experience": parsed_data.get("WorkExperience", []),
        "Core Tasks": "",
        "Supplementary Tasks": "",
        "Emerging Tasks": "",
        "Knowledge": "",
        "Skills": "",
        "Work activities": "",
        "Work styles": "",
        "Work values": "",
        "Technical Skills": parsed_data.get("Skills", {}).get("HardSkills", []),
        "Hot Technologies": "",
        "Soft Skills": parsed_data.get("Skills", {}).get("SoftSkills", []),
        "Functional Skills": "",
        "Certifications": parsed_data.get("Certifications", []),
        "Salary grades": "",
        "Career Objective": parsed_data.get("Summary") if has_cv else "",
        "Career Interest Areas": ""
    }

    anchor_attrs = {
        "Achievements": "",
        "Behavioral Skills": "",
        "Interests": "",
        "Competency": "",
        "Cognitive Preferences": "",
        "Creative Inclinations": "",
        "Exploration Interest": "",
        "Future Study Intent": "",
        "Cultural Exposure": "",
        "Emerging Tech Awareness": "",
        "Hobbies": "",
        "Learning Agility": "",
        "Life Skills": "",
        "Motivation Drivers": "",
        "Motivating Activities": "",
        "Newly Acquired Skills": "",
        "Organizational Skills": "",
        "Personal Interests": "",
        "Social Causes": "",
        "Volunteering": "",
        "Personality Traits": ""
    }

    async def fetch_answer(parameter: str, section: str):
        query_filter = {
            "user_id": user_id,
            "section": section,
            "parameter": {"$regex": f".*{parameter}.*", "$options": "i"},
        }
        if has_cv:
            query_filter["cv_id"] = reference_id
        else:
            query_filter["document_id"] = reference_id

        ans_doc = await active_answers_collection.find_one(
            query_filter, sort=[("created_at", DESCENDING)]
        )
        if not ans_doc:
            return None

        VALUE_ONLY_FIELDS = [
            "Core Tasks",
            "Supplementary Tasks",
            "Emerging Tasks",
            "Knowledge",
            "Skills",
        ]

        if parameter.lower() == "achievements":
            value_obj = ans_doc.get("value", {})
            if isinstance(value_obj, dict):
                return value_obj.get("text") or value_obj.get("selected")
            return None

        if parameter in VALUE_ONLY_FIELDS:
            return ans_doc.get("value")

        return (
            ans_doc.get("free_text")
            or ans_doc.get("selected_options")
            or ans_doc.get("value")
        )

    for field, value in talent_info.items():
        db_field_name = "Career Interests" if field == "Career Interest Areas" else field

        needs_fetch = (
            field == "Career Interest Areas"
            or not value
            or value in ["", [], None]
        )

        if needs_fetch:
            if has_cv:
                answer_val = await fetch_answer(db_field_name, "Cv Missing")
                if not answer_val:
                    answer_val = await fetch_answer(db_field_name, "Job Attributes")
            else:
                answer_val = await fetch_answer(db_field_name, "Job Attributes")

            if answer_val:
                talent_info[field] = answer_val

    
    for field in anchor_attrs:
        answer_val = await fetch_answer(field, "Anchor Attributes")
        if answer_val:
            anchor_attrs[field] = answer_val

    return {
        "success": True,
        "flow": active_flow,
        "cv_id_or_document_id": reference_id,
        "latest_cv_uploaded_at": latest_cv_time,
        "latest_without_cv_created_at": latest_no_cv_time,
        "Talent Information": talent_info,
        "Anchor Attributes": anchor_attrs,
    }


def deduplicate_keywords(data):
    """
    Deduplicate values across all fields in the nested dictionary.
    Converts lists to a single value and avoids repeated keywords.
    """
    seen = set()

    def process_subdict(subdict):
        for key, value in subdict.items():
            if isinstance(value, str):
                val = value.strip()
                if val.lower() == "not specified" or val == "":
                    continue
                if val in seen:
                    subdict[key] = ""
                else:
                    seen.add(val)
            elif isinstance(value, list):
                for item in value:
                    if item not in seen:
                        subdict[key] = item
                        seen.add(item)
                        break
                else:
                    subdict[key] = ""
    
    for main_key in data:
        for sub_key in data[main_key]:
            process_subdict(data[main_key][sub_key])
    return data

def to_catchy_keyword(phrase):
    """
    Converts a phrase to a concise, catchy keyword.
    Picks up to 3 words, keeps the essence.
    """
    if not phrase or phrase.lower() == "not specified":
        return phrase

    phrase = phrase.strip()

    words = phrase.split()

    if len(words) > 3:
        words = words[:3]

    return " ".join([w.capitalize() for w in words])

@router.get("/summary/model")
async def extract_cv_summary(
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_user: dict = Depends(get_current_user)
):
    """
    Uses Gemini to summarize the profile data, retaining all fields
    in the output structure regardless of content duplication.
    """

    cv_data = await get_cv_profile_data(db, current_user)

    parsed_resume = {
        "Talent Information": cv_data.get("Talent Information", {}),
        "Anchor Attributes": cv_data.get("Anchor Attributes", {})
    }

    # Handling key mapping consistency for Gemini prompt
    key_map = {
        "Behavioral Skills": "Behavioural Skills",
        "Social Causes": "Social Cause",
        "Future study intent": "Future Study Intent"
    }
    for section in parsed_resume:
        for old_key, new_key in key_map.items():
            if old_key in parsed_resume[section]:
                parsed_resume[section][new_key] = parsed_resume[section].pop(old_key)

    # Note: We must update the prompt to remove the "all keywords are unique" constraint,
    # as the Python code is now designed to tolerate duplicates.
    extract_prompt = f"""
You are a precise JSON extractor. Your task is to extract the **most relevant and concise keywords or phrases** from a structured resume JSON.  

Requirements:
1. For each field, provide a **single short keyword or catchy phrase** (max 3 words).  
2. Prefer **impactful, buzzword-style keywords** that can stand alone.
3. **DO NOT enforce uniqueness** across fields. Provide the best keyword for each field, even if it is similar to another.
4. If a field is missing or contains "Not specified", output "Not specified" (except for Hobbies, which outputs []). 
5. The output must strictly follow the provided JSON structure.

[... Rest of the prompt structure and groupings remain the same ...]

**Output format:** Provide a **single JSON object** with exactly this structure:

{{
  "Talent attributes": {{
    "Core Code": {{
      "Core Tasks": "",
      "Supplementary Tasks": "",
      "Hot Technologies": "",
      "Functional Skills": "",
      "Skills": ""
    }},
    "DNA of work": {{
      "Work Activities": "",
      "Work Values": "",
      "Work Styles": "",
      "Abilities": ""
    }},
    "Interest Compass": {{
      "Career Interest Areas": "",
      "Knowledge": "",
      "Emerging Tasks": ""
    }},
    "Upskills Unlocked": {{
      "Newly Acquired Skills": "",
      "Emerging Tech Awareness": ""
    }}
  }},
  "Anchor attributes": {{
    "Passion Palette": {{
      "Hobbies": [],
      "Personal Interests": "",
      "Motivating Activities": "",
      "Social Cause": "",
      "Cultural Exposure": "",
      "Volunteering": ""
    }},
    "Drives You": {{
      "Motivation Drivers": "",
      "Competency": "",
      "Learning Agility": "",
      "Cognitive Preferences": "",
      "Creative Inclinations": ""
    }},
    "Rooted In You": {{
      "Achievements": "",
      "Life Skills": "",
      "Behavioural Skills": "",
      "Organizational Skills": "",
      "Personality Traits": ""
    }},
    "Moves you forward": {{
      "Exploration Interest": "",
      "Future Study Intent": ""
    }}
  }}
}}

**Instructions:**
Review each field in the input JSON.  
Extract the **most relevant item** per field.  
Convert it into a **short, buzzword-style phrase**.  
Input JSON:
{json.dumps(parsed_resume)}
"""
    gemini_model = get_llm_model()
    response = await asyncio.to_thread(
        gemini_model.generate_content,
        contents=[extract_prompt],
        generation_config=genai.types.GenerationConfig(
            response_mime_type="application/json",
            temperature=0
        ),
    )
    try:
        extracted_data = json.loads(response.text)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Failed to parse Gemini output",
                "raw_output": response.text
            }
        )

    def safe_keyword(value):
        """Return single catchy keyword; fallback to 'Not specified' but DO NOT remove."""
        if not value:
            return "Not specified"
        if isinstance(value, list) and value:
            if field == "Hobbies":
                return [to_catchy_keyword(item) for item in value if item] 
            
            keyword = to_catchy_keyword(value[0])
            return keyword or "Not specified" 

        if isinstance(value, str):
            keyword = to_catchy_keyword(value)
            return keyword or "Not specified"
            
        return "Not specified"

    for main_key in extracted_data:
        for sub_key in extracted_data[main_key]:
            for field, value in extracted_data[main_key][sub_key].items():
                
                extracted_data[main_key][sub_key][field] = safe_keyword(value)

    for main_key in extracted_data:
        for sub_key in extracted_data[main_key]:
            for field, value in extracted_data[main_key][sub_key].items():
                extracted_data[main_key][sub_key][field] = safe_keyword(value)

    job_attribute_groups = {
        "Core Code": ["Core Tasks", "Supplementary Tasks", "Hot Technologies", "Functional Skills", "Skills"],
        "DNA of work": ["Work Activities", "Work Values", "Work Styles", "Abilities"],
        "Interest Compass": ["Career Interest Areas", "Knowledge", "Emerging Tasks"],
    }
    
    anchor_attribute_groups = {
        "Passion Palette": ["Hobbies", "Personal Interests", "Motivating Activities", "Social Cause", "Cultural Exposure", "Volunteering"],
        "Drives You": ["Motivation Drivers", "Competency", "Learning Agility", "Cognitive Preferences", "Creative Inclinations"],
        "Rooted In You": ["Achievements", "Life Skills", "Behavioural Skills", "Organizational Skills", "Personality Traits"],
    }
    def build_attribute_list_values_only(data_source, mapping):
        result = []
        for title, field_keys in mapping.items():
            items = []
            sub_data = data_source.get(title, {}) 
            for key in field_keys:
                value = sub_data.get(key)
                
                if isinstance(value, list):
                    items.extend(item for item in value if item and item != "Not specified")
                elif isinstance(value, str) and value and value != "Not specified":
                    items.append(value)
            unique_items = list(set(items))

            if unique_items: 
                result.append({
                    "title": title,
                    "items": unique_items  
                })
        return result
    
    talent_data = extracted_data.get("Talent attributes", {})
    anchor_data = extracted_data.get("Anchor attributes", {})
    
    job_attributes = build_attribute_list_values_only(talent_data, job_attribute_groups)

    anchor_attributes = build_attribute_list_values_only(anchor_data, anchor_attribute_groups)
    
    upskills_raw = [] 
    upskills_source = talent_data.get("Upskills Unlocked", {})
    for key in ["Newly Acquired Skills", "Emerging Tech Awareness"]:
        value = upskills_source.get(key)
        if isinstance(value, str) and value and value != "Not specified":
            upskills_raw.append(value)
    
    upskills_list = list(set(upskills_raw))

    forwards_raw = [] 
    forwards_source = anchor_data.get("Moves you forward", {})
    for key in ["Exploration Interest", "Future Study Intent"]:
        value = forwards_source.get(key)
        if isinstance(value, str) and value and value != "Not specified":
            forwards_raw.append(value)

    forwards_list = list(set(forwards_raw))
    
    job_prediction_output = {
        "jobAttributes": job_attributes,
        "anchorAttributes": anchor_attributes,
        "upskills": upskills_list,
        "forwards": forwards_list,
    }

    return {
        "success": True,
        "jobPrediction": job_prediction_output
    }
    
from app.services.user import get_user_management_summary
from app.schemas.user import UserManagementResponse
from fastapi import APIRouter, Query
from app.utils.token import get_current_user


# @router.get(
#     "/user-management/full-summary",
#     tags=["User Management"]
# )
# async def user_management_full_summary(user_id: str):
#     return await get_user_management_summary(user_id)

@router.get(
    "/user-management/full-summary",
    tags=["User Management"]
)
async def user_management_full_summary(
    current_user: dict = Depends(get_current_user)
):
    user_id = current_user["id"]   # derived from token
    return await get_user_management_summary(user_id)


@router.put("/edit-profile")
async def edit_profile(
    payload: EditProfileRequest,
    db: AsyncIOMotorDatabase = Depends(get_database),
    current_user: dict = Depends(get_current_user)
):
    users_collection = db["users"]

    user_id = ObjectId(current_user["_id"])

    update_data = {}

    # ---------------- Update Name ----------------
    if payload.first_name:
        update_data["first_name"] = payload.first_name

    if payload.last_name:
        update_data["last_name"] = payload.last_name

    # ---------------- Update Email ----------------
    if payload.email:

        existing_email = await users_collection.find_one({
            "email": payload.email,
            "_id": {"$ne": user_id}
        })

        if existing_email:
            raise HTTPException(
                status_code=400,
                detail="Email already exists"
            )

        update_data["email"] = payload.email

    # ---------------- Change Password ----------------
    if payload.new_password:

        if not payload.current_password:
            raise HTTPException(
                status_code=400,
                detail="Current password is required"
            )

        user = await users_collection.find_one({"_id": user_id})

        if not verify_password(payload.current_password, user["password"]):
            raise HTTPException(
                status_code=400,
                detail="Current password is incorrect"
            )

        update_data["password"] = hash_password(payload.new_password)

    # ---------------- No Data Check ----------------
    if not update_data:
        raise HTTPException(
            status_code=400,
            detail="No fields provided to update"
        )

    # ---------------- Update User ----------------
    await users_collection.update_one(
        {"_id": user_id},
        {"$set": update_data}
    )

    updated_user = await users_collection.find_one({"_id": user_id})

    return {
        "success": True,
        "message": "Profile updated successfully",
        "user": {
            "id": str(updated_user["_id"]),
            "first_name": updated_user.get("first_name"),
            "last_name": updated_user.get("last_name"),
            "email": updated_user.get("email")
        }
    }