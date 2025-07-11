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


