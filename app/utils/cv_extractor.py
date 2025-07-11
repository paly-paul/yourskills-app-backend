import pathlib
import json
import os
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-1.5-flash")

def extract_cv_data_from_file(filepath: str, mime_type: str):
    file_bytes = pathlib.Path(filepath).read_bytes()

    prompt = """
You are an expert resume parser.

Given a resume file, extract structured JSON with the following fields:

{
  "Name": "",
  "Email": "",
  "Phone": "",
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
  ]
}
Categorize Skills as:
- "HardSkills": technical abilities (e.g., Python, Excel, React)
- "SoftSkills": personal traits (e.g., teamwork, communication)

If a section doesn’t exist in the resume, return empty list or empty string.
Return **only valid JSON**. Start your response with `{` and end with `}`. No markdown or explanations.
"""

    response = model.generate_content(
        [
            {"mime_type": mime_type, "data": file_bytes},
            prompt
        ],
        stream=False
    )

    try:
        response_text = response.text.strip()
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]

        response_text = response_text.strip()
        start_idx = response_text.find('{')
        end_idx = response_text.rfind('}')
        response_text = response_text[start_idx:end_idx+1]
        return json.loads(response_text)
    except Exception as e:
        print("CV Extraction Error:", str(e))
        return {"error": "Failed to parse CV data"}
