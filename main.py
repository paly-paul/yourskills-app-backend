from fastapi import FastAPI
from app.api.router import router
from app.db.database import Base, engine
from fastapi.openapi.utils import get_openapi

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

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="Skill Snapshot API",
        version="v1",
        description="This API uses JWT for authentication. Use the 'Authorize' button and provide a token prefixed with 'Bearer '.",
        routes=app.routes,
    )
    openapi_schema["components"]["securitySchemes"] = {
        "bearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
    }
    for path in openapi_schema["paths"].values():
        for operation in path.values():
            operation["security"] = [{"bearerAuth": []}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi
