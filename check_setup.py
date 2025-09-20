"""
Simplified test runner to diagnose and fix import issues.
"""

import sys
import os
from pathlib import Path

# Setup environment
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

os.environ["ENVIRONMENT"] = "test"
os.environ["TESTING"] = "true"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"


def check_dependencies():
    """Check if required dependencies are available."""
    required_packages = [
        "fastapi",
        "sqlalchemy",
        "pydantic",
        "uvicorn",
        "pytest",
        "asyncio",
    ]

    missing = []
    for package in required_packages:
        try:
            __import__(package)
            print(f"✅ {package} - OK")
        except ImportError:
            print(f"❌ {package} - MISSING")
            missing.append(package)

    return missing


def test_app_import():
    """Test importing the main app."""
    try:
        from app.main import app

        print("✅ app.main import - SUCCESS")
        return True
    except Exception as e:
        print(f"❌ app.main import - FAILED: {e}")
        return False


if __name__ == "__main__":
    print("🔧 Dependency Check for Hospital Blood Request System")
    print("=" * 55)

    print("\n📦 Checking required packages:")
    missing = check_dependencies()

    print(f"\n🏥 Testing app import:")
    app_ok = test_app_import()

    if missing:
        print(f"\n❌ Missing packages: {', '.join(missing)}")
        print("Install with: pip install " + " ".join(missing))

    if app_ok and not missing:
        print("\n✅ All checks passed! You can now run tests.")
        print("Try: python -m pytest -v")
    else:
        print("\n⚠️  Please fix the issues above before running tests.")
