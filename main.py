# main.py
from fastapi import FastAPI
from app.api.router import router
from app.db.database import connect_to_mongo, close_mongo_connection
from fastapi.openapi.utils import get_openapi

app = FastAPI(
    title="Skill Snapshot API",
    version="v1"
)

@app.on_event("startup")
async def startup_db_client():
    await connect_to_mongo()

@app.on_event("shutdown")
async def shutdown_db_client():
    await close_mongo_connection()

@app.get("/")
def read_root():
    return {"msg": "Skill Snapshot API is live"}


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
