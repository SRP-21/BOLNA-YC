"""
Tests for Phase 4: Task list clarity.
Verifies that GET /api/tasks excludes cancelled tasks by default,
and includes them when ?include_cancelled=true is requested.
"""
import pytest
from datetime import datetime
from starlette.testclient import TestClient

from db import init_db, SessionLocal, Task, TaskStatus
from main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_db():
    init_db()
    db = SessionLocal()
    db.query(Task).delete()
    db.commit()
    db.close()


def test_list_tasks_excludes_cancelled_by_default():
    """Verify cancelled tasks are omitted from GET /api/tasks by default."""
    db = SessionLocal()
    t_scheduled = Task(title="Team Standup", due_at=datetime(2026, 10, 31, 10, 0, 0),
                       status=TaskStatus.SCHEDULED.value)
    t_done = Task(title="Send Invoice", due_at=datetime(2026, 10, 31, 11, 0, 0),
                  status=TaskStatus.DONE.value)
    t_cancelled = Task(title="Old Meeting", due_at=datetime(2026, 10, 31, 12, 0, 0),
                       status=TaskStatus.CANCELLED.value)
    t_snoozed = Task(title="Call Mom", due_at=datetime(2026, 10, 31, 13, 0, 0),
                     status=TaskStatus.SNOOZED.value)
    db.add_all([t_scheduled, t_done, t_cancelled, t_snoozed])
    db.commit()
    db.close()

    resp = client.get("/api/tasks")
    assert resp.status_code == 200
    data = resp.json()

    titles = [t["title"] for t in data]
    assert "Team Standup" in titles
    assert "Send Invoice" in titles
    assert "Call Mom" in titles
    assert "Old Meeting" not in titles
    assert len(data) == 3


def test_list_tasks_includes_cancelled_with_flag():
    """Verify ?include_cancelled=true returns all tasks including cancelled."""
    db = SessionLocal()
    t_scheduled = Task(title="Active Task", due_at=datetime(2026, 10, 31, 10, 0, 0),
                       status=TaskStatus.SCHEDULED.value)
    t_cancelled = Task(title="Removed Task", due_at=datetime(2026, 10, 31, 11, 0, 0),
                       status=TaskStatus.CANCELLED.value)
    db.add_all([t_scheduled, t_cancelled])
    db.commit()
    db.close()

    # With flag=true
    resp_inc = client.get("/api/tasks?include_cancelled=true")
    assert resp_inc.status_code == 200
    data_inc = resp_inc.json()
    titles_inc = [t["title"] for t in data_inc]
    assert "Active Task" in titles_inc
    assert "Removed Task" in titles_inc
    assert len(data_inc) == 2

    # With flag=false
    resp_exc = client.get("/api/tasks?include_cancelled=false")
    assert resp_exc.status_code == 200
    data_exc = resp_exc.json()
    titles_exc = [t["title"] for t in data_exc]
    assert "Active Task" in titles_exc
    assert "Removed Task" not in titles_exc
    assert len(data_exc) == 1
