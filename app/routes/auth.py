from fastapi import APIRouter, Depends,  Depends, Query, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse
from app.schemas.user import AuthResponse
from app.services.user_service import UserService
from app.dependencies import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models import User
from app.utils.email_verification import send_verification_email
from app.utils.security import create_verification_token
 




router = APIRouter(
    prefix="/users/auth",
    tags=["auth"]
)

@router.post("/login", response_model=AuthResponse)
async def login( background_tasks: BackgroundTasks, email: str = Query(...), password: str = Query(...), db: AsyncSession = Depends(get_db),):

    user_service = UserService(db)
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=400, detail="Invalid email or password")

    if not user.is_verified:
        
        token = create_verification_token(email)
        user.verification_token = token
        await db.commit()
    
        background_tasks.add_task(send_verification_email, email, token)

        return JSONResponse(
            status_code=400,
            content={"detail": "Email not verified. A new verification link has been sent to your email."}
        )


    response = await user_service.authenticate_user(email=email, password=password)

    return response
