import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
from uuid import uuid4
from fastapi import HTTPException
# Import your modules
from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate
from app.services.user_service import UserService
from app.utils.security import get_password_hash

pytestmark = pytest.mark.asyncio


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
            email="healfibre@gmail.com",
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
            email="healfibre@gmail.com",
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
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        self.db_mock.execute.return_value = mock_result
        
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
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_user
        self.db_mock.execute.return_value = mock_result
        
        with pytest.raises(HTTPException) as exc_info:
            await self.user_service.create_user(sample_user_data)
        
        assert exc_info.value.status_code == 400
        assert "Email already registered" in str(exc_info.value.detail)
    
    async def test_authenticate_user_success(self, sample_user):
        """Test successful user authentication"""
        # Mock database query to return user
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_user
        self.db_mock.execute.return_value = mock_result

        with patch('app.utils.security.verify_password') as mock_verify, \
            patch('app.routes.auth.TokenManager.create_access_token') as mock_token:

            mock_verify.return_value = True
            mock_token.return_value = "access_token"

            result = await self.user_service.authenticate_user("healfibre@gmail.com", "Password123")

            assert "access_token" in result
            assert "user" in result
            assert result["access_token"] == "access_token"

            # Verify last login was updated
            self.db_mock.commit.assert_called_once()

    
    async def test_authenticate_user_invalid_credentials(self):
        """Test authentication with invalid credentials"""
        # Mock database query to return None
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        self.db_mock.execute.return_value = mock_result
        
        with pytest.raises(HTTPException) as exc_info:
            await self.user_service.authenticate_user("healfibre@gmail.com", "wrong_password")
        
        assert exc_info.value.status_code == 401
        assert "Invalid credentials" in str(exc_info.value.detail)
    
    async def test_authenticate_user_not_verified(self, sample_user):
        """Test authentication with unverified user"""
        sample_user.is_verified = False
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_user
        self.db_mock.execute.return_value = mock_result
        
        with patch('app.utils.security.verify_password') as mock_verify:
            mock_verify.return_value = True
            
            with pytest.raises(HTTPException) as exc_info:
                await self.user_service.authenticate_user("healfibre@gmail.com", "Password123")
            
            assert exc_info.value.status_code == 400
            assert "User email not verified" in str(exc_info.value.detail)
    
    async def test_get_user_success(self, sample_user):
        """Test successful user retrieval"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_user
        self.db_mock.execute.return_value = mock_result
        
        result = await self.user_service.get_user(self.sample_user_id)
        
        assert result == sample_user
        self.db_mock.execute.assert_called_once()
    
    async def test_get_user_not_found(self):
        """Test user retrieval when user doesn't exist"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        self.db_mock.execute.return_value = mock_result
        
        result = await self.user_service.get_user(self.sample_user_id)
        
        assert result is None
    
    async def test_update_user_success(self, sample_user):
        """Test successful user update"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_user
        self.db_mock.execute.return_value = mock_result
        
        update_data = UserUpdate(first_name="Jane", last_name="Smith")
        
        result = await self.user_service.update_user(self.sample_user_id, update_data)
        
        assert sample_user.first_name == "Jane"
        assert sample_user.last_name == "Smith"
        self.db_mock.commit.assert_called_once()
        self.db_mock.refresh.assert_called_once()
    
    async def test_update_user_not_found(self):
        """Test user update when user doesn't exist"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        self.db_mock.execute.return_value = mock_result
        
        update_data = UserUpdate(first_name="Jane")
        
        with pytest.raises(HTTPException) as exc_info:
            await self.user_service.update_user(self.sample_user_id, update_data)
        
        assert exc_info.value.status_code == 404
        assert "User not Found" in str(exc_info.value.detail)
    
    async def test_delete_user_success(self, sample_user):
        """Test successful user deletion"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_user
        self.db_mock.execute.return_value = mock_result
        
        await self.user_service.delete_user(self.sample_user_id)
        
        self.db_mock.delete.assert_called_once_with(sample_user)
        self.db_mock.commit.assert_called_once()
    
    async def test_delete_user_not_found(self):
        """Test user deletion when user doesn't exist"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        self.db_mock.execute.return_value = mock_result
        
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
        
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = staff_users
        mock_result.scalars.return_value = mock_scalars
        self.db_mock.execute.return_value = mock_result
        
        result = await self.user_service.get_all_staff_users(self.sample_facility_id)
        
        assert len(result) == 2
        assert all(user.role in ["staff", "lab_manager"] for user in result)
