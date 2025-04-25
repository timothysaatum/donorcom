from fastapi import APIRouter
from .users import router as users_router
from .facility import router as facility_router
from .auth import router as auth_router

router = APIRouter()

router.include_router(users_router)
router.include_router(facility_router)
# Include other routers here later
router.include_router(auth_router)
# router.include_router(items_router)