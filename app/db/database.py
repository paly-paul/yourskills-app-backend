# app/db/database.py
import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

# db.createUser({
#   user: "snapshot_user",
#   pwd: "change-this-app-pass",
#   roles: [{ role: "readWrite", db: "snapshot" }]
# });
# DB_URL=mongodb://snapshot_user:admin@localhost:27017/snapshot?authSource=snapshot
# MONGO_DB=snapshot

MONGO_URL = os.getenv("DB_URL")
MONGO_DB_NAME = os.getenv("MONGO_DB")

client: AsyncIOMotorClient = None
db = None

async def connect_to_mongo():
    global client, db
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[MONGO_DB_NAME]
    print("Connected to MongoDB")

async def close_mongo_connection():
    global client
    if client:
        client.close()
        print("MongoDB connection closed")

async def get_database():
    """Dependency that provides a MongoDB database instance."""
    return db