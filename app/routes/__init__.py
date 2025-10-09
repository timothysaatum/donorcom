from fastapi import APIRouter
from .users_routes import router as users_router
from .facility_routes import router as facility_router
from .auth_routes import router as auth_router
from .blood_bank_routes import router as blood_bank_router
from .inventory_routes import router as blood_inventory_router
from .distribution_routes import router as distribution_router
from .tracking_ruotes import router as tracking_router
from .stats_routes import router as inventory_stats_route
from .request_routes import router as request_router
from .notification_routes import router as notification_router


router = APIRouter()

router.include_router(users_router)
router.include_router(auth_router)
router.include_router(facility_router)
router.include_router(inventory_stats_route)
router.include_router(blood_bank_router)
router.include_router(blood_inventory_router)
router.include_router(request_router)
router.include_router(distribution_router)
router.include_router(tracking_router)
router.include_router(notification_router)
