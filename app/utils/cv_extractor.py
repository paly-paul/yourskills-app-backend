import asyncio
import os
import json
import pathlib
import logging
import time
from datetime import datetime
from dateutil import parser as date_parser
from dotenv import load_dotenv
import google.generativeai as genai
from docx import Document
import re
from typing import Dict, List, Tuple, Any
from collections import defaultdict
from app.db.database import get_database
import random
import uuid
from fastapi import HTTPException
from bson import ObjectId

logger = logging.getLogger("gemini")

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-2.5-flash-lite")

_gemini_call_counter = 0


async def _gemini_with_retry(prompt, max_retries: int = 4, caller: str = "unknown"):
    global _gemini_call_counter
    _gemini_call_counter += 1
    call_id = _gemini_call_counter
    prompt_preview = str(prompt)[:120].replace("\n", " ")
    logger.info(f"[GEMINI CALL #{call_id}] caller={caller} | prompt_preview={prompt_preview!r}")
    delay = 2.0
    for attempt in range(max_retries):
        t0 = time.time()
        try:
            response = await model.generate_content_async(prompt)
            elapsed = round(time.time() - t0, 2)
            logger.info(f"[GEMINI CALL #{call_id}] SUCCESS | attempt={attempt+1} | time={elapsed}s | caller={caller}")
            return response
        except Exception as exc:
            elapsed = round(time.time() - t0, 2)
            err = str(exc)
            is_rate_limit = "429" in err or "ResourceExhausted" in err or "quota" in err.lower()
            if is_rate_limit and attempt < max_retries - 1:
                logger.warning(f"[GEMINI CALL #{call_id}] RATE LIMIT | attempt={attempt+1} | retrying in {delay}s | caller={caller}")
                await asyncio.sleep(delay)
                delay *= 2
                continue
            logger.error(f"[GEMINI CALL #{call_id}] FAILED | attempt={attempt+1} | time={elapsed}s | error={err[:200]} | caller={caller}")
            raise

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


# def extract_cv_data_from_file(filepath: str, mime_type: str):
    
#     prompt = """
# You are a Senior HR Recruitment, Talent Analyst, and Skill Intelligence Expert trained to extract accurate structured information from resumes, profiles, or people data.

# Your task:
# Read the documents/data and return a CLEAN, VALID JSON object following the exact schema below.
# Use your skill analytics and HR experience to extract and interpret information correctly.
# Do NOT delete, modify, rename, or reorder existing keys.
# You may ONLY add the additional keys provided at the bottom.
# If information is missing, return "Not specified".
# Return ONLY valid JSON. No commentary, no markdown, no explanations.


# ------------------------------------------------------------
# CRITICAL OVERRIDES (STRONG RULES YOU MUST FOLLOW)
# ------------------------------------------------------------

# 1. INDUSTRY RULE (STRICT)
#    - You MUST return exactly ONE ** Industry**, even if the resume mentions multiple.
#    - Choose the MOST RECENT logical industry based on last 1–2 job roles.
#    - Examples:
#         If last job is at Lowe’s → Industry = "Retail"
#         If last job is Diageo → Industry = "Beverage / FMCG"
#         If last job is in IT consulting → Industry = "Information Technology Services"
#         - Retail  
#         - FMCG  
#         - Consulting  
#         - Insurance  
#         - IT Services  
#         - Telecommunications  

# 2. DOMAIN RULE (STRICT)
#    - You MUST return exactly ONE ** Domain**.
#    - Domain = functional expertise (HRBP, L&D, DEI, Program Management, etc.)
#    - Choose the MOST dominant domain based on:
#         - 70% of responsibilities across roles
#         - Skills & certifications
#    - Example: "Leadership & Organizational Development",“Human Resources – L&D & Organizational Development”, “HR Business Partnering”, “DEI & Culture Transformation” ,“Program Management Office (PMO)”  
#    - DO NOT produce multiple domains.

# 3. TECHNICAL SKILL LIMIT (VERY STRICT)
#    - Output ONLY the **top 10 relevant technical/hard skills**.
#    - If more than 10 appear → select the 10 MOST RELEVANT for the job role.

# 4. SKILL LIMITS (STRICT)
#    • HardSkills → MAX 10  
#    • SoftSkills → MAX 5  
#    • Tools → unlimited but keep only relevant tools  
#    • Remove duplicates (e.g., “Machine Learning” vs “ML” → keep standard term)
#    • Choose most relevant skills (based on last roles + responsibilities)
   
# 5. CERTIFICATION RULES (ALREADY EXISTING)
#    - If certifications exist → keep them unchanged.
#    - If missing → generate exactly 3 realistic certifications in LLM_Generated_Certificates only.
#    - NEVER auto-fill original Certification fields when empty.

# 6. AUTO-FILL RULE (STRICT)
#    Auto-fill ONLY if the corresponding field is EMPTY:
#       • Technical Skills → fill ONLY "LLM_Generated_Technical_Skills"
#       • Soft Skills → fill ONLY "LLM_Generated_Soft_Skills"
#       • Certifications → fill ONLY "LLM_Generated_Certificates"
      
# 7. EMPTY means: "", null, whitespace, empty array, or arrays containing only empty values.


# ------------------------------------------------------------
# INSTRUCTION RULES (APPLY TO ALL FIELDS)
# ------------------------------------------------------------
# SUMMARY:
# The "Summary" must be a powerful 2–3 line high-level snapshot capturing:
# – Role/domain identity  
# – Key skills (technical or soft)  
# – Highest education or academic background  
# – Only One appropriate **Industry–Domain pairing**, chosen **ONLY one domain and industry** from resume evidence and based on the examples below:

