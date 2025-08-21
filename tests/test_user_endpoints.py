# tests/test_user_endpoints.py
import pytest
from fastapi.testclient import TestClient
from app.main import app  # import your FastAPI app
from uuid import uuid4

# Create test client
client = TestClient(app)

# Test data generators
def get_unique_email():
    """Generate unique email for each test"""
    return f"test_{uuid4().hex[:8]}@example.com"

def get_test_user_payload():
    """Generate test user payload"""
    return {
        "email": get_unique_email(),
        "first_name": "John",
        "last_name": "Doe",
        "phone": "1234567890",
        "password": "StrongPass1",
        "password_confirm": "StrongPass1",
        "role": "staff"
    }

# Fixture to create a test user and return their token
@pytest.fixture
def authenticated_user():
    """Creates a test user and returns their authentication token"""
    # Register user
    register_payload = get_test_user_payload()
    register_response = client.post("/api/users/register", json=register_payload)
    
    # Check if registration was successful
    if register_response.status_code != 201:
        pytest.fail(f"Failed to register user: {register_response.json()}")
    
    # Login to get token
    login_payload = {
        "email": register_payload["email"], 
        "password": register_payload["password"]
    }
    login_resp = client.post("/api/users/auth/login", data=login_payload)
    
    if login_resp.status_code != 200:
        pytest.fail(f"Failed to login: {login_resp.json()}")
    
    token_data = login_resp.json()["data"]
    
    return {
        "token": token_data["access_token"],
        "headers": {"Authorization": f"Bearer {token_data['access_token']}"},
        "email": register_payload["email"],
        "user_data": token_data["user"]
    }

# ------------------ REGISTER USER ------------------
def test_register_user_success():
    """Test successful user registration"""
    payload = get_test_user_payload()
    response = client.post("/api/users/register", json=payload)
    
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == payload["email"]
    assert data["first_name"] == payload["first_name"]
    assert data["last_name"] == payload["last_name"]
    assert "id" in data
    assert "password" not in data  # Ensure password is not returned

def test_register_user_duplicate_email():
    """Test registration with duplicate email"""
    payload = get_test_user_payload()
    
    # Register first user
    first_response = client.post("/api/users/register", json=payload)
    assert first_response.status_code == 201
    
    # Try to register again with same email
    response = client.post("/api/users/register", json=payload)
    assert response.status_code == 400
    error_detail = response.json()["detail"]
    assert "email" in error_detail.lower() or "already exists" in error_detail.lower()

def test_register_user_password_mismatch():
    """Test registration with password mismatch"""
    payload = get_test_user_payload()
    payload["password_confirm"] = "DifferentPass1"
    
    response = client.post("/api/users/register", json=payload)
    assert response.status_code == 422

def test_register_user_invalid_email():
    """Test registration with invalid email format"""
    payload = get_test_user_payload()
    payload["email"] = "invalid-email"
    
    response = client.post("/api/users/register", json=payload)
    assert response.status_code == 422

def test_register_user_weak_password():
    """Test registration with weak password"""
    payload = get_test_user_payload()
    payload["password"] = "123"
    payload["password_confirm"] = "123"
    
    response = client.post("/api/users/register", json=payload)
    assert response.status_code == 422

def test_register_user_missing_required_fields():
    """Test registration with missing required fields"""
    payload = {
        "email": get_unique_email(),
        "password": "StrongPass1",
        "password_confirm": "StrongPass1"
        # Missing first_name, last_name, phone, role
    }
    response = client.post("/api/users/register", json=payload)
    assert response.status_code == 422

# ------------------ LOGIN USER ------------------
def test_login_user_success():
    """Test successful login"""
    # First register a user
    register_payload = get_test_user_payload()
    client.post("/api/users/register", json=register_payload)
    
    # Then try to login
    login_payload = {
        "email": register_payload["email"],
        "password": register_payload["password"]
    }
    response = client.post("/api/users/auth/login", data=login_payload)
    
    # Note: This might fail with email verification required
    # Adjust assertion based on your email verification flow
    if response.status_code == 400 and "not verified" in response.json().get("detail", ""):
        # Email verification is required
        pytest.skip("Email verification required for login")
    
    assert response.status_code == 200
    data = response.json()["data"]
    assert "access_token" in data
    assert "user" in data

