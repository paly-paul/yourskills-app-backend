from fastapi import HTTPException
from bson import ObjectId
from pymongo import DESCENDING
from datetime import datetime
from app.utils.cv_extractor import predict_audience_type
from app.utils.cv_extractor import generate_missing_field_suggestions, generate_anchor_attribute_options
from app.services.cv_comparison import get_cv_summary
import json


# async def get_profile_summary_service(db, current_user):
#     uploads_collection = db["uploads"]
#     user_id = str(current_user.get("_id"))

#     query = {"user_id": {"$in": [user_id, ObjectId(user_id)]}}
#     latest_upload = await uploads_collection.find_one(
#         query,
#         sort=[("uploaded_at", DESCENDING)]
#     )
#     if not latest_upload:
#         raise HTTPException(status_code=404, detail="No CV uploaded yet")

#     parsed_data = latest_upload.get("parsed_data", {}) or {}

#     work_experiences = parsed_data.get("WorkExperience", []) or []
#     def parse_duration(duration_str: str):
#         import re
#         from dateutil import parser as date_parser
#         try:
#             parts = re.split(r"\s*(?:-|–|—|to)\s*", duration_str or "", flags=re.IGNORECASE)
#             if len(parts) != 2:
#                 return None
#             start_str, end_str = parts[0].strip(), parts[1].strip().lower()
#             start_date = date_parser.parse(start_str, fuzzy=True)
#             if any(x in end_str for x in ("present", "current", "ongoing")):
#                 end_date = datetime.today()
#             else:
#                 end_date = date_parser.parse(end_str, fuzzy=True)
#             return start_date, end_date
#         except Exception:
#             return None

#     job_role = None
#     latest_end = datetime.min
#     for job in work_experiences:
#         parsed = parse_duration(job.get("Duration", ""))
#         if parsed:
#             _, end = parsed
#             if end > latest_end:
#                 latest_end = end
#                 job_role = job.get("Role")

#     summary = await get_cv_summary(parsed_data)
#     known_fields = len(summary.get("known", []))
#     unknown_fields = len(summary.get("unknown", []))
#     total_fields = known_fields + unknown_fields

#     known_percentage = round((known_fields / total_fields) * 100, 2) if total_fields else 0.0

#     return {
#         "candidate": {
#             "name": parsed_data.get("Name"),
#             "job_role": job_role,
#             "audience_type": predict_audience_type(parsed_data),
#             "known_percentage": known_percentage
#         }
#     }


async def get_missing_field_questions_service(section: str, db, current_user):
    uploads_collection = db["uploads"]
    questions_collection = db["questions"]
    skill_suggestions_collection = db["skill_suggestions"]

    user_id = str(current_user.get("_id"))

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
        "Salary Grades": None,
    }

    latest_cv = await uploads_collection.find_one(
        {"user_id": {"$in": [user_id, ObjectId(user_id)]}},
        sort=[("_id", -1)]
    )

    if not latest_cv:
        return {
            "success": False,
            "reason": "No CV found for user.",
            "section": section,
            "questions": [],
            "missing_fields": [],
        }

    parsed_data = latest_cv.get("parsed_data", {})
    cv_id = str(latest_cv["_id"])

    questions_doc = await questions_collection.find_one({}) or {}
    questions_docs = questions_doc.get(section, [])

    all_parameters = [
        q.get("parameter")
        for q in questions_docs
        if q.get("parameter") and q["parameter"] != "Tools"
    ]

    missing_fields = []

    hard_skills = parsed_data.get("Skills", {}).get("HardSkills", [])
    if not hard_skills:
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
            if isinstance(value, dict):
                value = value.get(k)
            else:
                value = None
            if value is None:
                break

        if not value or (isinstance(value, list) and len(value) == 0):
            missing_fields.append(param)
        elif isinstance(value, dict):
            if all(not v or (isinstance(v, list) and len(v) == 0) for v in value.values()):
                missing_fields.append(param)

    suggestions_data = {}

    skill_doc = None
    llm_suggestions = None

    if any(field in missing_fields for field in ["Technical Skills", "Soft Skills"]):
        skill_doc = await skill_suggestions_collection.find_one({"cv_id": cv_id})

        if "Technical Skills" in missing_fields:
            if skill_doc and skill_doc.get("technical_skills_suggestions"):
                suggestions_data["Technical Skills"] = skill_doc["technical_skills_suggestions"]
            else:
                llm_suggestions = await generate_missing_field_suggestions(parsed_data)
                suggestions_data["Technical Skills"] = llm_suggestions.get("technical_skills_suggestions", [])

        if "Soft Skills" in missing_fields:
            if skill_doc and skill_doc.get("softskills_suggestions"):
                suggestions_data["Soft Skills"] = skill_doc["softskills_suggestions"]
            else:
                llm_suggestions = llm_suggestions or await generate_missing_field_suggestions(parsed_data)
                suggestions_data["Soft Skills"] = llm_suggestions.get("softskills_suggestions", [])

    missing_questions = []
    for q in questions_docs:
        param = q.get("parameter")
        if param in missing_fields:
            q_entry = {**q}
            if "_id" in q_entry:
                q_entry["_id"] = str(q_entry["_id"])
       
            if param in suggestions_data:
                q_entry["options"] = suggestions_data[param]
            missing_questions.append(q_entry)

    return {
        "success": True,
        "section": section,
        "count": len(missing_questions),
        "questions": missing_questions,
        "missing_fields": missing_fields,
        "cv_id": cv_id,
    }


