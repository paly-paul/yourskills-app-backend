from sqlalchemy.orm import Session
from app.models import User
from app.schemas import UserCreate
from app.utils import hash_password
from app.models import User
from app.utils.hash import hash_password, generate_temp_password
from sqlalchemy.orm import Session

def create_user(db: Session, user: UserCreate):
    db_user = User(
        username=user.username,
        email=user.email,
        password=hash_password(user.password)
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def get_user_by_username(db: Session, username: str):
    return db.query(User).filter(User.username == username).first()

def forgot_password(db: Session, email: str) -> str | None:
    user = db.query(User).filter(User.email == email).first()
    if not user:
        return None

    temp_pass = generate_temp_password()
    user.password = hash_password(temp_pass)
    user.is_temp_password = True
    db.commit()
    return temp_pass
