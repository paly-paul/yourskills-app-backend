import os
import json
import re
import warnings
import logging
from typing import Dict, Any, List

# External Dependencies
import google.generativeai as genai
import pandas as pd
from rapidfuzz import fuzz
from dotenv import load_dotenv

# --- Silence gRPC & Abseil Warnings (Clean Console Output) ---
os.environ.update({
    "GRPC_VERBOSITY": "ERROR",
    "GRPC_CPP_VERBOSITY": "ERROR",
    "GRPC_TRACE": "none",
})
logging.getLogger("absl").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", category=UserWarning)

# --- T5/LoRA Dependencies (Optional, if available) ---
try:
    import torch
    from transformers import T5Tokenizer, T5ForConditionalGeneration

    # Load .env
    load_dotenv()

    # Configure Gemini API key
    GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not GEMINI_API_KEY:
        GEMINI_API_KEY = "AIzaSyABfTlImtxScyj41CTyjsp9pFZ_1MZvyE0"
        print("⚠️ WARNING: Using placeholder/unverified API key. Please set GOOGLE_API_KEY in .env.")

    genai.configure(api_key=GEMINI_API_KEY)

    MODEL_DIR = "output_t5_lora-3"
    DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    print(f"Loading T5 Model from {MODEL_DIR} on device {DEVICE}...")
    T5_TOKENIZER = T5Tokenizer.from_pretrained(MODEL_DIR, legacy=False)
    T5_MODEL = T5ForConditionalGeneration.from_pretrained(MODEL_DIR).to(DEVICE)
    print("T5 Model loaded successfully.")
    T5_AVAILABLE = True

except (ImportError, ValueError, FileNotFoundError) as e:
    print(f"--- ERROR: T5/Torch setup failed. ---\n{e}")
    T5_TOKENIZER = None
    T5_MODEL = None
    DEVICE = "cpu"
    T5_AVAILABLE = False



# --- CONFIGURATION & FILE PATHS ---

# NOTE: Update this path to your actual resume file
#FILE_PATH = r"resume_data/For demo/Rocky Sasmal_Lowes Jun'23.pdf" 
#FILE_PATH = r"resume_data/For demo/Paly_resume1.pdf"
FILE_PATH=r"resume_data/candata_resumes/pragya.pdf"

OUTPUT_JSON_FINAL = "merged_output_4.json"
OUTPUT_EXCEL_FINAL = "merged_output_4.xlsx"

# Gemini Model Configuration
GEMINI_MODEL_NAME = "gemini-2.5-pro"
GENERATION_CONFIG_JSON = genai.types.GenerationConfig(
    response_mime_type="application/json",
    temperature=0.0
)
GENERATION_CONFIG_TEXT = genai.types.GenerationConfig(
    temperature=0.0
)

# --- COMMON FIELD LISTS (From Model-1 & Model-2) ---

TALENT_FIELDS = [
    "Education", "Experience", "Internships", "Projects", "Core Tasks", "Supplementary Tasks", "Emerging Tasks",
    "Knowledge", "Skills", "Abilities", "Work activities", "Work styles", "Work values",
    "Technical Skills", "Hot Technologies", "Soft Skills", "Functional Skills",
    "Certifications", "Salary grades", "Career Objective", "Career Interest Areas"
]

ANCHOR_FIELDS = [
    "Achievements", "Behavioral Skills", "Interests", "Competency", "Cognitive Preferences", "Creative Inclinations",
    "Exploration Interest", "Future study intent", "Cultural Exposure", "Emerging Tech Awareness",
    "Hobbies", "Learning Agility", "Life Skills", "Motivation Drivers", "Motivating Activities",
    "Newly Acquired Skills", "Organizational Skills", "Personal Interests", "Social Causes", "Volunteering",
    "Personality Traits"
]

# Cache for skills retrieved from Gemini to avoid redundant API calls
SKILLS_CACHE: Dict[str, set] = {}
# Cache for Model-2 predicted industries
INDUSTRY_CACHE: List[str] = []

# --- UTILITY FUNCTIONS (COMBINED & REFINED) ---

def safe_str(val):
    """Safely converts complex types to string for LLM/T5 input."""
    if isinstance(val, str):
        return val
    elif isinstance(val, dict):
        return json.dumps(val)
    elif isinstance(val, list):
        return ", ".join([safe_str(item) for item in val])
    else:
        return str(val)

def clean_value(value):
    if not value or value == "Not specified":
        return ""
    if isinstance(value, str):
        return ' '.join(value.replace(',', ' ').split())
    elif isinstance(value, list):
        return ' '.join(map(str, value))
    return str(value)

def clean_t5_output(t5_output_text):
    jobs = []
    # Split multiple jobs if they are separated by |
    for block in t5_output_text.split('|'):
        job = {}
        # Extract values using regex
        job_title_match = re.search(r'Job Title:\s*(.+)', block)
        sector_match = re.search(r'Sector:\s*(.+)', block)
        sub_sector_match = re.search(r'Sub-Sector:\s*(.+)', block)
        industry_match = re.search(r'Industry:\s*(.+)', block)

        if job_title_match:
            job['Job Title'] = job_title_match.group(1).strip()
        if sector_match:
            job['Sector'] = sector_match.group(1).strip()
        if sub_sector_match:
            job['Sub-Sector'] = sub_sector_match.group(1).strip()
        if industry_match:
            job['Industry'] = industry_match.group(1).strip()

        if job:  # Only append if we found at least one field
            jobs.append(job)
    return jobs