async def get_audience_questions_service(db, current_user):
    uploads_collection = db["uploads"]

    latest_cv = await uploads_collection.find_one(
        {"user_id": ObjectId(current_user["_id"])},
        sort=[("_id", -1)]
    )
    if not latest_cv or "parsed_data" not in latest_cv:
        raise HTTPException(status_code=404, detail="No CV data found for this user")

    audience_type = latest_cv.get("audienceType")
    job_questions_with_options = latest_cv.get("job_questions_with_options", [])

    if not job_questions_with_options:
        raise HTTPException(status_code=404, detail="No job questions found for this user")

    return {
        "success": True,
        "audienceType": audience_type,
        "questions": job_questions_with_options,
    }






def normalize_parameter(param):
    """Convert uploads params (array) into the same format as questions collection"""
    if isinstance(param, list):
        return " + ".join(param)
    return param

# async def get_questions_by_audience(db, current_user, attribute_type: str):
#     """Fetch questions based on audience type and attribute category (Job/Anchor).
#        Two parameters come from uploads (with options), rest from questions collection.
#     """
#     uploads_collection = db["uploads"]
#     questions_collection = db["questions"]

#     latest_cv = await uploads_collection.find_one(
#         {"user_id": ObjectId(current_user["_id"])},
#         sort=[("_id", -1)]
#     )
#     if not latest_cv or "parsed_data" not in latest_cv:
#         raise HTTPException(status_code=404, detail="No CV data found for this user")

#     parsed_data = latest_cv["parsed_data"]

#     audience_type = predict_audience_type(parsed_data)

#     questions_doc = await questions_collection.find_one({})
#     if not questions_doc:
#         raise HTTPException(status_code=404, detail="No questions collection found")

#     attributes = questions_doc.get(attribute_type, [])
#     matching_entry = next(
#         (item for item in attributes if item.get("audienceType") == audience_type),
#         None
#     )
#     if not matching_entry:
#         raise HTTPException(
#             status_code=404,
#             detail=f"No {attribute_type.lower()} questions found for audience type: {audience_type}"
#         )

#     results = []

#     special_params = [
#         "Creative Inclinations + Organizational Skills + Competency + Personality Traits",
#         "Newly Acquired Skills + Emerging Tech Awareness + Future Study Intent"
#     ]

#     upload_questions = latest_cv.get("anchor_questions_with_options", [])
#     for uq in upload_questions:
#         param = normalize_parameter(uq.get("parameters"))
#         if param in special_params:
#             results.append({
#                 "parameter": param,
#                 "question": uq.get("question"),
#                 "type": uq.get("type"),
#                 "options": uq.get("options", []),
#                 "iconfilename": uq.get("iconfilename"),
#                 "source": "uploads"
#             })

#     for cq in matching_entry.get("questions", []):
#         param = normalize_parameter(cq.get("parameter"))
#         if param not in [r["parameter"] for r in results]: 
#             results.append({
#                 "parameter": param,
#                 "question": cq.get("question"),
#                 "type":cq.get("type"),
#                 "options": cq.get("options", []),
#                 "iconfilename": cq.get("iconfilename"),
#                 "source": "questions_collection"
#             })

#     return {
#         "success": True,
#         "audienceType": audience_type,
#         "questions": results,
#     }


async def get_questions_by_parameters(db, current_user, attribute_type: str, parameters: list):
    """Fetch specific questions from anchor attributes based on parameters & audience type."""
    uploads_collection = db["uploads"]
    questions_collection = db["questions"]

    latest_cv = await uploads_collection.find_one(
        {"user_id": ObjectId(current_user["_id"])},
        sort=[("_id", -1)]
    )
    if not latest_cv or "parsed_data" not in latest_cv:
        raise HTTPException(status_code=404, detail="No CV data found for this user")

    parsed_data = latest_cv["parsed_data"]

    audience_type = predict_audience_type(parsed_data)

    questions_doc = await questions_collection.find_one({})
    if not questions_doc:
        raise HTTPException(status_code=404, detail="No questions collection found")

    attributes = questions_doc.get(attribute_type, [])
    matching_entry = next(
        (item for item in attributes if item.get("audienceType") == audience_type),
        None
    )
    if not matching_entry:
        raise HTTPException(
            status_code=404,
            detail=f"No {attribute_type.lower()} questions found for audience type: {audience_type}"
        )


    results = []
    for cq in matching_entry.get("questions", []):
        param = normalize_parameter(cq.get("parameter"))
        if param in parameters:
            results.append({
                "parameter": param,
                "question": cq.get("question"),
                "type": cq.get("type"),
                "options": cq.get("options", []),
                "iconfilename": cq.get("iconfilename"),
                "source": "questions_collection"
            })

    return {
        "success": True,
        "audienceType": audience_type,
        "questions": results,
    }
