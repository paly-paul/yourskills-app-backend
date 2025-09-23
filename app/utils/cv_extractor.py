import os
import json
import pathlib
from datetime import datetime
from dateutil import parser as date_parser
from dotenv import load_dotenv
import google.generativeai as genai
from docx import Document
import re
from typing import Dict, List, Tuple,Any
from collections import defaultdict
from app.db.database import get_database
import random
import json
import uuid
from datetime import datetime
from fastapi import HTTPException
from bson import ObjectId


load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-1.5-flash")


def parse_duration(duration_str):
    try:
        duration_str = duration_str.replace("’", "'").replace("‘", "'").strip()
        duration_str = re.sub(r"\s+", " ", duration_str)
        duration_str = re.sub(r"\(.*?\)", "", duration_str)

        parts = re.split(r"\s*(?:-|–|—|to)\s*", duration_str, flags=re.IGNORECASE)
        if len(parts) != 2:
            return None

        start_str, end_str = parts[0].strip(), parts[1].strip().lower()

        try:
            start_date = datetime.strptime(start_str, "%m/%Y")
        except:
            start_date = date_parser.parse(start_str, fuzzy=True)

        if any(word in end_str for word in ["present", "current", "now"]):
            end_date = datetime.today()
        else:
            try:
                end_date = datetime.strptime(end_str, "%m/%Y")
            except:
                end_date = date_parser.parse(end_str, fuzzy=True)

        return start_date, end_date
    except Exception as e:
        print("Duration parsing error:", str(e))
        return None
def extract_years_from_summary(summary_text: str) -> float:
    """
    Extract years of experience directly from the Summary section
    if WorkExperience durations are missing.
    """
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
        parsed = parse_duration(duration_str)
        if parsed:
            start, end = parsed
            months = (end.year - start.year) * 12 + (end.month - start.month) + 1
            total_months += max(0, months)
    return round(total_months / 12, 2)


def clean_json(obj):
    if isinstance(obj, dict):
        return {k: clean_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_json(v) for v in obj]
    elif obj is None:
        return ""
    return obj


def extract_docx_text(filepath):
    doc = Document(filepath)
    texts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                cell_text = cell.text.strip()
                if cell_text:
                    texts.append(cell_text)
    return "\n".join(texts)
def extract_job_role(parsed_json):

    work_exps = parsed_json.get("WorkExperience", [])
    if work_exps and work_exps[0].get("Role"):
        role = work_exps[0]["Role"]

        return role.split("/")[0].split(",")[0].strip()

    summary = parsed_json.get("Summary", "")
    if summary:
        match = re.search(r"(?i)([A-Z][a-zA-Z\s\/\-]+)\s+with\s+\d+\s+years", summary)
        if match:
            role = match.group(1).strip()
            return role.split("/")[0].split(",")[0].strip()

    return None


