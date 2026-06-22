"""
Centralized prompt constants for all Gemini LLM calls.

Every prompt template used across cv_extractor.py and router.py lives here.
Dynamic values are injected via str.format() or f-string at call sites.
"""

import json

# ---------------------------------------------------------------------------
# CV EXTRACTION
# ---------------------------------------------------------------------------

CV_EXTRACTION_PROMPT = """\
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
        If last job is at Lowe's → Industry = "Retail"
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
• Examples: "Leadership & Organizational Development", "HR Business Partnering", "DEI & Culture Transformation", "Program Management Office (PMO)".

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
"Fresher", "Junior", "Mid-Level", "Senior", "Lead", "Manager",
"Senior Manager", "Director", "Senior Director", "Vice President",
"Senior Vice President", "C-Level Executive",
"Head / Department Head", "Founder / Co-Founder", "Not specified".

PERSONA INSIGHTS
Infer ONLY behavioural patterns and strengths (no hallucination).

CAREER STAGE CATEGORY
One of: "Student", "Early Professional", "Mid Career Pivot", "Job Seeker".
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

# ---------------------------------------------------------------------------
# MISSING FIELD SUGGESTIONS
# ---------------------------------------------------------------------------

MISSING_FIELD_SUGGESTIONS_PROMPT = (
    "You are an AI assistant specialized in analyzing CV/resume data to suggest missing or weak content. "
    "Analyze the provided CV Context and identify relevant professional suggestions for ALL fields listed in 'Missing Fields'.\n\n"
    "CV Context:\n{context_str}\n\n"
    "Missing Fields: {missing_fields}\n\n"
    "**CRITICAL RESPONSE FORMAT INSTRUCTIONS**\n"
    "1. **Respond ONLY in valid JSON.**\n"
    "2. **You MUST include a key for every field listed in 'Missing Fields'.** Use the exact key names (e.g., 'SoftSkills', 'Certifications').\n"
    "3. **Each value MUST be a JSON array of strings.**\n"
    "4. **Format Reference for Certifications:** For 'Certifications', format each suggestion as a single string: "
    "'Certification Name – Issuing Organization'. Example: 'PMP – PMI', 'AWS Certified Developer – Amazon', or 'CSIR-UGC NET JRF - NTA'.\n"
    "5. **Format Reference for Skills:** For 'SoftSkills' and 'HardSkills', provide single-word or short-phrase skills. "
    "Example: 'Python', 'Leadership', 'Data Analysis'."
)

# ---------------------------------------------------------------------------
# JOB ATTRIBUTE OPTIONS (shared by with-CV and without-CV flows)
# ---------------------------------------------------------------------------

JOB_ATTRIBUTE_OPTIONS_PROMPT = (
    "Generate focused, high-quality multiple-choice options based on the user's professional background and "
    "the intent of the question.\n\n"
    "Generate options based on the content of the question, ensuring they introduce new elements not already "
    "included in the resume/CV but relatable to the job title.\n\n"
    "CONTEXT SUMMARY:\n"
    "{context_str}\n\n"
    "QUESTION:\n"
    "{question_text}\n\n"
    "PARAMETERS:\n"
    "{parameters}\n\n"
    "OUTPUT FORMAT (STRICT JSON):\n"
    "{{\n"
    "  \"options\": [\"Option 1\", \"Option 2\", ...]\n"
    "}}\n\n"
    "REQUIREMENTS:\n"
    "- Provide EXACTLY {option_count} options.\n"
    "- Options must be short, clear (2–5 words), and directly related to the parameters and the question.\n"
    "- Each option must start with a capital letter.\n"
    "- No numbering, bullets, special symbols, or prefixes.\n"
    "- Avoid generic, vague, or repetitive wording.\n"
)

JOB_ATTRIBUTE_OPTIONS_WITHOUT_CV_PROMPT = (
    "Generate focused, high-quality multiple-choice options based on the user's professional background and "
    "the intent of the question.\n\n"
    "Generate options based on the content of the question, ensuring they introduce new elements not already "
    "included in the resume/CV but relatable to the job title.\n\n"
    "Audience Type: {audience_type}\n\n"
    "Missing CV Context:\n"
    "{context_str}\n\n"
    "QUESTION:\n"
    "{question_text}\n\n"
    "OUTPUT FORMAT (STRICT JSON):\n"
    "{{\n"
    "  \"options\": [\"Option 1\", \"Option 2\", ...]\n"
    "}}\n\n"
    "REQUIREMENTS:\n"
    "- Provide EXACTLY {option_count} concise, distinct options.\n"
    "- Keep each option 2–5 words long.\n"
    "- Avoid numbering or letters (no A/B/C/... prefixes).\n"
    "- Make sure they fit the question meaningfully.\n"
)

# ---------------------------------------------------------------------------
# ANCHOR OPTIONS — shared building blocks
# ---------------------------------------------------------------------------

STYLE_NOISE_POOL = [
    "use uncommon synonyms",
    "reorder ideas differently",
    "make phrasing more concise",
    "add creative wording twists",
    "slightly formal tone",
    "slightly casual tone",
    "shuffle activity order",
    "split compound ideas differently",
]

VARIATION_INSTRUCTIONS = (
    "- Ensure each execution produces DIFFERENT wording, even if the free-text is unchanged.\n"
    "- Randomly split, merge, or rephrase phrases so that no two runs look the same.\n"
    "- Introduce synonyms, shuffle word order, or shorten differently.\n"
    "- Do NOT invent anything that is not explicitly present in the free-text answers.\n"
    "- Apply these random variation rules: {style_noise}\n"
)

ANCHOR_OPTIONS_WITH_CV_PROMPT = (
    "You are an AI assistant generating short, career-related multiple-choice options.\n\n"
    "Generate options inspired by the user's Personal Interests, Hobbies, Exploration Interests, "
    "Motivation Drivers, Motivating Activities, and Achievements—without directly copying their context. "
    "Infer the user's underlying nature (e.g., creative, organized, exploratory) and tailor the options "
    "to reflect that. Ensure the options remain relevant to the user's job title and aligned with their "
    "inferred personality and interests.\n\n"
    "Also generate options based on the content of the question, ensuring they introduce new elements "
    "that are not already included in the resume/CV but relatable to the job title.\n\n"
    "STRICT KNOWLEDGE BASE (use ONLY this content, no invention):\n{context}\n\n"
    "Target parameters: {parameters}\n"
    "Question: {question_text}\n\n"
    "Instructions:\n"
    "- Generate EXACTLY {option_count} options.\n"
    "- Each option must rephrase or summarize ideas from the context.\n"
    "- Keep options SHORT (2–5 words).\n"
    "- Start each option with a CAPITAL letter.\n"
    "- No numbers, bullets, or labels.\n"
    "- All options must be distinct.\n"
    "{variation_instructions}"
    "- Variation key: {variation_key}\n\n"
    "Respond ONLY in JSON format:\n"
    "{{\n"
    "  \"options\": [\"<Short phrase 1>\", \"<Short phrase 2>\", ...]\n"
    "}}\n"
)

ANCHOR_OPTIONS_WITHOUT_CV_PROMPT = (
    "You are an AI assistant generating multiple-choice options for career-related questions.\n\n"
    "STRICT KNOWLEDGE BASE (rephrase ONLY from this, do not add new ideas):\n{context}\n\n"
    "Target sub-parameters: {parameters}\n"
    "Question: {question_text}\n\n"
    "Instructions:\n"
    "- Generate EXACTLY {option_count} short options.\n"
    "- Each option must be a direct rephrasing, splitting, or summarizing of the free-text answers.\n"
    "- DO NOT invent anything that is not explicitly present in the free-text answers.\n"
    "- Keep each option SHORT (2–5 words).\n"
    "{variation_instructions}"
    "- Variation key (for uniqueness): {variation_key}\n\n"
    "Respond ONLY in JSON format:\n"
    "{{\n"
    "  \"options\": [\n"
    "{option_placeholders}"
    "\n  ]\n"
    "}}"
)

# ---------------------------------------------------------------------------
# SUMMARY / KEYWORD EXTRACTION (router.py /summary/model)
# ---------------------------------------------------------------------------

SUMMARY_EXTRACTION_PROMPT = """\
You are a precise JSON extractor. Your task is to extract the **most relevant and concise keywords or phrases** from a structured resume JSON.

