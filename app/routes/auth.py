from fastapi import APIRouter, Depends,  Depends, Query
from app.schemas.user import AuthResponse
from app.services.user_service import UserService
from app.dependencies import get_db
from sqlalchemy.ext.asyncio import AsyncSession



router = APIRouter(
    prefix="/users/auth",
    tags=["auth"]
)

@router.post("/login", response_model=AuthResponse)
async def login(
    email: str = Query(...),
    password: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    user_service = UserService(db)
    response = await user_service.authenticate_user(email=email, password=password)
    return response