async def get_questions_excluding_parameters(
    db, current_user, attribute_type: str, exclude_params: list, model, get_database
):
    """Fetch up to two questions from uploads collection (CV),
    then fetch questions from questions collection excluding
    given parameters and any already in uploads.
    """

    uploads_collection = db["uploads"]
    questions_collection = db["questions"]

    # Fetch the latest CV
    latest_cv = await uploads_collection.find_one(
        {"user_id": ObjectId(current_user["_id"]), "source": "cv"},
        sort=[("uploaded_at", -1)]
    )
    if not latest_cv or "parsed_data" not in latest_cv:
        raise HTTPException(status_code=404, detail="No CV data found for this user")

    parsed_data = latest_cv["parsed_data"]
    cv_id = str(latest_cv["_id"])
    audience_type = predict_audience_type(parsed_data)

    normalized_excludes = [normalize_parameter(e) for e in exclude_params]

    # Build upload_questions from existing anchor_questions_with_options
    upload_questions = []
    upload_params = set()
    for aq in latest_cv.get("anchor_questions_with_options", []):
        included_params = [
            normalize_parameter(p)
            for p in aq.get("parameters", [])
            if normalize_parameter(p) not in normalized_excludes
        ]

        if included_params:
            upload_params.update(included_params)
            upload_questions.append({
                "parameters": included_params,
                "question": aq.get("question"),
                "type": aq.get("type"),
                "options": aq.get("options", []),
                "iconfilename": aq.get("iconfilename"),
                "source": "uploads_collection"
            })

        if len(upload_questions) >= 2:
            break

    # Fetch questions from questions_collection
    questions_doc = await questions_collection.find_one({})
    if not questions_doc:
        raise HTTPException(status_code=404, detail="No questions collection found")

    attributes = questions_doc.get(attribute_type, [])
    matching_entry = next(
        (item for item in attributes if item.get("audienceType") == audience_type),
        None
    )
    if not matching_entry:
        raise HTTPException(
            status_code=404,
            detail=f"No {attribute_type.lower()} questions found for audience type: {audience_type}"
        )

    # Prepare results from questions_collection
    results = []
    for cq in matching_entry.get("questions", []):
        param = normalize_parameter(cq.get("parameter"))

        if param in normalized_excludes:
            continue

        skip = False
        for up in upload_params:
            if up in param or param in up:
                skip = True
                break
        if skip:
            continue

        results.append({
            "parameter": param,
            "question": cq.get("question"),
            "type": cq.get("type"),
            "options": cq.get("options", []),
            "iconfilename": cq.get("iconfilename"),
            "source": "questions_collection"
        })

    # Generate options for target parameters and save to DB
    anchor_response = await generate_anchor_attribute_options(
        questions=results,
        model=model,
        get_database=get_database,
        user_id=str(current_user["_id"])
    )

    generated_map = {
        normalize_parameter(p): suggestion.get("options", [])
        for suggestion in anchor_response.get("suggestions", [])
        for p in suggestion.get("parameters", [])
    }

    for q in results:
        param = normalize_parameter(q["parameter"])
        if param in generated_map:
            q["options"] = generated_map[param]

    # 🔑 Re-fetch latest CV to rebuild upload_questions including generated options
    latest_cv = await uploads_collection.find_one({"_id": latest_cv["_id"]})

    # Rebuild upload_questions strictly from CV, max 2
    upload_questions = []
    upload_params = set()
    for aq in latest_cv.get("anchor_questions_with_options", []):
        included_params = [
            normalize_parameter(p)
            for p in aq.get("parameters", [])
            if normalize_parameter(p) not in normalized_excludes
        ]

        if included_params:
            upload_params.update(included_params)
            upload_questions.append({
                "parameters": included_params,
                "question": aq.get("question"),
                "type": aq.get("type"),
                "options": aq.get("options", []),
                "iconfilename": aq.get("iconfilename"),
                "source": "uploads_collection"
            })

        if len(upload_questions) >= 2:
            break

    # Filter results to exclude any already in upload_questions
    results = [
        q for q in results
        if not any(
            up in normalize_parameter(q["parameter"]) or normalize_parameter(q["parameter"]) in up
            for up in upload_params
        )
    ]

    return {
        "success": True,
        "audienceType": audience_type,
        "cv_id": cv_id,
        "questions": results,
        "upload_questions": upload_questions
    }







