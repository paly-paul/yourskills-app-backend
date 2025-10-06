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
model = genai.GenerativeModel("gemini-2.5-flash-lite")

def parse_duration(duration_str):
    try:
        # --- Normalize input ---
        duration_str = duration_str.replace("’", "'").replace("‘", "'")
        duration_str = re.sub(r"[–—−]", "-", duration_str).strip()
        duration_str = re.sub(r"\s+", " ", duration_str)
        duration_str = re.sub(r"\(.*?\)", "", duration_str)  # remove (...) notes

        # --- Handle "Since <date>" ---
        if duration_str.lower().startswith("since"):
            start_str = duration_str[5:].strip()
            try:
                start_date = date_parser.parse(start_str, fuzzy=True)
            except:
                return None
            return start_date, datetime.today()

        # --- Split into start/end parts (accepts -, to, –) ---
        parts = re.split(r"\s*(?:-|to)\s*", duration_str, flags=re.IGNORECASE)
        if len(parts) != 2:
            return None

        start_str, end_str = parts[0].strip(), parts[1].strip().lower()

        # --- Parse start date ---
        start_date = None
        for fmt in ["%m/%Y", "%b'%y", "%b %y"]:
            try:
                start_date = datetime.strptime(start_str, fmt)
                break
            except:
                continue
        if not start_date:
            start_date = date_parser.parse(start_str, fuzzy=True)

        # --- Parse end date ---
        if any(word in end_str for word in ["present", "current", "now"]):
            end_date = datetime.today()
        else:
            end_date = None
            for fmt in ["%m/%Y", "%b'%y", "%b %y"]:
                try:
                    end_date = datetime.strptime(end_str, fmt)
                    break
                except:
                    continue
            if not end_date:
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
1. Extract data **only if explicitly mentioned** in the resume text.
2. Do **NOT** infer, guess, or add any information not directly written in the document.

3. **Skills Extraction Rules:**
   - Only extract skills from sections explicitly labeled as:
     “Skills”, “Technical Skills”, “Core Competencies”, “Key Skills”, “Tech Stack”, or “Technologies”.
   - Categorize as follows:
     - **Tools** → Include all items listed under “Technical Skills”, “Tech Stack”, or similar headings.
       This includes programming languages, software, frameworks, platforms, and technologies.
       Example: Python, Java, AWS, Excel, React, Git, Figma, etc.
     - **HardSkills** → Only include non-tool, domain-specific, or professional capabilities explicitly listed under “Skills” or “Core Competencies”.
       Example: Data Analysis, Project Management, Financial Modeling, etc.
     - **SoftSkills** → Only include personal or interpersonal skills explicitly listed, such as Communication, Leadership, Problem Solving, etc.
   - Do not extract or infer skills from experience descriptions, project details, or summaries.
   - Record skills exactly as written (no normalization or assumption).
   - If a skill category is not present, leave it empty.

4. **WorkExperience, Education, Certifications, Projects, etc.:**
   - Extract only explicit data.
   - Skip any field not mentioned.

5. **YearsOfExperience:**
   - Extract only if the resume explicitly states a value (e.g., “5 years of experience”).
   - Do not compute or infer from job dates.

6. Return only **valid JSON**, starting with `{` and ending with `}`.
7. Do not summarize, rephrase, or infer any data.
8. If any section is missing, return an empty string or empty array for that section.
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
    "technical_skills": "technical_skills_suggestions",

    "certifications": "certifications_suggestions",
    "certification": "certifications_suggestions"
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
        "technical_skills_suggestions": [],
        "certifications_suggestions": []
    }

    skills = cv_context.get("Skills", {}) or {}
    missing_fields = []

    # Detect which fields are missing
    if not skills.get("SoftSkills"):
        missing_fields.append("SoftSkills")
    if not skills.get("HardSkills"):
        missing_fields.append("HardSkills")
    if not cv_context.get("Certifications"):
        missing_fields.append("Certifications")

    # ✅ Skip generation if everything is present
    if not missing_fields:
        return suggestions

    # Build context string for model
    context_str = "\n".join(f"{k}: {v}" for k, v in cv_context.items() if v)
    prompt = (
        "You are an AI helping complete missing CV fields.\n"
        f"CV Context:\n{context_str}\n\n"
        f"Missing Fields: {missing_fields}\n"
        "Respond ONLY in valid JSON with keys matching the missing fields. "
        "Each value must be a JSON array of strings.\n"
        "For 'Certifications', provide certifications in the professional format: "
        "'Certification Name – Issuing Organization', like "
        "'Google Data Analytics - Coursera', 'Scrum Master – Scrum Alliance', "
        "or 'UI/UX Bootcamp – Springboard'."
    )

    # Ask the model to generate
    response = await model.generate_content_async(prompt)
    cleaned = clean_llm_json_response(response.text)

    try:
        parsed = json.loads(cleaned)
    except Exception:
        parsed = {f: [] for f in missing_fields}

    # Map and assign generated data only for missing fields
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

        if mapped_field == "softskills_suggestions" and "SoftSkills" in missing_fields:
            suggestions["softskills_suggestions"].extend(items)

        if mapped_field == "technical_skills_suggestions" and "HardSkills" in missing_fields:
            suggestions["technical_skills_suggestions"].extend(items)

        if mapped_field == "certifications_suggestions" and "Certifications" in missing_fields:
            suggestions["certifications_suggestions"].extend(items)

    # Deduplicate lists
    for k in suggestions:
        suggestions[k] = list(set(suggestions[k]))

    return suggestions


