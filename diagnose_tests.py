"""
Diagnostic script to identify pytest issues.
"""

import sys
import os
from pathlib import Path
import traceback

# Setup environment like conftest.py
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("TESTING", "true")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-jwt-tokens")


def test_individual_imports():
    """Test importing each component individually."""
    print("🔍 Testing individual imports...")

    try:
        from app.main import app

        print("✅ app.main - OK")
    except Exception as e:
        print(f"❌ app.main - FAILED: {e}")
        traceback.print_exc()

    try:
        from app.database import get_db

        print("✅ app.database - OK")
    except Exception as e:
        print(f"❌ app.database - FAILED: {e}")
        traceback.print_exc()

    try:
        from app.models.user import User

        print("✅ app.models.user - OK")
    except Exception as e:
        print(f"❌ app.models.user - FAILED: {e}")
        traceback.print_exc()

    try:
        import pytest

        print("✅ pytest - OK")
    except Exception as e:
        print(f"❌ pytest - FAILED: {e}")
        traceback.print_exc()


def test_conftest_import():
    """Test importing conftest.py."""
    print("\n🔍 Testing conftest.py import...")

    try:
        # Change to tests directory
        tests_dir = project_root / "tests"
        sys.path.insert(0, str(tests_dir))

        import conftest

        print("✅ conftest.py - OK")
    except Exception as e:
        print(f"❌ conftest.py - FAILED: {e}")
        traceback.print_exc()


def test_basic_test_file():
    """Test importing a basic test file."""
    print("\n🔍 Testing basic test file import...")

    try:
        from tests.test_basic_setup import test_basic_import

        print("✅ test_basic_setup - OK")
    except Exception as e:
        print(f"❌ test_basic_setup - FAILED: {e}")
        traceback.print_exc()


def run_single_test():
    """Try running a single test function."""
    print("\n🔍 Running single test function...")

    try:
        import pytest

        result = pytest.main(["-v", "tests/test_basic_setup.py::test_basic_math"])
        print(f"Test result code: {result}")
    except Exception as e:
        print(f"❌ Running test - FAILED: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    print("🏥 Pytest Diagnostic Tool")
    print("=" * 50)
    print(f"Project root: {project_root}")
    print(f"Current directory: {os.getcwd()}")
    print(f"Python path: {sys.path[:3]}...")
    print("-" * 50)

    test_individual_imports()
    test_conftest_import()
    test_basic_test_file()
    run_single_test()

    print("\n" + "=" * 50)
    print("🔍 Diagnostic complete!")
    print("If any tests failed above, that's likely the issue.")
    print("Please share the error details so I can help fix them.")
