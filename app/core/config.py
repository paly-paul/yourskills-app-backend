from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = 'Skill Snapshot'
    API_VERSION: str = 'v1'
    DB_URL: str
    MONGO_DB: str
    GEMINI_API_KEY: str
    JWT_SECRET: str
    GOOGLE_CLIENT_ID: str = ""
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "us-east-1"
    MAIL_FROM: str = ""

    class Config:
        env_file = ".env"

settings = Settings()
