from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from app.db.database import get_database
from app.schemas import UserCreate, UserLogin, ForgotPasswordRequest
from app.services.user import create_user, get_user_by_username, forgot_password, save_extracted_cv_data
from app.utils import verify_password
from app.utils.cv_extractor import extract_cv_data_from_file
from app.utils.token import create_access_token, get_current_user
from app.services.cv_comparison import get_cv_summary
import tempfile
from bson import ObjectId

router = APIRouter()

@router.post("/register")
async def register(user: UserCreate, db=Depends(get_database)):
    existing = await get_user_by_username(db, user.username)
    if existing:
        return {"success": False, "reason": "Username already exists."}

    created_user = await create_user(db, user)

    token_data = {"user_id": str(created_user["_id"]), "username": created_user["username"]}
    access_token = create_access_token(token_data)

    return {
        "success": True,
        "token": access_token,
        "tenant_id": created_user["tenant_id"]
    }



@router.post("/login")
async def login(user: UserLogin, db=Depends(get_database)):
    db_user = None
    if user.username:
        db_user = await get_user_by_username(db, user.username)
    elif user.email:
        db_user = await db["users"].find_one({"email": user.email})  

    if not db_user:
        return {"success": False, "reason": "User not found."}

    if not verify_password(user.password, db_user["password"]):
        return {"success": False, "reason": "Invalid password."}

    token_data = {"user_id": str(db_user["_id"]), "username": db_user["username"]}
    access_token = create_access_token(token_data)

    return {
        "success": True,
        "token": access_token,
        "tenant_id": db_user["tenant_id"]
    }


@router.get("/profile")
def get_profile(current_user=Depends(get_current_user)):
    if not current_user:
        return {"success": False, "reason": "Unauthorized access or token invalid."}

    profile_data = {
        "id": str(current_user["_id"]),
        "username": current_user["username"],
        "email": current_user["email"]
    }
    return {"success": True, "profile": profile_data}


@router.post("/forgot-password")
def forgot_password_route(payload: ForgotPasswordRequest, db=Depends(get_database)):
    temp_password = forgot_password(db, payload.email)
    if not temp_password:
        raise HTTPException(status_code=404, detail="User not found")

    return {"temp_password": temp_password, "message": "Use this to log in and reset your password"}


@router.post("/extract-cv")
async def extract_cv(
    file: UploadFile = File(...),
    db=Depends(get_database),
    current_user=Depends(get_current_user)
):
    mime_type = file.content_type

    with tempfile.NamedTemporaryFile(delete=False, suffix="." + file.filename.split('.')[-1]) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    data = extract_cv_data_from_file(tmp_path, mime_type)

    save_result = await save_extracted_cv_data(
        user_id=current_user["_id"],
        parsed_data=data,
        file_path=tmp_path,
        db=db
    )

    summary = await get_cv_summary(data)

    return {
        "parsed_data": data,
        "summary": summary,
        **save_result,
        "message": "CV data extracted and saved successfully"
    }

# =========================
# NEW: Get all questions API
# =========================
@router.get("/questions")
async def get_all_questions(db=Depends(get_database)):
    questions_cursor = db["questions"].find({})
    questions = []
    async for q in questions_cursor:
        q["_id"] = str(q["_id"])  # convert ObjectId to string for JSON
        questions.append(q)

    return {
        "success": True,
        "count": len(questions),
        "questions": questions
    }


