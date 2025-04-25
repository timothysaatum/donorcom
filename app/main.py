from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from app.routes import router as api_router
from app.config import settings
from sqladmin import Admin
from .admin.user_admin import UserAdmin
from app.database import engine
# from app.utils.security import get_current_user
from fastapi import Request

# class AuthenticatedAdmin(Admin):
#     def __init__(self, app, engine, base_url="/admin"):
#         super().__init__(app, engine, base_url)
        
#     def is_accessible(self, request: Request) -> bool:
#         """
#         Override this method to require authentication for accessing the admin panel.
#         """
#         try:
#             # Use `get_current_user` to verify if the user is authenticated
#             get_current_user(request)
#         except HTTPException:
#             # If JWT is invalid or expired, block access
#             raise HTTPException(status_code=401, detail="Access denied. Please log in.")
#         return True

def create_application() -> FastAPI:
    app = FastAPI(
        title=settings.PROJECT_NAME,
        description=settings.PROJECT_DESCRIPTION,
        version=settings.VERSION,
        docs_url=settings.DOCS_URL,
        redoc_url=None
    )

    # CORS setup
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include API routes
    app.include_router(api_router, prefix=settings.API_PREFIX)

    admin = Admin(app, engine, base_url="/admin")
    admin.add_view(UserAdmin)

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

        # Protect only specific paths
        protected_paths = [
            f"{settings.API_PREFIX}/facilities",
            f"{settings.API_PREFIX}/users/{{user_id}}",
        ]

        for path, methods in openapi_schema["paths"].items():
            if any(path.startswith(p) for p in protected_paths):
                for method in methods.values():
                    method.setdefault("security", []).append({"BearerAuth": []})

        app.openapi_schema = openapi_schema
        return app.openapi_schema

    # Assign the custom OpenAPI schema
    app.openapi = custom_openapi

    return app

# Create and expose the FastAPI app
app = create_application()
