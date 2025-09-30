from fastapi import HTTPException
from bson import ObjectId
from pymongo import DESCENDING
from datetime import datetime
from app.utils.cv_extractor import predict_audience_type
from app.utils.cv_extractor import generate_missing_field_suggestions, generate_anchor_attribute_options, generate_anchor_options_from_answers_without_cv, generate_job_attribute_options_without_cv
from app.services.cv_comparison import get_cv_summary
import json



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
    """
    Always run option generation first, then merge uploads + system,
    keeping uploads no matter what, and suppressing only system duplicates.
    """
    uploads_collection = db["uploads"]
    questions_collection = db["questions"]

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

    system_questions = []
    for cq in matching_entry.get("questions", []):
        param = normalize_parameter(cq.get("parameter"))
        if param in normalized_excludes:
            continue

        sq_obj = {
            "parameter": param,
            "question": cq.get("question"),
            "type": cq.get("type"),
            "options": cq.get("options", []),
            "iconfilename": cq.get("iconfilename")
        }
        if "limit" in cq or "Limit" in cq:
            sq_obj["limit"] = cq.get("limit") or cq.get("Limit")

        system_questions.append(sq_obj)
    if "anchor_questions_with_options" not in latest_cv:

        await generate_anchor_attribute_options(
            user_id=str(current_user["_id"]),
            questions=system_questions, 
            model=model,
            get_database=get_database
        )

        latest_cv = await uploads_collection.find_one({"_id": latest_cv["_id"]})

    upload_questions = []
    for aq in latest_cv.get("anchor_questions_with_options", []):
        params = aq.get("parameter", [])
        if isinstance(params, str):
            params = [params]

        included = [
            normalize_parameter(p)
            for p in params
            if normalize_parameter(p) not in normalized_excludes
        ]
        if not included:
            continue

        uq_obj = {
            "parameter": " + ".join(included),
            "question": aq.get("question"),
            "type": aq.get("type"),
            "options": aq.get("options", []),
            "iconfilename": aq.get("iconfilename")
        }
        if "limit" in aq or "Limit" in aq:
            uq_obj["limit"] = aq.get("limit") or aq.get("Limit")

        upload_questions.append(uq_obj)
        if len(upload_questions) >= 2:
            break

    upload_params = {normalize_parameter(q["parameter"]) for q in upload_questions}
    merged_questions = upload_questions + [
        q for q in system_questions
        if normalize_parameter(q["parameter"]) not in upload_params
    ]

    return {
        "success": True,
        "audienceType": audience_type,
        "cv_id": cv_id,
        "questions": merged_questions
    }
#___________________________________________________________________________________________________________________________________________________
#____________________________________________________________________________________________________________________________________________________
#----------------------------------------------------------Second Flow-----------------------------------------------------------------------------

async def get_audience_questions_service_without_cv(db, current_user):
    """
    Fetch audience-specific job questions with options 
    for a user who proceeded without CV upload.
    Auto-generates if not already saved.
    """
    proceed_collection = db["proceed_without_cv"]

    latest_doc = await proceed_collection.find_one(
        {"user_id": str(current_user["_id"])}, 
        sort=[("created_at", -1)]
    )
    if not latest_doc:
        raise HTTPException(status_code=404, detail="No proceed_without_cv doc found for this user")

    audience_type = latest_doc.get("audienceType")
    job_questions_with_options = latest_doc.get("job_questions_with_options", [])

    if not job_questions_with_options:
        
        generated = await generate_job_attribute_options_without_cv(str(current_user["_id"]), db)
        job_questions_with_options = generated["suggestions"]

    return {
        "success": True,
        "audienceType": audience_type,
        "questions": job_questions_with_options
    }