def get_managerial_level(job_title):
    if not job_title or job_title == "Not specified":
        return "Not specified"
    prompt_managerial = f"""
    You are an expert career analyst. Classify the following job title into one of these seven managerial levels:
    - C-suite
    - VP (Vice President)
    - Head
    - Director
    - Manager
    - Senior
    - Entry

    Job Title: {job_title}

    Provide your answer in a structured JSON object with one key:
    1. "managerial_level": The classification you chose.
    """
    gemini_model = genai.GenerativeModel("gemini-2.5-pro")
    try:
        response = gemini_model.generate_content(
            contents=prompt_managerial,
            generation_config=genai.types.GenerationConfig(
                response_mime_type="application/json",
                temperature=0.0
            )
        )
        classification = json.loads(response.text)
        return classification.get("managerial_level", "Not specified")
    except Exception as e:
        print(f"Error during Gemini classification for '{job_title}': {e}")
        return "Not specified"

def normalize_skill(skill):
    """Normalizes a skill string for fuzzy matching."""
    skill = safe_str(skill).lower().strip()
    skill = re.sub(r"[^\w\s]", " ", skill)
    skill = ' '.join(skill.split())
    return skill

def is_valid_industry(industry):
    """Simple validation for T5-predicted industry text."""
    return 1 <= len(industry.split()) <= 6 and not any(char.isdigit() for char in industry)

def compute_match_percentage(matched_count, required_count):
    if not required_count:
        return 0.0
    return round((matched_count / required_count) * 100, 2)

def scale_single_pct(pct, scale=1.0, cap=100.0):
    return round(min(pct * scale, cap), 2)

def scaled_match_percentage(talent_pct, anchor_pct, scale=1.0, cap=100.0):
    # Apply 95/5 weighting as per the original Model-1 prompt context for a single score
    avg_pct = ((talent_pct or 0.0) * 0.95 + (anchor_pct or 0.0) * 0.05) 
    scaled_pct = avg_pct * scale
    capped_pct = min(scaled_pct, cap)
    return round(capped_pct, 2)

def fuzzy_match_skills(candidate_skills, required_skills, threshold=65):
    """Performs fuzzy matching between two sets of skills."""
    matched, missing = set(), set()
    for req in required_skills:
        req_norm = normalize_skill(req)
        found = False
        for cand in candidate_skills:
            cand_norm = normalize_skill(cand)
            if fuzz.token_set_ratio(req_norm, cand_norm) >= threshold:
                # Add the original required skill back to the matched set
                matched.add(req)
                found = True
                break
        if not found:
            missing.add(req)
    return matched, missing

def extract_candidate_skills(data_dict, fields_list):
    """Extracts and normalizes all skills/values from specified resume fields."""
    skills = []
    for field in fields_list:
        val = data_dict.get(field, "Not specified")
        if val and val != "Not specified":
            if isinstance(val, list):
                skills.extend([safe_str(item).strip() for item in val if safe_str(item).strip()])
            else:
                skills.extend([s.strip() for s in safe_str(val).split(",") if s.strip()])
                
    # Return the normalized set of skills for matching
    return set([normalize_skill(s) for s in skills if s])

# --- GEMINI/T5 INTERACTION FUNCTIONS (COMMON) ---

def run_t5_inference(input_text, max_length=128, **kwargs):
    """Runs inference on the T5 model if available."""
    if not T5_AVAILABLE:
        return "Job Title: Not specified | Job Family: Not specified | Sector: Not specified | Sub-Sector: Not specified | Industry: Not specified"

    # Original T5 model logic from your Model-1 code
    T5_MODEL.eval()
    T5_MODEL.config.use_cache = True
    with torch.no_grad():
        inputs = T5_TOKENIZER(
            input_text, return_tensors="pt", truncation=True, padding=True, max_length=512
        ).to(DEVICE)
        outputs = T5_MODEL.generate(
            input_ids=inputs["input_ids"],
            attention_mask=inputs["attention_mask"],
            max_length=max_length,
            num_beams=kwargs.get("num_beams", 4),
            num_return_sequences=kwargs.get("num_return_sequences", 1),
            early_stopping=True,
            do_sample=kwargs.get("do_sample", False),
            top_k=kwargs.get("top_k", None),
            top_p=kwargs.get("top_p", None),
        )
        decoded = [T5_TOKENIZER.decode(o, skip_special_tokens=True) for o in outputs]
        return decoded if decoded else ["Not specified"]

def parse_t5_job_output(output_text, single=False):
    jobs = []
    for block in output_text.split('|'):
        block = block.strip()
        if "job title" in block.lower():
            fields = [f.strip() for f in block.split('|')]
            job = {}
            for f in fields:
                key_val = f.split(':', 1)
                if len(key_val) == 2:
                    job[key_val[0].strip()] = key_val[1].strip()
            if job:
                jobs.append(job)
    if single:
        return jobs[0] if jobs else {}
    return jobs

