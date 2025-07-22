import pytest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from jose import jwt
import os

from app.routes.auth import TokenManager

# Remove the asyncio mark since these tests are not async
# pytestmark = pytest.mark.asyncio  # <- Remove this line


class TestTokenManager:
    """Test cases for TokenManager class"""
    
    def setup_method(self):
        """Set up test fixtures before each test method."""
        self.secret_key = "test-secret-key-for-testing-purposes-only"
        self.algorithm = "HS256"
        self.user_id = uuid4()
    
    def test_create_access_token_default_expiry(self):
        """Test creating access token with default expiry"""
        data = {"sub": str(self.user_id)}
        
        with patch.dict(os.environ, {'SECRET_KEY': self.secret_key}):
            token = TokenManager.create_access_token(data)
        
        # Decode and verify token
        decoded = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
        assert decoded["sub"] == str(self.user_id)
        assert decoded["type"] == "access"
        assert "exp" in decoded
        
        # Verify expiration is in the future
        exp_time = datetime.fromtimestamp(decoded["exp"], tz=timezone.utc)
        assert exp_time > datetime.now(timezone.utc)
    
    def test_create_access_token_custom_expiry(self):
        """Test creating access token with custom expiry"""
        data = {"sub": str(self.user_id)}
        expires_delta = timedelta(minutes=30)
        expected_exp_time = datetime.now(timezone.utc) + expires_delta
        
        with patch.dict(os.environ, {'SECRET_KEY': self.secret_key}):
            token = TokenManager.create_access_token(data, expires_delta)
        
        decoded = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
        assert decoded["sub"] == str(self.user_id)
        assert decoded["type"] == "access"
        
        # Verify custom expiration time (within 1 minute tolerance)
        exp_time = datetime.fromtimestamp(decoded["exp"], tz=timezone.utc)
        time_diff = abs((exp_time - expected_exp_time).total_seconds())
        assert time_diff < 60  # Within 1 minute tolerance
    
    def test_create_refresh_token(self):
        """Test creating refresh token"""
        with patch.dict(os.environ, {'SECRET_KEY': self.secret_key}):
            token = TokenManager.create_refresh_token(self.user_id)
        
        decoded = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
        assert decoded["sub"] == str(self.user_id)
        assert decoded["type"] == "refresh"
        assert "jti" in decoded  # JWT ID for refresh token uniqueness
        assert "exp" in decoded
        
        # Verify expiration is in the future
        exp_time = datetime.fromtimestamp(decoded["exp"], tz=timezone.utc)
        assert exp_time > datetime.now(timezone.utc)
        
        # Verify jti is a valid UUID string
        from uuid import UUID
        UUID(decoded["jti"])  # This will raise ValueError if invalid
    
    def test_decode_token_success(self):
        """Test successful token decoding"""
        data = {
            "sub": str(self.user_id), 
            "type": "access",
            "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()
        }
        
        with patch.dict(os.environ, {'SECRET_KEY': self.secret_key}):
            token = jwt.encode(data, self.secret_key, algorithm=self.algorithm)
            decoded = TokenManager.decode_token(token)
        
        assert decoded["sub"] == str(self.user_id)
        assert decoded["type"] == "access"
        assert "exp" in decoded
    
    def test_decode_token_invalid(self):
        """Test decoding invalid token"""
        with patch.dict(os.environ, {'SECRET_KEY': self.secret_key}):
            with pytest.raises(ValueError, match="Invalid or expired token"):
                TokenManager.decode_token("invalid-token")
    
    def test_decode_token_malformed(self):
        """Test decoding malformed token"""
        with patch.dict(os.environ, {'SECRET_KEY': self.secret_key}):
            with pytest.raises(ValueError, match="Invalid or expired token"):
                TokenManager.decode_token("not.a.valid.jwt.token.structure")
    
    def test_decode_token_expired(self):
        """Test decoding expired token"""
        past_time = datetime.now(timezone.utc) - timedelta(hours=1)
        data = {
            "sub": str(self.user_id), 
            "type": "access",
            "exp": past_time.timestamp()
        }
        
        with patch.dict(os.environ, {'SECRET_KEY': self.secret_key}):
            token = jwt.encode(data, self.secret_key, algorithm=self.algorithm)
            with pytest.raises(ValueError, match="Invalid or expired token"):
                TokenManager.decode_token(token)
    
    def test_decode_token_wrong_secret(self):
        """Test decoding token with wrong secret key"""
        data = {
            "sub": str(self.user_id), 
            "type": "access",
            "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()
        }
        
        # Create token with one secret
        token = jwt.encode(data, "wrong-secret", algorithm=self.algorithm)
        
        # Try to decode with different secret
        with patch.dict(os.environ, {'SECRET_KEY': self.secret_key}):
            with pytest.raises(ValueError, match="Invalid or expired token"):
                TokenManager.decode_token(token)
    
    def test_create_tokens_have_different_jtis(self):
        """Test that multiple refresh tokens have unique JTIs"""
        with patch.dict(os.environ, {'SECRET_KEY': self.secret_key}):
            token1 = TokenManager.create_refresh_token(self.user_id)
            token2 = TokenManager.create_refresh_token(self.user_id)
        
        decoded1 = jwt.decode(token1, self.secret_key, algorithms=[self.algorithm])
        decoded2 = jwt.decode(token2, self.secret_key, algorithms=[self.algorithm])
        
        # JTIs should be different for each refresh token
        assert decoded1["jti"] != decoded2["jti"]
        assert decoded1["sub"] == decoded2["sub"]  # Same user
    
    def test_token_contains_required_fields(self):
        """Test that tokens contain all required fields"""
        data = {"sub": str(self.user_id), "role": "user"}
        
        with patch.dict(os.environ, {'SECRET_KEY': self.secret_key}):
            access_token = TokenManager.create_access_token(data)
            refresh_token = TokenManager.create_refresh_token(self.user_id)
        
        # Decode tokens
        access_decoded = jwt.decode(access_token, self.secret_key, algorithms=[self.algorithm])
        refresh_decoded = jwt.decode(refresh_token, self.secret_key, algorithms=[self.algorithm])
        
        # Check required fields
        required_fields = ["sub", "type", "exp"]
        for field in required_fields:
            assert field in access_decoded
            assert field in refresh_decoded
        
        # Check specific fields
        assert access_decoded["role"] == "user"  # Custom data preserved
        assert "jti" in refresh_decoded  # Refresh token has JTI
        assert "jti" not in access_decoded  # Access token doesn't need JTI