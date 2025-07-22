import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
import httpx
from datetime import datetime
from uuid import uuid4
from jose import jwt
import os

# Import your modules
from app.models.user import User
from app.routes.users import router as users_router


pytestmark = pytest.mark.asyncio



class TestEmailVerification:
    """Test cases for email verification"""
    
    def setup_method(self):
        self.app = FastAPI()
        self.app.include_router(users_router)
        self.sample_user_id = uuid4()
        self.test_secret = "test-secret-key-for-testing"
        self.test_algorithm = "HS256"

    @pytest.fixture
    def sample_user(self):
        return User(
            id=self.sample_user_id,
            email="healfibre@gmail.com",
            first_name="John",
            last_name="Doe",
            is_verified=False,
            verification_token="valid_token",
            created_at=datetime.now()
        )

    @pytest.fixture
    def verified_user(self):
        return User(
            id=self.sample_user_id,
            email="healfibre@gmail.com",
            first_name="John",
            last_name="Doe",
            is_verified=True,
            verification_token="valid_token",
            created_at=datetime.now()
        )

    async def test_verify_email_success(self, sample_user):
        """Test successful email verification"""
        with patch('app.dependencies.get_db') as mock_get_db, \
             patch.dict(os.environ, {'SECRET_KEY': self.test_secret, 'ALGORITHM': self.test_algorithm}):
            
            mock_db = AsyncMock()
            mock_get_db.return_value = mock_db
            
            # Generate valid token
            token_data = {"sub": sample_user.email}
            valid_token = jwt.encode(token_data, self.test_secret, algorithm=self.test_algorithm)
            
            # Mock database query
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = sample_user
            mock_db.execute.return_value = mock_result
            
            async with httpx.AsyncClient(app=self.app, base_url=r"http://test") as client:
                response = await client.get(f"//verify-email?token={valid_token}")
                
            assert response.status_code == 200
            assert "successfully verified" in response.json()["message"]
            # Verify that the user's is_verified status was updated
            mock_db.commit.assert_called_once()

    async def test_verify_email_invalid_token(self):
        """Test email verification with invalid JWT"""
        with patch.dict(os.environ, {'SECRET_KEY': self.test_secret, 'ALGORITHM': self.test_algorithm}):
            async with httpx.AsyncClient(app=self.app, base_url=r"http://test") as client:
                response = await client.get("//verify-email?token=invalid_token")
                
            assert response.status_code == 400
            assert "Invalid or expired token" in response.json()["detail"]

    async def test_verify_email_expired_token(self, sample_user):
        """Test email verification with expired JWT"""
        with patch.dict(os.environ, {'SECRET_KEY': self.test_secret, 'ALGORITHM': self.test_algorithm}):
            # Create an expired token (you'll need to mock datetime or use a past exp claim)
            import time
            token_data = {"sub": sample_user.email, "exp": int(time.time()) - 3600}  # Expired 1 hour ago
            expired_token = jwt.encode(token_data, self.test_secret, algorithm=self.test_algorithm)
            
            async with httpx.AsyncClient(app=self.app, base_url=r"http://test") as client:
                response = await client.get(f"//verify-email?token={expired_token}")
                
            assert response.status_code == 400
            assert "Invalid or expired token" in response.json()["detail"]

    async def test_verify_email_user_not_found(self, sample_user):
        """Test verification with valid token but user not found in DB"""
        with patch('app.dependencies.get_db') as mock_get_db, \
             patch.dict(os.environ, {'SECRET_KEY': self.test_secret, 'ALGORITHM': self.test_algorithm}):
            
            mock_db = AsyncMock()
            mock_get_db.return_value = mock_get_db
            
            # Mock database query to return None
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_db.execute.return_value = mock_result
            
            token_data = {"sub": sample_user.email}
            token = jwt.encode(token_data, self.test_secret, algorithm=self.test_algorithm)
            
            async with httpx.AsyncClient(app=self.app, base_url=r"http://test") as client:
                response = await client.get(f"//verify-email?token={token}")
                
            assert response.status_code == 404
            assert "User not found" in response.json()["detail"]

    async def test_verify_email_already_verified(self, verified_user):
        """Test verification of already verified user"""
        with patch('app.dependencies.get_db') as mock_get_db, \
             patch.dict(os.environ, {'SECRET_KEY': self.test_secret, 'ALGORITHM': self.test_algorithm}):
            
            mock_db = AsyncMock()
            mock_get_db.return_value = mock_db
            
            # Mock database query to return already verified user
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = verified_user
            mock_db.execute.return_value = mock_result
            
            token_data = {"sub": verified_user.email}
            token = jwt.encode(token_data, self.test_secret, algorithm=self.test_algorithm)
            
            async with httpx.AsyncClient(app=self.app, base_url=r"http://test") as client:
                response = await client.get(f"//verify-email?token={token}")
                
            assert response.status_code == 400
            assert "already verified" in response.json()["detail"]

    async def test_verify_email_missing_token(self):
        """Test verification request without token parameter"""
        async with httpx.AsyncClient(app=self.app, base_url=r"http://test") as client:
            response = await client.get("//verify-email")
            
        assert response.status_code == 422  # Unprocessable Entity for missing query param

    async def test_verify_email_empty_token(self):
        """Test verification with empty token"""
        async with httpx.AsyncClient(app=self.app, base_url=r"http://test") as client:
            response = await client.get("//verify-email?token=")
            
        assert response.status_code == 400
        assert "Invalid or expired token" in response.json()["detail"]

    async def test_verify_email_malformed_token(self):
        """Test verification with malformed JWT token"""
        with patch.dict(os.environ, {'SECRET_KEY': self.test_secret, 'ALGORITHM': self.test_algorithm}):
            malformed_token = "not.a.jwt"
            
            async with httpx.AsyncClient(app=self.app, base_url=r"http://test") as client:
                response = await client.get(f"//verify-email?token={malformed_token}")
                
            assert response.status_code == 400
            assert "Invalid or expired token" in response.json()["detail"]

    async def test_verify_email_wrong_secret(self, sample_user):
        """Test verification with token signed with wrong secret"""
        with patch('app.dependencies.get_db') as mock_get_db, \
             patch.dict(os.environ, {'SECRET_KEY': self.test_secret, 'ALGORITHM': self.test_algorithm}):
            
            mock_db = AsyncMock()
            mock_get_db.return_value = mock_db
            
            # Generate token with wrong secret
            token_data = {"sub": sample_user.email}
            wrong_token = jwt.encode(token_data, "wrong-secret", algorithm=self.test_algorithm)
            
            async with httpx.AsyncClient(app=self.app, base_url=r"http://test") as client:
                response = await client.get(f"//verify-email?token={wrong_token}")
                
            assert response.status_code == 400
            assert "Invalid or expired token" in response.json()["detail"]

    async def test_verify_email_database_error(self, sample_user):
        """Test verification when database query fails"""
        with patch('app.dependencies.get_db') as mock_get_db, \
             patch.dict(os.environ, {'SECRET_KEY': self.test_secret, 'ALGORITHM': self.test_algorithm}):
            
            mock_db = AsyncMock()
            mock_get_db.return_value = mock_db
            
            # Mock database to raise an exception
            mock_db.execute.side_effect = Exception("Database connection error")
            
            token_data = {"sub": sample_user.email}
            token = jwt.encode(token_data, self.test_secret, algorithm=self.test_algorithm)
            
            async with httpx.AsyncClient(app=self.app, base_url=r"http://test") as client:
                response = await client.get(f"//verify-email?token={token}")
                
            assert response.status_code == 500
            assert "Internal server error" in response.json()["detail"]