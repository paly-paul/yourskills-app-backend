import os
import json
import pathlib
from datetime import datetime
from dateutil import parser as date_parser
from dotenv import load_dotenv
import google.generativeai as genai
from docx import Document
import re

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-1.5-flash")

def parse_duration(duration_str):
    try:
        parts = re.split(r"\s*[-–—]\s*", duration_str)  
        if len(parts) != 2:
            return None

        start_str, end_str = parts[0].strip(), parts[1].strip().lower()
        start_date = date_parser.parse(start_str)
        if "present" in end_str or "now" in end_str:
            end_date = datetime.today()
        else:
            end_date = date_parser.parse(end_str)

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
            months = (end.year - start.year) * 12 + (end.month - start.month)
            total_months += max(0, months)
    return round(total_months / 12, 1)

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

- Categorize **Skills** as:
  - "HardSkills": Technical or domain-specific abilities (e.g., Programming, Operating Systems, Cloud Computing)
  - "SoftSkills": Personal or interpersonal qualities (e.g., Communication, Team Work, Adaptability)

- Extract a separate **Tools** field (not inside Skills):
  - These are specific technologies, software, frameworks, or programming languages (e.g., C++, Java, C#, Photoshop, Excel, etc.)
  - Include tools mentioned in Skills, WorkExperience, Projects, and Certifications.

- "YearsOfExperience": Calculate total professional experience from the WorkExperience section based on the durations provided. If "Present" is used as an end date, assume the current date.

- If any section is missing in the resume, return an empty list or empty string.

Return only valid JSON. Start your response with `{` and end with `}`. No markdown or explanations.
"""

    try:
        if mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            doc = Document(filepath)
            file_text = "\n".join([para.text for para in doc.paragraphs])
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

        work_exp = parsed_json.get("WorkExperience", [])
        parsed_json["YearsOfExperience"] = calculate_years_of_experience(work_exp)

        return parsed_json

    except Exception as e:
        print("CV Extraction Error:", str(e))
        return {"error": "Failed to parse CV data"}
