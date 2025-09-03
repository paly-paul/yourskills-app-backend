

import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from app.db.database import get_database
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from dotenv import load_dotenv


load_dotenv()

SECRET_KEY = os.getenv("JWT_SECRET", "your-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 60))

security = HTTPBearer()

async def get_mongo_db() -> AsyncIOMotorDatabase:
    db_instance = await get_database()
    if db_instance is None:
        raise HTTPException(status_code=500, detail="Database not connected")
    return db_instance



def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT token with an expiration time.
    `data` should at least contain 'user_id' (string).
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncIOMotorDatabase = Depends(get_mongo_db)
) -> Dict[str, Any]:
    """
    FastAPI dependency to get the current user from MongoDB based on the JWT token.
    Supports both ObjectId and UUID string IDs.
    """
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token payload")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = None
    try:
        oid = ObjectId(user_id)
        user = await db.users.find_one({"_id": oid})
    except Exception:
        user = await db.users.find_one({"_id": user_id})  
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user["id"] = str(user["_id"])
    return user