#     • Industry - Financial Services  
#       Domain - Retail Banking, Mortgage Processing, Fraud Detection  

#     • Industry - Healthcare  
#       Domain - Patient Scheduling, Clinical Documentation, Medical Billing & Claims  

#     • Industry - E-commerce / Retail  
#       Domain - Inventory Management, Logistics & Fulfillment  

#     • Industry - Telecommunications  
#       Domain - Billing and Invoicing, Network Provisioning, Customer Relationship Management  


# SKILLS:
# Tools → programming languages, frameworks, cloud tools, software, platforms  
# HardSkills → technical, domain, analytical, operational skills  
# SoftSkills → behavioural, communication, leadership, interpersonal skills  

# EXPERIENCE:
# YearsOfExperience is used ONLY if explicitly mentioned.
# You MAY calculate or infer from dates and timelines if clearly provided.

# PROFILE SNAPSHOT:
# A short 1-line mini-summary of role + experience + key skill.

# EXPERIENCE LEVEL:
# Choose ONLY from actual job roles, job titles, leadership positions, or responsibilities.
# Allowed values:
# “Fresher”,  
# “Junior”,  
# “Mid-Level”,  
# “Senior”,  
# “Lead”,  
# “Manager”,  
# “Senior Manager”,  
# “Director”,  
# “Senior Director”,  
# “Vice President”,  
# “Senior Vice President”,  
# “C-Level Executive”,  
# “Founder / Co-Founder”,  
# “Head / Department Head”,  
# “Not specified”

# PERSONA INSIGHTS:
# Interpret strengths, behaviour traits, and working style ONLY from resume evidence.

# CAREER STAGE CATEGORY:
# One of:
# “Student”, “Early Professional”, “Mid Career Pivot”, “Job Seeker”.
# ------------------------------------------------------------
# JSON OUTPUT SCHEMA (DO NOT MODIFY EXISTING KEYS)
# ------------------------------------------------------------

# {
#   "Name": "",
#   "DOB": "",
#   "Email": "",
#   "Phone": "",
#   "Address": "",
#   "LinkedIn": "",
#   "Summary": "",
#   "Skills": {
#     "HardSkills": [],
#     "SoftSkills": [],
#     "Tools": []
#   },
#   "WorkExperience": [
#     {
#       "Company": "",
#       "Role": "",
#       "Duration": "",
#       "Description": ""
#     }
#   ],
#   "Education": [
#     {
#       "Degree": "",
#       "Institution": "",
#       "Grade": "",
#       "Year": ""
#     }
#   ],
#   "Certifications": [
#     {
#       "Name": "",
#       "Issuer": "",
#       "Year": ""
#     }
#   ],
#    "Interships": [
#     {
#       "Title": "",
#       "Description": ""
#     }
#   ],
#   "Projects": [
#     {
#       "Title": "",
#       "Description": ""
#     }
#   ],
#   "Languages": [
#     {
#       "Language": "",
#       "Proficiency": ""
#     }
#   ],
#   "Awards": [
#     {
#       "Title": "",
#       "Issuer": "",
#       "Year": ""
#     }
#   ],
#   "VolunteerExperience": [
#     {
#       "Organization": "",
#       "Role": "",
#       "Duration": "",
#       "Description": ""
#     }
#   ],
#   "Hobbies": [],
#   "OtherSections": [
#     {
#       "Title": "",
#       "Description": ""
#     }
#   ],
#   "YearsOfExperience": 0.0,

#   "Talent Information": {
#     "Core Tasks": "",
#     "Supplementary Tasks": "",
#     "Emerging Tasks": "",
#     "Knowledge": "",
#     "Skills": "",
#     "Abilities": "",
#     "Work activities": "",
#     "Work styles": "",
#     "Work values": "",
#     "Technical Skills": "",
#     "Hot Technologies": "",
#     "Soft Skills": "",
#     "Functional Skills": "",
#     "Certifications": [
#       {
#         "Name": "",
#         "Provider": "",
#         "Year": ""
#       }
#     ],
#     "Salary grades": "",
#     "Career Objective": "",
#         "Career Interest Areas": "",
#   },

#   "Anchor Attributes": {
#     "Achievements": "",
#     "Behavioral Skills": "",
#     "Interests": "",
#     "Competency": "",
#     "Cognitive Preferences": "",
#     "Creative Inclinations": "",
#     "Exploration Interest": "",
#     "Future study intent": "",
#     "Cultural Exposure": "",
#     "Emerging Tech Awareness": "",
#     "Hobbies": "",
#     "Learning Agility": "",
#     "Life Skills": "",
#     "Motivation Drivers": "",
#     "Motivating Activities": "",
#     "Newly Acquired Skills": "",
#     "Organizational Skills": "",
#     "Personal Interests": "",
#     "Social Causes": "",
#     "Volunteering": "",
#     "Personality Traits": ""
#   },

#   "Know about yourself": {
#     "Inferred Persona Insights": "",
#     "Career stage category": ""
#   },

#   "Domain": "",
#   "Industry":"",
#   "ProfileSnapshot": "",
#   "ExperienceLevel": "",

#   "LLM_Generated_Certificates": [],
#   "LLM_Generated_Technical_Skills": [],
#   "LLM_Generated_Soft_Skills": []
# }

# ------------------------------------------------------------
# FINAL RULES
# ------------------------------------------------------------
# – Output MUST be valid JSON.  
# – Start with “{” and end with “}”.  
# – No explanation, no markdown, no extra text.  
# – Never hallucinate factual data.  
# – Only auto-fill Technical Skills, Soft Skills, and Certifications inside Talent Information if missing.
# – Respect top-skill limits  
# – If empty, DO NOT fill the original fields.
# – Instead fill ONLY:
#     "LLM_Generated_Technical_Skills",
#     "LLM_Generated_Soft_Skills",
#     "LLM_Generated_Certificates".
# – If any certifications exist in the resume → LLM_Generated_Certificates MUST be empty.
# – If no certifications exist → LLM_Generated_Certificates MUST be generated.
# – Infer ONLY in Persona Insights, not in structured fields.
# – Keep domain & industry specific and evidence-based

