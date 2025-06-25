from fastapi import APIRouter, Depends, HTTPException, status, Response
from app.schemas.user import (UserCreate, UserResponse, UserUpdate, UserWithFacility) 
from app.services.user_service import UserService
from app.dependencies import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import User
from fastapi import BackgroundTasks
from jose import jwt, JWTError
import os
from app.utils.security import get_current_user
from sqlalchemy.future import select
from app.utils.data_wrapper import DataWrapper
from uuid import UUID



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


# @router.patch("/update-account", response_model=DataWrapper[UserResponse])
# async def update_user(
#     user_data: UserUpdate,
#     db: AsyncSession = Depends(get_db),
#     current_user: User = Depends(get_current_user),
# ):
#     user_service = UserService(db)
#     updated_user = await user_service.update_user(current_user.id, user_data)
#     return {"data": updated_user}
@router.patch("/update-account/{user_id}", response_model=DataWrapper[UserResponse])
async def update_user(
    user_id: UUID,
    user_data: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),):
    # Check if current user has permission to update this user
    if str(current_user.id) != str(user_id) and current_user.role not in ["facility_administrator", "lab_manager"]:
        raise HTTPException(status_code=403, detail="You can only update your own account or must be an admin/lab manager")
    
    user_service = UserService(db)
    updated_user = await user_service.update_user(user_id, user_data)
    return {"data": updated_user}


# @router.delete("/delete-account", status_code=status.HTTP_204_NO_CONTENT)
# async def delete_account(
#     db: AsyncSession = Depends(get_db),
#     current_user: User = Depends(get_current_user),
# ):
#     user_service = UserService(db)
#     await user_service.delete_user(current_user.id)
@router.delete("delete-account/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),):
    # Check permissions
    if str(current_user.id) != str(user_id) and current_user.role not in ["facility_administrator", "lab_manager"]:
        raise HTTPException(
            status_code=403,
            detail="You can only delete your own account or must be an admin/lab manager"
        )
    
    user_service = UserService(db)
    await user_service.delete_user(user_id)


@router.post("/staff/create", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_staff_user(
    user_data: UserCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Lab Managers or Facility Admins create staff/lab manager accounts.
    Automatically assigns them to the creator's facility.
    """
    if current_user.role not in ["facility_administrator", "lab_manager"]:
        raise HTTPException(status_code=403, detail="Only lab managers or facility admins can create staff.")

    if user_data.role not in ["staff", "lab_manager"]:
        raise HTTPException(status_code=400, detail="You can only assign staff or lab_manager roles.")

    # Make sure the current user has a facility
    if not current_user.facility:
        raise HTTPException(status_code=400, detail="You are not assigned to any facility.")

    # Inject facility_id into user creation logic
    user_service = UserService(db)
    created_user = await user_service.create_user(
        user_data=user_data,
        background_tasks=background_tasks,
        facility_id=current_user.facility.id
    )

    return created_user


@router.get("/staff", response_model=list[UserResponse], summary="Get all staff users")
async def get_all_staff_users(
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
    ):
    """
    Get all staff users in the current user's facility.
    Only accessible by facility admins or lab managers.
    """
    if current_user.role not in ["facility_administrator", "lab_manager"]:
        raise HTTPException(status_code=403, detail="Only lab managers or facility admins can view staff.")

    user_service = UserService(db)
    staff_users = await user_service.get_all_staff_users(current_user.facility.id)

    return staff_users