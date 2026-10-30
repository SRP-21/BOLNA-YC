import sys
import os
import pytest

# Ensure project root is in python path for all tests
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    """Ensure database schema is created for fresh test runs."""
    from db import init_db
    init_db()

