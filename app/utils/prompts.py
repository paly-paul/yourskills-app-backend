"""
Centralized prompt constants for all Gemini LLM calls.

Every prompt template used across cv_extractor.py and router.py lives here.
Dynamic values are injected via str.format() or f-string at call sites.
"""

import json

# ---------------------------------------------------------------------------
# CV EXTRACTION
# ---------------------------------------------------------------------------

# The instructions are kept minimal; the JSON schema IS the spec.
# ~200 instruction tokens + ~480 schema tokens = ~680 total (was 1082).
CV_EXTRACTION_PROMPT = """\
Extract structured resume data into the JSON schema below. Return ONLY valid JSON.

RULES:
- Industry: exactly ONE, based on most recent 1-2 roles.
- Domain: exactly ONE functional expertise (e.g. HRBP, L&D, PMO).
- HardSkills: max 10. SoftSkills: max 5. Tools: relevant only. Deduplicate.
- Certifications: keep originals if present. If NONE exist, generate 3 realistic ones ONLY in LLM_Generated_Certificates.
- Auto-fill LLM_Generated_Technical_Skills, LLM_Generated_Soft_Skills, LLM_Generated_Certificates ONLY when originals are empty.
- Summary: 2-3 lines covering role, key skills, education, domain+industry.
- ProfileSnapshot: one line summarizing role+experience+core capability.
- ExperienceLevel: one of Fresher|Junior|Mid-Level|Senior|Lead|Manager|Senior Manager|Director|Senior Director|Vice President|Senior Vice President|C-Level Executive|Head / Department Head|Founder / Co-Founder|Not specified.
- "Know about yourself" > "Career stage category": one of Student|Early Professional|Mid Career Pivot|Job Seeker.
- YearsOfExperience: calculate from dates if possible.
- Missing fields: "Not specified". No hallucination. No markdown.

JSON SCHEMA:
{
  "Name": "", "DOB": "", "Email": "", "Phone": "", "Address": "", "LinkedIn": "",
  "Summary": "",
  "Skills": {"HardSkills": [], "SoftSkills": [], "Tools": []},
  "WorkExperience": [{"Company": "", "Role": "", "Duration": "", "Description": ""}],
  "Education": [{"Degree": "", "Institution": "", "Grade": "", "Year": ""}],
  "Certifications": [{"Name": "", "Issuer": "", "Year": ""}],
  "Interships": [{"Title": "", "Description": ""}],
  "Projects": [{"Title": "", "Description": ""}],
  "Languages": [{"Language": "", "Proficiency": ""}],
  "Awards": [{"Title": "", "Issuer": "", "Year": ""}],
  "VolunteerExperience": [{"Organization": "", "Role": "", "Duration": "", "Description": ""}],
  "Hobbies": [],
  "OtherSections": [{"Title": "", "Description": ""}],
  "YearsOfExperience": 0.0,
  "Talent Information": {
    "Core Tasks": "", "Supplementary Tasks": "", "Emerging Tasks": "",
    "Knowledge": "", "Skills": "", "Abilities": "",
    "Work activities": "", "Work styles": "", "Work values": "",
    "Technical Skills": "", "Hot Technologies": "", "Soft Skills": "",
    "Functional Skills": "",
    "Certifications": [{"Name": "", "Provider": "", "Year": ""}],
    "Salary grades": "", "Career Objective": "", "Career Interest Areas": ""
  },
  "Anchor Attributes": {
    "Achievements": "", "Behavioral Skills": "", "Interests": "",
    "Competency": "", "Cognitive Preferences": "", "Creative Inclinations": "",
    "Exploration Interest": "", "Future study intent": "", "Cultural Exposure": "",
    "Emerging Tech Awareness": "", "Hobbies": "", "Learning Agility": "",
    "Life Skills": "", "Motivation Drivers": "", "Motivating Activities": "",
    "Newly Acquired Skills": "", "Organizational Skills": "",
    "Personal Interests": "", "Social Causes": "", "Volunteering": "",
    "Personality Traits": ""
  },
  "Know about yourself": {"Inferred Persona Insights": "", "Career stage category": ""},
  "Domain": "", "Industry": "", "ProfileSnapshot": "", "ExperienceLevel": "",
  "AllCompanies": [], "AllRoles": [],
  "LLM_Generated_Certificates": [],
  "LLM_Generated_Technical_Skills": [],
  "LLM_Generated_Soft_Skills": []
}
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
Extract one buzzword-style keyword (max 3 words) per field from the resume JSON. Return ONLY valid JSON.

RULES:
- Missing or "Not specified" fields → "Not specified" (Hobbies → []).
- Duplicates across fields are OK. No markdown.

JSON SCHEMA:
{{"Talent attributes": {{"Core Code": {{"Core Tasks":"","Supplementary Tasks":"","Hot Technologies":"","Functional Skills":"","Skills":""}}, "DNA of work": {{"Work Activities":"","Work Values":"","Work Styles":"","Abilities":""}}, "Interest Compass": {{"Career Interest Areas":"","Knowledge":"","Emerging Tasks":""}}, "Upskills Unlocked": {{"Newly Acquired Skills":"","Emerging Tech Awareness":""}}}}, "Anchor attributes": {{"Passion Palette": {{"Hobbies":[],"Personal Interests":"","Motivating Activities":"","Social Cause":"","Cultural Exposure":"","Volunteering":""}}, "Drives You": {{"Motivation Drivers":"","Competency":"","Learning Agility":"","Cognitive Preferences":"","Creative Inclinations":""}}, "Rooted In You": {{"Achievements":"","Life Skills":"","Behavioural Skills":"","Organizational Skills":"","Personality Traits":""}}, "Moves you forward": {{"Exploration Interest":"","Future Study Intent":""}}}}}}

Input JSON:
{resume_json}\
"""


def build_summary_extraction_prompt(parsed_resume: dict) -> str:
    return SUMMARY_EXTRACTION_PROMPT.format(resume_json=json.dumps(parsed_resume))