# """

#     try:
#         if mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
#             file_text = extract_docx_text(filepath)
#             content_input = [file_text, prompt]
#         else:
#             file_bytes = pathlib.Path(filepath).read_bytes()
#             content_input = [
#                 {"mime_type": mime_type, "data": file_bytes},
#                 prompt
#             ]

#         response = model.generate_content(content_input, stream=False)
#         response_text = response.text.strip()

#         if response_text.startswith("```json"):
#             response_text = response_text[7:]
#         if response_text.endswith("```"):
#             response_text = response_text[:-3]

#         response_text = response_text.strip()
#         start_idx = response_text.find('{')
#         end_idx = response_text.rfind('}')
#         response_text = response_text[start_idx:end_idx+1]

#         parsed_json = json.loads(response_text)
#         parsed_json = clean_json(parsed_json)

#         work_exp = parsed_json.get("WorkExperience", [])
#         years_from_work = calculate_years_of_experience(work_exp)

#         if years_from_work > 0:
#             parsed_json["YearsOfExperience"] = years_from_work
#         else:
#             parsed_json["YearsOfExperience"] = extract_years_from_summary(parsed_json.get("Summary", ""))

#         parsed_json["JobRole"] = extract_job_role(parsed_json)

#         return parsed_json

#     except Exception as e:
#         print("CV Extraction Error:", str(e))
#         return {"error": "Failed to parse CV data"}