def get_required_skills_from_gemini(job_title: str, skill_type: str) -> set:
    """Uses Gemini to get required skills for a job title, with caching."""
    if not job_title or job_title == "Not specified":
        return set()
    
    cache_key = f"{job_title}_{skill_type}".lower()
    if cache_key in SKILLS_CACHE:
        return SKILLS_CACHE[cache_key]

    gemini_model = genai.GenerativeModel(GEMINI_MODEL_NAME)
    base_prompt = (f"List the top skills (technical, soft, hard, behavior, Experience) required for the job title: '{job_title}'. "
                   f"Respond with a comma-separated list of skills only. Use short, concise phrases.")
    
    # Original skill prompt logic from Model-1/Model-2
    if skill_type == 'talent':
        prompt = base_prompt + (
            " Focus on talent-related skills: technical (top 5), certifications (top 1), functional (top 1), career oriented (top 2), Core Tasks (top 3), Knowledge(top 1), Hot Technologies (top 2)."
        )
    elif skill_type == 'anchor':
        prompt = base_prompt + (
            " Focus on anchor-related skills: behavioral (top 2), Hobbies (top 1), Motivation Drivers (top 1), Newly Acquired Skills (top 1), Organizational Skills (top 1), Personal Interests (top 1)."
        )
    else:
        prompt = base_prompt
        
    try:
        response = gemini_model.generate_content(prompt, generation_config=GENERATION_CONFIG_TEXT)
        skills_text = response.text.strip()
        if not skills_text or "not specified" in skills_text.lower():
            skills = set()
        else:
            # Return original case for displaying matched skills
            skills = set([s.strip() for s in skills_text.split(',') if s.strip()])
    except Exception as e:
        print(f"Error fetching skills for {job_title}: {e}")
        skills = set()
        
    SKILLS_CACHE[cache_key] = skills
    return skills


# --- 1. RESUME PARSER LOGIC ---

def run_resume_parser() -> Dict[str, Any]:
    """Parses a PDF resume using Gemini and returns the structured data."""
    print("\n--- 1. RESUME PARSER STARTING ---")

    resume_parser_prompt = """
    You are an intelligent AI Resume Parser and Career Analyst trained to extract and enhance structured metadata from resumes to support hiring, upskilling, and AI-powered career recommendations.

    📌 Your task:
    Read the resume and return a structured JSON object with four main categories:
    1. Profile Information
    2. Talent Information
    3. Anchor Attributes
    4. Inferred Persona Insights: Know about yourself (Inferred Persona Insights (Need to explain with contextualixation, expecting what a person might
      have gained thorugh his education, experience, certifications, hobbies, activities etc. Should be slighly elaborated) + Career stage category)

    You must:
    ✅ Analyze all details related to **experience**, **certifications**, and **skills**.
    ✅ Provide **augmented information** — such as inferred job level, personality traits, skill clusters, and career potential — even if not explicitly mentioned.

    🔍 Instructions:
    - Extract the fields **exactly as listed**.
    - If a field is not found, return "Not specified".
    - Use your knowledge of industries and job roles to infer missing or unclear values.
    - Your response should be a **valid JSON object**. Do not include commentary or explanation.

    📂 Output JSON Format:
    {
      "Profile Information": {
        "Full Name": "", "DOB": "", "Gender": "", "Email ID": "", "Phone Number": "", 
        "Address": "", "Nationality": "", "Marital Status": "", "LinkedIn": "", 
        "Languages Known": ""
      },
      "Talent Information": {
        "Education": "", "Internships":"", "Projects":"", "Experience": "", 
        "Core Tasks": "", "Supplementary Tasks": "", "Emerging Tasks": "", "Knowledge": "", 
        "Skills": "", "Abilities": "", "Work activities": "", "Work styles": "", 
        "Work values": "", "Technical Skills": "", "Hot Technologies": "", 
        "Soft Skills": "", "Functional Skills": "", "Certifications": "", 
        "Salary grades": "", "Career Objective": "", "Career Interest Areas": "",
      },
      "Anchor Attributes": {
        "Achievements": "", "Behavioral Skills": "", "Interests": "", "Competency": "", 
        "Cognitive Preferences": "", "Creative Inclinations": "", "Exploration Interest": "", 
        "Future study intent": "", "Cultural Exposure": "", "Emerging Tech Awareness": "", 
        "Hobbies": "", "Learning Agility": "", "Life Skills": "", "Motivation Drivers": "", 
        "Motivating Activities": "", "Newly Acquired Skills": "", "Organizational Skills": "", 
        "Personal Interests": "", "Social Causes": "", "Volunteering": "", 
        "Personality Traits": ""
      },
      "Know about yourself": {
        "Inferred Persona Insights": "",
        "Career stage category": "Based on the extracted information — especially total work experience (in years) and any noticeable skill or employment gaps — classify the individual into one of the following stages: 1. Student, 2. Early Professional, 3. Mid Career Pivot, 4. Job Seeker. Prioritize in order: Job Seeker > Mid Career Pivot > Early Professional > Student."
      }
    }
    Respond ONLY with the structured JSON.
    """
    uploaded_file = None
    try:
        if not os.path.exists(FILE_PATH):
            raise FileNotFoundError(f"The file {FILE_PATH} was not found.")

        print(f"Uploading file: {FILE_PATH}...")
        uploaded_file = genai.upload_file(path=FILE_PATH, display_name="Resume PDF")

        gemini_model = genai.GenerativeModel(GEMINI_MODEL_NAME)
        print("Generating structured data from the document...")
        response = gemini_model.generate_content(
            contents=[uploaded_file, resume_parser_prompt],
            generation_config=GENERATION_CONFIG_JSON
        )

        # Robust JSON cleaning and loading
        raw_text = response.text.strip()
        json_start = raw_text.find('{')
        json_end = raw_text.rfind('}')
        if json_start != -1 and json_end != -1:
            json_text = raw_text[json_start:json_end+1]
        else:
            raise json.JSONDecodeError("Could not find valid JSON structure in response.", raw_text, 0)
        
        extracted_data = json.loads(json_text)
        print("Resume Parsing Complete.")
        return extracted_data

    except Exception as e:
        print(f"Resume Parsing Failed: {e}")
        return {}
    finally:
        # Cleanup uploaded file
        if uploaded_file:
            try:
                genai.delete_file(uploaded_file.id)  # safer
                print(f"Cleaned up uploaded file: {uploaded_file.id}")
            except Exception:
                pass



