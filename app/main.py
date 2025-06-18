from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from app.routes import router as api_router
from app.config import settings
from sqladmin import Admin
from .admin.user_admin import UserAdmin
from .admin.facility_admin import FacilityAdmin
from .admin.blood_bank_admin import BloodBankAdmin
from .admin.inventory import BloodInventoryAdmin
from app.database import engine

def create_application() -> FastAPI:
    app = FastAPI(
        title=settings.PROJECT_NAME,
        description=settings.PROJECT_DESCRIPTION,
        version=settings.VERSION,
        docs_url=settings.DOCS_URL,
        redoc_url=None
    )

    # Enhanced CORS setup for Next.js frontend
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "Accept", "X-Requested-With", "Origin"],
        expose_headers=["Content-Length", "Content-Type", "Set-Cookie"],
        max_age=600,  # Cache preflight requests for 10 minutes
    )

    # Include API routes
    app.include_router(api_router, prefix=settings.API_PREFIX)

    admin = Admin(app, engine, base_url="/admin")
    admin.add_view(UserAdmin)
    admin.add_view(FacilityAdmin)
    admin.add_view(BloodBankAdmin)
    admin.add_view(BloodInventoryAdmin)

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
            f"{settings.API_PREFIX}/users/update-account",
            f"{settings.API_PREFIX}/users/delete-account",
            f"{settings.API_PREFIX}/users/me",
            f"{settings.API_PREFIX}/blood-inventory",
            f"{settings.API_PREFIX}/blood-distribution",
            f"{settings.API_PREFIX}/track-states",
            f"{settings.API_PREFIX}/users/staff",
        ]

        for path_key, path_item in openapi_schema["paths"].items():
            # Check if the path should be protected
            if any(path_key.startswith(p) for p in protected_paths):
                # Apply security to all methods in this path
                for method in path_item.values():
                    method.setdefault("security", []).append({"BearerAuth": []})

        app.openapi_schema = openapi_schema
        return app.openapi_schema

    # Assign the custom OpenAPI schema
    app.openapi = custom_openapi

    @app.options("/{full_path:path}")
    async def options_handler(full_path: str):
        """Handle OPTIONS requests - often needed for CORS preflight requests"""
        return {}

    return app

# Create and expose the FastAPI app
app = create_application()