Requirements:
1. For each field, provide a **single short keyword or catchy phrase** (max 3 words).
2. Prefer **impactful, buzzword-style keywords** that can stand alone.
3. **DO NOT enforce uniqueness** across fields. Provide the best keyword for each field, even if it is similar to another.
4. If a field is missing or contains "Not specified", output "Not specified" (except for Hobbies, which outputs []).
5. The output must strictly follow the provided JSON structure.

[... Rest of the prompt structure and groupings remain the same ...]

**Output format:** Provide a **single JSON object** with exactly this structure:

{{
  "Talent attributes": {{
    "Core Code": {{
      "Core Tasks": "",
      "Supplementary Tasks": "",
      "Hot Technologies": "",
      "Functional Skills": "",
      "Skills": ""
    }},
    "DNA of work": {{
      "Work Activities": "",
      "Work Values": "",
      "Work Styles": "",
      "Abilities": ""
    }},
    "Interest Compass": {{
      "Career Interest Areas": "",
      "Knowledge": "",
      "Emerging Tasks": ""
    }},
    "Upskills Unlocked": {{
      "Newly Acquired Skills": "",
      "Emerging Tech Awareness": ""
    }}
  }},
  "Anchor attributes": {{
    "Passion Palette": {{
      "Hobbies": [],
      "Personal Interests": "",
      "Motivating Activities": "",
      "Social Cause": "",
      "Cultural Exposure": "",
      "Volunteering": ""
    }},
    "Drives You": {{
      "Motivation Drivers": "",
      "Competency": "",
      "Learning Agility": "",
      "Cognitive Preferences": "",
      "Creative Inclinations": ""
    }},
    "Rooted In You": {{
      "Achievements": "",
      "Life Skills": "",
      "Behavioural Skills": "",
      "Organizational Skills": "",
      "Personality Traits": ""
    }},
    "Moves you forward": {{
      "Exploration Interest": "",
      "Future Study Intent": ""
    }}
  }}
}}

**Instructions:**
Review each field in the input JSON.
Extract the **most relevant item** per field.
Convert it into a **short, buzzword-style phrase**.
Input JSON:
{resume_json}\
"""


def build_summary_extraction_prompt(parsed_resume: dict) -> str:
    return SUMMARY_EXTRACTION_PROMPT.format(resume_json=json.dumps(parsed_resume))