def extract_cv_data_from_file(filepath: str, mime_type: str):
    prompt = """ 
You are an expert resume parser.

Given a resume file, extract structured JSON with the following fields:

{
  "Name": "",
  "Email": "",
  "Phone": "",
  "Address": "",
  "LinkedIn": "",
  "Summary": "",
  "Skills": {
    "HardSkills": [],
    "SoftSkills": [],
    "Tools": []
  },
  
  "WorkExperience": [
    {
      "Company": "",
      "Role": "",
      "Duration": "",
      "Description": ""
    }
  ],
  "Education": [
    {
      "Degree": "",
      "Institution": "",
      "Grade": "",
      "Year": ""
    }
  ],
  "Certifications": [
    {
      "Name": "",
      "Issuer": "",
      "Year": ""
    }
  ],
  "Projects": [
    {
      "Title": "",
      "Description": ""
    }
  ],
  "Languages": [
    {
      "Language": "",
      "Proficiency": ""
    }
  ],
  "Awards": [
    {
      "Title": "",
      "Issuer": "",
      "Year": ""
    }
  ],
  "VolunteerExperience": [
    {
      "Organization": "",
      "Role": "",
      "Duration": "",
      "Description": ""
    }
  ],
  "Hobbies": [],
  "OtherSections": [
    {
      "Title": "",
      "Description": ""
    }
  ],
  "YearsOfExperience": 0.0
}

Instructions:
1. Extract data only if explicitly mentioned in the CV text.
2. Do NOT infer, guess, or summarize missing values.
3. For Skills and Tools: extract explicitly mentioned items and categorize into HardSkills, SoftSkills, Tools.
4. For WorkExperience:
   - If an Experience section exists, extract normally.
   - If Duration is missing, scan Summary and Projects for Role and Years of Experience.
   - If no Experience section exists, analyze Summary and Projects for any mention of experience (e.g., years, roles, domains) and use that to populate WorkExperience.
   - If Summary explicitly mentions roles (e.g., "Project Manager", "Senior Developer"), include them in WorkExperience even if no company is listed.
5. For YearsOfExperience:
   - First, calculate based only on explicitly mentioned WorkExperience dates or durations.
   - If none are found, extract directly from Summary using explicit mentions like:
       - "X years of experience"
       - "over X years"
       - "more than X years"
     (Example regex pattern: (?i)(over|more than|about)?\s*(\d+)\s*(\+)?\s*years? of experience)
   - Use that number to populate YearsOfExperience.
6. Return only valid JSON. Start with { and end with }.
"""
    try:
        if mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            file_text = extract_docx_text(filepath)
            content_input = [file_text, prompt]
        else:
            file_bytes = pathlib.Path(filepath).read_bytes()
            content_input = [
                {"mime_type": mime_type, "data": file_bytes},
                prompt
            ]

        response = model.generate_content(content_input, stream=False)
        response_text = response.text.strip()

        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]

        response_text = response_text.strip()
        start_idx = response_text.find('{')
        end_idx = response_text.rfind('}')
        response_text = response_text[start_idx:end_idx+1]

        parsed_json = json.loads(response_text)
        parsed_json = clean_json(parsed_json)

        work_exp = parsed_json.get("WorkExperience", [])
        years_from_work = calculate_years_of_experience(work_exp)

        if years_from_work > 0:
            parsed_json["YearsOfExperience"] = years_from_work
        else:
            parsed_json["YearsOfExperience"] = extract_years_from_summary(parsed_json.get("Summary", ""))

        
        parsed_json["JobRole"] = extract_job_role(parsed_json)

        return parsed_json

    except Exception as e:
        print("CV Extraction Error:", str(e))
        return {"error": "Failed to parse CV data"}



def predict_audience_type(parsed_data: Dict) -> str:
    work_exp_list = parsed_data.get("WorkExperience", [])

    work_periods = []
    for job in work_exp_list:
        duration_str = job.get("Duration", "")
        parsed = parse_duration(duration_str)
        if parsed:
            work_periods.append(parsed)

    work_periods.sort(key=lambda x: x[0])

    merged_work: List[Tuple[datetime, datetime]] = []
    for p in work_periods:
        if not merged_work:
            merged_work.append(p)
        else:
            last_start, last_end = merged_work[-1]
            curr_start, curr_end = p
            if curr_start <= last_end:  
                merged_work[-1] = (last_start, max(last_end, curr_end))
            else:
                merged_work.append(p)

    if isinstance(parsed_data.get("YearsOfExperience"), (int, float)):
        total_years = float(parsed_data["YearsOfExperience"])
    else:
        total_years = sum((e - s).days for s, e in merged_work) / 365.0 if merged_work else 0.0

    currently_working = any(
        ("Duration" in w and re.search(r"(present|current|ongoing|now)", w["Duration"], re.IGNORECASE))
        for w in work_exp_list
    )

    def months_between(a: datetime, b: datetime) -> float:
        return (b - a).days / 30.0

    employment_gap = False
    if not currently_working and merged_work:
        last_end = merged_work[-1][1]
        if months_between(last_end, datetime.today()) >= 12:
            employment_gap = True

    if not currently_working and employment_gap:
        return "Job Seeker"
    elif total_years <= 1:
        return "Student"
    elif 1 < total_years <= 4:
        return "Early Professional (2-3 years of experience)"
    elif total_years > 4:
        return "Mid Career Pivot"
    else:
        return "Early Professional (2-3 years of experience)"


