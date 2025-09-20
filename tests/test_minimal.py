"""
Minimal test that should always work - no app imports.
"""


def test_python_works():
    """Test that Python and pytest are working."""
    assert True
    assert 1 + 1 == 2


def test_imports_work():
    """Test basic imports."""
    import os
    import sys

    assert os.path.exists(".")
    assert len(sys.path) > 0


def test_environment():
    """Test environment variables."""
    import os

    # These should be set by conftest or our runners
    print(f"ENVIRONMENT: {os.environ.get('ENVIRONMENT', 'not set')}")
    print(f"DATABASE_URL: {os.environ.get('DATABASE_URL', 'not set')}")
    assert True  # Just check it runs
