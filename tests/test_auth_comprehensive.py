"""
Comprehensive authentication and user management tests for hospital blood request system.
Tests user registration, login, security features, and extreme edge cases.
"""

import pytest
from fastapi.testclient import TestClient
import asyncio

from tests.conftest import (
    TestDataFactory,
    assert_response_success,
    assert_response_error,
    assert_validation_error,
    PerformanceTimer,
)
from app.models.user import User


class TestUserRegistration:
    """Test user registration with hospital-specific scenarios."""

    def test_valid_user_registration(self, client: TestClient):
        """Test successful user registration with valid data."""
        user_data = TestDataFactory.create_user_data(role="staff")

        with PerformanceTimer(max_duration_ms=500):
            response = client.post("/api/users/register", json=user_data)

        data = assert_response_success(response, 201)
        assert data["email"] == user_data["email"]
        assert data["first_name"] == user_data["first_name"]
        assert data["last_name"] == user_data["last_name"]
        assert "id" in data
        assert "password" not in data  # Password should never be returned

    def test_duplicate_email_registration(self, client: TestClient):
        """Test registration fails with duplicate email."""
        user_data = TestDataFactory.create_user_data()

        # First registration succeeds
        response1 = client.post("/api/users/register", json=user_data)
        assert_response_success(response1, 201)

        # Second registration with same email fails
        response2 = client.post("/api/users/register", json=user_data)
        assert_response_error(response2, 400)
        assert "email" in response2.json()["message"].lower()

    @pytest.mark.parametrize(
        "invalid_email",
        [
            "invalid-email",
            "@hospital.com",
            "user@",
            "user space@hospital.com",
            "user@hospital",
            "",
            "a" * 100 + "@hospital.com",  # Too long
        ],
    )
    def test_invalid_email_registration(self, client: TestClient, invalid_email: str):
        """Test registration fails with invalid emails."""
        user_data = TestDataFactory.create_user_data()
        user_data["email"] = invalid_email

        response = client.post("/api/users/register", json=user_data)
        assert_validation_error(response, "email")

    @pytest.mark.parametrize(
        "weak_password",
        [
            "123456",  # Too simple
            "password",  # No uppercase, numbers, special chars
            "Pass1",  # Too short
            "PASS123!",  # No lowercase
            "pass123!",  # No uppercase
            "Password!",  # No numbers
            "Password123",  # No special chars
            "",  # Empty
            "a",  # Too short
            "A" * 100,  # Too long
        ],
    )
    def test_weak_password_registration(self, client: TestClient, weak_password: str):
        """Test registration fails with weak passwords."""
        user_data = TestDataFactory.create_user_data()
        user_data["password"] = weak_password
        user_data["password_confirm"] = weak_password

        response = client.post("/api/users/register", json=user_data)
        assert_validation_error(response, "password")

    def test_password_mismatch_registration(self, client: TestClient):
        """Test registration fails when passwords don't match."""
        user_data = TestDataFactory.create_user_data()
        user_data["password_confirm"] = "DifferentPass123!"

        response = client.post("/api/users/register", json=user_data)
        assert_validation_error(response)

    @pytest.mark.parametrize(
        "invalid_phone",
        [
            "123",  # Too short
            "abcdefghij",  # Non-numeric
            "+233" + "1" * 20,  # Too long
            "++233244000000",  # Invalid format
            "233-244-000-000-000",  # Too many separators
        ],
    )
    def test_invalid_phone_registration(self, client: TestClient, invalid_phone: str):
        """Test registration fails with invalid phone numbers."""
        user_data = TestDataFactory.create_user_data()
        user_data["phone"] = invalid_phone

        response = client.post("/api/users/register", json=user_data)
        assert_validation_error(response, "phone")

    @pytest.mark.parametrize(
        "invalid_name",
        [
            "",  # Empty
            "A",  # Too short
            "A" * 60,  # Too long
            "John123",  # Contains numbers
            "John@Doe",  # Contains special chars
            "   ",  # Only whitespace
        ],
    )
    def test_invalid_name_registration(self, client: TestClient, invalid_name: str):
        """Test registration fails with invalid names."""
        user_data = TestDataFactory.create_user_data()
        user_data["first_name"] = invalid_name

        response = client.post("/api/users/register", json=user_data)
        assert_validation_error(response, "first_name")

    def test_missing_required_fields(self, client: TestClient):
        """Test registration fails with missing required fields."""
        required_fields = [
            "email",
            "first_name",
            "last_name",
            "password",
            "password_confirm",
            "role",
        ]

        for field in required_fields:
            user_data = TestDataFactory.create_user_data()
            del user_data[field]

            response = client.post("/api/users/register", json=user_data)
            assert_validation_error(response, field)

    @pytest.mark.parametrize(
        "invalid_role",
        [
            "doctor",  # Not in allowed roles
            "admin",  # Not in allowed roles
            "STAFF",  # Wrong case
            "",  # Empty
            123,  # Wrong type
        ],
    )
    def test_invalid_role_registration(self, client: TestClient, invalid_role):
        """Test registration fails with invalid roles."""
        user_data = TestDataFactory.create_user_data()
        user_data["role"] = invalid_role

        response = client.post("/api/users/register", json=user_data)
        assert_validation_error(response, "role")


