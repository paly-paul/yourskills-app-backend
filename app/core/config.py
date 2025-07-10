import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    PROJECT_NAME: str = 'Skill Snapshot'
    API_VERSION: str = 'v1'
    DB_URL: str = os.getenv('DATABASE_URL', 'sqlite:///./test.db')

settings = Settings()
