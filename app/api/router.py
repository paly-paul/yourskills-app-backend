from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.database import SessionLocal
from app.schemas import UserCreate, UserLogin, UserResponse
from app.services import create_user, get_user_by_username
from app.utils import verify_password
from app.schemas import ForgotPasswordRequest
from app.services.user import forgot_password

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/register", response_model=UserResponse)
def register(user: UserCreate, db: Session = Depends(get_db)):
    existing = get_user_by_username(db, user.username)
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")
    return create_user(db, user)

@router.post("/login")
def login(user: UserLogin, db: Session = Depends(get_db)):
    db_user = get_user_by_username(db, user.username)
    if not db_user or not verify_password(user.password, db_user.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Optional: Warn if user is logging in with temp password
    if db_user.is_temp_password:
        return {
            "message": "Login successful using temporary password.",
            "user_id": db_user.id,
            "temp_login": True
        }

    return {"message": "Login successful", "user_id": db_user.id}

@router.post("/forgot-password")
def forgot_password_route(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    temp_password = forgot_password(db, payload.email)
    if not temp_password:
        raise HTTPException(status_code=404, detail="User not found")

    # In production, email this instead
    return {"temp_password": temp_password, "message": "Use this to log in and reset your password"}