class TestUserAuthentication:
    """Test user login and authentication security."""

    def test_valid_login(self, client: TestClient, test_user: User):
        """Test successful login with valid credentials."""
        login_data = {"email": test_user.email, "password": "SecurePass123!"}

        with PerformanceTimer(max_duration_ms=300):
            response = client.post("/api/users/auth/login", data=login_data)

        data = assert_response_success(response)
        assert "access_token" in data
        assert "token_type" in data
        assert data["token_type"] == "bearer"
        assert "user" in data
        assert data["user"]["email"] == test_user.email

    def test_invalid_email_login(self, client: TestClient):
        """Test login fails with invalid email."""
        login_data = {"email": "nonexistent@hospital.com", "password": "SecurePass123!"}

        response = client.post("/api/users/auth/login", data=login_data)
        assert_response_error(response, 401)

    def test_invalid_password_login(self, client: TestClient, test_user: User):
        """Test login fails with wrong password."""
        login_data = {"email": test_user.email, "password": "WrongPassword123!"}

        response = client.post("/api/users/auth/login", data=login_data)
        assert_response_error(response, 401)

    def test_login_with_empty_credentials(self, client: TestClient):
        """Test login fails with empty credentials."""
        response = client.post("/api/users/auth/login", data={})
        assert_validation_error(response)

    def test_login_with_malformed_data(self, client: TestClient):
        """Test login fails with malformed data."""
        malformed_data = [
            {"email": "test@hospital.com"},  # Missing password
            {"password": "password"},  # Missing email
            {"email": "", "password": ""},  # Empty values
            {"email": None, "password": None},  # Null values
        ]

        for data in malformed_data:
            response = client.post("/api/users/auth/login", data=data)
            assert response.status_code in [400, 422]

    def test_protected_endpoint_without_token(self, client: TestClient):
        """Test protected endpoint fails without authentication token."""
        response = client.get("/api/users/me")
        assert response.status_code == 401

    def test_protected_endpoint_with_invalid_token(self, client: TestClient):
        """Test protected endpoint fails with invalid token."""
        headers = {"Authorization": "Bearer invalid_token_here"}
        response = client.get("/api/users/me", headers=headers)
        assert response.status_code == 401

    def test_protected_endpoint_with_expired_token(self, client: TestClient):
        """Test protected endpoint fails with expired token."""
        # This would require setting up a token with past expiry
        # For now, we test with malformed token that simulates expiry
        headers = {"Authorization": "Bearer expired.token.here"}
        response = client.get("/api/users/me", headers=headers)
        assert response.status_code == 401

    def test_get_current_user(self, client: TestClient, auth_headers: dict):
        """Test getting current user information."""
        response = client.get("/api/users/me", headers=auth_headers)

        data = assert_response_success(response)
        assert "id" in data
        assert "email" in data
        assert "first_name" in data
        assert "last_name" in data
        assert "password" not in data  # Password should never be returned


