"""
Test configuration and fixtures for hospital blood request management system.
Provides test database setup, authentication helpers, and data fixtures.
"""

import pytest
import asyncio
import sys
from pathlib import Path
from typing import AsyncGenerator, Generator
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import os
from uuid import uuid4
from datetime import datetime, timedelta, timezone

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Test database configuration
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

# Override environment variables for testing
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("TESTING", "true")
os.environ.setdefault("DATABASE_URL", TEST_DATABASE_URL)
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-jwt-tokens")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "30")

from app.main import app
from app.db.base import Base
from app.models.user_model import User
from app.models.health_facility_model import Facility
from app.models.request_model import BloodRequest
from app.services.user_service import UserService
from app.dependencies import get_db

# Test database URL (in-memory SQLite for fast tests)
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

# Test async engine
test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    echo=False,  # Set to True for SQL debugging
)

# Test session maker
TestingSessionLocal = sessionmaker(
    test_engine, class_=AsyncSession, expire_on_commit=False
)


@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def test_db_setup() -> AsyncGenerator[None, None]:
    """Set up test database schema."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def db_session(test_db_setup) -> AsyncGenerator[AsyncSession, None]:
    """Create a fresh database session for each test."""
    async with TestingSessionLocal() as session:
        yield session
        await session.rollback()


@pytest.fixture
def client(db_session: AsyncSession) -> TestClient:
    """Create test client with overridden database dependency."""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# --- Data Factories ---


class TestDataFactory:
    """Factory for creating test data with realistic hospital scenarios."""

    @staticmethod
    def unique_email(prefix: str = "test") -> str:
        """Generate unique email for testing."""
        return f"{prefix}_{uuid4().hex[:8]}@hospital.com"

    @staticmethod
    def create_facility_data(name: str = None) -> dict:
        """Create test facility data."""
        return {
            "name": name or f"Test Hospital {uuid4().hex[:4]}",
            "address": "123 Medical Center Drive",
            "contact_phone": "+233244000000",
            "email": TestDataFactory.unique_email("facility"),
            "facility_type": "hospital",
            "region": "GH-AA",  # Ghana Accra region
            "description": "Test hospital facility",
            "is_active": True,
        }


    @staticmethod
    def create_blood_request_data(
        facility_id: str, patient_id: str, requester_id: str
    ) -> dict:
        """Create test blood request data."""
        return {
            "facility_id": facility_id,
            "patient_id": patient_id,
            "blood_type": "A+",
            "quantity": 2,
            "priority": "urgent",
            "requester_id": requester_id,
            "requested_date": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
        }

    @staticmethod
    def create_inventory_data(blood_bank_id: str) -> dict:
        """Create test blood inventory data."""
        return {
            "blood_bank_id": blood_bank_id,
            "blood_type": "A+",
            "product_type": "whole_blood",
            "quantity": 10,
            "expiry_date": (datetime.now() + timedelta(days=30)).date().isoformat(),
            "donation_date": datetime.now().date().isoformat(),
            "storage_temperature": 4.0,
            "lot_number": f"LOT{uuid4().hex[:8]}",
            "status": "available",
        }


# --- Authentication Fixtures ---


@pytest.fixture
async def test_facility(db_session: AsyncSession) -> Facility:
    """Create a test facility."""
    from app.services.facility_service import FacilityService

    facility_data = TestDataFactory.create_facility_data("Test Hospital")
    facility = await FacilityService.create_facility(db_session, facility_data)
    await db_session.commit()
    return facility


@pytest.fixture
async def test_user(db_session: AsyncSession, test_facility: Facility) -> User:
    """Create a test user directly in database to bypass registration restrictions."""
    user_data = TestDataFactory.create_user_data(
        role="patient", facility_id=str(test_facility.id)  # Changed to patient role
    )

    # Create user directly in database
    user = User(
        email=user_data["email"],
        first_name=user_data["first_name"],
        last_name=user_data["last_name"],
        phone_number=user_data["phone_number"],
        role=user_data["role"],
        password_hash="$2b$12$LKPKlgXBm7E7YfWYqTKdYOBjXUhToMBYKJvhF/rPjHNhJHNIYSyxK",  # SecurePass123!
        is_active=True,
        email_verified=True,
    )

    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def admin_user(db_session: AsyncSession, test_facility: Facility) -> User:
    """Create an admin user directly in database."""
    user_data = TestDataFactory.create_user_data(
        role="facility_administrator", facility_id=str(test_facility.id)
    )
    user_data["email"] = "admin@test.hospital.gh"  # Ensure unique email

    # Create admin user directly in database
    user = User(
        email=user_data["email"],
        first_name=user_data["first_name"],
        last_name=user_data["last_name"],
        phone_number=user_data["phone_number"],
        role=user_data["role"],
        password_hash="$2b$12$LKPKlgXBm7E7YfWYqTKdYOBjXUhToMBYKJvhF/rPjHNhJHNIYSyxK",  # SecurePass123!
        is_active=True,
        email_verified=True,
    )

    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def lab_manager_user(db_session: AsyncSession, test_facility: Facility) -> User:
    """Create a lab manager user directly in database."""
    user_data = TestDataFactory.create_user_data(
        role="lab_manager", facility_id=str(test_facility.id)
    )
    user_data["email"] = "lab.manager@test.hospital.gh"  # Ensure unique email

    # Create lab manager user directly in database
    user = User(
        email=user_data["email"],
        first_name=user_data["first_name"],
        last_name=user_data["last_name"],
        phone_number=user_data["phone_number"],
        role=user_data["role"],
        password_hash="$2b$12$LKPKlgXBm7E7YfWYqTKdYOBjXUhToMBYKJvhF/rPjHNhJHNIYSyxK",  # SecurePass123!
        is_active=True,
        email_verified=True,
    )

    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def auth_headers(client: TestClient) -> dict:
    """Get authentication headers for a patient user."""
    # Create a simple user for authentication testing
    user_data = {
        "email": "test.patient@hospital.gh",
        "password": "SecurePass123!",
        "confirm_password": "SecurePass123!",
        "first_name": "Test",
        "last_name": "Patient",
        "phone_number": "+233244000000",
        "role": "patient",  # Use patient role which doesn't require admin approval
    }

    # Register user
    register_response = client.post("/api/users/register", json=user_data)
    if register_response.status_code != 201:
        # If registration fails, try login with existing user
        login_data = {"email": user_data["email"], "password": user_data["password"]}
        login_response = client.post("/api/users/auth/login", data=login_data)
        if login_response.status_code == 200:
            token = login_response.json()["data"]["access_token"]
            return {"Authorization": f"Bearer {token}"}
        else:
            # Return empty headers for tests that expect authentication to fail
            return {}

    # Login with the registered user
    login_data = {"email": user_data["email"], "password": user_data["password"]}
    login_response = client.post("/api/users/auth/login", data=login_data)

    if login_response.status_code == 200:
        token = login_response.json()["data"]["access_token"]
        return {"Authorization": f"Bearer {token}"}
    else:
        return {}


@pytest.fixture
def admin_auth_headers(client: TestClient) -> dict:
    """Get authentication headers for admin user."""
    # Create admin user data
    admin_data = {
        "email": "test.admin@hospital.gh",
        "password": "SecurePass123!",
        "confirm_password": "SecurePass123!",
        "first_name": "Test",
        "last_name": "Admin",
        "phone_number": "+233244000001",
        "role": "facility_administrator",
    }

    # Try to register admin (this might fail due to restrictions)
    client.post("/api/users/register", json=admin_data)

    # Try to login (assuming admin exists or was created by seed data)
    login_data = {"email": admin_data["email"], "password": admin_data["password"]}
    login_response = client.post("/api/users/auth/login", data=login_data)

    if login_response.status_code == 200:
        token = login_response.json()["data"]["access_token"]
        return {"Authorization": f"Bearer {token}"}
    else:
        return {}


# --- Utility Functions ---


def assert_response_success(response, expected_status: int = 200):
    """Assert response is successful with proper structure."""
    assert response.status_code == expected_status
    data = response.json()
    assert "success" in data
    assert data["success"] is True
    assert "data" in data
    return data["data"]


def assert_response_error(response, expected_status: int = 400):
    """Assert response is an error with proper structure."""
    assert response.status_code == expected_status
    data = response.json()
    assert "success" in data
    assert data["success"] is False
    assert "message" in data
    return data


def assert_validation_error(response, field_name: str = None):
    """Assert response is a validation error."""
    assert response.status_code == 422
    data = response.json()
    if field_name:
        assert any(error["loc"][-1] == field_name for error in data.get("detail", []))


# --- Performance Testing Utilities ---


class PerformanceTimer:
    """Context manager for measuring test performance."""

    def __init__(self, max_duration_ms: int = 1000):
        self.max_duration_ms = max_duration_ms
        self.start_time = None
        self.end_time = None

    def __enter__(self):
        import time

        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        import time

        self.end_time = time.perf_counter()
        duration_ms = (self.end_time - self.start_time) * 1000
        assert (
            duration_ms < self.max_duration_ms
        ), f"Test took {duration_ms:.2f}ms, expected < {self.max_duration_ms}ms"

    @property
    def duration_ms(self) -> float:
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time) * 1000
        return 0.0


@pytest.fixture
def performance_timer():
    """Fixture for performance testing."""
    return PerformanceTimer
