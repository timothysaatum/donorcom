import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException, Response
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import datetime, timedelta, timezone
from uuid import uuid4, UUID
from jose import jwt

# Import your modules
from app.models.user import User
from app.models.health_facility import Facility
from app.schemas.user import UserCreate, UserUpdate, LoginSchema, AuthResponse, UserWithFacility
from app.services.user_service import UserService
from app.auth import TokenManager, router as auth_router
from app.routes.users import router as users_router
from app.utils.security import get_password_hash, verify_password, create_verification_token


class TestTokenManager:
    """Test cases for TokenManager class"""
    
    def setup_method(self):
        self.secret_key = "test-secret-key"
        self.algorithm = "HS256"
        self.user_id = uuid4()
        
        # Mock environment variables
        with patch.dict('os.environ', {'SECRET_KEY': self.secret_key}):
            self.token_manager = TokenManager()
    
    def test_create_access_token_default_expiry(self):
        """Test creating access token with default expiry"""
        data = {"sub": str(self.user_id)}
        
        with patch.dict('os.environ', {'SECRET_KEY': self.secret_key}):
            token = TokenManager.create_access_token(data)
        
        # Decode and verify token
        decoded = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
        assert decoded["sub"] == str(self.user_id)
        assert decoded["type"] == "access"
        assert "exp" in decoded
    
    def test_create_access_token_custom_expiry(self):
        """Test creating access token with custom expiry"""
        data = {"sub": str(self.user_id)}
        expires_delta = timedelta(minutes=30)
        
        with patch.dict('os.environ', {'SECRET_KEY': self.secret_key}):
            token = TokenManager.create_access_token(data, expires_delta)
        
        decoded = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
        assert decoded["sub"] == str(self.user_id)
        assert decoded["type"] == "access"
    
    def test_create_refresh_token(self):
        """Test creating refresh token"""
        with patch.dict('os.environ', {'SECRET_KEY': self.secret_key}):
            token = TokenManager.create_refresh_token(self.user_id)
        
        decoded = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
        assert decoded["sub"] == str(self.user_id)
        assert decoded["type"] == "refresh"
        assert "jti" in decoded
        assert "exp" in decoded
    
    def test_decode_token_success(self):
        """Test successful token decoding"""
        data = {"sub": str(self.user_id), "type": "access"}
        
        with patch.dict('os.environ', {'SECRET_KEY': self.secret_key}):
            token = jwt.encode(data, self.secret_key, algorithm=self.algorithm)
            decoded = TokenManager.decode_token(token)
        
        assert decoded["sub"] == str(self.user_id)
        assert decoded["type"] == "access"
    
    def test_decode_token_invalid(self):
        """Test decoding invalid token"""
        with patch.dict('os.environ', {'SECRET_KEY': self.secret_key}):
            with pytest.raises(ValueError, match="Invalid or expired token"):
                TokenManager.decode_token("invalid-token")
    
    def test_decode_token_expired(self):
        """Test decoding expired token"""
        past_time = datetime.now(timezone.utc) - timedelta(hours=1)
        data = {"sub": str(self.user_id), "exp": past_time.timestamp()}
        
        with patch.dict('os.environ', {'SECRET_KEY': self.secret_key}):
            token = jwt.encode(data, self.secret_key, algorithm=self.algorithm)
            with pytest.raises(ValueError, match="Invalid or expired token"):
                TokenManager.decode_token(token)


class TestUserService:
    """Test cases for UserService class"""
    
    def setup_method(self):
        self.db_mock = AsyncMock(spec=AsyncSession)
        self.user_service = UserService(self.db_mock)
        self.sample_user_id = uuid4()
        self.sample_facility_id = uuid4()
    
    @pytest.fixture
    def sample_user_data(self):
        return UserCreate(
            email="test@example.com",
            first_name="John",
            last_name="Doe",
            password="Password123",
            password_confirm="Password123",
            role="staff",
            phone="1234567890"
        )
    
    @pytest.fixture
    def sample_user(self):
        return User(
            id=self.sample_user_id,
            email="test@example.com",
            first_name="John",
            last_name="Doe",
            password=get_password_hash("Password123"),
            role="staff",
            phone="1234567890",
            is_verified=True,
            is_active=True,
            created_at=datetime.now(),
            last_login=None
        )
    
    async def test_create_user_success(self, sample_user_data):
        """Test successful user creation"""
        # Mock database query to return None (no existing user)
        self.db_mock.execute.return_value.scalar_one_or_none.return_value = None
        
        with patch('app.utils.security.get_password_hash') as mock_hash, \
             patch('app.utils.security.create_verification_token') as mock_token:
            
            mock_hash.return_value = "hashed_password"
            mock_token.return_value = "verification_token"
            
            result = await self.user_service.create_user(sample_user_data)
            
            # Verify database operations
            self.db_mock.add.assert_called_once()
            self.db_mock.commit.assert_called_once()
            self.db_mock.refresh.assert_called_once()
    
    async def test_create_user_email_already_exists(self, sample_user_data, sample_user):
        """Test user creation with existing email"""
        # Mock database query to return existing user
        self.db_mock.execute.return_value.scalar_one_or_none.return_value = sample_user
        
        with pytest.raises(HTTPException) as exc_info:
            await self.user_service.create_user(sample_user_data)
        
        assert exc_info.value.status_code == 400
        assert "Email already registered" in str(exc_info.value.detail)
    
    async def test_authenticate_user_success(self, sample_user):
        """Test successful user authentication"""
        # Mock database query to return user
        self.db_mock.execute.return_value.scalar_one_or_none.return_value = sample_user
        
        with patch('app.utils.security.verify_password') as mock_verify, \
             patch('app.utils.security.create_access_token') as mock_token:
            
            mock_verify.return_value = True
            mock_token.return_value = "access_token"
            
            result = await self.user_service.authenticate_user("test@example.com", "Password123")
            
            assert "access_token" in result
            assert "user" in result
            assert result["access_token"] == "access_token"
            
            # Verify last login was updated
            self.db_mock.commit.assert_called_once()
    
    async def test_authenticate_user_invalid_credentials(self):
        """Test authentication with invalid credentials"""
        # Mock database query to return None
        self.db_mock.execute.return_value.scalar_one_or_none.return_value = None
        
        with pytest.raises(HTTPException) as exc_info:
            await self.user_service.authenticate_user("test@example.com", "wrong_password")
        
        assert exc_info.value.status_code == 401
        assert "Invalid credentials" in str(exc_info.value.detail)
    
    async def test_authenticate_user_not_verified(self, sample_user):
        """Test authentication with unverified user"""
        sample_user.is_verified = False
        self.db_mock.execute.return_value.scalar_one_or_none.return_value = sample_user
        
        with patch('app.utils.security.verify_password') as mock_verify:
            mock_verify.return_value = True
            
            with pytest.raises(HTTPException) as exc_info:
                await self.user_service.authenticate_user("test@example.com", "Password123")
            
            assert exc_info.value.status_code == 400
            assert "User email not verified" in str(exc_info.value.detail)
    
    async def test_get_user_success(self, sample_user):
        """Test successful user retrieval"""
        self.db_mock.execute.return_value.scalar_one_or_none.return_value = sample_user
        
        result = await self.user_service.get_user(self.sample_user_id)
        
        assert result == sample_user
        self.db_mock.execute.assert_called_once()
    
    async def test_get_user_not_found(self):
        """Test user retrieval when user doesn't exist"""
        self.db_mock.execute.return_value.scalar_one_or_none.return_value = None
        
        result = await self.user_service.get_user(self.sample_user_id)
        
        assert result is None
    
    async def test_update_user_success(self, sample_user):
        """Test successful user update"""
        self.db_mock.execute.return_value.scalar_one_or_none.return_value = sample_user
        
        update_data = UserUpdate(first_name="Jane", last_name="Smith")
        
        result = await self.user_service.update_user(self.sample_user_id, update_data)
        
        assert sample_user.first_name == "Jane"
        assert sample_user.last_name == "Smith"
        self.db_mock.commit.assert_called_once()
        self.db_mock.refresh.assert_called_once()
    
    async def test_update_user_not_found(self):
        """Test user update when user doesn't exist"""
        self.db_mock.execute.return_value.scalar_one_or_none.return_value = None
        
        update_data = UserUpdate(first_name="Jane")
        
        with pytest.raises(HTTPException) as exc_info:
            await self.user_service.update_user(self.sample_user_id, update_data)
        
        assert exc_info.value.status_code == 404
        assert "User not Found" in str(exc_info.value.detail)
    
    async def test_delete_user_success(self, sample_user):
        """Test successful user deletion"""
        self.db_mock.execute.return_value.scalar_one_or_none.return_value = sample_user
        
        await self.user_service.delete_user(self.sample_user_id)
        
        self.db_mock.delete.assert_called_once_with(sample_user)
        self.db_mock.commit.assert_called_once()
    
    async def test_delete_user_not_found(self):
        """Test user deletion when user doesn't exist"""
        self.db_mock.execute.return_value.scalar_one_or_none.return_value = None
        
        with pytest.raises(HTTPException) as exc_info:
            await self.user_service.delete_user(self.sample_user_id)
        
        assert exc_info.value.status_code == 404
        assert "User not found" in str(exc_info.value.detail)
    
    async def test_get_all_staff_users_success(self):
        """Test successful staff users retrieval"""
        staff_users = [
            User(id=uuid4(), email="staff1@example.com", role="staff"),
            User(id=uuid4(), email="staff2@example.com", role="lab_manager")
        ]
        
        self.db_mock.execute.return_value.scalars.return_value.all.return_value = staff_users
        
        result = await self.user_service.get_all_staff_users(self.sample_facility_id)
        
        assert len(result) == 2
        assert all(user.role in ["staff", "lab_manager"] for user in result)


class TestAuthEndpoints:
    """Test cases for authentication endpoints"""
    
    def setup_method(self):
        self.client = TestClient(auth_router)
        self.sample_user_id = uuid4()
        self.sample_facility_id = uuid4()
    
    @pytest.fixture
    def sample_user(self):
        return User(
            id=self.sample_user_id,
            email="test@example.com",
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
            "email": "test@example.com",
            "password": "Password123"
        }
    
    async def test_login_success(self, login_data, sample_user):
        """Test successful login"""
        with patch('app.dependencies.get_db') as mock_get_db, \
             patch('app.services.user_service.UserService') as mock_user_service:
            
            mock_db = AsyncMock()
            mock_get_db.return_value = mock_db
            
            # Mock database query
            mock_db.execute.return_value.scalar_one_or_none.return_value = sample_user
            
            # Mock user service
            mock_service_instance = AsyncMock()
            mock_user_service.return_value = mock_service_instance
            mock_service_instance.authenticate_user.return_value = {
                "access_token": "test_token",
                "user": {"id": str(sample_user.id), "email": sample_user.email}
            }
            
            response = self.client.post("/users/auth/login", json=login_data)
            
            assert response.status_code == 200
            data = response.json()
            assert "data" in data
            assert "access_token" in data["data"]
            assert "user" in data["data"]
    
    async def test_login_invalid_credentials(self, login_data):
        """Test login with invalid credentials"""
        with patch('app.dependencies.get_db') as mock_get_db:
            mock_db = AsyncMock()
            mock_get_db.return_value = mock_db
            
            # Mock database query to return None
            mock_db.execute.return_value.scalar_one_or_none.return_value = None
            
            response = self.client.post("/users/auth/login", json=login_data)
            
            assert response.status_code == 400
            assert "Invalid email or password" in response.json()["detail"]
    
    async def test_login_unverified_user(self, login_data, sample_user):
        """Test login with unverified user"""
        sample_user.is_verified = False
        
        with patch('app.dependencies.get_db') as mock_get_db, \
             patch('app.utils.security.create_verification_token') as mock_token, \
             patch('app.utils.email_verification.send_verification_email') as mock_send_email:
            
            mock_db = AsyncMock()
            mock_get_db.return_value = mock_db
            mock_db.execute.return_value.scalar_one_or_none.return_value = sample_user
            mock_token.return_value = "verification_token"
            
            response = self.client.post("/users/auth/login", json=login_data)
            
            assert response.status_code == 400
            assert "Email not verified" in response.json()["detail"]
    
    async def test_refresh_token_success(self, sample_user):
        """Test successful token refresh"""
        refresh_token = TokenManager.create_refresh_token(sample_user.id)
        
        with patch('app.dependencies.get_db') as mock_get_db, \
             patch.dict('os.environ', {'SECRET_KEY': 'test-secret-key'}):
            
            mock_db = AsyncMock()
            mock_get_db.return_value = mock_db
            mock_db.execute.return_value.scalar_one_or_none.return_value = sample_user
            
            # Mock request with refresh token cookie
            response = self.client.get(
                "/users/auth/refresh",
                cookies={"refresh_token": refresh_token}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert "data" in data
            assert "access_token" in data["data"]
    
    async def test_refresh_token_missing(self):
        """Test refresh token when no token provided"""
        response = self.client.get("/users/auth/refresh")
        
        assert response.status_code == 401
        assert "No refresh token provided" in response.json()["detail"]
    
    async def test_refresh_token_invalid(self):
        """Test refresh token with invalid token"""
        response = self.client.get(
            "/users/auth/refresh",
            cookies={"refresh_token": "invalid_token"}
        )
        
        assert response.status_code == 401
        assert "Invalid or expired refresh token" in response.json()["detail"]
    
    def test_logout_success(self):
        """Test successful logout"""
        response = self.client.post("/users/auth/logout")
        
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["message"] == "Logged out successfully"


class TestUserEndpoints:
    """Test cases for user management endpoints"""
    
    def setup_method(self):
        self.client = TestClient(users_router)
        self.sample_user_id = uuid4()
        self.sample_facility_id = uuid4()
    
    @pytest.fixture
    def sample_user(self):
        return User(
            id=self.sample_user_id,
            email="test@example.com",
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
             patch('app.services.user_service.UserService') as mock_user_service:
            
            mock_db = AsyncMock()
            mock_get_db.return_value = mock_db
            
            mock_service_instance = AsyncMock()
            mock_user_service.return_value = mock_service_instance
            
            # Mock successful user creation
            created_user = User(
                id=uuid4(),
                email=user_create_data["email"],
                first_name=user_create_data["first_name"],
                last_name=user_create_data["last_name"]
            )
            mock_service_instance.create_user.return_value = created_user
            
            response = self.client.post("/users/register", json=user_create_data)
            
            assert response.status_code == 201
    
    async def test_get_me_success(self, sample_user):
        """Test successful current user retrieval"""
        with patch('app.utils.security.get_current_user') as mock_get_current_user:
            mock_get_current_user.return_value = sample_user
            
            response = self.client.get("/users/me")
            
            assert response.status_code == 200
            data = response.json()
            assert "data" in data
            assert data["data"]["email"] == sample_user.email
    
    async def test_update_user_success(self, sample_user):
        """Test successful user update"""
        update_data = {
            "first_name": "Updated",
            "last_name": "Name"
        }
        
        with patch('app.dependencies.get_db') as mock_get_db, \
             patch('app.utils.security.get_current_user') as mock_get_current_user, \
             patch('app.services.user_service.UserService') as mock_user_service:
            
            mock_db = AsyncMock()
            mock_get_db.return_value = mock_db
            mock_get_current_user.return_value = sample_user
            
            mock_service_instance = AsyncMock()
            mock_user_service.return_value = mock_service_instance
            
            # Mock successful update
            updated_user = sample_user
            updated_user.first_name = "Updated"
            updated_user.last_name = "Name"
            mock_service_instance.update_user.return_value = updated_user
            
            response = self.client.patch(
                f"/users/update-account/{sample_user.id}",
                json=update_data
            )
            
            assert response.status_code == 200
    
    async def test_update_user_permission_denied(self, sample_user):
        """Test user update with insufficient permissions"""
        other_user_id = uuid4()
        update_data = {"first_name": "Updated"}
        
        with patch('app.utils.security.get_current_user') as mock_get_current_user:
            mock_get_current_user.return_value = sample_user
            
            response = self.client.patch(
                f"/users/update-account/{other_user_id}",
                json=update_data
            )
            
            assert response.status_code == 403
    
    async def test_delete_user_success(self, sample_user):
        """Test successful user deletion"""
        with patch('app.dependencies.get_db') as mock_get_db, \
             patch('app.utils.security.get_current_user') as mock_get_current_user, \
             patch('app.services.user_service.UserService') as mock_user_service:
            
            mock_db = AsyncMock()
            mock_get_db.return_value = mock_db
            mock_get_current_user.return_value = sample_user
            
            mock_service_instance = AsyncMock()
            mock_user_service.return_value = mock_service_instance
            
            response = self.client.delete(f"/users/delete-account/{sample_user.id}")
            
            assert response.status_code == 204
    
    async def test_create_staff_user_success(self, admin_user, user_create_data):
        """Test successful staff user creation by admin"""
        # Mock facility for admin user
        facility_mock = MagicMock()
        facility_mock.id = self.sample_facility_id
        admin_user.facility = facility_mock
        
        with patch('app.dependencies.get_db') as mock_get_db, \
             patch('app.utils.security.get_current_user') as mock_get_current_user, \
             patch('app.services.user_service.UserService') as mock_user_service:
            
            mock_db = AsyncMock()
            mock_get_db.return_value = mock_db
            mock_get_current_user.return_value = admin_user
            
            mock_service_instance = AsyncMock()
            mock_user_service.return_value = mock_service_instance
            
            # Mock successful staff creation
            created_user = User(
                id=uuid4(),
                email=user_create_data["email"],
                first_name=user_create_data["first_name"],
                last_name=user_create_data["last_name"]
            )
            mock_service_instance.create_user.return_value = created_user
            
            response = self.client.post("/users/staff/create", json=user_create_data)
            
            assert response.status_code == 201
    
    async def test_create_staff_user_permission_denied(self, sample_user, user_create_data):
        """Test staff user creation with insufficient permissions"""
        with patch('app.utils.security.get_current_user') as mock_get_current_user:
            mock_get_current_user.return_value = sample_user
            
            response = self.client.post("/users/staff/create", json=user_create_data)
            
            assert response.status_code == 403
    
    async def test_get_all_staff_users_success(self, admin_user):
        """Test successful staff users retrieval"""
        # Mock facility for admin user
        facility_mock = MagicMock()
        facility_mock.id = self.sample_facility_id
        admin_user.facility = facility_mock
        
        with patch('app.dependencies.get_db') as mock_get_db, \
             patch('app.utils.security.get_current_user') as mock_get_current_user, \
             patch('app.services.user_service.UserService') as mock_user_service:
            
            mock_db = AsyncMock()
            mock_get_db.return_value = mock_db
            mock_get_current_user.return_value = admin_user
            
            mock_service_instance = AsyncMock()
            mock_user_service.return_value = mock_service_instance
            
            # Mock staff users
            staff_users = [
                User(id=uuid4(), email="staff1@example.com", role="staff"),
                User(id=uuid4(), email="staff2@example.com", role="lab_manager")
            ]
            mock_service_instance.get_all_staff_users.return_value = staff_users
            
            response = self.client.get("/users/staff")
            
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 2


class TestEmailVerification:
    """Test cases for email verification"""
    
    def setup_method(self):
        self.client = TestClient(users_router)
        self.sample_user_id = uuid4()
    
    @pytest.fixture
    def sample_user(self):
        return User(
            id=self.sample_user_id,
            email="test@example.com",
            first_name="John",
            last_name="Doe",
            is_verified=False,
            verification_token="valid_token"
        )
    
    async def test_verify_email_success(self, sample_user):
        """Test successful email verification"""
        with patch('app.dependencies.get_db') as mock_get_db, \
             patch('app.utils.security.create_verification_token') as mock_create_token, \
             patch.dict('os.environ', {'SECRET_KEY': 'test-secret', 'ALGORITHM': 'HS256'}):
            
            mock_db = AsyncMock()
            mock_get_db.return_value = mock_db
            
            # Create a valid verification token
            token_data = {"sub": sample_user.email}
            valid_token = jwt.encode(token_data, "test-secret", algorithm="HS256")
            
            mock_db.execute.return_value.scalar_one_or_none.return_value = sample_user
            
            response = self.client.get(f"/users/verify-email?token={valid_token}")
            
            assert response.status_code == 200
            assert "successfully verified" in response.json()["message"]
    
    async def test_verify_email_invalid_token(self):
        """Test email verification with invalid token"""
        with patch.dict('os.environ', {'SECRET_KEY': 'test-secret', 'ALGORITHM': 'HS256'}):
            response = self.client.get("/users/verify-email?token=invalid_token")
            
            assert response.status_code == 400
            assert "Invalid or expired token" in response.json()["detail"]
    
    async def test_verify_email_user_not_found(self):
        """Test email verification when user doesn't exist"""
        with patch('app.dependencies.get_db') as mock_get_db, \
             patch.dict('os.environ', {'SECRET_KEY': 'test-secret', 'ALGORITHM': 'HS256'}):
            
            mock_db = AsyncMock()
            mock_get_db.return_value = mock_db
            mock_db.execute.return_value.scalar_one_or_none.return_value = None
            
            # Create a valid token
            token_data = {"sub": "nonexistent@example.com"}
            valid_token = jwt.encode(token_data, "test-secret", algorithm="HS256")
            
            response = self.client.get(f"/users/verify-email?token={valid_token}")
            
            assert response.status_code == 400
            assert "Invalid request" in response.json()["detail"]


# Integration Test Examples
class TestIntegration:
    """Integration tests for the complete authentication flow"""
    
    def setup_method(self):
        self.client = TestClient(auth_router)
        self.sample_user_id = uuid4()
    
    async def test_complete_auth_flow(self):
        """Test complete authentication flow: register -> verify -> login -> refresh -> logout"""
        # This would be a more complex integration test that tests the entire flow
        # You would need to set up a test database and mock email sending
        pass
    
    async def test_role_based_access_control(self):
        """Test role-based access control across different endpoints"""
        # Test that different roles can access appropriate endpoints
        pass


# Performance Tests
class TestPerformance:
    """Performance tests for authentication system"""
    
    def test_token_generation_performance(self):
        """Test token generation performance"""
        import time
        
        start_time = time.time()
        
        # Generate 1000 tokens
        for _ in range(1000):
            with patch.dict('os.environ', {'SECRET_KEY':