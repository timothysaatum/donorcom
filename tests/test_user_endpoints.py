import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException, FastAPI
import httpx
from datetime import datetime
from uuid import uuid4
import os

# Import your modules
from app.models.user import User
from app.routes.auth import TokenManager, router as auth_router
from app.routes.users import router as users_router
from app.utils.security import get_password_hash

pytestmark = pytest.mark.asyncio



class TestAuthEndpoints:
    """Test cases for authentication endpoints"""
    
    def setup_method(self):
        # Create FastAPI app with the auth router
        self.app = FastAPI()
        self.app.include_router(auth_router)
        self.sample_user_id = uuid4()
        self.sample_facility_id = uuid4()
    
    @pytest.fixture
    def sample_user(self):
        return User(
            id=self.sample_user_id,
            email="healfibre@gmail.com",
            first_name="John",
            last_name="Doe",
            password=get_password_hash("Password123"),
            role="staff",
            is_verified=True,
            is_active=True,
            created_at=datetime.now()
        )
    
    @pytest.fixture
    def login_data(self):
        return {
            "email": "healfibre@gmail.com",
            "password": "Password123"
        }
    
    # 
    async def test_login_success(self, login_data, sample_user):
        """Test successful login"""
        with patch('app.dependencies.get_db') as mock_get_db, \
             patch('app.services.user_service.UserService.authenticate_user') as mock_auth, \
             patch('app.routes.auth.select') as mock_select:  # Mock the select query

            mock_db = AsyncMock()
            mock_get_db.return_value = mock_db
            
            # Mock the database query result for user lookup
            mock_result = AsyncMock()
            mock_result.scalar_one_or_none.return_value = sample_user
            mock_db.execute.return_value = mock_result
            
            # Set sample_user as verified to avoid email verification logic
            sample_user.is_verified = True

            # Mock authenticate_user to return success
            mock_auth.return_value = {
                "access_token": "test_token",
                "user": {"id": str(sample_user.id), "email": sample_user.email}
            }

            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test") as client:
                response = await client.post("/users/auth/login", json=login_data)

            assert response.status_code == 200
    
    async def test_login_invalid_credentials(self, login_data):
        """Test login with invalid credentials"""
        with patch('app.dependencies.get_db') as mock_get_db, \
             patch('app.routes.auth.select') as mock_select:

            mock_db = AsyncMock()
            mock_get_db.return_value = mock_db
            
            # Mock the database query to return None (user not found)
            mock_result = AsyncMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_db.execute.return_value = mock_result

            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test") as client:
                response = await client.post("/users/auth/login", json=login_data)

            assert response.status_code == 400
    
    async def test_refresh_token_success(self, sample_user):
        """Test successful token refresh"""
        with patch.dict(os.environ, {'SECRET_KEY': 'test-secret-key'}):
            refresh_token = TokenManager.create_refresh_token(sample_user.id)
        
        with patch('app.dependencies.get_db') as mock_get_db:
            
            mock_db = AsyncMock()
            mock_get_db.return_value = mock_db
            
            # Mock database query to return user
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = sample_user
            mock_db.execute.return_value = mock_result
            
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test") as client:
                response = await client.get(
                    "/users/auth/refresh",
                    cookies={"refresh_token": refresh_token}
                )
            
            assert response.status_code == 200
            data = response.json()
            assert "data" in data
            assert "access_token" in data["data"]
    
    async def test_refresh_token_missing(self):
        """Test refresh token when no token provided"""
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test") as client:
            response = await client.get("/users/auth/refresh")
        
        assert response.status_code == 401
        assert "No refresh token provided" in response.json()["detail"]
    
    async def test_refresh_token_invalid(self):
        """Test refresh token with invalid token"""
        with patch.dict(os.environ, {'SECRET_KEY': 'test-secret-key'}):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test") as client:
                response = await client.get(
                    "/users/auth/refresh",
                    cookies={"refresh_token": "invalid_token"}
                )
            
            assert response.status_code == 401
            assert "Invalid or expired refresh token" in response.json()["detail"]
    
    async def test_logout_success(self):
        """Test successful logout"""
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test") as client:
            response = await client.post("/users/auth/logout")
        
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["message"] == "Logged out successfully"


class TestUserEndpoints:
    """Test cases for user management endpoints"""
    
    def setup_method(self):
        # Create FastAPI app with the users router
        self.app = FastAPI()
        self.app.include_router(users_router)
        self.sample_user_id = uuid4()
        self.sample_facility_id = uuid4()
    
    @pytest.fixture
    def sample_user(self):
        return User(
            id=self.sample_user_id,
            email="healfibre@gmail.com",
            first_name="John",
            last_name="Doe",
            password=get_password_hash("Password123"),
            role="staff",
            is_verified=True,
            is_active=True,
            created_at=datetime.now()
        )
    
    @pytest.fixture
    def admin_user(self):
        return User(
            id=uuid4(),
            email="admin@example.com",
            first_name="Admin",
            last_name="User",
            password=get_password_hash("Password123"),
            role="facility_administrator",
            is_verified=True,
            is_active=True,
            created_at=datetime.now()
        )
    
    @pytest.fixture
    def user_create_data(self):
        return {
            "email": "newuser@example.com",
            "first_name": "New",
            "last_name": "User",
            "password": "Password123",
            "password_confirm": "Password123",
            "role": "staff",
            "phone": "1234567890"
        }
    
    async def test_create_user_success(self, user_create_data):
        """Test successful user creation"""
        with patch('app.dependencies.get_db') as mock_get_db, \
             patch('app.services.user_service.UserService.create_user') as mock_create:

            mock_db = AsyncMock()
            mock_get_db.return_value = mock_db

            # Create a proper UserResponse object that matches your schema
            from app.schemas.user import UserResponse
            created_user_data = {
                "id": str(uuid4()),
                "email": user_create_data["email"],
                "first_name": user_create_data["first_name"],
                "last_name": user_create_data["last_name"],
                "role": user_create_data.get("role", "staff"),
                "is_verified": False,
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
                "last_login": None
            }
            
            # Mock create_user to return UserResponse object
            mock_create.return_value = UserResponse(**created_user_data)

            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test") as client:
                response = await client.post("/users/register", json=user_create_data)

            assert response.status_code == 201
    
    async def test_get_me_success(self, sample_user):
        """Test successful current user retrieval"""
        with patch('app.utils.security.get_current_user') as mock_get_current_user, \
             patch('app.dependencies.get_db') as mock_get_db:
            
            mock_get_current_user.return_value = sample_user
            mock_db = AsyncMock()
            mock_get_db.return_value = mock_db

            # Create a mock access token and add it to headers
            headers = {"Authorization": "Bearer mock_token"}

            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test") as client:
                response = await client.get("/users/me", headers=headers)

            assert response.status_code == 200
    
    async def test_update_user_success(self, sample_user):
        """Test successful user update"""
        update_data = {
            "first_name": "Updated",
            "last_name": "Name"
        }

        with patch('app.dependencies.get_db') as mock_get_db, \
             patch('app.utils.security.get_current_user') as mock_get_current_user, \
             patch('app.services.user_service.UserService.update_user') as mock_update:

            mock_db = AsyncMock()
            mock_get_db.return_value = mock_db
            mock_get_current_user.return_value = sample_user

            # Mock successful update
            updated_user = sample_user
            updated_user.first_name = "Updated"
            updated_user.last_name = "Name"
            mock_update.return_value = updated_user

            headers = {"Authorization": "Bearer mock_token"}

            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test") as client:
                response = await client.patch(
                    f"/users/update-account/{sample_user.id}",
                    json=update_data,
                    headers=headers
                )

            assert response.status_code == 200
    
    async def test_update_user_permission_denied(self, sample_user):
        """Test user update with insufficient permissions"""
        other_user_id = uuid4()
        update_data = {"first_name": "Updated"}
        
        with patch('app.utils.security.get_current_user') as mock_get_current_user:
            mock_get_current_user.return_value = sample_user
            
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test") as client:
                response = await client.patch(
                    f"users/update-account/{other_user_id}",
                    json=update_data
                )
            
            assert response.status_code == 403
    
    async def test_delete_user_success(self, sample_user):
        """Test successful user deletion"""
        with patch('app.dependencies.get_db') as mock_get_db, \
             patch('app.utils.security.get_current_user') as mock_get_current_user, \
             patch('app.services.user_service.UserService.delete_user') as mock_delete:
            
            mock_db = AsyncMock()
            mock_get_db.return_value = mock_db
            mock_get_current_user.return_value = sample_user
            
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test") as client:
                response = await client.delete(f"users/delete-account/{sample_user.id}")
            
            assert response.status_code == 204
    
    async def test_create_staff_user_success(self, admin_user, user_create_data):
        """Test successful staff user creation by admin"""
        # Mock facility for admin user
        facility_mock = MagicMock()
        facility_mock.id = self.sample_facility_id
        admin_user.facility = facility_mock
        
        with patch('app.dependencies.get_db') as mock_get_db, \
             patch('app.utils.security.get_current_user') as mock_get_current_user, \
             patch('app.services.user_service.UserService.create_user') as mock_create:
            
            mock_db = AsyncMock()
            mock_get_db.return_value = mock_db
            mock_get_current_user.return_value = admin_user
            
            # Mock successful staff creation
            created_user = User(
                id=uuid4(),
                email=user_create_data["email"],
                first_name=user_create_data["first_name"],
                last_name=user_create_data["last_name"]
            )
            mock_create.return_value = created_user
            
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test") as client:
                response = await client.post("users/staff/create", json=user_create_data)
            
            assert response.status_code == 201
    
    async def test_create_staff_user_permission_denied(self, sample_user, user_create_data):
        """Test staff user creation with insufficient permissions"""
        with patch('app.utils.security.get_current_user') as mock_get_current_user:
            mock_get_current_user.return_value = sample_user
            
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test") as client:
                response = await client.post("users/staff/create", json=user_create_data)
            
            assert response.status_code == 403
    
    async def test_get_all_staff_users_success(self, admin_user):
        """Test successful staff users retrieval"""
        # Mock facility for admin user
        facility_mock = MagicMock()
        facility_mock.id = self.sample_facility_id
        admin_user.facility = facility_mock
        
        with patch('app.dependencies.get_db') as mock_get_db, \
             patch('app.utils.security.get_current_user') as mock_get_current_user, \
             patch('app.services.user_service.UserService.get_all_staff_users') as mock_get_staff:
            
            mock_db = AsyncMock()
            mock_get_db.return_value = mock_db
            mock_get_current_user.return_value = admin_user
            
            # Mock staff users
            staff_users = [
                User(id=uuid4(), email="staff1@example.com", role="staff"),
                User(id=uuid4(), email="staff2@example.com", role="lab_manager")
            ]
            mock_get_staff.return_value = staff_users
            
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test") as client:
                response = await client.get("users/staff")
            
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 2