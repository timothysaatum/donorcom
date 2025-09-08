from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Application Config
    PROJECT_NAME: str = Field(default="DonorCom API", env="PROJECT_NAME")
    PROJECT_DESCRIPTION: str = Field(
        default="Blood Bank Management System", env="PROJECT_DESCRIPTION"
    )
    VERSION: str = Field(default="1.0.0", env="VERSION")
    API_PREFIX: str = Field(default="/api", env="API_PREFIX")
    DOCS_URL: str = Field(default="/docs", env="DOCS_URL")

    # Environment
    ENVIRONMENT: str = Field(default="development", env="ENVIRONMENT")
    DEBUG: bool = Field(default=True, env="DEBUG")

    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=30, env="ACCESS_TOKEN_EXPIRE_MINUTES"
    )  # 30 minutes
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(
        default=7, env="REFRESH_TOKEN_EXPIRE_DAYS"
    )  # 7 days

    MAX_LOGIN_ATTEMPTS: int = Field(default=5, env="MAX_LOGIN_ATTEMPTS")
    ACCOUNT_LOCKOUT_DURATION_MINUTES: int = Field(
        default=15, env="ACCOUNT_LOCKOUT_DURATION_MINUTES"
    )

    # Database
    DATABASE_URL: str = Field(default="", env="DATABASE_URL")
    DATABASE_POOL_SIZE: int = Field(default=10, env="DATABASE_POOL_SIZE")
    DATABASE_MAX_OVERFLOW: int = Field(default=20, env="DATABASE_MAX_OVERFLOW")
    DATABASE_POOL_TIMEOUT: int = Field(default=30, env="DATABASE_POOL_TIMEOUT")

    # Development database fallback
    DEV_DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///./db.sqlite3", env="DEV_DATABASE_URL"
    )

    # Security
    SECRET_KEY: str = Field(default="dev-secret-key", env="SECRET_KEY")
    ALGORITHM: str = Field(default="HS256", env="ALGORITHM")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=30, env="ACCESS_TOKEN_EXPIRE_MINUTES"
    )

    # Email Configuration
    EMAIL_HOST: str = Field(default="smtp.gmail.com", env="EMAIL_HOST")
    EMAIL_PORT: int = Field(default=587, env="EMAIL_PORT")
    EMAIL_USE_TLS: bool = Field(default=True, env="EMAIL_USE_TLS")
    HOST_EMAIL: str = Field(default="", env="HOST_EMAIL")
    HOST_PASSWORD: str = Field(default="", env="HOST_PASSWORD")
    EMAIL_FROM_NAME: str = Field(default="DonorCom System", env="EMAIL_FROM_NAME")

    # CORS Configuration
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

    # Rate Limiting
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = Field(
        default=60, env="RATE_LIMIT_REQUESTS_PER_MINUTE"
    )
    LOGIN_RATE_LIMIT_PER_MINUTE: int = Field(
        default=5, env="LOGIN_RATE_LIMIT_PER_MINUTE"
    )

    # Logging
    LOG_LEVEL: str = Field(default="INFO", env="LOG_LEVEL")
    LOG_TO_FILE: bool = Field(default=True, env="LOG_TO_FILE")

    # Admin Configuration
    SYS_ADMIN: str = Field(default="admin@example.com", env="SYS_ADMIN")
    SYS_ADMIN_PASS: str = Field(default="admin123", env="SYS_ADMIN_PASS")
    ADMIN_PATH: str = Field(default="/admin", env="ADMIN_PATH")

    # Request Limits
    MAX_REQUEST_SIZE_MB: int = Field(default=10, env="MAX_REQUEST_SIZE_MB")
    REQUEST_TIMEOUT_SECONDS: int = Field(default=30, env="REQUEST_TIMEOUT_SECONDS")
    MAX_FILE_SIZE_MB: int = Field(default=5, env="MAX_FILE_SIZE_MB")

    # Maintenance
    MAINTENANCE_MODE: bool = Field(default=False, env="MAINTENANCE_MODE")

    # Pydantic v2 config
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",  # This will ignore extra fields in .env that aren't defined here
    )

    def model_post_init(self, __context) -> None:
        """Post-initialization validation and setup"""
        # Handle CORS origins from comma-separated string
        if isinstance(self.BACKEND_CORS_ORIGINS, str):
            self.BACKEND_CORS_ORIGINS = [
                origin.strip() for origin in self.BACKEND_CORS_ORIGINS.split(",")
            ]

        # Handle DATABASE_URL logic
        if self.ENVIRONMENT.lower() == "production":
            # In production, require DATABASE_URL to be explicitly set
            if not self.DATABASE_URL:
                raise ValueError("DATABASE_URL must be set in production!")
            # Validate required fields in production
            if not self.SECRET_KEY or self.SECRET_KEY == "dev-secret-key":
                raise ValueError(
                    "SECRET_KEY must be set to a secure value in production!"
                )
            if not self.HOST_EMAIL:
                raise ValueError("HOST_EMAIL must be set in production!")
            if not self.HOST_PASSWORD:
                raise ValueError("HOST_PASSWORD must be set in production!")
        else:
            # In development, use DATABASE_URL if provided, otherwise fall back to DEV_DATABASE_URL
            if not self.DATABASE_URL:
                self.DATABASE_URL = self.DEV_DATABASE_URL


# Instantiate settings
settings = Settings()
