from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException, Response, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import datetime, timedelta, timezone
from typing import Optional
import os

from jose import jwt, JWTError
from passlib.context import CryptContext
from uuid import UUID, uuid4

from app.models import User
from app.schemas.user import AuthResponse, LoginSchema
from app.dependencies import get_db
from app.services.user_service import UserService
from app.utils.email_verification import send_verification_email
from app.utils.security import create_verification_token
from app.utils.data_wrapper import DataWrapper, ResponseWrapper

# JWT and Token Configuration
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class TokenManager:
    @staticmethod
    def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
        """Create a JWT access token"""
        to_encode = data.copy()
        expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
        to_encode.update({"exp": expire, "type": "access"})
        return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

    @staticmethod
    def create_refresh_token(user_id: UUID) -> str:
        """Create a refresh token"""
        expires = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        to_encode = {
            "sub": str(user_id),
            "exp": expires,
            "type": "refresh",
            "jti": str(uuid4())  # Unique identifier for the token
        }
        return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

    @staticmethod
    def decode_token(token: str) -> dict:
        """Decode and verify a JWT token"""
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            return payload
        except JWTError as e:
            raise ValueError("Invalid or expired token") from e

# Authentication Router
router = APIRouter(
    prefix="/users/auth",
    tags=["auth"]
)

@router.post("/login", response_model=DataWrapper[AuthResponse])
async def login(
    response: Response, 
    background_tasks: BackgroundTasks, 
    credentials: LoginSchema, 
    db: AsyncSession = Depends(get_db)
):
    """
    Login endpoint with refresh token support and user data return
    """
    email = credentials.email
    password = credentials.password
    user_service = UserService(db)
    
    # Fetch user
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

    # Authenticate user and get auth data
    auth_data = await user_service.authenticate_user(email=email, password=password)

    # Create tokens
    access_token = TokenManager.create_access_token({"sub": str(user.id)})
    refresh_token = TokenManager.create_refresh_token(user.id)

    # Set refresh token in an HTTP-only, secure cookie
    response.set_cookie(
        key="refresh_token", 
        value=refresh_token, 
        httponly=True,  # Prevent JavaScript access
        secure=True,    # Only send over HTTPS
        samesite="lax", # Protect against CSRF
        max_age=60 * 60 * 24 * REFRESH_TOKEN_EXPIRE_DAYS  # Cookie expiration
    )

    # Modify auth_data to include the access token if needed
    auth_response = AuthResponse(**auth_data)
    auth_response.access_token = access_token

    return {"data": auth_response}


@router.get("/refresh", response_model=DataWrapper[AuthResponse])
async def refresh_token(
    response: Response,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Refresh access token using the refresh token from cookies
    """
    # Get refresh token from cookies
    refresh_token = request.cookies.get("refresh_token")
    
    if not refresh_token:
        raise HTTPException(
            status_code=401, 
            detail="No refresh token provided"
        )

    try:
        # Decode and validate refresh token
        payload = TokenManager.decode_token(refresh_token)
        
        # Ensure it's a refresh token
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=401, 
                detail="Invalid token type"
            )

        # Get user ID from token
        user_id_str = payload.get("sub")
        if not user_id_str:
            raise HTTPException(
                status_code=401, 
                detail="Invalid token"
            )

        user_id = UUID(user_id_str)

        # Get the user data from the database
        user_service = UserService(db)
        user = await user_service.get_user(user_id)
        
        if not user:
            raise HTTPException(
                status_code=401, 
                detail="User not found"
            )

        # Create new access token with user data
        token_data = {"sub": str(user.id), "email": user.email}
        new_access_token = TokenManager.create_access_token(token_data)

        # Create a new refresh token (token rotation)
        new_refresh_token = TokenManager.create_refresh_token(user.id)
        
        # Update refresh token cookie
        response.set_cookie(
            key="refresh_token", 
            value=new_refresh_token, 
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=60 * 60 * 24 * REFRESH_TOKEN_EXPIRE_DAYS
        )

        # Get user data with facility and blood bank (similar to authenticate_user method)
        # But without password verification
        from sqlalchemy.orm import selectinload
        from app.models.health_facility import Facility
        
        # Get the full user with facility and blood bank loaded
        result = await db.execute(
            select(User)
            .options(
                selectinload(User.facility).selectinload(Facility.blood_bank)
            )
            .where(User.id == user_id)
        )
        user_with_relations = result.scalar_one_or_none()
        
        # Update last login time
        user_with_relations.last_login = datetime.now()
        await db.commit()
        
        # Convert to schema
        from app.schemas.user import UserWithFacility
        user_data = UserWithFacility.model_validate(user_with_relations, from_attributes=True).model_dump()
        
        # Create auth response
        auth_data = {
            "access_token": new_access_token,
            "user": user_data
        }
        
        auth_response = AuthResponse(**auth_data)

        return {"data": auth_response}

    except ValueError as e:
        # Token is invalid or expired
        raise HTTPException(
            status_code=401, 
            detail=f"Invalid or expired refresh token: {str(e)}"
        )

@router.post("/logout")
async def logout(response: Response):
    """
    Logout endpoint that clears the refresh token cookie
    """
    response.delete_cookie("refresh_token")
    return {"data": {"message": "Logged out successfully"}}