def extract_cv_data_from_file(filepath: str, mime_type: str):
    
    prompt = """
You are a Senior HR Recruitment, Talent Analyst, and Skill Intelligence Expert trained to extract accurate structured information from resumes, profiles, or people data.

Your task:
Read the documents/data and return a CLEAN, VALID JSON object following the exact schema below.
Use your HR experience to extract and interpret information correctly.
Do NOT delete, modify, rename, or reorder existing keys.
You may ONLY add the additional keys provided at the bottom.
If information is missing, return "Not specified".
Return ONLY valid JSON. No commentary, no markdown, no explanations.

------------------------------------------------------------
CRITICAL OVERRIDES (STRICT)
------------------------------------------------------------
1. INDUSTRY RULE (STRICT)
   - You MUST return exactly ONE ** Industry**, even if the resume mentions multiple.
   - Choose the MOST RECENT logical industry based on last 1–2 job roles.
   - Examples:
        If last job is at Lowe’s → Industry = "Retail"
        If last job is Diageo → Industry = "Beverage / FMCG"
        If last job is in IT consulting → Industry = "Information Technology Services"
        - Retail  
        - FMCG  
        - Consulting  
        - Insurance  
        - IT Services  
        - Telecommunications  
        
2. DOMAIN (MUST BE EXACTLY ONE)
• Domain = primary functional expertise (HRBP, L&D, DEI, PMO, etc.).
• Select ONE domain based on:
    – 70%+ responsibilities across roles
    – Skills and certifications
• Examples: “Leadership & Organizational Development”, “HR Business Partnering”, “DEI & Culture Transformation”, “Program Management Office (PMO)”.

3. SKILL LIMITS (VERY STRICT)
• HardSkills → MAX 10  
• SoftSkills → MAX 5  
• Tools → unlimited but relevant only  
• Remove duplicates (standardize names)  
• Choose skills most relevant to the latest 1–2 roles.

4. CERTIFICATION RULES
• If certifications exist → keep EXACTLY as they appear.
• If NO certifications → generate EXACTLY 3 realistic ones ONLY inside:
      "LLM_Generated_Certificates"
• NEVER fill original Certification fields when empty.

5. AUTO-FILL RULE (STRICT)
Auto-fill ONLY if original field is EMPTY:
• Technical Skills → fill ONLY "LLM_Generated_Technical_Skills"
• Soft Skills     → fill ONLY "LLM_Generated_Soft_Skills"
• Certifications  → fill ONLY "LLM_Generated_Certificates"

6. EMPTY DEFINITION
EMPTY = "", null, whitespace, empty list, or list of empty objects.

------------------------------------------------------------
INSTRUCTION RULES (APPLY TO ALL FIELDS)
------------------------------------------------------------

SUMMARY (2–3 lines)
Must include:
• Role/domain identity  
• Key technical or soft skills  
• Highest relevant education  
• ONE Domain + ONE Industry  

SKILLS CLASSIFICATION
• Tools = platforms, software, cloud tools  
• HardSkills = technical or domain skills  
• SoftSkills = behavioural and communication skills  

EXPERIENCE
YearsOfExperience may be calculated if dates are clearly provided.

PROFILE SNAPSHOT
One strong line summarizing role + experience + core capability.

EXPERIENCE LEVEL
Allowed values:
“Fresher”, “Junior”, “Mid-Level”, “Senior”, “Lead”, “Manager”,  
“Senior Manager”, “Director”, “Senior Director”, “Vice President”,  
“Senior Vice President”, “C-Level Executive”,  
“Head / Department Head”, “Founder / Co-Founder”, “Not specified”.

PERSONA INSIGHTS
Infer ONLY behavioural patterns and strengths (no hallucination).

CAREER STAGE CATEGORY
One of: “Student”, “Early Professional”, “Mid Career Pivot”, “Job Seeker”.
------------------------------------------------------------
JSON OUTPUT SCHEMA (DO NOT MODIFY EXISTING KEYS)
------------------------------------------------------------

{
  "Name": "",
  "DOB": "",
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
   "Interships": [
    {
      "Title": "",
      "Description": ""
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
  "YearsOfExperience": 0.0,

  "Talent Information": {
    "Core Tasks": "",
    "Supplementary Tasks": "",
    "Emerging Tasks": "",
    "Knowledge": "",
    "Skills": "",
    "Abilities": "",
    "Work activities": "",
    "Work styles": "",
    "Work values": "",
    "Technical Skills": "",
    "Hot Technologies": "",
    "Soft Skills": "",
    "Functional Skills": "",
    "Certifications": [
      {
        "Name": "",
        "Provider": "",
        "Year": ""
      }
    ],
    "Salary grades": "",
    "Career Objective": "",
    "Career Interest Areas": ""
  },

  "Anchor Attributes": {
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
  },

  "Know about yourself": {
    "Inferred Persona Insights": "",
    "Career stage category": ""
  },

  "Domain": "",
  "Industry":"",
  "ProfileSnapshot": "",
  "ExperienceLevel": "",
  "AllCompanies": [],
  "AllRoles": [],

  "LLM_Generated_Certificates": [],
  "LLM_Generated_Technical_Skills": [],
  "LLM_Generated_Soft_Skills": []
}

------------------------------------------------------------
FINAL RULES
------------------------------------------------------------
– Output MUST be valid JSON only.  
– No explanation, no markdown, no surrounding text.  
– NO hallucination of factual information.  
– Respect ALL skill limits (HardSkills=10, SoftSkills=5).  
– Auto-fill ONLY the LLM_Generated_* fields when originals are empty.  
– If certifications exist in resume → LLM_Generated_Certificates MUST remain empty.  
– Keep Domain and Industry as exactly ONE each.  
– Do NOT modify existing schema or reorder keys.  

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

        logger.info("[GEMINI CALL] caller=extract_cv_data_from_file | sending CV file to Gemini for parsing")
        t0 = time.time()
        response = model.generate_content(content_input, stream=False)
        logger.info(f"[GEMINI CALL] caller=extract_cv_data_from_file | SUCCESS | time={round(time.time()-t0,2)}s")
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
    elif total_years == 0:
        return "Student"
    elif 0 < total_years <= 5:
        return "Early Professional (2-3 years of experience)"
    elif total_years > 5:
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
    "certification": "certifications_suggestions",
    "certificate": "certifications_suggestions",
    "certificates": "certifications_suggestions",
    "certification_suggestions": "certifications_suggestions"
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
    if not skills.get("SoftSkills"):
        missing_fields.append("SoftSkills")
    if not skills.get("HardSkills"):
        missing_fields.append("HardSkills")
    if not cv_context.get("Certifications"):
        missing_fields.append("Certifications")

    if not missing_fields:
        return suggestions

    context_str = "\n".join(f"{k}: {v}" for k, v in cv_context.items() if v)
    prompt = (
        "You are an AI assistant specialized in analyzing CV/resume data to suggest missing or weak content. "
        "Analyze the provided CV Context and identify relevant professional suggestions for ALL fields listed in 'Missing Fields'.\n\n"
        f"CV Context:\n{context_str}\n\n"
        f"Missing Fields: {missing_fields}\n\n"
        "**CRITICAL RESPONSE FORMAT INSTRUCTIONS**\n"
        "1. **Respond ONLY in valid JSON.**\n"
        "2. **You MUST include a key for every field listed in 'Missing Fields'.** Use the exact key names (e.g., 'SoftSkills', 'Certifications').\n"
        "3. **Each value MUST be a JSON array of strings.**\n"
        "4. **Format Reference for Certifications:** For 'Certifications', format each suggestion as a single string: 'Certification Name – Issuing Organization'. Example: 'PMP – PMI', 'AWS Certified Developer – Amazon', or 'CSIR-UGC NET JRF - NTA'.\n"
        "5. **Format Reference for Skills:** For 'SoftSkills' and 'HardSkills', provide single-word or short-phrase skills. Example: 'Python', 'Leadership', 'Data Analysis'."
    )

    response = await _gemini_with_retry(prompt, caller="generate_missing_field_suggestions")
    cleaned = clean_llm_json_response(response.text)

    try:
        parsed = json.loads(cleaned)
    except Exception:
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

        if mapped_field == "softskills_suggestions" and "SoftSkills" in missing_fields:
            suggestions["softskills_suggestions"].extend(items)

        if mapped_field == "technical_skills_suggestions" and "HardSkills" in missing_fields:
            suggestions["technical_skills_suggestions"].extend(items)

        if mapped_field == "certifications_suggestions" and "Certifications" in missing_fields:
            suggestions["certifications_suggestions"].extend(items)

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

    # ---- Extract the required fields ----
    summary = cv_context.get("Summary")
    experience = cv_context.get("Experience") or cv_context.get("WorkExperience")
    industry = cv_context.get("Industry") or cv_context.get("IndustryDomain")
    domain = cv_context.get("Domain")
    technical_skills = cv_context.get("TechnicalSkills") or cv_context.get("Skills", {}).get("HardSkills")
    soft_skills = cv_context.get("SoftSkills") or cv_context.get("Skills", {}).get("SoftSkills")
    talent_attributes = cv_context.get("TalentAttributes") or cv_context.get("Talent Information")

    # ---- DEDUPLICATION HELPER ----
    def dedupe(value):
        if isinstance(value, list):
            seen = set()
            unique = []
            for v in value:
                key = str(v)
                if key not in seen:
                    seen.add(key)
                    unique.append(v)
            return unique

        if isinstance(value, str):
            # Remove duplicate lines
            lines = value.split("\n")
            unique_lines = list(dict.fromkeys(lines))
            return "\n".join(unique_lines)

        return value  # dict or others

    # ---- Build CLEAN context with NO duplicates ----
    filtered_context = {
        "Summary": dedupe(summary),
        "Experience": dedupe(experience),
        "Industry": dedupe(industry),
        "Domain": dedupe(domain),
        "TechnicalSkills": dedupe(technical_skills),
        "SoftSkills": dedupe(soft_skills),
        "TalentAttributes": dedupe(talent_attributes),
    }

    # ---- Convert filtered items into a string for LLM ----
    context_str = "\n".join(
        f"{k}: {v}" for k, v in filtered_context.items() if v
    )

    # ---- Audience filter ----
    audience_type = cv_context.get("audience_type") or cv_context.get("audience")

    if audience_type:
        questions_from_db = [
            q for q in questions_from_db
            if not q.get("audience") or q.get("audience") == audience_type
        ]

    async def _fetch_options_for_question(q):
        parameter = q.get("parameter", "")
        question_text = q.get("question")
        qtype = q.get("type")
        iconfilename = q.get("iconfilename")
        limit = q.get("limit") or q.get("Limit")

        parameter_list = [p.strip() for p in parameter.split(" + ")]
        option_count = 5 if len(parameter_list) == 1 else 2 * len(parameter_list)

        prompt = (
            "Generate focused, high-quality multiple-choice options based on the user's professional background and "
            "the intent of the question.\n\n"
            "Generate options based on the content of the question, ensuring they introduce new elements not already "
            "included in the resume/CV but relatable to the job title.\n\n"
            "CONTEXT SUMMARY:\n"
            f"{context_str}\n\n"
            "QUESTION:\n"
            f"{question_text}\n\n"
            "PARAMETERS:\n"
            f"{', '.join(parameter_list)}\n\n"
            "OUTPUT FORMAT (STRICT JSON):\n"
            "{{\n"
            "  \"options\": [\"Option 1\", \"Option 2\", ...]\n"
            "}}\n\n"
            "REQUIREMENTS:\n"
            f"- Provide EXACTLY {option_count} options.\n"
            "- Options must be short, clear (2–5 words), and directly related to the parameters and the question.\n"
            "- Each option must start with a capital letter.\n"
            "- No numbering, bullets, special symbols, or prefixes.\n"
            "- Avoid generic, vague, or repetitive wording.\n"
        )

        try:
            response = await _gemini_with_retry(prompt, caller="generate_job_attribute_options")
            cleaned = clean_llm_json_response(response.text)
            parsed = json.loads(cleaned)
            options = parsed.get("options", [])

            formatted_options = []
            for opt in options:
                opt = re.sub(r"^[^A-Za-z]+", "", opt.strip())
                opt = (opt[:1].upper() + opt[1:]) if opt else "Option"
                formatted_options.append(opt)

            while len(formatted_options) < option_count:
                formatted_options.append(f"Option {len(formatted_options) + 1}")

            result_item = {
                "parameter": parameter_list,
                "question": question_text,
                "type": qtype,
                "iconfilename": iconfilename,
                "options": formatted_options,
            }
        except Exception:
            result_item = {
                "parameter": parameter_list,
                "question": question_text,
                "type": qtype,
                "iconfilename": iconfilename,
                "options": [f"Option {i+1}" for i in range(option_count)],
            }

        if limit is not None:
            result_item["limit"] = limit
        return result_item

    logger.info(f"[GEMINI GATHER] generate_job_attribute_options | firing {len(questions_from_db)} calls in parallel")
    results = await asyncio.gather(*[_fetch_options_for_question(q) for q in questions_from_db])
    logger.info(f"[GEMINI GATHER] generate_job_attribute_options | all {len(questions_from_db)} calls complete")

    return {
        "success": True,
        "suggestions": list(results),
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


# async def generate_anchor_attribute_options(user_id: str, questions, model, get_database):
#     """
#     Generate multiple-choice options for Anchor attributes based ONLY on:
#     - Personal Interests + Hobbies + Exploration Interest + Motivation Drivers + Motivating Activities
#     - Achievements (text field only)

