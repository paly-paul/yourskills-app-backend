

import bcrypt
import random
import string
import uuid
from bson import ObjectId

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))

def generate_temp_password(length: int = 8) -> str:
    """Generate a temporary random alphanumeric password."""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

def generate_otp(length: int = 6) -> str:
    """Generate a numeric OTP of the given length."""
    return ''.join(random.choices(string.digits, k=length))

def generate_tenant_id(length: int = 10) -> str:
    """Generate a unique tenant ID prefixed with TEN."""
    prefix = "TEN"
    suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))
    return f"{prefix}{suffix}"

def generate_uuid() -> str:
    """Generate a UUID string (good for unique MongoDB document IDs)."""
    return str(uuid.uuid4())

def generate_object_id() -> ObjectId:
    """Generate a new MongoDB ObjectId."""
    return ObjectId()
