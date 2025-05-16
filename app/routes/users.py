# from fastapi import APIRouter, Depends, HTTPException, status
# from app.schemas.user import UserCreate, UserResponse, UserUpdate
# from app.services.user_service import UserService
# from app.dependencies import get_db
# from sqlalchemy.ext.asyncio import AsyncSession
# from uuid import UUID
# from app.models.user import User
# from fastapi import BackgroundTasks
# from jose import jwt, JWTError
# import os
# from app.utils.security import get_current_user
# from sqlalchemy.future import select



# router = APIRouter(
#     prefix="/users",
#     tags=["users"]
# )



# @router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED, summary="Create new user")
# async def create_user(user_data: UserCreate, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):

#     """
#     Create a new user with the following information:
#     - **email**: must be unique
#     - **password**: will be hashed
#     - **name**: full name
#     - **role**: user role
#     """
#     return await UserService(db).create_user(user_data, background_tasks)


# @router.get("/verify-email")
# async def verify_email(token: str, db: AsyncSession = Depends(get_db)):

#     SECRET_KEY = os.getenv("SECRET_KEY")
#     ALGORITHM = os.getenv("ALGORITHM")

#     try:
#         payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
#         user_id = payload.get("sub")

#         if not user_id:
#             raise HTTPException(status_code=400, detail="Invalid token")
    
#     except JWTError:
#         raise HTTPException(status_code=400, detail="Invalid or expired token")

#     result = await db.execute(select(User).where(User.email == user_id))
#     user = result.scalar_one_or_none()

#     if not user or user.is_verified:
#         raise HTTPException(status_code=400, detail="Invalid request")

#     user.is_verified = True
#     user.verification_token = None
#     await db.commit()
#     return {"message": "Email successfully verified!"}


# @router.get("/me", response_model=UserResponse, summary="Get current user")
# async def get_me(current_user: User = Depends(get_current_user)):

#     """
#     Retrieve the current authenticated user's info using JWT token.
#     """
#     return current_user


# @router.patch("/update-account", response_model=UserResponse)
# async def update_user(
#     user_data: UserUpdate,
#     db: AsyncSession = Depends(get_db),
#     current_user: User = Depends(get_current_user),
# ):
#     user_service = UserService(db)
#     updated_user = await user_service.update_user(current_user.id, user_data)
#     return updated_user


# @router.delete("/delete-account", status_code=status.HTTP_204_NO_CONTENT)
# async def delete_account(
#     db: AsyncSession = Depends(get_db),
#     current_user: User = Depends(get_current_user),
# ):
#     user_service = UserService(db)
#     await user_service.delete_user(current_user.id)
from fastapi import APIRouter, Depends, HTTPException, status, Response
from app.schemas.user import UserCreate, UserResponse, UserUpdate, UserWithFacility
from app.services.user_service import UserService
from app.dependencies import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from app.models.user import User
from fastapi import BackgroundTasks
from jose import jwt, JWTError
import os
from app.utils.security import get_current_user
from sqlalchemy.future import select
from app.utils.data_wrapper import DataWrapper



router = APIRouter(
    prefix="/users",
    tags=["users"]
)



@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED, summary="Create new user")
async def create_user(user_data: UserCreate, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):

    """
    Create a new user with the following information:
    - **email**: must be unique
    - **password**: will be hashed
    - **name**: full name
    - **role**: user role
    """
    return await UserService(db).create_user(user_data, background_tasks)


@router.get("/verify-email")
async def verify_email(token: str, db: AsyncSession = Depends(get_db)):

    SECRET_KEY = os.getenv("SECRET_KEY")
    ALGORITHM = os.getenv("ALGORITHM")

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")

        if not user_id:
            raise HTTPException(status_code=400, detail="Invalid token")
    
    except JWTError:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    result = await db.execute(select(User).where(User.email == user_id))
    user = result.scalar_one_or_none()

    if not user or user.is_verified:
        raise HTTPException(status_code=400, detail="Invalid request")

    user.is_verified = True
    user.verification_token = None
    await db.commit()
    return {"message": "Email successfully verified!"}


@router.get("/me", response_model=DataWrapper[UserWithFacility], summary="Get current user")
async def get_me(current_user: User = Depends(get_current_user)):
    """
    Retrieve the current authenticated user's info using JWT token.
    Response includes user details and related facility/blood bank information.
    """
    # Convert to Pydantic model to include relationships
    user_data = UserWithFacility.model_validate(current_user, from_attributes=True)
    return {"data": user_data}


@router.options("/me")
async def options_me():
    """
    Handle OPTIONS request for the /me endpoint specifically
    This helps with CORS preflight requests
    """
    response = Response()
    return response


@router.patch("/update-account", response_model=DataWrapper[UserResponse])
async def update_user(
    user_data: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_service = UserService(db)
    updated_user = await user_service.update_user(current_user.id, user_data)
    return {"data": updated_user}


@router.delete("/delete-account", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_service = UserService(db)
    await user_service.delete_user(current_user.id)