# --- 2. SUMMARY GENERATION LOGIC ---

def run_summary_generator(parsed_resume: Dict[str, Any]) -> Dict[str, Any]:
    """Generates a concise, keyword-based summary using Gemini."""
    print("\n--- 2. SUMMARY GENERATOR STARTING ---")

    if not parsed_resume:
        print("Skipping summary: No parsed data found.")
        return {"Summary Attributes": "Not generated"}

    # Define the fields to be extracted for the summary
    extraction_fields = {
        "Core Code": ["Core Tasks", "Supplementary Tasks", "Hot Technologies", "Functional Skills", "Skills"],
        "DNA of work": ["Work activities", "Work values", "Work styles", "Abilities"],
        "Interest Compass": ["Career Interest Areas", "Knowledge", "Emerging Tasks"],
        "Upskills Unlocked": ["Newly Acquired Skills", "Emerging Tech Awareness"],
        "Passion Palette": ["Hobbies", "Personal Interests", "Motivating Activities", "Social Causes", "Cultural Exposure", "Volunteering"],
        "Drives You": ["Motivation Drivers", "Competency", "Learning Agility", "Cognitive Preferences", "Creative Inclinations"],
        "Rooted In You": ["Achievements", "Life Skills", "Behavioral Skills", "Organizational Skills", "Personality Traits"],
        "Moves you forward": ["Exploration Interest", "Future study intent"]
    }
    
    # Prepare the input JSON (Original logic to pass the data structure)
    summary_input = {
        "Talent Information": {k: parsed_resume.get("Talent Information", {}).get(k, "Not specified") 
                               for group in ["Core Code", "DNA of work", "Interest Compass", "Upskills Unlocked"] 
                               for k in extraction_fields.get(group, [])},
        "Anchor Attributes": {k: parsed_resume.get("Anchor Attributes", {}).get(k, "Not specified")
                              for group in ["Passion Palette", "Drives You", "Rooted In You", "Moves you forward"] 
                              for k in extraction_fields.get(group, [])}
    }


    extract_prompt = f"""
    You are a JSON extractor.
    
    From the following structured resume JSON, extract the most relevant and concise keyword or phrase (max 3 words) for each specified field.

    Instructions:
    - **Uniqueness is mandatory**: Ensure every extracted keyword/phrase is unique across all fields. If a keyword is a duplicate, replace it with 'Unique keyword not found'.
    - **Conciseness**: Provide a single, short, catchy keyword or very concise phrase (max 3 words).
    - **Handle Missing Data**: If a field is missing or 'Not specified', use 'Not specified' (except for 'Hobbies', which should be an empty list []).
    - **Structure**: Output a single JSON object strictly following the required output format.
    
    Output JSON Format:
    {{
      "Talent attributes": {{
        "Core Code": {{ "Core Tasks": "", "Supplementary Tasks": "", "Hot Technologies": "", 
          "Functional Skills": "", "Skills": "" }},
        "DNA of work": {{ "Work activities": "", "Work values": "", "Work styles": "", "Abilities": "" }},
        "Interest Compass": {{ "Career Interest Areas": "", "Knowledge": "", "Emerging Tasks": "" }},
        "Upskills Unlocked": {{ "Newly Acquired Skills": "", "Emerging Tech Awareness": "" }}
      }},
      "Anchor attributes": {{
        "Passion Palette": {{ "Hobbies": [], "Personal Interests": "", "Motivating Activities": "", 
          "Social Causes": "", "Cultural Exposure": "", "Volunteering": "" }},
        "Drives You": {{ "Motivation Drivers": "", "Competency": "", "Learning Agility": "", 
          "Cognitive Preferences": "", "Creative Inclinations": "" }},
        "Rooted In You": {{ "Achievements": "", "Life Skills": "", "Behavioral Skills": "", 
          "Organizational Skills": "", "Personality Traits": "" }},
        "Moves you forward": {{ "Exploration Interest": "", "Future Study Intent": "" }}
      }}
    }}

    Input JSON to extract from: {json.dumps(summary_input)}
    """

    try:
        gemini_model = genai.GenerativeModel(GEMINI_MODEL_NAME)
        response = gemini_model.generate_content(
            contents=[extract_prompt],
            generation_config=GENERATION_CONFIG_JSON
        )
        
        # Post-processing for strict deduplication (Your original logic)
        extracted_data = json.loads(response.text)
        
        def deduplicate_keywords_recursive(data):
            seen = set()

            def process_value(value):
                nonlocal seen
                if isinstance(value, str):
                    val_lower = value.strip().lower()
                    if val_lower in ["not specified", ""]:
                        return value
                    if val_lower in seen:
                        return "Unique keyword not found"
                    seen.add(val_lower)
                    return value
                elif isinstance(value, list):
                    unique_list = []
                    for item in value:
                        item_lower = safe_str(item).strip().lower()
                        if item_lower in seen:
                            continue
                        seen.add(item_lower)
                        unique_list.append(item)
                    return unique_list
                return value

            if isinstance(data, dict):
                return {k: deduplicate_keywords_recursive(v) for k, v in data.items()}
            elif isinstance(data, list):
                return [deduplicate_keywords_recursive(item) for item in data]
            else:
                return process_value(data)
            
        final_summary = deduplicate_keywords_recursive(extracted_data)

        print("Summary Generation Complete.")
        return {"Summary": final_summary}

    except Exception as e:
        print(f"Summary Generation Failed: {e}")
        return {"Summary": {"Status": "Generation Failed", "Error": str(e)}}