async def get_questions_by_parameters_withoutcv(
    db,
    current_user,
    attribute_type: str,
    parameters: list,
    audience_type: str = None  # optionally pass audienceType directly
):
    """
    Fetch specific questions from anchor attributes based on parameters & audience type.
    If audience_type is not provided, fetch it from the latest proceed_without_cv document.
    Also returns the latest document _id as doc_id.
    """
    questions_collection = db["questions"]
    proceed_collection = db["proceed_without_cv"]

    # Fetch latest proceed_without_cv record if audience_type not passed
    if not audience_type:
        latest_record = await proceed_collection.find_one(
            {"user_id": str(current_user["_id"])},
            sort=[("_id", -1)]
        )
        if not latest_record or "audienceType" not in latest_record:
            raise HTTPException(status_code=404, detail="Audience type not found for user")
        audience_type = latest_record["audienceType"]
        doc_id = str(latest_record["_id"])
    else:
        # If audience_type is provided, fetch the latest doc_id for reference
        latest_record = await proceed_collection.find_one(
            {"user_id": str(current_user["_id"])},
            sort=[("_id", -1)]
        )
        doc_id = str(latest_record["_id"]) if latest_record else None

    # Fetch questions collection
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

    # Filter questions by parameters
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
        "doc_id": doc_id,
        "questions": results,
    }


async def get_remaining_anchor_questions_without_cv(
    db, current_user, model, exclude_params=None, attribute_type=None
):
    """
    Fetch remaining anchor questions for user using latest proceed_without_cv,
    merged with system questions, excluding duplicates.
    """
    user_id = str(current_user["_id"])
    if exclude_params is None:
        exclude_params = [
            "Personal Interests + Hobbies + Exploration Interest + Motivation Drivers + Motivating Activities",
            "Achievements",
        ]
    if attribute_type is None:
        attribute_type = "Anchor attributes"

    # Fetch the latest proceed_without_cv document
    latest_proceed_list = await db["proceed_without_cv"].find(
        {"user_id": user_id}
    ).sort("created_at", -1).to_list(length=1)
    latest_proceed = latest_proceed_list[0] if latest_proceed_list else None

    if not latest_proceed:
        raise HTTPException(status_code=404, detail="No proceed_without_cv found for user")

    audience_type = latest_proceed.get("audienceType", "General")

    # Fetch system questions based on audienceType
    questions_doc = await db["questions"].find_one({}) or {}
    system_questions = []
    for item in questions_doc.get(attribute_type, []):
        if item.get("audienceType") != audience_type:
            continue
        for q in item.get("questions", []):
            param = q.get("parameter")
            if param:
                system_questions.append(q)

    # Only generate options if they don’t exist yet
    if "anchor_questions_with_options" in latest_proceed:
        suggestions = latest_proceed["anchor_questions_with_options"]
    else:
        await generate_anchor_options_from_answers_without_cv(
            user_id=user_id,
            questions=system_questions,
            model=model,
            get_database=lambda: db,
        )
        latest_proceed_list = await db["proceed_without_cv"].find(
            {"user_id": user_id}
        ).sort("created_at", -1).to_list(length=1)
        latest_proceed = latest_proceed_list[0]
        suggestions = latest_proceed.get("anchor_questions_with_options", [])

    # Collect user questions excluding the ones in exclude_params
    user_questions = []
    seen_parameters = set()
    for aq in suggestions:
        param = aq.get("parameter")
        if param:
            # Normalize to string
            if isinstance(param, list):
                param_str = " + ".join(param)
            else:
                param_str = param
            if param_str not in exclude_params and param_str not in seen_parameters:
                user_questions.append(
                    {
                        "parameter": param_str,
                        "question": aq.get("question"),
                        "options": aq.get("options", []),
                    }
                )
                seen_parameters.add(param_str)

    # Merge with system questions not in exclude_params or already seen
    for item in system_questions:
        param = item.get("parameter")
        if not param:
            continue
        if isinstance(param, list):
            param_str = " + ".join(param)
        else:
            param_str = param
        if param_str in exclude_params or param_str in seen_parameters:
            continue
        user_questions.append(
            {
                "parameter": param_str,
                "question": item.get("question"),
                "options": item.get("options", []),
            }
        )
        seen_parameters.add(param_str)

    return {"success": True, "audienceType": audience_type, "questions": user_questions}