FIELD_MAPPING = {
    "softskills": "softskills_suggestions",
    "soft skills": "softskills_suggestions",
    "softskills_suggestions": "softskills_suggestions",
    "hardskills": "technical_skills_suggestions",
    "hard skills": "technical_skills_suggestions",
    "tools": "technical_skills_suggestions",
    "technicalskills": "technical_skills_suggestions",
    "technical_skills": "technical_skills_suggestions"
}

def normalize_key(key: str) -> str:
    return key.strip().lower().replace("_", "").replace(" ", "")

def clean_llm_json_response(response_text: str) -> str:
    response_text = response_text.strip()
    if response_text.startswith("```json"):
        response_text = response_text[len("```json"):].strip()
    if response_text.startswith("```"):
        response_text = response_text[3:].strip()
    if response_text.endswith("```"):
        response_text = response_text[:-3].strip()

    start_idx = response_text.find("{")
    end_idx = response_text.rfind("}")
    if start_idx != -1 and end_idx != -1:
        response_text = response_text[start_idx:end_idx + 1]

    return response_text


async def generate_missing_field_suggestions(cv_context: dict) -> dict:
    suggestions = {
        "softskills_suggestions": [],
        "technical_skills_suggestions": []
    }

    missing_fields = []
    generate_technical = False

    if not cv_context.get("Skills", {}).get("SoftSkills"):
        missing_fields.append("SoftSkills")

    if not cv_context.get("Skills", {}).get("HardSkills") or not cv_context.get("Tools"):
        missing_fields.extend(["HardSkills", "Tools"])
        generate_technical = True

    if not missing_fields:
        return suggestions

    context_str = "\n".join(f"{k}: {v}" for k, v in cv_context.items() if v)
    prompt = (
        "You are an AI helping complete missing CV fields.\n"
        f"CV Context:\n{context_str}\n\n"
        f"Missing Fields: {missing_fields}\n"
        "Respond ONLY in JSON with keys matching the missing fields. "
        "Each value must be a JSON array of strings."
    )

    response = await model.generate_content_async(prompt)
    cleaned = clean_llm_json_response(response.text)

    try:
        parsed = json.loads(cleaned)
    except Exception as e:
        parsed = {f: [] for f in missing_fields}

    for key, value in parsed.items():
        norm_key = normalize_key(key)
        mapped_field = FIELD_MAPPING.get(norm_key)

        if not mapped_field:
            continue

        if isinstance(value, str):
            items = [s.strip() for s in value.split(",") if s.strip()]
        elif isinstance(value, list):
            items = [str(s).strip() for s in value if str(s).strip()]
        else:
            items = []

        if mapped_field == "softskills_suggestions":
            suggestions["softskills_suggestions"].extend(items)
        if mapped_field == "technical_skills_suggestions" and generate_technical:
            suggestions["technical_skills_suggestions"].extend(items)

    suggestions["softskills_suggestions"] = list(set(suggestions["softskills_suggestions"]))
    suggestions["technical_skills_suggestions"] = list(set(suggestions["technical_skills_suggestions"]))

    return suggestions



async def generate_job_attribute_options(cv_context: dict, questions_from_db: list) -> dict:
    """
    Generates multiple-choice options for each job attribute question.
    Each parameter contributes exactly 5 options.
    If the parameter string has multiple joined with '+', 
    total options = 5 * number_of_parameters.
    NOTE: limit is ignored for generation, but preserved in output.
    Audience type is taken from cv_context (uploads collection).
    """
    results = []
    context_str = "\n".join(f"{k}: {v}" for k, v in cv_context.items() if v)

    # 🔹 Extract audience type from uploads collection (cv_context)
    audience_type = cv_context.get("audience_type") or cv_context.get("audience")

    # 🔹 Filter questions based on audience type
    if audience_type:
        questions_from_db = [
            q for q in questions_from_db
            if not q.get("audience") or q.get("audience") == audience_type
        ]

    for q in questions_from_db:
        parameter = q.get("parameter", "")
        question_text = q.get("question")
        qtype = q.get("type")
        iconfilename = q.get("iconfilename")
        limit = q.get("limit") or q.get("Limit")

        parameter_list = [p.strip() for p in parameter.split("+")]
        option_count = 5 * len(parameter_list)
        labels = [chr(65 + i) for i in range(option_count)]

        prompt = (
            "You are an AI assistant generating career-related multiple-choice options.\n\n"
            f"CV Context:\n{context_str}\n\n"
            f"Question: {question_text}\n\n"
            "Respond ONLY in JSON format:\n"
            "{\n"
            "  \"options\": [\n"
            + ",\n".join([f"    \"{lbl}. <short phrase>\"" for lbl in labels]) +
            "\n  ]\n"
            "}\n\n"
            "RULES:\n"
            f"- Always provide EXACTLY {option_count} options.\n"
            f"- Each option must begin with {', '.join(labels)}.\n"
            "- Keep options SHORT (2–5 words, no full sentences).\n"
            "- Options must be distinct and meaningful."
        )

        try:
            response = await model.generate_content_async(prompt)
            cleaned = clean_llm_json_response(response.text)
            parsed = json.loads(cleaned)

            options = parsed.get("options", [])
            formatted_options = []
            for i in range(option_count):
                if i < len(options):
                    opt_text = options[i].strip()
                else:
                    opt_text = f"Option {i+1}"

                if not opt_text.startswith(f"{labels[i]}."):
                    opt_text = f"{labels[i]}. {opt_text}"

                formatted_options.append(opt_text)

            result_item = {
                "parameter": parameter_list,
                "question": question_text,
                "type": qtype,
                "iconfilename": iconfilename,
                "options": formatted_options
            }
            if limit is not None:
                result_item["limit"] = limit

            results.append(result_item)

        except Exception:
            result_item = {
                "parameter": parameter_list,
                "question": question_text,
                "type": qtype,
                "iconfilename": iconfilename,
                "options": [f"{labels[i]}. Option {i+1}" for i in range(option_count)]
            }
            if limit is not None:
                result_item["limit"] = limit

            results.append(result_item)

    return {
        "success": True,
        "suggestions": results
    }


async def get_latest_user_cv(db, user_id: str):
    """
    Fetch the most recent uploaded CV for a logged-in user.
    """
    latest_cv = await db["uploads"].find_one(
        {"user_id": ObjectId(user_id), "source": "cv"},
        sort=[("uploaded_at", -1)]
    )
    return latest_cv


