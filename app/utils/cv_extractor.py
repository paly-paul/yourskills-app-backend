import os
import json
import pathlib
from datetime import datetime
from dateutil import parser as date_parser
from dotenv import load_dotenv
import google.generativeai as genai
from docx import Document
import re
from typing import Dict, List, Tuple
from collections import defaultdict

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
    "SoftSkills": []
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
4. For YearsOfExperience, calculate based on WorkExperience dates only.
5. Return only valid JSON. Start with { and end with }.
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
        parsed_json["YearsOfExperience"] = calculate_years_of_experience(work_exp)

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
    """
    results = []
    context_str = "\n".join(f"{k}: {v}" for k, v in cv_context.items() if v)

    for q in questions_from_db:
        parameter = q.get("parameter", "")
        question_text = q.get("question")
        iconfilename = q.get("iconfilename")

        parameter_list = [p.strip() for p in parameter.split("+")]
        option_count = 5 * len(parameter_list)

        labels = [chr(65 + i) for i in range(option_count)]  # ['A','B','C'...]

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

            results.append({
                "parameters": parameter_list,
                "question": question_text,
                "iconfilename": iconfilename,
                "options": formatted_options
            })

        except Exception:
            results.append({
                "parameters": parameter_list,
                "question": question_text,
                "iconfilename": iconfilename,
                "options": [f"{labels[i]}. Option {i+1}" for i in range(option_count)]
            })

    return {
        "success": True,
        "suggestions": results
    }



async def generate_anchor_attribute_options(parsed_data, questions):
    """
    Generate multiple-choice options for specific Anchor parameters.
    Each parameter contributes 5 options.
    If parameter string has multiple (joined with '+'), total = 5 × number_of_parameters.
    Returns { "suggestions": [ {parameters, question, iconfilename, options} ] }
    """
    target_parameters = {
        "Creative Inclinations + Organizational Skills + Competency + Personality Traits",
        "Newly Acquired Skills + Emerging Tech Awareness + Future Study Intent"
    }

    context_str = "\n".join(f"{k}: {v}" for k, v in parsed_data.items() if v)

    suggestions = []

    for q in questions:
        parameter = q.get("parameter")
        if parameter not in target_parameters:
            continue

        question_text = q.get("question")
        iconfilename = q.get("iconfilename")

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

            formatted = []
            for i in range(option_count):
                opt = options[i].strip() if i < len(options) else f"Option {i+1}"
                if not opt.startswith(f"{labels[i]}."):
                    opt = f"{labels[i]}. {opt}"
                formatted.append(opt)

            suggestions.append({
                "parameters": parameter_list,   
                "question": question_text,
                "iconfilename": iconfilename,
                "options": formatted
            })
        except Exception:
            suggestions.append({
                "parameters": parameter_list,
                "question": question_text,
                "iconfilename": iconfilename,
                "options": [f"{labels[i]}. Option {i+1}" for i in range(option_count)]
            })

    return {"suggestions": suggestions}