#     Each parameter contributes EXACTLY 2 options (fixed count).
#     Saves results in the latest uploaded CV document for the user.
#     """

#     target_parameters = {
#         "Creative Inclinations + Organizational Skills + Competency + Personality Traits",
#         "Newly Acquired Skills + Emerging Tech Awareness + Future Study Intent"
#     }

#     db = await get_database()
#     latest_cv = await get_latest_user_cv(db, user_id)
#     if not latest_cv or "parsed_data" not in latest_cv:
#         raise HTTPException(status_code=404, detail="No CV found for this user")

#     cv_id = str(latest_cv["_id"])

#     cursor = db["answers"].find({
#         "cv_id": cv_id,
#         "section": "Anchor Attributes",
#         "parameter": {
#             "$in": [
#                 "Personal Interests + Hobbies + Exploration Interest + Motivation Drivers + Motivating Activities",
#                 "Achievements"
#             ]
#         }
#     })
#     answers = await cursor.to_list(length=None)

#     if not answers:
#         raise HTTPException(status_code=404, detail="No required anchor answers found")

#     base_free_text_map = {}
#     for ans in answers:
#         param = ans["parameter"]
#         val = ans["value"]
#         if isinstance(val, str):
#             base_free_text_map[param] = val
#         elif isinstance(val, dict) and "text" in val:
#             base_free_text_map[param] = val["text"]

#     non_empty_texts = [t for t in base_free_text_map.values() if t]
#     random.shuffle(non_empty_texts)
#     context_sample = "\n".join(non_empty_texts)