async def generate_anchor_attribute_options(user_id: str, questions, model, get_database):
    """
    Generate multiple-choice options for Anchor attributes based ONLY on:
    - Personal Interests + Hobbies + Exploration Interest + Motivation Drivers + Motivating Activities
    - Achievements (text field only)

    Save them back into uploads collection under the latest CV document of the logged-in user.
    """

    target_parameters = {
        "Creative Inclinations + Organizational Skills + Competency + Personality Traits",
        "Newly Acquired Skills + Emerging Tech Awareness + Future Study Intent"
    }

    db = await get_database()

    latest_cv = await get_latest_user_cv(db, user_id)
    if not latest_cv or "parsed_data" not in latest_cv:
        raise HTTPException(status_code=404, detail="No CV found for this user")

    cv_id = str(latest_cv["_id"])

    cursor = db["answers"].find({
        "cv_id": cv_id,
        "section": "Anchor Attributes",
        "parameter": {
            "$in": [
                "Personal Interests + Hobbies + Exploration Interest + Motivation Drivers + Motivating Activities",
                "Achievements"
            ]
        }
    })
    answers = await cursor.to_list(length=None)

    if not answers:
        raise HTTPException(status_code=404, detail="No required anchor answers found")

    base_free_text_map = {}
    for ans in answers:
        param = ans["parameter"]
        val = ans["value"]
        if isinstance(val, str):
            base_free_text_map[param] = val
        elif isinstance(val, dict) and "text" in val:
            base_free_text_map[param] = val["text"]

    suggestions = []
    variation_key = f"{uuid.uuid4()}-{datetime.utcnow().timestamp()}"

    style_noise_pool = [
        "use uncommon synonyms",
        "reorder ideas differently",
        "make phrasing more concise",
        "add creative wording twists",
        "slightly formal tone",
        "slightly casual tone",
        "shuffle activity order",
        "split compound ideas differently"
    ]
    random.shuffle(style_noise_pool)
    style_noise = ", ".join(style_noise_pool[:3])

    non_empty_texts = [t for t in base_free_text_map.values() if t]
    random.shuffle(non_empty_texts)
    context_sample = "\n".join(non_empty_texts)

    for q in questions:
        parameter = q.get("parameter")
        if parameter not in target_parameters:
            continue

        question_text = q.get("question")
        type_ = q.get("type")
        iconfilename = q.get("iconfilename")

        parameter_list = [p.strip() for p in parameter.split("+")]
        option_count = 5 * len(parameter_list)
        labels = [chr(65 + i) for i in range(option_count)]

        variation_instructions = (
            "- Ensure each execution produces DIFFERENT wording, even if the free-text is unchanged.\n"
            "- Randomly split, merge, or rephrase phrases so that no two runs look the same.\n"
            "- Introduce synonyms, shuffle word order, or shorten differently.\n"
            "- Do NOT invent anything that is not explicitly present in the free-text answers.\n"
            f"- Apply these random variation rules: {style_noise}\n"
        )

        prompt = (
            "You are an AI assistant generating multiple-choice options for career-related questions.\n\n"
            f"STRICT KNOWLEDGE BASE (rephrase ONLY from this, do not add new ideas):\n{context_sample}\n\n"
            f"Target sub-parameters: {', '.join(parameter_list)}\n"
            f"Question: {question_text}\n\n"
            "Instructions:\n"
            f"- Generate EXACTLY {option_count} options.\n"
            f"- Each option must begin with {', '.join(labels)}.\n"
            "- Each option must be a direct rephrasing, splitting, or summarizing of the free-text answers.\n"
            "- DO NOT invent anything that is not explicitly present in the free-text answers.\n"
            "- Keep each option SHORT (2–5 words).\n"
            "- Ensure all options are distinct and meaningful.\n"
            f"{variation_instructions}"
            f"- Variation key (for uniqueness): {variation_key}\n\n"
            "Respond ONLY in JSON format:\n"
            "{\n"
            "  \"options\": [\n"
            + ",\n".join([f"    \"{lbl}. <short phrase>\"" for lbl in labels]) +
            "\n  ]\n"
            "}"
        )

        try:
            response = await model.generate_content_async(prompt)
            cleaned = clean_llm_json_response(response.text)
            parsed = json.loads(cleaned)
            options = parsed.get("options", [])

            formatted = []
            for i in range(option_count):
                opt = options[i].strip() if i < len(options) else f"Option {i+1}"
                if not opt.startswith(f"{labels[i]}."):
                    opt = f"{labels[i]}. {opt}"
                formatted.append(opt)

            suggestions.append({
                "parameter": parameter_list,
                "question": question_text,
                "type": type_,
                "iconfilename": iconfilename,
                "options": formatted
            })

        except Exception as e:
            suggestions.append({
                "parameter": parameter_list,
                "question": question_text,
                "type": type_,
                "iconfilename": iconfilename,
                "options": [f"{labels[i]}. Option {i+1}" for i in range(option_count)],
                "error": str(e)
            })

    await db["uploads"].update_one(
        {"_id": latest_cv["_id"]},
        {"$set": {"anchor_questions_with_options": suggestions}}
    )

    return {"success": True, "suggestions": suggestions}


#--------------Second Flow--------------