global ALL_ALTERNATE_JOBS
#ALL_ALTERNATE_JOBS = []
ALL_ALTERNATE_JOBS: List[dict] = []

def generate_alternate_jobs(
    best_fit_job_title: str,
    industry: str,
    input_string: str,
    talent_info: dict,
    anchor_info: dict,
    max_alternates: int = 3
) -> list:
    global ALL_ALTERNATE_JOBS  # reference the global list
    alternate_jobs_list = []

    if not industry or industry.lower() == "not specified":
        print("Industry not specified. Skipping alternate job generation.")
        return alternate_jobs_list

    print(f"-> Generating up to {max_alternates} alternate jobs in industry: {industry}...")
    seen_titles = {best_fit_job_title.lower()} if best_fit_job_title else set()
    t5_input = (
        f"Suggest alternate jobs similar to '{best_fit_job_title}' in the {industry} industry. "
        f"Do not repeat any of these titles: {', '.join(seen_titles)}. "
        f"Resume Info: {input_string} "
        "Provide all fields: Job Title, Job Family, Sector, Sub-Sector, Industry. "
        "Format: Job Title: ... | Job Family: ... | Sector: ... | Sub-Sector: ... | Industry: ...\n"
        "Ensure Sub-Sector and Industry are not the same."
    )

    outputs = run_t5_inference(
        t5_input,
        max_length=512,
        do_sample=True,
        top_k=50,
        top_p=0.85,
        num_return_sequences=10,
        num_beams=15,
    )

    for job_alt_output in outputs:
        job_alt_str = job_alt_output if isinstance(job_alt_output, str) else str(job_alt_output[0])
        job_alt_list = parse_t5_job_output(job_alt_str)
        job_alt = job_alt_list[0] if job_alt_list else {}

        job_title_alt = job_alt.get("Job Title", "").strip()
        if not job_title_alt or job_title_alt.lower() in seen_titles:
            continue

        job_alt["Managerial Level"] = get_managerial_level(job_title_alt)
        job_alt.update(compute_match_metrics(job_title_alt, talent_info, anchor_info))

        alternate_jobs_list.append(job_alt)
        ALL_ALTERNATE_JOBS.append(job_alt)  # <-- append to global list
        seen_titles.add(job_title_alt.lower())

        if len(alternate_jobs_list) >= max_alternates:
            break

    print(f"Generated {len(alternate_jobs_list)} alternate jobs for {best_fit_job_title}.")
    return alternate_jobs_list