#     style_noise_pool = [
#         "use uncommon synonyms",
#         "reorder ideas differently",
#         "make phrasing more concise",
#         "add creative wording twists",
#         "slightly formal tone",
#         "slightly casual tone",
#         "shuffle activity order",
#         "split compound ideas differently"
#     ]
#     random.shuffle(style_noise_pool)
#     style_noise = ", ".join(style_noise_pool[:3])
#     variation_key = f"{uuid.uuid4()}-{datetime.utcnow().timestamp()}"

#     suggestions = []

#     for q in questions:
#         parameter = q.get("parameter")
#         if parameter not in target_parameters:
#             continue

#         question_text = q.get("question")
#         type_ = q.get("type")
#         iconfilename = q.get("iconfilename")

#         parameter_list = [p.strip() for p in parameter.split("+")]
#         option_count = 2 * len(parameter_list)  

#         import pdb;pdb.set_trace()
#         variation_instructions = (
#             "- Ensure each execution produces DIFFERENT wording, even if the free-text is unchanged.\n"
#             "- Randomly split, merge, or rephrase phrases so that no two runs look the same.\n"
#             "- Introduce synonyms, shuffle word order, or shorten differently.\n"
#             "- Do NOT invent anything that is not explicitly present in the free-text answers.\n"
#             f"- Apply these random variation rules: {style_noise}\n"
#         )

#         prompt = (
#             "You are an AI assistant generating short, career-related multiple-choice options.\n\n"
#             f"STRICT KNOWLEDGE BASE (rephrase ONLY from this, do not add new ideas):\n{context_sample}\n\n"
#             f"Target parameters: {', '.join(parameter_list)}\n"
#             f"Question: {question_text}\n\n"
#             "Instructions:\n"
#             f"- Generate EXACTLY {option_count} short options.\n"
#             "- Each option must rephrase, split, or summarize the ideas from the free-text.\n"
#             "- DO NOT invent anything not in the context.\n"
#             "- Keep options SHORT (2–5 words).\n"
#             "- Start each option with a CAPITAL letter.\n"
#             "- Return plain text options only (no labels or numbers).\n"
#             "- All options must be distinct and meaningful.\n"
#             f"{variation_instructions}"
#             f"- Variation key: {variation_key}\n\n"
#             "Respond ONLY in JSON format:\n"
#             "{\n"
#             "  \"options\": [\"<Short phrase 1>\", \"<Short phrase 2>\", ...]\n"
#             "}"
#         )

#         try:
#             response = await _gemini_with_retry(prompt)
#             cleaned = clean_llm_json_response(response.text)
#             parsed = json.loads(cleaned)
#             options = parsed.get("options", [])

#             formatted = []
#             for opt in options[:option_count]:
#                 cleaned_opt = opt.strip().lstrip("0123456789.- ").capitalize()
#                 formatted.append(cleaned_opt)

#             while len(formatted) < option_count:
#                 formatted.append(f"Option {len(formatted)+1}")

#             suggestions.append({
#                 "parameter": parameter_list,
#                 "question": question_text,
#                 "type": type_,
#                 "iconfilename": iconfilename,
#                 "options": formatted
#             })

#         except Exception as e:
#             suggestions.append({
#                 "parameter": parameter_list,
#                 "question": question_text,
#                 "type": type_,
#                 "iconfilename": iconfilename,
#                 "options": [f"Option {i+1}" for i in range(option_count)],
#                 "error": str(e)
#             })

#     await db["uploads"].update_one(
#         {"_id": latest_cv["_id"]},
#         {"$set": {"anchor_questions_with_options": suggestions}}
#     )

#     return {"success": True, "suggestions": suggestions}

