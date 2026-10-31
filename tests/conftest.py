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


@pytest.fixture(autouse=True)
def reset_db_state():
    """Clean pending agent state and utterance history between tests to prevent cross-test pollution."""
    from agent.pending_action import clear_pending_action
    from agent.pending_choice import clear_pending_choice
    from agent.replan import set_pending_plan
    from db import SessionLocal, Utterance

    clear_pending_action()
    clear_pending_choice()
    set_pending_plan(None)
    session = SessionLocal()
    session.query(Utterance).delete()
    session.commit()
    session.close()

    yield

    clear_pending_action()
    clear_pending_choice()
    set_pending_plan(None)
    session = SessionLocal()
    session.query(Utterance).delete()
    session.commit()
    session.close()
