# from pydantic import Field
# from pydantic_settings import BaseSettings, SettingsConfigDict

# class Settings(BaseSettings):

#     # Application Config
#     PROJECT_NAME: str = "DonorCom API"
#     PROJECT_DESCRIPTION: str = "Blood Bank Management System"
#     VERSION: str = "1.0.0"
#     API_PREFIX: str = "/api"
#     DOCS_URL: str = "/docs"

#     # Database
#     DATABASE_URL: str = Field(..., env="DATABASE_URL")
#     TEST_DATABASE_URL: str = Field(default="sqlite:///./test.db")

#     # Security
#     SECRET_KEY: str = Field(..., env="SECRET_KEY")
#     ALGORITHM: str = Field(..., env="ALGORITHM")
#     ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=60 * 24 * 7)
#     HOST_EMAIL: str = Field(..., env="HOST_EMAIL")
#     HOST_PASSWORD: str = Field(..., env="HOST_PASSWORD")

#     # CORS
#     # origins = [
#     # 'http://localhost:3000',
#     # 'http://localhost:3001',
#     # 'https:haemolync.com'
#     # ]

#     BACKEND_CORS_ORIGINS: list[str] = Field(default=["*"])

#     # New in Pydantic v2
#     model_config = SettingsConfigDict(
#         env_file=".env",
#         env_file_encoding="utf-8",
#         case_sensitive=True,
#         extra="ignore"
#     )

# settings = Settings()
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):

    # Application Config
    PROJECT_NAME: str = "DonorCom API"
    PROJECT_DESCRIPTION: str = "Blood Bank Management System"
    VERSION: str = "1.0.0"
    API_PREFIX: str = "/api"
    DOCS_URL: str = "/docs"

    # Database
    DATABASE_URL: str = Field(..., env="DATABASE_URL")
    TEST_DATABASE_URL: str = Field(default="sqlite:///./test.db")

    # Security
    SECRET_KEY: str = Field(..., env="SECRET_KEY")
    ALGORITHM: str = Field(..., env="ALGORITHM")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=60 * 24 * 7)
    HOST_EMAIL: str = Field(..., env="HOST_EMAIL")
    HOST_PASSWORD: str = Field(..., env="HOST_PASSWORD")

    # CORS
    BACKEND_CORS_ORIGINS: list[str] = Field(
        default=[
            "http://localhost:3000",  # Next.js default dev server
            "http://localhost:3001",  # Alternative Next.js port
            "http://localhost",
            "https://haemolync.com",  # Production domain
            "https://www.haemolync.com",  # Production domain with www
        ]
    )

    # New in Pydantic v2
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )

settings = Settings()