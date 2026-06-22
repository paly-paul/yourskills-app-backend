import google.generativeai as genai
from app.core.config import settings

GEMINI_MODEL = "gemini-2.5-flash-lite"

genai.configure(api_key=settings.GEMINI_API_KEY)

model = genai.GenerativeModel(GEMINI_MODEL)