async def generate_job_attribute_options(cv_context: dict, questions_from_db: list) -> dict:
    """
    Generates career-related multiple-choice options for each question.

    Rules:
    - If single parameter → 5 options.
    - If multiple parameters joined with '+' → 2 options per parameter.
    - Considers both parameters and question meaning to generate options.
    - Outputs a single list of options.
    - Each option starts with a capital letter.
    """
    results = []
    context_str = "\n".join(f"{k}: {v}" for k, v in cv_context.items() if v)

    # 🔹 Extract audience type
    audience_type = cv_context.get("audience_type") or cv_context.get("audience")

    # 🔹 Filter by audience type
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

        # Split parameters
        parameter_list = [p.strip() for p in parameter.split(" + ")]

        # Determine option count
        option_count = 5 if len(parameter_list) == 1 else 2 * len(parameter_list)

        # 🔹 Build smart prompt
        prompt = (
            "You are an AI assistant that generates short, relevant career-related multiple-choice options.\n\n"
            "Each option should reflect the professional context implied by both the parameters and the question.\n"
            "Use the information below:\n\n"
            f"CV Context:\n{context_str}\n\n"
            f"Question:\n{question_text}\n\n"
            f"Parameters: {', '.join(parameter_list)}\n\n"
            "Respond ONLY in JSON format like this:\n"
            "{\n"
            "  \"options\": [\"Option 1\", \"Option 2\", ...]\n"
            "}\n\n"
            "RULES:\n"
            f"- Provide EXACTLY {option_count} options.\n"
            "- Make options meaningful, realistic, and varied.\n"
            "- Each option should be 2–5 words.\n"
            "- Reflect both the question and parameters.\n"
            "- Start each option with a capital letter.\n"
            "- No numbers, bullets, or punctuation at the start."
        )

        try:
            # 🔹 Call model
            response = await model.generate_content_async(prompt)
            cleaned = clean_llm_json_response(response.text)
            parsed = json.loads(cleaned)
            options = parsed.get("options", [])

            # 🔹 Clean, capitalize, and validate
            formatted_options = []
            for opt in options:
                opt = re.sub(r"^[^A-Za-z]+", "", opt.strip())  # remove weird prefixes
                if opt:
                    opt = opt[:1].upper() + opt[1:]  # ensure first letter capitalized
                else:
                    opt = "Option"
                formatted_options.append(opt)

            # Fill missing ones if model gives fewer
            while len(formatted_options) < option_count:
                formatted_options.append(f"Option {len(formatted_options)+1}")

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
            # 🔹 Fallback
            fallback = [f"Option {i+1}" for i in range(option_count)]
            result_item = {
                "parameter": parameter_list,
                "question": question_text,
                "type": qtype,
                "iconfilename": iconfilename,
                "options": fallback
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

    Each parameter contributes EXACTLY 2 options (fixed count).
    Saves results in the latest uploaded CV document for the user.
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

    # Fetch required free-text anchor answers
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

    # Build free-text context map
    base_free_text_map = {}
    for ans in answers:
        param = ans["parameter"]
        val = ans["value"]
        if isinstance(val, str):
            base_free_text_map[param] = val
        elif isinstance(val, dict) and "text" in val:
            base_free_text_map[param] = val["text"]

    # Create context string and variation style
    non_empty_texts = [t for t in base_free_text_map.values() if t]
    random.shuffle(non_empty_texts)
    context_sample = "\n".join(non_empty_texts)

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
    variation_key = f"{uuid.uuid4()}-{datetime.utcnow().timestamp()}"

    suggestions = []

    for q in questions:
        parameter = q.get("parameter")
        if parameter not in target_parameters:
            continue

        question_text = q.get("question")
        type_ = q.get("type")
        iconfilename = q.get("iconfilename")

        # Split multiple parameters and calculate count
        parameter_list = [p.strip() for p in parameter.split("+")]
        option_count = 2 * len(parameter_list)  # ✅ 2 options per parameter

        variation_instructions = (
            "- Ensure each execution produces DIFFERENT wording, even if the free-text is unchanged.\n"
            "- Randomly split, merge, or rephrase phrases so that no two runs look the same.\n"
            "- Introduce synonyms, shuffle word order, or shorten differently.\n"
            "- Do NOT invent anything that is not explicitly present in the free-text answers.\n"
            f"- Apply these random variation rules: {style_noise}\n"
        )

        # 🔹 Build prompt (consider both question & parameter)
        prompt = (
            "You are an AI assistant generating short, career-related multiple-choice options.\n\n"
            f"STRICT KNOWLEDGE BASE (rephrase ONLY from this, do not add new ideas):\n{context_sample}\n\n"
            f"Target parameters: {', '.join(parameter_list)}\n"
            f"Question: {question_text}\n\n"
            "Instructions:\n"
            f"- Generate EXACTLY {option_count} short options.\n"
            "- Each option must rephrase, split, or summarize the ideas from the free-text.\n"
            "- DO NOT invent anything not in the context.\n"
            "- Keep options SHORT (2–5 words).\n"
            "- Start each option with a CAPITAL letter.\n"
            "- Return plain text options only (no labels or numbers).\n"
            "- All options must be distinct and meaningful.\n"
            f"{variation_instructions}"
            f"- Variation key: {variation_key}\n\n"
            "Respond ONLY in JSON format:\n"
            "{\n"
            "  \"options\": [\"<Short phrase 1>\", \"<Short phrase 2>\", ...]\n"
            "}"
        )

        try:
            response = await model.generate_content_async(prompt)
            cleaned = clean_llm_json_response(response.text)
            parsed = json.loads(cleaned)
            options = parsed.get("options", [])

            # Clean and capitalize each option
            formatted = []
            for opt in options[:option_count]:
                cleaned_opt = opt.strip().lstrip("0123456789.- ").capitalize()
                formatted.append(cleaned_opt)

            # If fewer options than expected, fill with placeholders
            while len(formatted) < option_count:
                formatted.append(f"Option {len(formatted)+1}")

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
                "options": [f"Option {i+1}" for i in range(option_count)],
                "error": str(e)
            })

    # 🔹 Save to uploads collection
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

    # Fetch the latest proceed_without_cv document for the user
    latest_proceed = await db["proceed_without_cv"].find(
        {"user_id": user_id}
    ).sort("created_at", -1).to_list(length=1)

    if not latest_proceed:
        raise HTTPException(status_code=404, detail="No proceed_without_cv found for user")

    document = latest_proceed[0]
    document_id = document["_id"]
    audience_type = document.get("audienceType", "General")

    # Fetch answers linked to this document_id
    answers_cursor = db["answers_without_cv"].find(
        {
            "user_id": user_id,
            "document_id": str(document_id),
            "parameter": {
                "$in": [
                    "Personal Interests + Hobbies + Exploration Interest + Motivation Drivers + Motivating Activities",
                    "Achievements",
                ]
            },
        }
    )
    answers = await answers_cursor.to_list(length=None)

    if not answers:
        raise HTTPException(status_code=404, detail="No required anchor answers found")

    # Extract free-text values from answers
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

    # Variation instructions
    variation_key = f"{uuid.uuid4()}-{datetime.utcnow().timestamp()}"
    style_noise_pool = [
        "use uncommon synonyms",
        "reorder ideas differently",
        "make phrasing more concise",
        "add creative wording twists",
        "slightly formal tone",
        "slightly casual tone",
        "shuffle activity order",
        "split compound ideas differently",
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
            + ",\n".join([f"    \"{lbl}. <short phrase>\"" for lbl in labels])
            + "\n  ]\n"
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

            suggestions.append(
                {
                    "parameter": parameter_list,
                    "question": question_text,
                    "type": type_,
                    "iconfilename": iconfilename,
                    "options": formatted,
                }
            )

        except Exception as e:
            suggestions.append(
                {
                    "parameter": parameter_list,
                    "question": question_text,
                    "type": type_,
                    "iconfilename": iconfilename,
                    "options": [f"{labels[i]}. Option {i+1}" for i in range(option_count)],
                    "error": str(e),
                }
            )

    # Update the proceed_without_cv document with the generated options
    await db["proceed_without_cv"].update_one(
        {"_id": document_id},
        {"$set": {"anchor_questions_with_options": suggestions}},
    )

    return {
        "success": True,
        "document_id": str(document_id),
        "audienceType": audience_type,
        "suggestions": suggestions,
    }