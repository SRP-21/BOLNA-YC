"""
Tests for Replan API endpoints:
- POST /api/replan/preview
- POST /api/replan/confirm
- POST /api/replan/reject
- POST /api/replan/undo
"""
import pytest
from datetime import datetime
from starlette.testclient import TestClient

from db import init_db, SessionLocal, Task, TaskStatus, ReplanSnapshot
from main import app
from agent.replan import set_pending_plan
from timeutil import IST

client = TestClient(app)
FROZEN_NOW = datetime(2026, 10, 31, 10, 0, 0, tzinfo=IST)


@pytest.fixture(autouse=True)
def clean_db():
    init_db()
    db = SessionLocal()
    db.query(Task).delete()
    db.query(ReplanSnapshot).delete()
    db.commit()
    db.close()
    set_pending_plan(None)


def test_replan_api_preview_confirm_undo():
    """Test full preview, confirm, and undo lifecycle via API."""
    db = SessionLocal()
    t = Task(
        title="Send Invoice",
        due_at=datetime(2026, 10, 31, 11, 0, 0),
        status=TaskStatus.SCHEDULED.value,
        is_fixed=False,
    )
    db.add(t)
    db.commit()
    task_id = t.id
    db.close()

    # 1. Preview
    resp = client.post("/api/replan/preview", json={
        "text": "push everything by 30 minutes",
        "now": FROZEN_NOW.isoformat(),
    })
    assert resp.status_code == 200
    plan = resp.json()
    assert len(plan["changes"]) == 1
    assert plan["changes"][0]["title"] == "Send Invoice"

    # Task should not be changed yet
    db = SessionLocal()
    t_check = db.query(Task).filter_by(id=task_id).first()
    assert t_check.due_at == datetime(2026, 10, 31, 11, 0, 0)
    db.close()

    # 2. Confirm
    resp_confirm = client.post("/api/replan/confirm")
    assert resp_confirm.status_code == 200
    confirm_data = resp_confirm.json()
    assert confirm_data["ok"] is True
    assert confirm_data["tasks_updated"] == 1

    # Task should now be updated to 11:30
    db = SessionLocal()
    t_updated = db.query(Task).filter_by(id=task_id).first()
    assert t_updated.due_at == datetime(2026, 10, 31, 11, 30, 0)
    db.close()

    # 3. Undo
    resp_undo = client.post("/api/replan/undo")
    assert resp_undo.status_code == 200
    undo_data = resp_undo.json()
    assert undo_data["ok"] is True

    # Task should be back to 11:00
    db = SessionLocal()
    t_reverted = db.query(Task).filter_by(id=task_id).first()
    assert t_reverted.due_at == datetime(2026, 10, 31, 11, 0, 0)
    db.close()


def test_replan_api_reject():
    """Rejecting a preview clears pending plan without touching tasks."""
    db = SessionLocal()
    t = Task(
        title="Gym",
        due_at=datetime(2026, 10, 31, 18, 0, 0),
        status=TaskStatus.SCHEDULED.value,
        is_fixed=False,
    )
    db.add(t)
    db.commit()
    task_id = t.id
    db.close()

    # Preview
    client.post("/api/replan/preview", json={"text": "push everything by 45 minutes"})

    # Reject
    resp = client.post("/api/replan/reject")
    assert resp.status_code == 200

    # Confirming after reject should return 400
    resp_confirm = client.post("/api/replan/confirm")
    assert resp_confirm.status_code == 400

    # Task intact
    db = SessionLocal()
    t_check = db.query(Task).filter_by(id=task_id).first()
    assert t_check.due_at == datetime(2026, 10, 31, 18, 0, 0)
    db.close()
