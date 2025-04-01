from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.schemas.user import AuthResponse
from app.services.user_service import UserService
from app.dependencies import get_db



router = APIRouter(
    prefix="/users/auth",
    tags=["auth"]
)



@router.post("/login", response_model=AuthResponse)
def login_user(email: str, password: str, db: Session = Depends(get_db)):
    user_service = UserService(db)
    return user_service.authenticate_user(email, password)