async def generate_job_attribute_options_without_cv(user_id: str, db) -> dict:
    """
    Generates multiple-choice options for missing CV attributes
    and saves them to the proceed_without_cv collection.
    """

    proceed_collection = db["proceed_without_cv"]
    answers_collection = db["answers_without_cv"]
    questions_collection = db["questions"]

    latest_doc = await proceed_collection.find_one(
        {"user_id": user_id},
        sort=[("created_at", -1)]
    )
    if not latest_doc:
        raise HTTPException(status_code=404, detail="No proceed_without_cv doc found")

    latest_document_id = str(latest_doc["_id"])
    audience_type = latest_doc.get("audienceType")

    missing_answers_cursor = answers_collection.find(
        {"user_id": user_id, "document_id": latest_document_id, "section": "Cv Missing"}
    )
    missing_answers = await missing_answers_cursor.to_list(length=None)

    if not missing_answers:
        raise HTTPException(status_code=404, detail="No missing answers found")

    context_str = "\n".join(
        f"{a['parameter']}: {a.get('value')}" for a in missing_answers if a.get("value")
    )

    questions_doc = await questions_collection.find_one({})
    if not questions_doc:
        raise HTTPException(status_code=404, detail="No questions document found")

    job_attributes = questions_doc.get("Job attributes", [])

    questions_for_user = []
    for qa in job_attributes:
        if qa.get("audienceType") == audience_type:
            questions_for_user = qa.get("questions", [])
            break

    if not questions_for_user:
        raise HTTPException(status_code=404, detail=f"No questions found for audienceType {audience_type}")

    results = []

    for q in questions_for_user:
        parameter = q.get("parameter", "")
        question_text = q.get("question")
        qtype = q.get("type")
        iconfilename = q.get("iconfilename")
        limit = q.get("limit") or q.get("Limit")

        parameter_list = [p.strip() for p in parameter.split("+")]
        option_count = 5 * len(parameter_list)
        labels = [chr(65 + i) for i in range(option_count)]

        prompt = (
            "You are an AI assistant generating career-related multiple-choice options.\n\n"
            f"Audience Type: {audience_type}\n\n"
            f"Missing CV Context:\n{context_str}\n\n"
            f"Question: {question_text}\n\n"
            "Respond ONLY in JSON format:\n"
            "{\n"
            "  \"options\": [\n"
            + ",\n".join([f"    \"{lbl}. <short phrase>\"" for lbl in labels]) +
            "\n  ]\n"
            "}\n\n"
            "RULES:\n"
            f"- Always provide EXACTLY {option_count} options.\n"
            f"- Each option must begin with {', '.join(labels)}.\n"
            "- Keep options SHORT (2–5 words).\n"
            "- Options must be distinct and meaningful."
        )

        try:
            response = await model.generate_content_async(prompt)
            cleaned = clean_llm_json_response(response.text)
            parsed = json.loads(cleaned)

            options = parsed.get("options", [])
            formatted_options = []
            for i in range(option_count):
                opt_text = options[i].strip() if i < len(options) else f"Option {i+1}"
                if not opt_text.startswith(f"{labels[i]}."):
                    opt_text = f"{labels[i]}. {opt_text}"
                formatted_options.append(opt_text)

            result_item = {
                "parameter": parameter_list,
                "question": question_text,
                "type": qtype,
                "iconfilename": iconfilename,
                "options": formatted_options,
            }
            if limit is not None:
                result_item["limit"] = limit

            results.append(result_item)

        except Exception:
            result_item = {
                "parameter": parameter_list,
                "question": question_text,
                "type": qtype,
                "iconfilename": iconfilename,
                "options": [f"{labels[i]}. Option {i+1}" for i in range(option_count)],
            }
            if limit is not None:
                result_item["limit"] = limit

            results.append(result_item)

    await proceed_collection.update_one(
        {"_id": latest_doc["_id"]},
        {"$set": {"job_questions_with_options": results, "updated_at": datetime.utcnow()}}
    )

    return {
        "success": True,
        "latest_document_id": latest_document_id,
        "audience_type": audience_type,
        "suggestions": results
    }

