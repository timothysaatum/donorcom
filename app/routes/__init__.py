from fastapi import APIRouter
from .users import router as users_router
from .facility import router as facility_router
from .auth import router as auth_router
from .blood_bank import router as blood_bank_router

router = APIRouter()

router.include_router(users_router)
router.include_router(facility_router)
router.include_router(blood_bank_router)
router.include_router(auth_router)