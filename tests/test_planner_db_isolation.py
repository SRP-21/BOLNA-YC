import os
import pytest
from tests.conftest import _planner_db_path, _initial_planner_mtime, _initial_planner_size


def test_planner_db_is_isolated_and_unmodified():
    """Assert that running pytest uses an isolated temporary DB and leaves planner.db untouched."""
    import db
    assert "planner.db" not in db.DATABASE_URL, f"Expected isolated DB, got {db.DATABASE_URL}"
    assert "test_session.db" in db.DATABASE_URL

    if _initial_planner_mtime is not None and os.path.exists(_planner_db_path):
        current_mtime = os.path.getmtime(_planner_db_path)
        current_size = os.path.getsize(_planner_db_path)
        assert current_mtime == _initial_planner_mtime, "planner.db modification time changed during test run!"
        assert current_size == _initial_planner_size, "planner.db file size changed during test run!"
