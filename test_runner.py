#!/usr/bin/env python3
"""
Simple test runner for the hospital blood request management system.
This script properly sets up the Python path and environment before running tests.
"""

import sys
import os
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Set environment variables for testing
os.environ["ENVIRONMENT"] = "test"
os.environ["TESTING"] = "true"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-secret-key-for-jwt-tokens"
os.environ["ALGORITHM"] = "HS256"
os.environ["ACCESS_TOKEN_EXPIRE_MINUTES"] = "30"

if __name__ == "__main__":
    import pytest

    print("🏥 Hospital Blood Request Management System - Test Runner")
    print("=" * 55)
    print(f"Project Root: {project_root}")
    print(f"Python Path: {sys.path[0]}")
    print(f"Environment: {os.environ.get('ENVIRONMENT', 'not set')}")
    print("-" * 55)

    # Run pytest with the arguments passed to this script
    args = sys.argv[1:] if len(sys.argv) > 1 else ["-v"]

    try:
        # Test basic import first
        from app.main import app

        print("✅ Successfully imported app.main")

        # Run tests
        exit_code = pytest.main(args)
        sys.exit(exit_code)

    except ImportError as e:
        print(f"❌ Import Error: {e}")
        print("\nPlease ensure all dependencies are installed:")
        print("pip install -r requirements.txt")
        print("pip install pytest pytest-asyncio pytest-cov")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
