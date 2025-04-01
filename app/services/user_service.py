from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.models.user import User
from app.schemas.user import UserCreate, UserResponse
from app.utils.security import get_password_hash, verify_password, create_access_token
from datetime import timedelta
from typing import Optional


class UserService:
    def __init__(self, db: Session):
        self.db = db

    def create_user(self, user_data: UserCreate) -> User:
        if self.db.query(User).filter(User.email == user_data.email).first():
            raise HTTPException(status_code=400, detail="Email already registered")

        hashed_password = get_password_hash(user_data.password)
        db_user = User(
            email=user_data.email,
            name=user_data.name,
            password=hashed_password,
            role=user_data.role,
            phone=user_data.phone
        )
        self.db.add(db_user)
        self.db.commit()
        self.db.refresh(db_user)
        return db_user
        
    
    def authenticate_user(self, email: str, password: str) -> dict:
        user = self.db.query(User).filter(User.email == email).first()
        if not user or not verify_password(password, user.password):
            raise HTTPException(status_code=401, detail="Invalid credentials")

        # Create access token
        token_data = {"sub": str(user.id), "email": user.email}
        access_token = create_access_token(data=token_data, expires_delta=timedelta(minutes=60))

        # Convert user to a dictionary
        user_data = UserResponse.model_validate(user).model_dump()

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": user_data  # Ensure user is a dictionary, not a Pydantic model
        }

    def get_user(self, user_id: int) -> Optional[User]:
        return self.db.query(User).filter(User.id == user_id).first()