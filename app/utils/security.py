from passlib.context import CryptContext
from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from typing import Optional
import os
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession
from app.dependencies import get_db
from app.models.user import User
from sqlalchemy.future import select
from uuid import UUID
from sqlalchemy.orm import selectinload
from app.models.health_facility import Facility

load_dotenv()

# Password hashing configuration
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

# JWT configuration
SECRET_KEY = os.getenv("SECRET_KEY")
assert SECRET_KEY, "SECRET_KEY is not set in the .env file"

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 120

def get_password_hash(password: str) -> str:
    """Hash a plaintext password using bcrypt"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a hashed password"""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token"""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_verification_token(email: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=24)
    to_encode = {"sub": email, "exp": expire}

    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and verify a JWT token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    
    except JWTError as e:
        raise ValueError("Invalid or expired token") from e


# async def get_current_user(db: AsyncSession = Depends(get_db), token: str = Depends(oauth2_scheme)) -> User:
#     """
#     Get current user with proper relationship loading for the /me endpoint
#     """
#     try:
#         # Decode and verify the token
#         payload = decode_token(token)
        
#         # Extract user ID from the token (should be included in the 'sub' claim)
#         user_id = payload.get("sub")
#         if user_id is None:
#             raise HTTPException(
#                 status_code=status.HTTP_401_UNAUTHORIZED,
#                 detail="Token does not contain user ID",
#                 headers={"WWW-Authenticate": "Bearer"},
#             )

#         # Query the database to get the user by ID with facility and blood_bank loaded
#         result = await db.execute(
#             select(User)
#             .options(
#                 selectinload(User.facility).selectinload(Facility.blood_bank)
#             )
#             .where(User.id == UUID(user_id))
#         )
#         user = result.scalar_one_or_none()

#         if user is None:
#             raise HTTPException(
#                 status_code=status.HTTP_401_UNAUTHORIZED,
#                 detail="User not found",
#                 headers={"WWW-Authenticate": "Bearer"},
#             )

#         return user
        
#     except (JWTError, ValueError):
#         raise HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail="Invalid authentication credentials",
#             headers={"WWW-Authenticate": "Bearer"},
#         )
async def get_current_user(db: AsyncSession = Depends(get_db), token: str = Depends(oauth2_scheme)) -> User:
    try:
        payload = decode_token(token)
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token does not contain user ID",
                headers={"WWW-Authenticate": "Bearer"},
            )

        result = await db.execute(
            select(User)
            .options(
                selectinload(User.facility).selectinload(Facility.blood_bank),
                selectinload(User.work_facility).selectinload(Facility.blood_bank)  # ← Add this
            )
            .where(User.id == UUID(user_id))
        )
        user = result.scalar_one_or_none()

        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return user

    except (JWTError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )