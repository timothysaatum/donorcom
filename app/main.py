# from contextlib import asynccontextmanager
# from app.services.scheduler import start_scheduler, stop_scheduler
# from app.tasks.reverse_address import start_periodic_task, stop_periodic_task
# from app.utils.create_user_roles import seed_roles_and_permissions
# from fastapi import FastAPI, Request, Depends
# from fastapi.middleware.cors import CORSMiddleware
# from fastapi.openapi.utils import get_openapi
# from app.routes import router as api_router
# from app.config import settings
# from sqladmin import Admin
# from app.admin.user_admin import UserAdmin
# from app.admin.facility_admin import FacilityAdmin
# from app.admin.blood_bank_admin import BloodBankAdmin
# from app.admin.inventory import BloodInventoryAdmin
# from app.database import engine, async_session
# from app.dependencies import get_db
# from fastapi.responses import RedirectResponse
# from sqlalchemy.ext.asyncio import AsyncSession
# from sqlalchemy import select
# from sqlalchemy.orm import selectinload
# from app.models.rbac import Role, Permission
# from app.middlewares.logging_middleware import LoggingMiddleware


# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     """
#     Lifespan context manager for FastAPI application startup and shutdown events.
#     """
#     # Startup

#     start_scheduler()
#     start_periodic_task()

#     # Create database session for seeding roles and permissions
#     try:
#         async with async_session() as db:
#             try:
#                 await seed_roles_and_permissions(db)

#             except Exception as e:
#                 await db.rollback()

#                 raise
#     except Exception as e:
#         raise

#     yield

#     # Shutdown (add any cleanup code here if needed)
#     stop_scheduler()  # Gracefully stop the scheduler for refreshing dashboard metrics
#     stop_periodic_task()  # Stop the reverse address task for computing gps coordinates


# def create_application() -> FastAPI:  # Create the fastapi application
#     app = FastAPI(
#         title=settings.PROJECT_NAME,
#         description=settings.PROJECT_DESCRIPTION,
#         version=settings.VERSION,
#         docs_url=settings.DOCS_URL,
#         redoc_url=None,
#         lifespan=lifespan,  # Add the lifespan context manager
#     )

#     @app.middleware("http")
#     async def https_redirect(request: Request, call_next):
#         # Check if request came via HTTP (Classic LB terminates HTTPS
#         # and forwards as HTTP)
#         if request.headers.get("x-forwarded-proto") == "http":
#             url = request.url.replace(scheme="https")
#             return RedirectResponse(url)
#         return await call_next(request)

#     # Enhanced CORS setup for Next.js frontend
#     app.add_middleware(
#         CORSMiddleware,
#         allow_origins=settings.BACKEND_CORS_ORIGINS,
#         allow_credentials=True,
#         allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
#         allow_headers=[
#             "Content-Type",
#             "Authorization",
#             "Accept",
#             "X-Requested-With",
#             "Origin",
#         ],
#         expose_headers=["Content-Length", "Content-Type", "Set-Cookie"],
#         max_age=600,  # Cache preflight requests for 10 minutes
#     )

#     # Logging middleware
#     app.add_middleware(
#         LoggingMiddleware,
#         # exclude_paths=["/", "/metrics", "/docs", "/redoc", "/openapi.json"]
#     )

#     # Include API routes
#     app.include_router(api_router, prefix=settings.API_PREFIX)

#     # SQLAdmin setup
#     admin = Admin(app, engine, base_url="/admin")
#     admin.add_view(UserAdmin)
#     admin.add_view(FacilityAdmin)
#     admin.add_view(BloodBankAdmin)
#     admin.add_view(BloodInventoryAdmin)

#     # Custom OpenAPI config for Swagger
#     def custom_openapi():
#         if app.openapi_schema:
#             return app.openapi_schema

#         openapi_schema = get_openapi(
#             title=app.title,
#             version=app.version,
#             description=app.description,
#             routes=app.routes,
#         )

#         openapi_schema["components"]["securitySchemes"] = {
#             "BearerAuth": {
#                 "type": "http",
#                 "scheme": "bearer",
#                 "bearerFormat": "JWT",
#             }
#         }

#         # Protect routes that require authentication
#         protected_paths = [
#             f"{settings.API_PREFIX}/facilities",
#             f"{settings.API_PREFIX}/blood-bank",
#             f"{settings.API_PREFIX}/users/delete-account",
#             f"{settings.API_PREFIX}/users/me",
#             f"{settings.API_PREFIX}/users/auth/logout",
#             f"{settings.API_PREFIX}/users/auth/sessions",
#             f"{settings.API_PREFIX}/users/update-account",
#             f"{settings.API_PREFIX}/blood-inventory",
#             f"{settings.API_PREFIX}/blood-distribution",
#             f"{settings.API_PREFIX}/track-states",
#             f"{settings.API_PREFIX}/users/staff",
#             f"{settings.API_PREFIX}/requests",
#             f"{settings.API_PREFIX}/patients",
#             f"{settings.API_PREFIX}/stats",
#             f"{settings.API_PREFIX}/dashboard",
#             f"{settings.API_PREFIX}/notifications",
#         ]

#         for path_key, path_item in openapi_schema["paths"].items():
#             # Check if the path should be protected
#             if any(path_key.startswith(p) for p in protected_paths):
#                 # Apply security to all methods in this path
#                 for method in path_item.values():
#                     method.setdefault("security", []).append({"BearerAuth": []})

#         app.openapi_schema = openapi_schema
#         return app.openapi_schema

#     # Assign the custom OpenAPI schema
#     app.openapi = custom_openapi

#     # Health check endpoint
#     @app.get("/")
#     def read_root():
#         return {"status": "ok"}

#     @app.get("/debug/roles")
#     async def check_roles(db: AsyncSession = Depends(get_db)):
#         """Debug endpoint to check if roles and permissions were created"""
#         try:
#             # Get all roles with their permissions
#             result = await db.execute(
#                 select(Role).options(selectinload(Role.permissions))
#             )
#             roles = result.scalars().all()

#             roles_data = []
#             for role in roles:
#                 roles_data.append(
#                     {
#                         "id": role.id,
#                         "name": role.name,
#                         "permissions": [perm.name for perm in role.permissions],
#                     }
#                 )

#             return {"total_roles": len(roles), "roles": roles_data}
#         except Exception as e:
#             return {"error": str(e)}

#     @app.get("/debug/permissions")
#     async def check_permissions(db: AsyncSession = Depends(get_db)):
#         """Debug endpoint to check all permissions"""
#         try:
#             result = await db.execute(select(Permission))
#             permissions = result.scalars().all()

#             return {
#                 "total_permissions": len(permissions),
#                 "permissions": [{"id": p.id, "name": p.name} for p in permissions],
#             }
#         except Exception as e:
#             return {"error": str(e)}

#     @app.options("/{full_path:path}")
#     async def options_handler(full_path: str):
#         """Handle OPTIONS requests - often needed for CORS preflight requests"""
#         return {}

#     return app


# # Create and expose the FastAPI app
# app = create_application()
import os
import logging
from contextlib import asynccontextmanager
from app.services.scheduler import start_scheduler, stop_scheduler
from app.tasks.reverse_address import start_periodic_task, stop_periodic_task
from app.utils.create_user_roles import seed_roles_and_permissions
from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from app.routes import router as api_router
from app.config import settings
from sqladmin import Admin
from app.admin.user_admin import UserAdmin
from app.admin.facility_admin import FacilityAdmin
from app.admin.blood_bank_admin import BloodBankAdmin
from app.admin.inventory import BloodInventoryAdmin
from app.database import engine, async_session, close_db
from app.dependencies import get_db
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.models.rbac import Role, Permission
from app.middlewares.logging_middleware import LoggingMiddleware

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Check if running in serverless environment
IS_SERVERLESS = (
    os.getenv("VERCEL") == "1" or os.getenv("AWS_LAMBDA_FUNCTION_NAME") is not None
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for FastAPI application startup and shutdown events.
    """
    # Startup
    logger.info("Application starting up...")
    logger.info(f"Serverless mode: {IS_SERVERLESS}")

    # Only start scheduler in non-serverless environments
    # Serverless functions should use external cron jobs (e.g., Vercel Cron)
    if not IS_SERVERLESS:
        logger.info("Starting scheduler and periodic tasks...")
        start_scheduler()
        start_periodic_task()
    else:
        logger.info("Skipping scheduler in serverless mode")

    # Seed roles and permissions (with error handling)
    try:
        async with async_session() as db:
            try:
                await seed_roles_and_permissions(db)
                await db.commit()
                logger.info("Roles and permissions seeded successfully")
            except Exception as e:
                logger.error(f"Error seeding roles and permissions: {e}")
                await db.rollback()
                # Don't raise - allow app to start even if seeding fails
                # This prevents cold starts from failing if roles already exist
    except Exception as e:
        logger.error(f"Database connection error during startup: {e}")
        # Don't raise - allow app to start and handle errors per-request

    yield

    # Shutdown
    logger.info("Application shutting down...")

    # Stop scheduler and periodic tasks
    if not IS_SERVERLESS:
        logger.info("Stopping scheduler and periodic tasks...")
        stop_scheduler()
        stop_periodic_task()

    # Close database connections gracefully
    try:
        await close_db()
        logger.info("Database connections closed successfully")
    except Exception as e:
        logger.error(f"Error closing database connections: {e}")


def create_application() -> FastAPI:
    """Create the FastAPI application"""
    app = FastAPI(
        title=settings.PROJECT_NAME,
        description=settings.PROJECT_DESCRIPTION,
        version=settings.VERSION,
        docs_url=settings.DOCS_URL,
        redoc_url=None,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def https_redirect(request: Request, call_next):
        """Redirect HTTP to HTTPS in production"""
        if request.headers.get("x-forwarded-proto") == "http":
            url = request.url.replace(scheme="https")
            return RedirectResponse(url)
        return await call_next(request)

    # Enhanced CORS setup for Next.js frontend
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        allow_headers=[
            "Content-Type",
            "Authorization",
            "Accept",
            "X-Requested-With",
            "Origin",
        ],
        expose_headers=["Content-Length", "Content-Type", "Set-Cookie"],
        max_age=600,
    )

    # Logging middleware
    app.add_middleware(LoggingMiddleware)

    # Include API routes
    app.include_router(api_router, prefix=settings.API_PREFIX)

    # SQLAdmin setup (might have issues in serverless - consider disabling)
    if not IS_SERVERLESS:
        admin = Admin(app, engine, base_url="/admin")
        admin.add_view(UserAdmin)
        admin.add_view(FacilityAdmin)
        admin.add_view(BloodBankAdmin)
        admin.add_view(BloodInventoryAdmin)
    else:
        logger.warning("SQLAdmin disabled in serverless mode")

    # Custom OpenAPI config for Swagger
    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema

        openapi_schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )

        openapi_schema["components"]["securitySchemes"] = {
            "BearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
            }
        }

        # Protect routes that require authentication
        protected_paths = [
            f"{settings.API_PREFIX}/facilities",
            f"{settings.API_PREFIX}/blood-bank",
            f"{settings.API_PREFIX}/users/delete-account",
            f"{settings.API_PREFIX}/users/me",
            f"{settings.API_PREFIX}/users/auth/logout",
            f"{settings.API_PREFIX}/users/auth/sessions",
            f"{settings.API_PREFIX}/users/update-account",
            f"{settings.API_PREFIX}/blood-inventory",
            f"{settings.API_PREFIX}/blood-distribution",
            f"{settings.API_PREFIX}/track-states",
            f"{settings.API_PREFIX}/users/staff",
            f"{settings.API_PREFIX}/requests",
            f"{settings.API_PREFIX}/patients",
            f"{settings.API_PREFIX}/stats",
            f"{settings.API_PREFIX}/dashboard",
            f"{settings.API_PREFIX}/notifications",
        ]

        for path_key, path_item in openapi_schema["paths"].items():
            if any(path_key.startswith(p) for p in protected_paths):
                for method in path_item.values():
                    method.setdefault("security", []).append({"BearerAuth": []})

        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi

    # Health check endpoint
    @app.get("/")
    def read_root():
        return {
            "status": "ok",
            "serverless": IS_SERVERLESS,
            "environment": settings.ENVIRONMENT,
        }

    @app.get("/health")
    async def health_check(db: AsyncSession = Depends(get_db)):
        """Health check with database connectivity test"""
        try:
            # Test database connection
            await db.execute(select(1))
            return {
                "status": "healthy",
                "database": "connected",
                "serverless": IS_SERVERLESS,
            }
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "status": "unhealthy",
                "database": "disconnected",
                "error": str(e),
                "serverless": IS_SERVERLESS,
            }

    @app.get("/debug/roles")
    async def check_roles(db: AsyncSession = Depends(get_db)):
        """Debug endpoint to check if roles and permissions were created"""
        try:
            result = await db.execute(
                select(Role).options(selectinload(Role.permissions))
            )
            roles = result.scalars().all()

            roles_data = []
            for role in roles:
                roles_data.append(
                    {
                        "id": role.id,
                        "name": role.name,
                        "permissions": [perm.name for perm in role.permissions],
                    }
                )

            return {"total_roles": len(roles), "roles": roles_data}
        except Exception as e:
            logger.error(f"Error checking roles: {e}")
            return {"error": str(e)}

    @app.get("/debug/permissions")
    async def check_permissions(db: AsyncSession = Depends(get_db)):
        """Debug endpoint to check all permissions"""
        try:
            result = await db.execute(select(Permission))
            permissions = result.scalars().all()

            return {
                "total_permissions": len(permissions),
                "permissions": [{"id": p.id, "name": p.name} for p in permissions],
            }
        except Exception as e:
            logger.error(f"Error checking permissions: {e}")
            return {"error": str(e)}

    @app.options("/{full_path:path}")
    async def options_handler(full_path: str):
        """Handle OPTIONS requests for CORS preflight"""
        return {}

    return app


# Create and expose the FastAPI app
app = create_application()
