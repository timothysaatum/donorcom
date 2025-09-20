"""
Simple test to verify the test setup is working correctly.
"""

import pytest
import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Set environment variables
os.environ["ENVIRONMENT"] = "test"
os.environ["TESTING"] = "true"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-secret-key-for-jwt-tokens"


def test_basic_import():
    """Test that we can import the main app module."""
    try:
        from app.main import app

        assert app is not None
        print("✅ App import successful")
    except ImportError as e:
        pytest.fail(f"Failed to import app: {e}")


def test_environment_setup():
    """Test that environment variables are set correctly."""
    assert os.environ.get("ENVIRONMENT") == "test"
    assert os.environ.get("TESTING") == "true"
    assert "sqlite+aiosqlite" in os.environ.get("DATABASE_URL", "")
    print("✅ Environment setup correct")


def test_basic_math():
    """Simple test to verify pytest is working."""
    assert 2 + 2 == 4
    assert "hello" + " world" == "hello world"
    print("✅ Basic pytest functionality working")


if __name__ == "__main__":
    # Run this test file directly
    pytest.main([__file__, "-v"])
