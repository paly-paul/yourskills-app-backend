# ✅ Correct for Pydantic v2
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = 'Skill Snapshot'
    API_VERSION: str = 'v1'
    DB_URL: str  # No fallback – force it to be in .env

    class Config:
        env_file = ".env"

settings = Settings()