# --- 3. MODEL-1 LOGIC: BEST-FIT JOB & ALTERNATE JOBS ---
def run_model_1_best_fit(talent_info: Dict[str, Any], anchor_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    Predicts the single Best Fit Job, its Managerial Level, and suggests 3 Alternate Jobs
    using the T5 model and skill matching. Corrected version.
    """
    print("\n--- 3. MODEL-1 STARTING (Best Fit Job & Alternate Jobs) ---")
    
    if not T5_AVAILABLE:
        print("T5 model not available. Skipping Model-1.")
        return {
            "Model-1 Results": {
                "Best_Fit_Job": {},
                "Alternate_Jobs": []
            }
        }

    # --- Prepare T5 input string with Talent (95%) and Anchor (5%) weighting ---
    input_parts = []
    for field in TALENT_FIELDS:
        value = clean_value(talent_info.get(field, 'Not specified'))
        input_parts.append(f"{field} (weight: 0.95): {value}")
    for field in ANCHOR_FIELDS:
        value = clean_value(anchor_info.get(field, 'Not specified'))
        input_parts.append(f"{field} (weight: 0.05): {value}")
    input_string = " | ".join(input_parts)

    # --- T5 prompt for Best Fit Job ---
    job_prompt = (
        "Suggest one most suitable job title from a typical corporate hierarchy. "
        "You must provide all fields: Job Title, Job Family, Sector, Sub-Sector, Industry. "
        "Format: Job Title: ... | Job Family: ... | Sector: ... | Sub-Sector: ... | Industry: ...\n"
        "Ensure that Sub-Sector and Industry are not the same."
    )
    t5_input = job_prompt + " Resume Info: " + input_string

    # --- 3.2: Predict Best Fit Job ---
    predicted_output = run_t5_inference(t5_input, max_length=128, num_beams=5, do_sample=False)
    predicted_output_str = predicted_output[0] if isinstance(predicted_output, list) else predicted_output

    # --- Parse Best Fit Job ---
    best_fit_results_list = parse_t5_job_output(predicted_output_str)
    best_fit_results = best_fit_results_list[0] if best_fit_results_list else {}
    best_fit_job_title = best_fit_results.get("Job Title", "Not specified")

    best_fit_managerial_level = get_managerial_level(best_fit_job_title)
    best_fit_results["Managerial Level"] = best_fit_managerial_level

    # --- Compute skill match for Best Fit Job ---
    matched_data = compute_match_metrics(best_fit_job_title, talent_info, anchor_info)
    best_fit_results.update(matched_data)

    print(f"-> Best Fit Predicted: {best_fit_job_title}")

    # --- Generate Alternate Jobs ---
    industry = best_fit_results.get("Industry", "Not specified")
    alternate_jobs_list = []

    if industry != "Not specified":
        alternate_jobs_list = generate_alternate_jobs(
            best_fit_job_title,
            industry,
            input_string,
            talent_info,
            anchor_info,
            max_alternates=3
        )

    # --- Filter invalid or placeholder jobs ---
    alternate_jobs_list = [
        job for job in alternate_jobs_list
        if job.get("Job Title") and job["Job Title"].lower() != "not specified"
    ]
    print(f"Total alternate jobs generated globally: {len(ALL_ALTERNATE_JOBS)}")
    for job in ALL_ALTERNATE_JOBS:
        print(job.get("Job Title"), "-", job.get("Industry"))
    # --- Final Model-1 Output ---
    return {
        "Model-1 Results": {
            "Best_Fit_Job": best_fit_results,
            "Alternate_Jobs": alternate_jobs_list
        }
    }
    


# --- MODEL-2 LOGIC: INDUSTRY PREDICTION & JOB MATRIX ---
def run_model_2_job_matrix(parsed_data: dict) -> dict:
    """
    Predicts 5 most suitable industries and the best job title/match % within each
    using the T5 model and skill matching. Restored to previously working version.
    """
    print("\n--- 4. MODEL-2 STARTING (Industry Prediction & Job Matrix) ---")
    
    if not T5_AVAILABLE:
        return {"Model-2_Results": "T5 Model not loaded, skipping Model-2 analysis."}
        
    talent_info = parsed_data.get("Talent Information", {})
    anchor_info = parsed_data.get("Anchor Attributes", {})
    
    global INDUSTRY_CACHE
    if not INDUSTRY_CACHE:
        # Anchor attribute fields for industry prediction
        industry_anchor_attributes = [
            "Personal Interests", "Hobbies", "Exploration Interest", "Motivation Drivers",
            "Motivating Activities", "Achievements", "Creative Inclinations",
            "Organizational Skills", "Competency", "Personality Traits",
            "Social Causes", "Volunteering", "Cultural Exposure",
            "Newly Acquired Skills", "Emerging Tech Awareness", "Future study intent"
        ]

        combined_text_industry = " ".join(
            str(clean_value(anchor_info.get(f, ""))) 
            for f in industry_anchor_attributes 
            if anchor_info.get(f, "") != "Not specified"
        ) or "Not specified"
        
        try:
            # Previous working T5 industry prediction
            t5_industries_prompt = (
                f"Predict 5 most suitable industries for a person based on this text: {combined_text_industry}. "
                "Respond only in this format: Industry: <industry1> | Industry: <industry2> | Industry: <industry3> | Industry: <industry4> | Industry: <industry5>"
            )
            t5_industries_output = run_t5_inference(t5_industries_prompt, max_length=100)
            t5_industries_output_text = " ".join(t5_industries_output)  # Join list into a single string
            print("Raw T5 industries output:", t5_industries_output_text)

            predicted_industries = extract_industries_from_t5_output(t5_industries_output_text)
            if not predicted_industries:
                print("No valid industries extracted, falling back to Gemini.")

        except Exception:
            # Gemini fallback
            gemini_model = genai.GenerativeModel(GEMINI_MODEL_NAME)
            gemini_industries_prompt = (
                f"Based on the resume, suggest 5 relevant industries for: {combined_text_industry}. "
                "Respond with a comma-separated list of industries only."
            )
            response_text = gemini_model.generate_content(
                gemini_industries_prompt, generation_config=GENERATION_CONFIG_TEXT
            ).text.strip()
            # Support both comma or pipe separated lists
            predicted_industries = re.split(r'[|,;]', response_text)
            predicted_industries = [i.strip() for i in predicted_industries if i.strip()]
            predicted_industries = [i for i in predicted_industries if is_valid_industry(i)][:5]

        INDUSTRY_CACHE = [ind for ind in predicted_industries if ind.lower() != "not specified" and ind]
        
        print(f"-> Predicted Industries: {INDUSTRY_CACHE}")

    # Prepare T5 input text for job suggestion, inverse weighting of Anchor and Talent
    values_talent = [clean_value(talent_info.get(f, 'Not specified')) for f in TALENT_FIELDS]
    values_anchor = [clean_value(anchor_info.get(f, 'Not specified')) for f in ANCHOR_FIELDS]
    combined_text_jobs = " ".join(values_anchor * 19 + values_talent * 1)  # ~95:5 ratio favoring Anchor

    job_predictions_matrix = []
    for industry in INDUSTRY_CACHE:
        job_prompt = (
            f"Suggest one most suitable job title for a person with the following attributes in the {industry} industry: {combined_text_jobs}. "
            "You must provide all of the following fields: Job Title, Job Family, Sector, Sub-Sector, and Industry. "
            "Format: Job Title: ... | Job Family: ... | Sector: ... | Sub-Sector: ... | Industry: ..."
        )
        
        job_output = run_t5_inference(job_prompt, max_length=128, num_beams=5, do_sample=False)
        job_output_str = job_output[0] if isinstance(job_output, list) else job_output
        job_parsed = parse_t5_job_output(job_output_str)
        # Unpack first job dict safely
        job_details = job_parsed[0] if isinstance(job_parsed, list) and job_parsed else {}
        job_details["Industry"] = industry
        job_title = job_details.get("Job Title", "Not specified")
        job_details["Managerial Level"] = get_managerial_level(job_title)
        # Managerial level
        managerial_level = get_managerial_level(job_title)
        job_details["Managerial Level"] = managerial_level
        # Skill Match computation
        job_details.update(compute_match_metrics(job_title, talent_info, anchor_info))
        job_predictions_matrix.append(job_details)
    
    print(f"-> Generated {len(job_predictions_matrix)} job predictions for predicted industries.")
    
    return {
        "Model-2_Results": {
            "Job_Prediction_Matrix": job_predictions_matrix
        }
    }

def extract_industries_from_t5_output(text):
    industries = []
    for line in text.split('|'):
        if "industry" in line.lower():
            match = re.search(r"Industry:\s*([^|]+)", line, re.IGNORECASE)
            if match:
                industry = match.group(1).strip()
                if is_valid_industry(industry) and industry not in industries:
                    industries.append(industry)
    return industries[:5]  # take first 5


# --- SKILL MATCHING LOGIC (Used by Model-1 and Model-2) ---
def compute_match_metrics(job_title: str, talent_info: Dict[str, Any], anchor_info: Dict[str, Any]) -> Dict[str, Any]:
    """Computes Talent, Anchor, and Overall skill match percentages."""
    
    if job_title == "Not specified":
        return {
            "Talent Match %": 0.0, "Anchor Match %": 0.0, "Overall Match %": 0.0,
            "Matched Skills": [], "Missing Skills": []
        }
    
    # 1. Get Candidate Skills (Normalized for matching)
    candidate_talent_skills_norm = extract_candidate_skills(talent_info, TALENT_FIELDS)
    candidate_anchor_skills_norm = extract_candidate_skills(anchor_info, ANCHOR_FIELDS)

    # 2. Get Required Skills (Original case for reporting, set of strings)
    required_skills_talent_original = get_required_skills_from_gemini(job_title, skill_type='talent')
    required_skills_anchor_original = get_required_skills_from_gemini(job_title, skill_type='anchor')

    # --- This is where your snippet would go ---
    required_talent_norm = set(normalize_skill(s) for s in required_skills_talent_original)
    matched_talent, missing_talent = fuzzy_match_skills(candidate_talent_skills_norm, required_talent_norm)

    required_anchor_norm = set(normalize_skill(s) for s in required_skills_anchor_original)
    matched_anchor, missing_anchor = fuzzy_match_skills(candidate_anchor_skills_norm, required_anchor_norm)

    # 3. Calculate Match Percentages
    talent_match_pct = scale_single_pct(compute_match_percentage(len(matched_talent), len(required_skills_talent_original)))
    anchor_match_pct = scale_single_pct(compute_match_percentage(len(matched_anchor), len(required_skills_anchor_original)))
    overall_match_pct = scaled_match_percentage(talent_match_pct, anchor_match_pct, scale=1.0)

    # 4. Combine Matched/Missing Skills (ensure no duplicates)
    combined_matched = sorted(list(matched_talent.union(matched_anchor)))
    matched_lower = {s.lower() for s in combined_matched}
    combined_missing = sorted(list({s for s in missing_talent.union(missing_anchor) if s.lower() not in matched_lower}))

    return {
        "Talent Match %": talent_match_pct,
        "Anchor Match %": anchor_match_pct,
        "Overall Match %": overall_match_pct,
        "Matched Skills": combined_matched,
        "Missing Skills": combined_missing
    }

# --- 5 & 6. FINAL AGGREGATION AND PERSISTENCE ---

def save_to_excel(data: dict, excel_path: str):
    """Saves full parsed resume, summary, and model results into one Excel sheet with labeled sections."""
    import pandas as pd
    print(f"\n--- Saving full data to Excel: {excel_path} ---")

    # Helper: recursive flatten dict with list flattening
    def flatten_dict(d, parent_key='', sep=' - '):
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(flatten_dict(v, new_key, sep=sep))
            elif isinstance(v, list):
                list_val = ', '.join(str(i) for i in v)
                items.append((new_key, list_val))
            else:
                items.append((new_key, v))
        return items

    # Helper: flatten job record for tabular output
    def flatten_job_record(record, job_type):
        matched = ', '.join(record.get('Matched Skills', [])) if isinstance(record.get('Matched Skills'), (list, set)) else record.get('Matched Skills', '')
        missing = ', '.join(record.get('Missing Skills', [])) if isinstance(record.get('Missing Skills'), (list, set)) else record.get('Missing Skills', '')
        return [
            job_type,
            record.get("Job Title", ""),
            record.get("Managerial Level", ""),
            record.get("Job Family", ""),
            record.get("Sector", ""),
            record.get("Sub-Sector", ""),
            record.get("Industry", ""),
            record.get("Talent Match %", ""),
            record.get("Anchor Match %", ""),
            record.get("Overall Match %", ""),
            matched,
            missing
        ]

    rows = []
    # Add header row for job prediction tables
    header = [
        'Type', 'Job Title', 'Managerial Level', 'Job Family', 'Sector', 'Sub-Sector',
        'Industry', 'Talent Match %', 'Anchor Match %',
        'Overall Match %', 'Matched Skills', 'Missing Skills'
    ]

    # --- 1. Full Resume Parsed Data ---
    rows.append(["--- Full Resume Parsed Data ---", ""])
    resume_data = data.get("Resume_Parsed_Data", {})
    for key, val in flatten_dict(resume_data):
        rows.append([key, val])
    rows.append(["", ""])

    # --- 2. Summary Keywords ---
    rows.append(["--- Summary Keywords ---", ""])
    summary_data = data.get("Summary", {})
    for group_key, group_val in summary_data.items():
        for field_key, field_val in group_val.items():
            for k, v in field_val.items():
                rows.append([f"{group_key} - {field_key} - {k}", v])
    rows.append(["", ""])


    # Model-1 Job Predictions section header
    rows.append(["--- Model-1 Job Predictions ---", ""])

    # Extract Model-1 data
    model_1_data = data.get("Model-1_Results", {})
    best_fit = model_1_data.get("Best_Fit_Job", {})
    alternates = model_1_data.get("Alternate_Jobs", [])
    
    # Append header row for Model-1 jobs
    rows.append(header)

    # Append Best Fit Job if available
    if best_fit:
        rows.append(flatten_job_record(best_fit, "Best Fit Job"))

    # Append Alternate Jobs
    for i, alt_job in enumerate(alternates, 1):
        rows.append(flatten_job_record(alt_job, f"Alternate Job {i}"))

    # Blank line for spacing
    rows.append(["", ""])

    # Append Model-2 Job Prediction Matrix header
    rows.append(["--- Model-2 Job Prediction Matrix ---", ""])

    # Extract Model-2 results
    model_2_data = data.get("Model-2_Results", {})
    matrix = model_2_data.get("Job_Prediction_Matrix", [])

    # Append header row for Model-2 jobs
    rows.append(header)

    # Append each job record in the matrix
    for record in matrix:
        rows.append(flatten_job_record(record, "Model-2 Job"))

    # Normalize all rows to have the same number of columns
    max_cols = max(len(row) for row in rows)
    for idx, row in enumerate(rows):
        if len(row) < max_cols:
            rows[idx] = row + [""] * (max_cols - len(row))

    # Convert to DataFrame without header (already in data)
    df = pd.DataFrame(rows)

    # Save to Excel
    with pd.ExcelWriter(excel_path, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='Complete_Output', index=False, header=False)

    print("Full JSON data saved to Excel successfully.")

def main_processor():
    """Main execution function to run all models and save outputs."""
    final_output: Dict[str, Any] = {}

    # 1. Resume Parsing
    parsed_data = run_resume_parser()
    if not parsed_data:
        print("Fatal error: Resume parsing failed. Exiting.")
        return
    final_output["Resume_Parsed_Data"] = parsed_data

    # 2. Summary Generation
    summary_data = run_summary_generator(parsed_data)
    final_output["Summary"] = summary_data.get("Summary", {})

    # 3. Model-1: Best Fit Job + Alternate Jobs
    talent_info = parsed_data.get("Talent Information", {})
    anchor_info = parsed_data.get("Anchor Attributes", {})
    model_1_results = run_model_1_best_fit(talent_info, anchor_info)
    final_output.update(model_1_results)


    # 4. Model-2: Job Matrix Prediction
    model_2_results = run_model_2_job_matrix(parsed_data)
    final_output.update(model_2_results)

    # 5. Save full result to JSON
    with open(OUTPUT_JSON_FINAL, "w", encoding="utf-8") as f:
        json.dump(final_output, f, ensure_ascii=False, indent=2)
    print(f"Full output saved to JSON: {OUTPUT_JSON_FINAL}")

    # 6. Save full result to Excel
    save_to_excel(final_output, OUTPUT_EXCEL_FINAL)
    print(f"Full output saved to Excel: {OUTPUT_EXCEL_FINAL}")

    print("\nCompleted successfully.")

if __name__ == "__main__":
    main_processor()