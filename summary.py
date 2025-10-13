import json
import google.generativeai as genai

# Configure API key (replace with your actual key)
genai.configure(api_key="AIzaSyABfTlImtxScyj41CTyjsp9pFZ_1MZvyE0")

# Load the parsed resume JSON file
with open("structured_resume_data.json", "r", encoding="utf-8") as f:
    parsed_resume = json.load(f)

# Compose extraction prompt with instructions for uniqueness and catchiness
extract_prompt = f"""
You are a precise JSON extractor. Your task is to extract the **most relevant, unique, and concise keywords or phrases** from a structured resume JSON.  

Requirements:
1. For each field, provide a **single short keyword or catchy phrase** (max 3 words).  
2. Prefer **impactful, buzzword-style keywords** that can stand alone.  
3. Ensure **all keywords are unique** across all fields.  
4. If a field is missing or contains "Not specified", handle as:
   - "Hobbies": output []
   - All other fields: output "Not specified"  
5. If a value appears relevant for multiple fields, assign it to the **most appropriate field** only.  
6. Avoid generic duplicates. Each keyword must be distinct.

**Talent attributes:**
1. Core Code:
- Core Tasks
- Supplementary Tasks
- Hot Technologies
- Functional Skills
- Skills

2. DNA of Work:
- Work Activities
- Work Values
- Work Styles
- Abilities

3. Interest Compass:
- Career Interest Areas
- Knowledge
- Emerging Tasks

4. Upskills Unlocked:
- Newly Acquired Skills
- Emerging Tech Awareness

**Anchor attributes:**
1. Passion Palette:
- Hobbies (top 2 as a JSON array)
- Personal Interests
- Motivating Activities
- Social Cause
- Cultural Exposure
- Volunteering

2. Drives You:
- Motivation Drivers
- Competency
- Learning Agility
- Cognitive Preferences
- Creative Inclinations

3. Rooted In You:
- Achievements
- Life Skills
- Behavioural Skills
- Organizational Skills
- Personality Traits

4. Moves You Forward:
- Exploration Interest
- Future Study Intent

**Output format:**  
Provide a **single JSON object** with exactly this structure:

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
- Review each field in the input JSON.  
- Extract the **most relevant item** per field.  
- Convert it into a **short, unique, buzzword-style phrase**.  
- Do not repeat keywords across fields.  

Input JSON:
{json.dumps(parsed_resume)}
"""


# Create Gemini model instance
gemini_model = genai.GenerativeModel("gemini-2.5-pro")
generation_config = genai.types.GenerationConfig(
    response_mime_type="application/json",
    temperature=0
)

# Generate content with the prompt
response = gemini_model.generate_content(
    contents=[extract_prompt],
    generation_config=generation_config
)

#Post-processing function to deduplicate extracted keywords across all fields
def deduplicate_keywords(data):
    seen = set()

    def process_subdict(subdict):
        for key, value in subdict.items():
            if isinstance(value, str):
                val = value.strip()
                if val.lower() == "not specified" or val == "":
                    continue
                if val in seen:
                    subdict[key] = ""
                else:
                    seen.add(val)
            elif isinstance(value, list):
                unique_list = []
                for item in value:
                    if item not in seen:
                        seen.add(item)
                        unique_list.append(item)
                subdict[key] = unique_list

    for main_key in data:
        for sub_key in data[main_key]:
            process_subdict(data[main_key][sub_key])
    return data

import re

def to_catchy_keyword(phrase):
    # If empty or not specified, return as is
    if not phrase or phrase.lower() == "not specified":
        return phrase
    # Convert phrases to keywords: pick capitalized words or first word, remove stopwords if needed
    words = re.findall(r'\b[A-Z][a-z]*\b', phrase)
    # If no capital words detected, fallback to split by space and take first word
    if not words:
        words = phrase.split()
    # Return the most meaningful single keyword - prefer first extracted capitalized word
    return words[0]



# Parse and save output JSON
try:
    extracted_data = json.loads(response.text)
    # Deduplicate keywords
    extracted_data = deduplicate_keywords(extracted_data)
    # After loading JSON extracted_data from model output, call:
    

    print(json.dumps(extracted_data, indent=2))

    with open("summary.json", "w", encoding="utf-8") as f_out:
        json.dump(extracted_data, f_out, ensure_ascii=False, indent=2)

    print("✅ Extraction complete. Output saved to summary.json")

except json.JSONDecodeError:
    print("❌ Failed to parse JSON from extraction response:")
    print(response.text)
