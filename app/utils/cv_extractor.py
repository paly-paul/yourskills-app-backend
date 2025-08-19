import os
import json
import pathlib
from datetime import datetime
from dateutil import parser as date_parser
from dotenv import load_dotenv
import google.generativeai as genai
from docx import Document
import re
from typing import Dict

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-1.5-flash")



from datetime import datetime
import re
from dateutil import parser as date_parser

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
  "Tools": [],
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

- Extract data **only if explicitly mentioned** in the CV text. 
- Do NOT infer or guess missing values. 
- Leave any field empty (`""` or `[]`) if it is not clearly present.

- Categorize **Skills** only if a "Skills" section or explicit mentions exist:
  - "HardSkills": Technical or domain-specific abilities (e.g., Programming, Operating Systems, Cloud Computing).
  - "SoftSkills": Personal or interpersonal qualities (e.g., Communication, Team Work, Adaptability).
  - If no Skills section is present, both lists must remain empty.

- Extract a separate **Tools** field:
  - These are only specific technologies, frameworks, or software (e.g., C++, Java, C#, Photoshop, Excel).
  - Tools must be explicitly written in the CV (from Skills, WorkExperience, Projects, Certifications).
  - If none are found, return an empty list.

- "YearsOfExperience": Calculate from WorkExperience dates. 
  - If "Present" is used, assume today’s date.
  - If dates are unclear, return `0.0`.

- Never invent, summarize, or add generic placeholders.
- Return only valid JSON. Start with `{` and end with `}`. No markdown, no commentary.
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
    audience_type = None
    student_keywords = ["ongoing", "present", "currently pursuing", "in progress", "pursuing"]

    # Education
    for ed in parsed_data.get("Education", []):
        combined_fields = " ".join(str(v).lower() for v in ed.values() if v)
        if any(keyword in combined_fields for keyword in student_keywords):
            return "Student"

    # Work Experience
    work_exp_list = parsed_data.get("WorkExperience", [])
    has_current_job = any(
        str(w.get("isCurrent", "")).strip().lower() in ["true", "yes", "1"] or
        str(w.get("endDate", "")).strip().lower() in ["present", "current", "ongoing", ""]
        for w in work_exp_list
    )

    # Years of Experience
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
            return "Job Seeker"
        elif total_years <= 3:
            return "Early Professional (2-3 years of experience)"
        else:
            return "Mid - Career Pivot"

    return audience_type


import json

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
    """Remove markdown fences and extract clean JSON substring."""
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
    generate_technical = False  # ✅ group HardSkills + Tools as technical

    # Check Soft Skills
    if not cv_context.get("Skills", {}).get("SoftSkills"):
        missing_fields.append("SoftSkills")

    # Check HardSkills OR Tools
    if not cv_context.get("Skills", {}).get("HardSkills") or not cv_context.get("Tools"):
        missing_fields.extend(["HardSkills", "Tools"])
        generate_technical = True

    if not missing_fields:
        return suggestions

    # Build context string
    context_str = "\n".join(f"{k}: {v}" for k, v in cv_context.items() if v)
    prompt = (
        "You are an AI helping complete missing CV fields.\n"
        f"CV Context:\n{context_str}\n\n"
        f"Missing Fields: {missing_fields}\n"
        "Respond ONLY in JSON with keys matching the missing fields. "
        "Each value must be a JSON array of strings."
    )

    response = await model.generate_content_async(prompt)

    # Debug prints
    print("\n==== PROMPT SENT TO LLM ====")
    print(prompt)
    print("\n==== RAW RESPONSE FROM LLM ====")
    print(response.text)
    print("==============================\n")

    # Clean and parse response
    cleaned = clean_llm_json_response(response.text)
    try:
        parsed = json.loads(cleaned)
    except Exception as e:
        print("⚠️ JSON parse error:", e)
        parsed = {f: [] for f in missing_fields}

    # Map parsed values
    for key, value in parsed.items():
        norm_key = normalize_key(key)
        mapped_field = FIELD_MAPPING.get(norm_key)

        if not mapped_field:
            continue

        # Ensure value is a list
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

    # Deduplicate
    suggestions["softskills_suggestions"] = list(set(suggestions["softskills_suggestions"]))
    suggestions["technical_skills_suggestions"] = list(set(suggestions["technical_skills_suggestions"]))

    print("✅ Final mapped suggestions:", suggestions)
    return suggestions
