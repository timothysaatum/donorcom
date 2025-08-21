import pytest
from pydantic import ValidationError
from app.schemas.user import UserCreate, UserUpdate, UserRole


def test_user_create_valid():
    user = UserCreate(
        email="test@example.com",
        first_name="John",
        last_name="Doe",
        phone="1234567890",
        password="StrongPass1",
        password_confirm="StrongPass1",
        role="staff"
    )
    assert user.email == "test@example.com"
    assert user.role == UserRole.staff


def test_passwords_do_not_match():
    with pytest.raises(ValidationError) as exc:
        UserCreate(
            email="test@example.com",
            first_name="John",
            last_name="Doe",
            phone="1234567890",
            password="StrongPass1",
            password_confirm="WrongPass",
            role="staff"
        )
    assert "passwords do not match" in str(exc.value)


def test_password_complexity_missing_uppercase():
    with pytest.raises(ValidationError) as exc:
        UserCreate(
            email="test@example.com",
            first_name="John",
            last_name="Doe",
            phone="1234567890",
            password="weakpassword1",
            password_confirm="weakpassword1",
            role="staff"
        )
    assert "uppercase" in str(exc.value)


def test_user_update_partial():
    """Ensure optional fields work in UserUpdate"""
    user = UserUpdate(first_name="Jane")
    assert user.first_name == "Jane"
    assert user.email is None

    
def test_user_update_with_role():
    """Ensure role can be updated in UserUpdate"""
    user = UserUpdate(role="facility_administrator")
    assert user.role == "facility_administrator"