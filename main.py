from fastapi import FastAPI
from app.api.router import router
from app.db.database import Base, engine

# Auto-create tables (run once at startup)
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Skill Snapshot API",
    version="v1"
)

@app.get("/")
def read_root():
    return {"msg": "Skill Snapshot API is live"}

# Include all API routes (register/login/etc.)
app.include_router(router)
