# app/utils/hash.py

from passlib.context import CryptContext
import random
import string
import uuid
from bson import ObjectId

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    """Hash a plaintext password."""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)

def generate_temp_password(length: int = 8) -> str:
    """Generate a temporary random alphanumeric password."""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

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
