from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Application Config
    PROJECT_NAME: str = "DonorCom API"
    PROJECT_DESCRIPTION: str = "Blood Bank Management System"
    VERSION: str = "1.0.0"
    API_PREFIX: str = "/api"
    DOCS_URL: str = "/docs"

    # Environment
    ENVIRONMENT: str = Field("development", env="ENVIRONMENT")

    # Database
    DATABASE_URL: str = Field(default=None, env="DATABASE_URL")
    DEV_DATABASE_URL: str = Field(default="sqlite+aiosqlite:///./db.sqlite3")

    # Security
    SECRET_KEY: str = Field(..., env="SECRET_KEY")
    ALGORITHM: str = Field(..., env="ALGORITHM")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=60 * 24 * 7)
    HOST_EMAIL: str = Field(..., env="HOST_EMAIL")
    HOST_PASSWORD: str = Field(..., env="HOST_PASSWORD")

    BACKEND_CORS_ORIGINS: list[str] = Field(
        default=[
            # Development origins
            "http://localhost:3000",
            "http://localhost",

            # Production frontend origins
            "https://hemolync.vercel.app",
            "https://hemolync.donorcom.org",
            "https://www.hemolync.donorcom.org",
        ]
    )

    # Pydantic v2 config
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )

    def __init__(self, **values):
        super().__init__(**values)
        # Prod requires DATABASE_URL
        if self.ENVIRONMENT.lower() == "production":
            if not self.DATABASE_URL:
                raise ValueError("DATABASE_URL must be set in production!")
        else:
            # Dev fallback to SQLite if no DATABASE_URL
            self.DATABASE_URL = self.DATABASE_URL or self.DEV_DATABASE_URL

# Instantiate settings
settings = Settings()
