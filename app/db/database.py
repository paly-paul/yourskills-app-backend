

import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URL = os.getenv("DB_URL")
MONGO_DB_NAME = os.getenv("MONGO_DB", "snapshot")

client: AsyncIOMotorClient = None
db = None

async def connect_to_mongo():
    global client, db
    client = AsyncIOMotorClient(MONGO_URL, uuidRepresentation="standard")
    db = client[MONGO_DB_NAME]
   
    await db.command({"ping": 1})
    print(f"✅ Connected to MongoDB database: {MONGO_DB_NAME}")

async def close_mongo_connection():
    global client
    if client:
        client.close()
        print("🛑 MongoDB connection closed")

async def get_database():
    """Dependency that provides a MongoDB database instance."""
    return db