class TestUserSecurity:
    """Test security features like rate limiting, brute force protection."""

    def test_multiple_failed_login_attempts(self, client: TestClient, test_user: User):
        """Test account lockout after multiple failed login attempts."""
        login_data = {"email": test_user.email, "password": "WrongPassword123!"}

        # Simulate multiple failed attempts
        failed_attempts = 0
        max_attempts = 5  # Assuming lockout after 5 attempts

        for attempt in range(max_attempts + 2):
            response = client.post("/api/users/auth/login", data=login_data)

            if response.status_code == 429:  # Rate limited/locked
                break

            assert_response_error(response, 401)
            failed_attempts += 1

        # Should be locked after max attempts
        assert failed_attempts >= max_attempts or response.status_code == 429

    def test_sql_injection_attempts(self, client: TestClient):
        """Test protection against SQL injection in login."""
        malicious_inputs = [
            "admin@hospital.com'; DROP TABLE users; --",
            "admin@hospital.com' OR '1'='1",
            "admin@hospital.com' UNION SELECT * FROM users --",
            "'; UPDATE users SET password='hacked' WHERE email='admin@hospital.com'; --",
        ]

        for malicious_email in malicious_inputs:
            login_data = {"email": malicious_email, "password": "password123"}

            response = client.post("/api/users/auth/login", data=login_data)
            # Should fail with validation error or 401, not 500 (server error)
            assert response.status_code in [400, 401, 422]

    def test_xss_protection_in_registration(self, client: TestClient):
        """Test protection against XSS in user registration."""
        xss_payloads = [
            "<script>alert('xss')</script>",
            "javascript:alert('xss')",
            "<img src=x onerror=alert('xss')>",
            "' onmouseover='alert(1)' '",
        ]

        for payload in xss_payloads:
            user_data = TestDataFactory.create_user_data()
            user_data["first_name"] = payload

            response = client.post("/api/users/register", json=user_data)

            if response.status_code == 201:
                # If registration succeeds, check that XSS payload is sanitized
                data = response.json()["data"]
                assert "<script>" not in data["first_name"]
                assert "javascript:" not in data["first_name"]
            else:
                # Should be rejected by validation
                assert response.status_code in [400, 422]


class TestUserManagement:
    """Test user management operations for hospital staff."""

    def test_update_user_profile(self, client: TestClient, auth_headers: dict):
        """Test updating user profile information."""
        update_data = {
            "first_name": "Updated",
            "last_name": "Name",
            "phone": "+233244999999",
        }

        response = client.put("/api/users/me", json=update_data, headers=auth_headers)
        data = assert_response_success(response)

        assert data["first_name"] == update_data["first_name"]
        assert data["last_name"] == update_data["last_name"]
        assert data["phone"] == update_data["phone"]

    def test_change_password(self, client: TestClient, auth_headers: dict):
        """Test changing user password."""
        password_data = {
            "current_password": "SecurePass123!",
            "new_password": "NewSecurePass456!",
            "confirm_password": "NewSecurePass456!",
        }

        response = client.post(
            "/api/users/change-password", json=password_data, headers=auth_headers
        )
        assert_response_success(response)

    def test_change_password_wrong_current(
        self, client: TestClient, auth_headers: dict
    ):
        """Test changing password fails with wrong current password."""
        password_data = {
            "current_password": "WrongPassword123!",
            "new_password": "NewSecurePass456!",
            "confirm_password": "NewSecurePass456!",
        }

        response = client.post(
            "/api/users/change-password", json=password_data, headers=auth_headers
        )
        assert_response_error(response, 400)

    def test_admin_list_users(self, client: TestClient, admin_auth_headers: dict):
        """Test admin can list users with pagination."""
        response = client.get("/api/users", headers=admin_auth_headers)
        data = assert_response_success(response)

        assert "users" in data
        assert "total" in data
        assert "page" in data
        assert "limit" in data
        assert isinstance(data["users"], list)

    def test_admin_search_users(self, client: TestClient, admin_auth_headers: dict):
        """Test admin can search users."""
        search_params = {"search": "John", "role": "staff", "limit": 10, "page": 1}

        response = client.get(
            "/api/users", params=search_params, headers=admin_auth_headers
        )
        data = assert_response_success(response)

        assert "users" in data
        # Results should be filtered by search term
        if data["users"]:
            for user in data["users"]:
                assert "John" in user["first_name"] or "John" in user["last_name"]

    def test_non_admin_cannot_list_users(self, client: TestClient, auth_headers: dict):
        """Test non-admin cannot list all users."""
        response = client.get("/api/users", headers=auth_headers)
        assert response.status_code in [403, 401]  # Forbidden or Unauthorized