async def generate_anchor_attribute_options(user_id: str, questions, model, get_database):
    """
    Generate multiple-choice options for Anchor attributes based on:
    - Personal Interests + Hobbies + Exploration Interest + Motivation Drivers + Motivating Activities
    - Achievements
    - PLUS resume context: Summary + Experience text + Education text

    Each parameter contributes EXACTLY 2 options.
    Saves results in the latest uploaded CV document for the user.
    """

    target_parameters = {
        "Creative Inclinations + Organizational Skills + Competency + Personality Traits",
        "Newly Acquired Skills + Emerging Tech Awareness + Future Study Intent"
    }

    db = await get_database()

    # ---- Get latest CV upload ----
    latest_cv = await get_latest_user_cv(db, user_id)
    if not latest_cv or "parsed_data" not in latest_cv:
        raise HTTPException(status_code=404, detail="No CV found for this user")

    cv_id = str(latest_cv["_id"])

    # ---- Fetch only required anchor answers ----
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

    # ---- Extract free text for anchor parameters ----
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

    # ----------------------------------------------------------
    # 📌 ADD RESUME TEXT FROM UPLOADS → Summary, Experience, Education
    # ----------------------------------------------------------
    parsed = latest_cv.get("parsed_data", {})

    # Summary
    summary_text = parsed.get("Summary") or ""

    # Experience text (joining all descriptions)
    experience_text = ""
    work_exp = parsed.get("WorkExperience") or []
    if isinstance(work_exp, list):
        experience_text = "\n".join([
            w.get("Description", "") for w in work_exp if w.get("Description")
        ])

    # Education text
    education_text = ""
    edu_list = parsed.get("Education") or []
    if isinstance(edu_list, list):
        education_text = "\n".join([
            f"{e.get('Degree', '')} {e.get('College', '')} {e.get('Year', '')}".strip()
            for e in edu_list
            if e.get('Degree') or e.get('College') or e.get('Year')
        ])

    # Merge context + resume fields
    extra_resume_context = "\n".join([
        summary_text,
        experience_text,
        education_text
    ]).strip()

    combined_context = (context_sample + "\n" + extra_resume_context).strip()

    # ----------------------------------------------------------
    # RANDOM NOISE + VARIATION KEY
    # ----------------------------------------------------------
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

    async def _fetch_anchor_option(q):
        parameter = q.get("parameter")
        if parameter not in target_parameters:
            return None

        question_text = q.get("question")
        type_ = q.get("type")
        iconfilename = q.get("iconfilename")
        parameter_list = [p.strip() for p in parameter.split("+")]
        option_count = 2 * len(parameter_list)

        variation_instructions = (
            "- Ensure each execution produces DIFFERENT wording.\n"
            "- Randomly split, merge, or rephrase phrases from context.\n"
            "- Introduce synonyms or shuffle words.\n"
            "- Do NOT invent anything not present in the context.\n"
            f"- Apply variation rules: {style_noise}\n"
        )

        prompt = (
            "You are an AI assistant generating short, career-related multiple-choice options.\n\n"
            "Generate options inspired by the user’s Personal Interests, Hobbies, Exploration Interests, "
            "Motivation Drivers, Motivating Activities, and Achievements—without directly copying their context. "
            "Infer the user’s underlying nature (e.g., creative, organized, exploratory) and tailor the options "
            "to reflect that. Ensure the options remain relevant to the user’s job title and aligned with their "
            "inferred personality and interests.\n\n"
            "Also generate options based on the content of the question, ensuring they introduce new elements "
            "that are not already included in the resume/CV but relatable to the job title.\n\n"
            f"STRICT KNOWLEDGE BASE (use ONLY this content, no invention):\n{combined_context}\n\n"
            f"Target parameters: {', '.join(parameter_list)}\n"
            f"Question: {question_text}\n\n"
            "Instructions:\n"
            f"- Generate EXACTLY {option_count} options.\n"
            "- Each option must rephrase or summarize ideas from the context.\n"
            "- Keep options SHORT (2–5 words).\n"
            "- Start each option with a CAPITAL letter.\n"
            "- No numbers, bullets, or labels.\n"
            "- All options must be distinct.\n"
            f"{variation_instructions}"
            f"- Variation key: {variation_key}\n\n"
            "Respond ONLY in JSON format:\n"
            "{{\n"
            "  \"options\": [\"<Short phrase 1>\", \"<Short phrase 2>\", ...]\n"
            "}}\n"
        )

        try:
            response = await _gemini_with_retry(prompt, caller="generate_anchor_attribute_options")
            cleaned = clean_llm_json_response(response.text)
            parsed_json = json.loads(cleaned)
            options = parsed_json.get("options", [])

            formatted = []
            for opt in options[:option_count]:
                formatted.append(opt.strip().lstrip("0123456789.- ").capitalize())
            while len(formatted) < option_count:
                formatted.append(f"Option {len(formatted)+1}")

            return {
                "parameter": parameter_list,
                "question": question_text,
                "type": type_,
                "iconfilename": iconfilename,
                "options": formatted,
            }
        except Exception as e:
            return {
                "parameter": parameter_list,
                "question": question_text,
                "type": type_,
                "iconfilename": iconfilename,
                "options": [f"Option {i+1}" for i in range(option_count)],
                "error": str(e),
            }

    logger.info(f"[GEMINI GATHER] generate_anchor_attribute_options | firing {len(questions)} calls in parallel")
    raw = await asyncio.gather(*[_fetch_anchor_option(q) for q in questions])
    logger.info(f"[GEMINI GATHER] generate_anchor_attribute_options | all {len(questions)} calls complete")
    suggestions = [r for r in raw if r is not None]

    # ----------------------------------------------------------
    # SAVE RESULTS IN UPLOADS COLLECTION
    # ----------------------------------------------------------
    await db["uploads"].update_one(
        {"_id": latest_cv["_id"]},
        {"$set": {"anchor_questions_with_options": suggestions}}
    )

    return {"success": True, "suggestions": suggestions}


#--------------Second Flow--------------