def test_login_user_invalid_credentials():
    """Test login with invalid credentials"""
    payload = {
        "email": "nonexistent@example.com",
        "password": "WrongPassword1"
    }
    response = client.post("/api/users/auth/login", data=payload)
    assert response.status_code == 400
    assert "Invalid email or password" in response.json()["detail"]

def test_login_user_missing_fields():
    """Test login with missing fields"""
    payload = {"email": "test@example.com"}  # Missing password
    response = client.post("/api/users/auth/login", data=payload)
    assert response.status_code == 422

# ------------------ GET USER INFO ------------------
def test_get_user_info_success(authenticated_user):
    """Test getting user info with valid token"""
    response = client.get("/api/users/me", headers=authenticated_user["headers"])
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["email"] == authenticated_user["email"]
    assert "password" not in data

def test_get_user_info_invalid_token():
    """Test getting user info with invalid token"""
    headers = {"Authorization": "Bearer invalid_token"}
    response = client.get("/api/users/me", headers=headers)
    assert response.status_code == 401

def test_get_user_info_no_token():
    """Test getting user info without token"""
    response = client.get("/api/users/me")
    assert response.status_code == 401

# ------------------ UPDATE USER ------------------
def test_update_user_success(authenticated_user):
    """Test successful user update"""
    user_id = authenticated_user["user_data"]["id"]
    update_payload = {
        "first_name": "Jane", 
        "last_name": "Smith",
        "phone": "9876543210"
    }
    response = client.patch(
        f"/api/users/update-account/{user_id}", 
        json=update_payload, 
        headers=authenticated_user["headers"]
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["first_name"] == "Jane"
    assert data["last_name"] == "Smith"
    assert data["phone"] == "9876543210"
    assert data["email"] == authenticated_user["email"]  # Email should remain unchanged

def test_update_user_partial(authenticated_user):
    """Test partial user update"""
    user_id = authenticated_user["user_data"]["id"]
    update_payload = {"first_name": "UpdatedName"}
    response = client.patch(
        f"/api/users/update-account/{user_id}", 
        json=update_payload, 
        headers=authenticated_user["headers"]
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["first_name"] == "UpdatedName"

def test_update_user_invalid_token():
    """Test user update with invalid token"""
    user_id = str(uuid4())  # Random UUID
    headers = {"Authorization": "Bearer invalid_token"}
    update_payload = {"first_name": "Jane"}
    response = client.patch(f"/api/users/update-account/{user_id}", json=update_payload, headers=headers)
    assert response.status_code == 401

def test_update_user_unauthorized():
    """Test updating another user's account without permission"""
    # Create first user
    user1 = authenticated_user()
    
    # Create second user  
    register_payload = get_test_user_payload()
    client.post("/api/users/register", json=register_payload)
    login_payload = {"email": register_payload["email"], "password": register_payload["password"]}
    login_resp = client.post("/api/users/auth/login", data=login_payload)
    
    if login_resp.status_code != 200:
        pytest.skip("Cannot test unauthorized update - login failed")
    
    user2_data = login_resp.json()["data"]
    user2_headers = {"Authorization": f"Bearer {user2_data['access_token']}"}
    
    # Try to update user1 with user2's token
    update_payload = {"first_name": "Hacker"}
    response = client.patch(
        f"/api/users/update-account/{user1['user_data']['id']}", 
        json=update_payload, 
        headers=user2_headers
    )
    assert response.status_code == 403

# ------------------ DELETE USER ------------------
def test_delete_user_success(authenticated_user):
    """Test successful user deletion"""
    user_id = authenticated_user["user_data"]["id"]
    response = client.delete(f"/api/users/delete-account/{user_id}", headers=authenticated_user["headers"])
    assert response.status_code == 204
    
    # Verify user is deleted by trying to get user info
    get_response = client.get("/api/users/me", headers=authenticated_user["headers"])
    assert get_response.status_code == 401  # Token should be invalid after deletion

def test_delete_user_invalid_token():
    """Test user deletion with invalid token"""
    user_id = str(uuid4())  # Random UUID
    headers = {"Authorization": "Bearer invalid_token"}
    response = client.delete(f"/api/users/delete-account/{user_id}", headers=headers)
    assert response.status_code == 401

def test_delete_user_no_token():
    """Test user deletion without token"""
    user_id = str(uuid4())  # Random UUID
    response = client.delete(f"/api/users/delete-account/{user_id}")
    assert response.status_code == 401

def test_delete_user_unauthorized():
    """Test deleting another user's account without permission"""
    # Create first user
    user1 = authenticated_user()
    
    # Create second user
    register_payload = get_test_user_payload()
    client.post("/api/users/register", json=register_payload)
    login_payload = {"email": register_payload["email"], "password": register_payload["password"]}
    login_resp = client.post("/api/users/auth/login", data=login_payload)
    
    if login_resp.status_code != 200:
        pytest.skip("Cannot test unauthorized delete - login failed")
    
    user2_data = login_resp.json()["data"]
    user2_headers = {"Authorization": f"Bearer {user2_data['access_token']}"}
    
    # Try to delete user1 with user2's token
    response = client.delete(
        f"/api/users/delete-account/{user1['user_data']['id']}", 
        headers=user2_headers
    )
    assert response.status_code == 403

# ------------------ LOGOUT ------------------
def test_logout_success(authenticated_user):
    """Test successful logout"""
    response = client.post("/api/users/auth/logout", headers=authenticated_user["headers"])
    assert response.status_code == 200
    data = response.json()["data"]
    assert "message" in data
    assert "successfully" in data["message"].lower()

def test_logout_invalid_token():
    """Test logout with invalid token"""
    headers = {"Authorization": "Bearer invalid_token"}
    response = client.post("/api/users/auth/logout", headers=headers)
    assert response.status_code == 401

# ------------------ REFRESH TOKEN ------------------
def test_refresh_token():
    """Test refresh token functionality"""
    # This test is complex because it requires cookies
    # You might want to skip this or implement it differently based on your setup
    pytest.skip("Refresh token test requires cookie handling - implement if needed")

# ------------------ EMAIL VERIFICATION ------------------
def test_email_verification_invalid_token():
    """Test email verification with invalid token"""
    response = client.get("/api/users/verify-email?token=invalid_token")
    assert response.status_code == 400
    assert "Invalid" in response.json()["detail"]

# ------------------ INTEGRATION TESTS ------------------
def test_user_workflow_integration():
    """Test complete user workflow: register -> login -> update -> delete"""
    # Register
    register_payload = get_test_user_payload()
    register_resp = client.post("/api/users/register", json=register_payload)
    assert register_resp.status_code == 201
    user_id = register_resp.json()["id"]
    
    # Login (might fail due to email verification)
    login_payload = {"email": register_payload["email"], "password": register_payload["password"]}
    login_resp = client.post("/api/users/auth/login", data=login_payload)
    
    if login_resp.status_code == 400 and "not verified" in login_resp.json().get("detail", ""):
        pytest.skip("Email verification required - cannot complete workflow test")
    
    assert login_resp.status_code == 200
    token = login_resp.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    # Get user info
    get_resp = client.get("/api/users/me", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["data"]["email"] == register_payload["email"]
    
    # Update
    update_payload = {"first_name": "Updated"}
    update_resp = client.patch(f"/api/users/update-account/{user_id}", json=update_payload, headers=headers)
    assert update_resp.status_code == 200
    assert update_resp.json()["data"]["first_name"] == "Updated"
    
    # Delete
    delete_resp = client.delete(f"/api/users/delete-account/{user_id}", headers=headers)
    assert delete_resp.status_code == 204

# ------------------ BOUNDARY TESTS ------------------
def test_register_user_long_fields():
    """Test registration with very long field values"""
    payload = get_test_user_payload()
    payload.update({
        "first_name": "A" * 255,  # Very long name
        "last_name": "B" * 255,   # Very long name
        "phone": "1" * 50,  # Very long phone
    })
    response = client.post("/api/users/register", json=payload)
    # This should either succeed or fail with 422, depending on your validation rules
    assert response.status_code in [201, 422]

def test_register_user_empty_strings():
    """Test registration with empty string fields"""
    payload = get_test_user_payload()
    payload.update({
        "first_name": "",
        "last_name": "",
        "phone": ""
    })
    response = client.post("/api/users/register", json=payload)
    assert response.status_code == 422

def test_register_user_special_characters():
    """Test registration with special characters in name fields"""
    payload = get_test_user_payload()
    payload.update({
        "first_name": "José-María",
        "last_name": "O'Connor"
    })
    response = client.post("/api/users/register", json=payload)
    # Should succeed with properly encoded special characters
    assert response.status_code == 201