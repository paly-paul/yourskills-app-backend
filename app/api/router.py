from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.database import SessionLocal
from app.schemas import UserCreate, UserLogin, UserResponse
from app.services import create_user, get_user_by_username
from app.utils import verify_password
from app.schemas import ForgotPasswordRequest
from app.services.user import forgot_password
from fastapi import APIRouter, UploadFile, File
import tempfile
from app.utils.cv_extractor import extract_cv_data_from_file
from app.services.user import save_extracted_cv_data
from app.utils.token import create_access_token
from app.models import User
from app.utils.token import get_current_user

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/register")
def register(user: UserCreate, db: Session = Depends(get_db)):
    existing = get_user_by_username(db, user.username)
    if existing:
        return {"success": False, "reason": "Username already exists."}

    created_user = create_user(db, user)

    token_data = {"user_id": created_user.id, "username": created_user.username}
    access_token = create_access_token(token_data)

    return {"success": True, "token": access_token}


@router.post("/login")
def login(user: UserLogin, db: Session = Depends(get_db)):
    db_user = None
    if user.username:
        db_user = get_user_by_username(db, user.username)
    elif user.email:
        db_user = db.query(User).filter(User.email == user.email).first()

    if not db_user:
        return {"success": False, "reason": "User not found."}

    if not verify_password(user.password, db_user.password):
        return {"success": False, "reason": "Invalid password."}

    token_data = {"user_id": db_user.id, "username": db_user.username}
    access_token = create_access_token(token_data)

    return {"success": True, "token": access_token}


@router.get("/profile")
def get_profile(current_user: User = Depends(get_current_user)):
    if not current_user:
        return {"success": False, "reason": "Unauthorized access or token invalid."}

    profile_data = {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email
    }
    return {"success": True, "profile": profile_data}

@router.post("/forgot-password")
def forgot_password_route(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    temp_password = forgot_password(db, payload.email)
    if not temp_password:
        raise HTTPException(status_code=404, detail="User not found")

    return {"temp_password": temp_password, "message": "Use this to log in and reset your password"}



@router.post("/extract-cv")
async def extract_cv(file: UploadFile = File(...), db: Session = Depends(get_db), user_id: int = 1):
    mime_type = file.content_type

    with tempfile.NamedTemporaryFile(delete=False, suffix=file.filename.split('.')[-1]) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    data = extract_cv_data_from_file(tmp_path, mime_type)

    #Save parsed data into DB
    save_result = save_extracted_cv_data(user_id, data, tmp_path, db)

    return {"parsed_data": data, **save_result}