async def generate_job_attribute_options_without_cv(user_id: str, db) -> dict:
    """
    Generates multiple-choice options for  Job attributes
    and saves them to the proceed_without_cv collection.
    """

    proceed_collection = db["proceed_without_cv"]
    answers_collection = db["answers_without_cv"]
    questions_collection = db["questions"]

    # Get latest proceed_without_cv doc
    latest_doc = await proceed_collection.find_one(
        {"user_id": user_id},
        sort=[("created_at", -1)]
    )
    if not latest_doc:
        raise HTTPException(status_code=404, detail="No proceed_without_cv doc found")

    latest_document_id = str(latest_doc["_id"])
    audience_type = latest_doc.get("audienceType")

    # Get missing answers
    missing_answers_cursor = answers_collection.find(
        {"user_id": user_id, "document_id": latest_document_id, "section": "Cv Missing"}
    )
    missing_answers = await missing_answers_cursor.to_list(length=None)

    if not missing_answers:
        raise HTTPException(status_code=404, detail="No missing answers found")

    # Build context string
    context_str = "\n".join(
        f"{a['parameter']}: {a.get('value')}" for a in missing_answers if a.get("value")
    )

    # Fetch job attributes questions
    questions_doc = await questions_collection.find_one({})
    if not questions_doc:
        raise HTTPException(status_code=404, detail="No questions document found")

    job_attributes = questions_doc.get("Job attributes", [])
    questions_for_user = [
        qa for qa in job_attributes if qa.get("audienceType") == audience_type
    ]

    if not questions_for_user:
        raise HTTPException(
            status_code=404, detail=f"No questions found for audienceType {audience_type}"
        )

    all_questions = [
        q for qa_group in questions_for_user for q in qa_group.get("questions", [])
    ]

    async def _fetch_without_cv_option(q):
        parameter = q.get("parameter", "")
        question_text = q.get("question")
        qtype = q.get("type")
        iconfilename = q.get("iconfilename")
        limit = q.get("limit") or q.get("Limit")

        parameter_list = [p.strip() for p in parameter.split("+")]
        option_count = 5 if len(parameter_list) == 1 else 2 * len(parameter_list)

        prompt = (
            "You are an AI assistant generating short, career-related multiple-choice options.\n\n"
            f"Audience Type: {audience_type}\n\n"
            f"Missing CV Context:\n{context_str}\n\n"
            f"Question: {question_text}\n\n"
            "Respond ONLY in JSON format:\n"
            "{{\n"
            "  \"options\": [\n"
            "    \"<short phrase>\",\n"
            "    \"<short phrase>\"\n"
            "  ]\n"
            "}}\n\n"
            "RULES:\n"
            f"- Provide EXACTLY {option_count} concise, distinct options.\n"
            "- Keep each option 2–5 words long.\n"
            "- Avoid numbering or letters (no A/B/C/... prefixes).\n"
            "- Make sure they fit the question meaningfully."
        )

        try:
            response = await _gemini_with_retry(prompt, caller="generate_job_attribute_options_without_cv")
            cleaned = clean_llm_json_response(response.text)
            parsed = json.loads(cleaned)
            options = parsed.get("options", [])
            formatted_options = [opt.strip() for opt in options[:option_count]]
            while len(formatted_options) < option_count:
                formatted_options.append(f"Option {len(formatted_options)+1}")
            result_item = {
                "parameter": parameter_list,
                "question": question_text,
                "type": qtype,
                "iconfilename": iconfilename,
                "options": formatted_options,
            }
        except Exception as e:
            print(f"Fallback due to error: {e}")
            result_item = {
                "parameter": parameter_list,
                "question": question_text,
                "type": qtype,
                "iconfilename": iconfilename,
                "options": [f"Option {i+1}" for i in range(option_count)],
            }

        if limit is not None:
            result_item["limit"] = limit
        return result_item

    logger.info(f"[GEMINI GATHER] generate_job_attribute_options_without_cv | firing {len(all_questions)} calls in parallel")
    results = list(await asyncio.gather(*[_fetch_without_cv_option(q) for q in all_questions]))
    logger.info(f"[GEMINI GATHER] generate_job_attribute_options_without_cv | all {len(all_questions)} calls complete")

    # Save results
    await proceed_collection.update_one(
        {"_id": latest_doc["_id"]},
        {"$set": {"job_questions_with_options": results, "updated_at": datetime.utcnow()}}
    )

    return {
        "success": True,
        "latest_document_id": latest_document_id,
        "audience_type": audience_type,
        "suggestions": results,
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

    OPTIONS_PER_PARAMETER = 2

    target_parameters = {
        "Creative Inclinations + Organizational Skills + Competency + Personality Traits",
        "Newly Acquired Skills + Emerging Tech Awareness + Future Study Intent",
    }

    db = await get_database()
    latest_proceed = await db["proceed_without_cv"].find(
        {"user_id": user_id}
    ).sort("created_at", -1).to_list(length=1)

    if not latest_proceed:
        raise HTTPException(status_code=404, detail="No proceed_without_cv found for user")

    document = latest_proceed[0]
    document_id = document["_id"]
    audience_type = document.get("audienceType", "General")

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

    async def _fetch_anchor_without_cv(q):
        parameter = q.get("parameter")
        if parameter not in target_parameters:
            return None

        question_text = q.get("question")
        type_ = q.get("type")
        iconfilename = q.get("iconfilename")
        parameter_list = [p.strip() for p in parameter.split("+")]
        option_count = OPTIONS_PER_PARAMETER * len(parameter_list)

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
            f"- Generate EXACTLY {option_count} short options.\n"
            "- Each option must be a direct rephrasing, splitting, or summarizing of the free-text answers.\n"
            "- DO NOT invent anything that is not explicitly present in the free-text answers.\n"
            "- Keep each option SHORT (2–5 words).\n"
            f"{variation_instructions}"
            f"- Variation key (for uniqueness): {variation_key}\n\n"
            "Respond ONLY in JSON format:\n"
            "{{\n"
            "  \"options\": [\n"
            + ",\n".join(["    \"<short phrase>\"" for _ in range(option_count)])
            + "\n  ]\n"
            "}}"
        )

        try:
            response = await _gemini_with_retry(prompt, caller="generate_anchor_options_from_answers_without_cv")
            cleaned = clean_llm_json_response(response.text)
            parsed = json.loads(cleaned)
            options = parsed.get("options", [])
            formatted = [
                options[i].strip() if i < len(options) else f"Option {i+1}"
                for i in range(option_count)
            ]
            return {
                "parameter": parameter_list,
                "question": question_text,
                "type": type_,
                "iconfilename": iconfilename,
                "options": formatted,
            }
        except Exception as e:
            return {
                "parameter": parameter_list,
                "question": question_text,
                "type": type_,
                "iconfilename": iconfilename,
                "options": [f"Option {i+1}" for i in range(option_count)],
                "error": str(e),
            }

    logger.info(f"[GEMINI GATHER] generate_anchor_options_from_answers_without_cv | firing {len(questions)} calls in parallel")
    raw = await asyncio.gather(*[_fetch_anchor_without_cv(q) for q in questions])
    logger.info(f"[GEMINI GATHER] generate_anchor_options_from_answers_without_cv | all {len(questions)} calls complete")
    suggestions = [r for r in raw if r is not None]
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
