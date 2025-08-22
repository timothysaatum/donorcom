from passlib.context import CryptContext
from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from typing import Optional
import os
from fastapi import Depends, HTTPException, status, WebSocket
from fastapi.security import OAuth2PasswordBearer
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession
from app.dependencies import get_db
from app.models.user import User
from sqlalchemy.future import select
from uuid import UUID
from sqlalchemy.orm import selectinload
from app.models.health_facility import Facility
from uuid import uuid4

load_dotenv()

# Password hashing configuration
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

# JWT configuration
SECRET_KEY = os.getenv("SECRET_KEY")
assert SECRET_KEY, "SECRET_KEY is not set in the .env file"

# JWT and Token Configuration
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 180
REFRESH_TOKEN_EXPIRE_DAYS = 7


class TokenManager:
    @staticmethod
    def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
        """Create a JWT access token"""
        secret_key = os.getenv("SECRET_KEY")
        algorithm = os.getenv("ALGORITHM", "HS256")

        to_encode = data.copy()
        expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
        to_encode.update({"exp": expire, "type": "access"})

        return jwt.encode(to_encode, secret_key, algorithm=algorithm)

    @staticmethod
    def create_refresh_token(user_id: UUID) -> str:
        """Create a refresh token"""
        secret_key = os.getenv("SECRET_KEY")
        algorithm = os.getenv("ALGORITHM", "HS256")

        expires = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        to_encode = {
            "sub": str(user_id),
            "exp": expires,
            "type": "refresh",
            "jti": str(uuid4())
        }

        return jwt.encode(to_encode, secret_key, algorithm=algorithm)

    @staticmethod
    def decode_token(token: str) -> dict:
        """Decode and verify a JWT token"""
        secret_key = os.getenv("SECRET_KEY")
        algorithm = os.getenv("ALGORITHM", "HS256")

        try:
            payload = jwt.decode(token, secret_key, algorithms=[algorithm])
            return payload
        except JWTError as e:
            raise ValueError("Invalid or expired token") from e

            
def get_password_hash(password: str) -> str:
    """Hash a plaintext password using bcrypt"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a hashed password"""
    return pwd_context.verify(plain_password, hashed_password)


# def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
#     """Create a JWT access token"""
#     to_encode = data.copy()
#     expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
#     to_encode.update({"exp": expire})
    
#     return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_verification_token(email: str) -> str:

    expire = datetime.now(timezone.utc) + timedelta(hours=24)
    to_encode = {"sub": email, "exp": expire}

    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# def decode_token(token: str) -> dict:
#     """Decode and verify a JWT token"""
#     try:
#         payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
#         return payload
    
#     except JWTError as e:
#         raise ValueError("Invalid or expired token") from e


async def get_current_user(db: AsyncSession = Depends(get_db), token: str = Depends(oauth2_scheme)) -> User:
    try:
        payload = TokenManager.decode_token(token)
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
                selectinload(User.work_facility).selectinload(Facility.blood_bank)
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
    

async def get_current_user_ws(websocket: WebSocket, db: AsyncSession) -> User:
    # Token from cookie
    token = websocket.cookies.get("access_token")
    if token is None:
        await websocket.close(code=1008)
        raise HTTPException(status_code=401, detail="Missing token")

    try:
        payload = TokenManager.decode_token(token)
        user_id = payload.get("sub")
        if not user_id:
            await websocket.close(code=1008)
            raise HTTPException(status_code=401, detail="Invalid token")

        result = await db.execute(
            select(User)
            .where(User.id == UUID(user_id))
        )
        user = result.scalar_one_or_none()
        if not user:
            await websocket.close(code=1008)
            raise HTTPException(status_code=401, detail="User not found")
        return user

    except Exception:
        await websocket.close(code=1008)
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")