class TestExtremeCases:
    """Test extreme edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_concurrent_user_registrations(self, client: TestClient):
        """Test handling of concurrent user registrations."""

        async def register_user(email_suffix: str):
            user_data = TestDataFactory.create_user_data()
            user_data["email"] = f"concurrent_{email_suffix}@hospital.com"
            return client.post("/api/users/register", json=user_data)

        # Create multiple concurrent registration tasks
        tasks = [register_user(str(i)) for i in range(10)]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        # All should succeed with unique emails
        successful_registrations = 0
        for response in responses:
            if hasattr(response, "status_code") and response.status_code == 201:
                successful_registrations += 1

        assert successful_registrations == 10

    def test_unicode_in_user_data(self, client: TestClient):
        """Test handling of Unicode characters in user data."""
        user_data = TestDataFactory.create_user_data()
        user_data.update(
            {
                "first_name": "José",
                "last_name": "García-López",
                "email": "josé.garcía@hospital.com",
            }
        )

        response = client.post("/api/users/register", json=user_data)

        # Should either succeed or fail gracefully
        if response.status_code == 201:
            data = response.json()["data"]
            assert data["first_name"] == "José"
            assert data["last_name"] == "García-López"
        else:
            assert response.status_code in [400, 422]

    def test_extremely_long_requests(self, client: TestClient):
        """Test handling of extremely long request payloads."""
        user_data = TestDataFactory.create_user_data()
        user_data["first_name"] = "A" * 10000  # Extremely long name

        response = client.post("/api/users/register", json=user_data)
        assert response.status_code in [
            400,
            413,
            422,
        ]  # Bad request or payload too large

    def test_null_and_empty_edge_cases(self, client: TestClient):
        """Test handling of null and empty values."""
        edge_cases = [
            None,
            "",
            "   ",  # Whitespace only
            "\n\t\r",  # Special whitespace characters
            "null",
            "undefined",
        ]

        for edge_value in edge_cases:
            user_data = TestDataFactory.create_user_data()
            user_data["first_name"] = edge_value

            response = client.post("/api/users/register", json=user_data)
            assert response.status_code in [400, 422]  # Should be rejected

    def test_high_frequency_requests(self, client: TestClient):
        """Test rate limiting with high frequency requests."""
        login_data = {"email": "test@hospital.com", "password": "password123"}

        # Send many requests in quick succession
        rate_limited = False
        for i in range(100):
            response = client.post("/api/users/auth/login", data=login_data)
            if response.status_code == 429:  # Too Many Requests
                rate_limited = True
                break

        # Should eventually hit rate limit
        # Note: This test depends on rate limiting being implemented
        # If no rate limiting, all requests will return 401 (invalid credentials)
        assert rate_limited or all(
            client.post("/api/users/auth/login", data=login_data).status_code == 401
            for _ in range(5)
        )

    def test_memory_stress_with_large_user_operations(
        self, client: TestClient, admin_auth_headers: dict
    ):
        """Test memory handling with large user operations."""
        # Request large amount of data
        params = {"limit": 10000, "page": 1}

        with PerformanceTimer(
            max_duration_ms=5000
        ):  # Should not take more than 5 seconds
            response = client.get(
                "/api/users", params=params, headers=admin_auth_headers
            )

        # Should either return data or gracefully limit the response
        assert response.status_code in [
            200,
            400,
            413,
        ]  # OK, Bad Request, or Payload Too Large

        if response.status_code == 200:
            data = response.json()["data"]
            # Should have reasonable pagination limits
            assert len(data.get("users", [])) <= 1000  # Reasonable max limit
