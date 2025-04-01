from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.schemas.user import UserCreate, UserResponse
from app.services.user_service import UserService
from app.dependencies import get_db

router = APIRouter(
    prefix="/users",
    tags=["users"]
)

@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create new user"
)
async def create_user(
    user_data: UserCreate, 
    db: Session = Depends(get_db)
):
    """
    Create a new user with the following information:
    - **email**: must be unique
    - **password**: will be hashed
    - **name**: full name
    - **role**: user role
    """
    return UserService(db).create_user(user_data)

@router.get(
    "/{user_id}",
    response_model=UserResponse,
    summary="Get user by ID"
)
async def get_user(
    user_id: int,
    db: Session = Depends(get_db)
):
    """Retrieve a specific user by their ID"""
    user = UserService(db).get_user(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    return user