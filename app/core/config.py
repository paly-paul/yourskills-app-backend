from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = 'Skill Snapshot'
    API_VERSION: str = 'v1'
    DB_URL: str 
    GEMINI_API_KEY: str
    JWT_SECRET: str

    class Config:
        env_file = ".env"

settings = Settings()
