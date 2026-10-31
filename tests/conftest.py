import sys
import os
import tempfile
import shutil
import pytest

# Ensure project root is in python path for all tests
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Isolate all tests to a temporary SQLite database so planner.db is NEVER touched by pytest
_test_dir = tempfile.mkdtemp(prefix="bolna_test_")
_test_db_path = os.path.join(_test_dir, "test_session.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_test_db_path}"

# Record planner.db initial state to verify isolation
_planner_db_path = os.path.abspath("planner.db")
_initial_planner_mtime = os.path.getmtime(_planner_db_path) if os.path.exists(_planner_db_path) else None
_initial_planner_size = os.path.getsize(_planner_db_path) if os.path.exists(_planner_db_path) else None


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    """Ensure test database schema is created on temporary DB and planner.db is untouched."""
    import db
    db.init_db()
    yield
    # Check that planner.db was never modified during the test suite
    if _initial_planner_mtime is not None and os.path.exists(_planner_db_path):
        current_mtime = os.path.getmtime(_planner_db_path)
        current_size = os.path.getsize(_planner_db_path)
        assert current_mtime == _initial_planner_mtime, f"planner.db mtime changed during tests! {_initial_planner_mtime} -> {current_mtime}"
        assert current_size == _initial_planner_size, f"planner.db size changed during tests! {_initial_planner_size} -> {current_size}"
    # Cleanup temp directory
    shutil.rmtree(_test_dir, ignore_errors=True)