async def generate_anchor_options_from_answers_without_cv(
    user_id: str, questions, model, get_database
) -> Dict[str, Any]:
    """
    Generate multiple-choice options for Anchor attributes based ONLY on:
    - Personal Interests + Hobbies + Exploration Interest + Motivation Drivers + Motivating Activities
    - Achievements (text field only)
    Fetch answers from answers_without_cv based on the latest proceed_without_cv.document_id,
    generate options using LLM, and save them back into proceed_without_cv.
    """
    target_parameters = {
        "Creative Inclinations + Organizational Skills + Competency + Personality Traits",
        "Newly Acquired Skills + Emerging Tech Awareness + Future Study Intent"
    }

    db = get_database()

    latest_proceed = await db["proceed_without_cv"].find(
        {"user_id": user_id}
    ).sort("created_at", -1).to_list(length=1)

    if not latest_proceed:
        raise HTTPException(status_code=404, detail="No proceed_without_cv found for user")

    document_id = latest_proceed[0]["_id"]

    answers_cursor = db["answers_without_cv"].find(
        {"user_id": user_id, "document_id": str(document_id),
         "parameter": {"$in": [
            "Personal Interests + Hobbies + Exploration Interest + Motivation Drivers + Motivating Activities",
            "Achievements"
         ]}}
    )
    answers = await answers_cursor.to_list(length=None)

    if not answers:
        raise HTTPException(status_code=404, detail="No required anchor answers found")

    base_free_text_map = {}
    for ans in answers:
        param = ans["parameter"]
        val = ans["value"]
        if isinstance(val, str):
            base_free_text_map[param] = val
        elif isinstance(val, dict) and "text" in val:
            base_free_text_map[param] = val["text"]

    non_empty_texts = [t for t in base_free_text_map.values() if t]
    random.shuffle(non_empty_texts)
    context_sample = "\n".join(non_empty_texts)

    variation_key = f"{uuid.uuid4()}-{datetime.utcnow().timestamp()}"
    style_noise_pool = [
        "use uncommon synonyms", "reorder ideas differently", "make phrasing more concise",
        "add creative wording twists", "slightly formal tone", "slightly casual tone",
        "shuffle activity order", "split compound ideas differently"
    ]
    random.shuffle(style_noise_pool)
    style_noise = ", ".join(style_noise_pool[:3])

    suggestions = []

    for q in questions:
        parameter = q.get("parameter")
        if parameter not in target_parameters:
            continue

        question_text = q.get("question")
        type_ = q.get("type")
        iconfilename = q.get("iconfilename")

        parameter_list = [p.strip() for p in parameter.split("+")]
        option_count = 5 * len(parameter_list)
        labels = [chr(65 + i) for i in range(option_count)]

        variation_instructions = (
            "- Ensure each execution produces DIFFERENT wording, even if the free-text is unchanged.\n"
            "- Randomly split, merge, or rephrase phrases so that no two runs look the same.\n"
            "- Introduce synonyms, shuffle word order, or shorten differently.\n"
            "- Do NOT invent anything that is not explicitly present in the free-text answers.\n"
            f"- Apply these random variation rules: {style_noise}\n"
        )

        prompt = (
            "You are an AI assistant generating multiple-choice options for career-related questions.\n\n"
            f"STRICT KNOWLEDGE BASE (rephrase ONLY from this, do not add new ideas):\n{context_sample}\n\n"
            f"Target sub-parameters: {', '.join(parameter_list)}\n"
            f"Question: {question_text}\n\n"
            "Instructions:\n"
            f"- Generate EXACTLY {option_count} options.\n"
            f"- Each option must begin with {', '.join(labels)}.\n"
            "- Each option must be a direct rephrasing, splitting, or summarizing of the free-text answers.\n"
            "- DO NOT invent anything that is not explicitly present in the free-text answers.\n"
            "- Keep each option SHORT (2–5 words).\n"
            f"{variation_instructions}"
            f"- Variation key (for uniqueness): {variation_key}\n\n"
            "Respond ONLY in JSON format:\n"
            "{\n"
            "  \"options\": [\n"
            + ",\n".join([f"    \"{lbl}. <short phrase>\"" for lbl in labels]) +
            "\n  ]\n"
            "}"
        )

        try:
            response = await model.generate_content_async(prompt)
            cleaned = clean_llm_json_response(response.text)
            parsed = json.loads(cleaned)
            options = parsed.get("options", [])

            formatted = []
            for i in range(option_count):
                opt = options[i].strip() if i < len(options) else f"Option {i+1}"
                if not opt.startswith(f"{labels[i]}."):
                    opt = f"{labels[i]}. {opt}"
                formatted.append(opt)

            suggestions.append({
                "parameter": parameter_list,
                "question": question_text,
                "type": type_,
                "iconfilename": iconfilename,
                "options": formatted
            })

        except Exception as e:
            suggestions.append({
                "parameter": parameter_list,
                "question": question_text,
                "type": type_,
                "iconfilename": iconfilename,
                "options": [f"{labels[i]}. Option {i+1}" for i in range(option_count)],
                "error": str(e)
            })

    await db["proceed_without_cv"].update_one(
        {"_id": document_id},
        {"$set": {"anchor_questions_with_options": suggestions}}
    )

    return {"success": True, "document_id": str(document_id), "suggestions": suggestions}