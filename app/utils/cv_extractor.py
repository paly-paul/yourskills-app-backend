import pathlib
import json
import os
import mimetypes
from dotenv import load_dotenv
import google.generativeai as genai
from docx import Document
import fitz  

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-1.5-flash")

def extract_text_from_docx(filepath: str) -> str:
    doc = Document(filepath)
    return "\n".join([para.text for para in doc.paragraphs])

def extract_text_from_pdf(filepath: str) -> str:
    doc = fitz.open(filepath)
    return "\n".join([page.get_text() for page in doc])

def extract_text_from_plain(filepath: str) -> str:
    return pathlib.Path(filepath).read_text()

def extract_cv_data_from_file(filepath: str, mime_type: str = None):
    if not mime_type:
        mime_type, _ = mimetypes.guess_type(filepath)

    try:
        if mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            text_content = extract_text_from_docx(filepath)
        elif mime_type == "application/pdf":
            text_content = extract_text_from_pdf(filepath)
        elif mime_type == "text/plain":
            text_content = extract_text_from_plain(filepath)
        else:
            return {"error": f"Unsupported mime type: {mime_type}"}
    except Exception as e:
        return {"error": f"Failed to extract text from file: {str(e)}"}

  
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
  ]
}

Categorize Skills as:
- "HardSkills": technical abilities (e.g., Python, Excel, React)
- "SoftSkills": personal traits (e.g., teamwork, communication)
If a section doesn’t exist in the resume, return empty list or empty string.
Use "OtherSections" only for unmatched or custom-named sections.
Return **only valid JSON**. Start your response with `{` and end with `}`. No markdown or explanations.
"""

    try:
        response = model.generate_content([prompt, text_content], stream=False)
        response_text = response.text.strip()

        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]

        response_text = response_text.strip()
        start_idx = response_text.find('{')
        end_idx = response_text.rfind('}')
        response_text = response_text[start_idx:end_idx + 1]

        return json.loads(response_text)

    except Exception as e:
        print("CV Extraction Error:", str(e))
        return {"error": "Failed to parse CV data"}
