"""
Tests for Step 4: Evening recap, strict rephrase validator, carry-over, and honest demo data.
Requirements tested:
- Recap counts match stored DB data exactly
- Strict validator rejects hallucinated numbers or task names
- Carry-over moves missed tasks to tomorrow morning through conflict detection
- Honest demo data tool is gated behind ENABLE_DEMO_DATA
- Synthetic marker is set on all generated records and can be cleared
"""
import pytest
from datetime import datetime, timedelta
from starlette.testclient import TestClient

from db import init_db, SessionLocal, Task, TaskStatus, Event, LearnedPreference
from main import app
from agent.recap import (
    build_evening_recap, validate_recap_rephrase, apply_carryover_to_tomorrow,
    is_recap_command
)
from agent.demo_data import generate_demo_data, clear_demo_data
from timeutil import IST
from scheduler import scheduler

client = TestClient(app)
FROZEN_NOW = datetime(2026, 10, 31, 20, 30, 0, tzinfo=IST)


@pytest.fixture(autouse=True)
def clean_db():
    init_db()
    db = SessionLocal()
    db.query(Task).delete()
    db.query(Event).delete()
    db.query(LearnedPreference).delete()
    db.commit()
    db.close()


def test_recap_counts_match_stored_data_exactly():
    """Verify recap counts (done, missed, snoozed, cancelled) match DB exactly."""
    db = SessionLocal()
    # Today's date = 2026-10-31
    t1 = Task(title="Standup", due_at=datetime(2026, 10, 31, 10, 0, 0),
              status=TaskStatus.DONE.value, snooze_count=0)
    t2 = Task(title="Invoice", due_at=datetime(2026, 10, 31, 12, 0, 0),
              status=TaskStatus.DONE.value, snooze_count=1)
    t3 = Task(title="Gym", due_at=datetime(2026, 10, 31, 18, 0, 0),
              status=TaskStatus.MISSED.value, snooze_count=2)
    t4 = Task(title="Old Meeting", due_at=datetime(2026, 10, 31, 14, 0, 0),
              status=TaskStatus.CANCELLED.value, snooze_count=0)
    # Yesterday task should NOT count in today's counts
    t_yest = Task(title="Yesterday Walk", due_at=datetime(2026, 10, 30, 18, 0, 0),
                  status=TaskStatus.DONE.value)
    db.add_all([t1, t2, t3, t4, t_yest])
    db.commit()

    recap = build_evening_recap(db, now=FROZEN_NOW, language="en")
    assert recap["total_tasks"] == 4
    assert recap["done_count"] == 2
    assert recap["missed_count"] == 1
    assert recap["snoozed_count"] == 2
    assert recap["cancelled_count"] == 1
    assert recap["completion_rate"] == 50.0
    assert len(recap["missed_tasks"]) == 1
    assert recap["missed_tasks"][0]["title"] == "Gym"

    assert "completed 2 tasks, missed 1, and snoozed 2" in recap["spoken_text"]
    assert "Gym" in recap["spoken_text"]
    db.close()


def test_strict_validator_rejects_hallucinations():
    """Strict validator permits real numbers/titles and rejects invented numbers or tasks."""
    source_data = {
        "date": "2026-10-31",
        "total_tasks": 4,
        "done_count": 2,
        "missed_count": 1,
        "snoozed_count": 2,
        "completion_rate": 50.0,
        "missed_tasks": [{"title": "Gym"}],
    }

    # 1. Valid rephrase containing only real numbers and real task
    valid_rephrase = "You wrapped up 2 tasks today, snoozed 2 times, and missed 'Gym'."
    assert validate_recap_rephrase(valid_rephrase, source_data) is True

    # 2. Hallucinated number (e.g. claims 9 tasks or 5 done)
    hallucinated_num = "Great job finishing 5 tasks today with 0 missed!"
    assert validate_recap_rephrase(hallucinated_num, source_data) is False

    # 3. Hallucinated task title (e.g. claims missed 'Dentist Checkup')
    hallucinated_task = "You missed 'Dentist Checkup' today."
    assert validate_recap_rephrase(hallucinated_task, source_data) is False


def test_carryover_moves_missed_tasks_to_tomorrow_morning():
    """Carryover moves missed tasks to 09:00 tomorrow with min gap and schedules them."""
    db = SessionLocal()
    t1 = Task(title="Gym", due_at=datetime(2026, 10, 31, 18, 0, 0),
              status=TaskStatus.MISSED.value)
    t2 = Task(title="Groceries", due_at=datetime(2026, 10, 31, 19, 0, 0),
              status=TaskStatus.MISSED.value)
    db.add_all([t1, t2])
    db.commit()
    t1_id, t2_id = t1.id, t2.id

    res = apply_carryover_to_tomorrow(db, now=FROZEN_NOW)
    assert res["ok"] is True
    assert res["carried_count"] == 2

    # Check updated tasks in DB
    updated_1 = db.query(Task).filter_by(id=t1_id).first()
    updated_2 = db.query(Task).filter_by(id=t2_id).first()

    assert updated_1.status == TaskStatus.SCHEDULED.value
    assert updated_2.status == TaskStatus.SCHEDULED.value

    # First task at 09:00 AM on Nov 1
    assert updated_1.due_at == datetime(2026, 11, 1, 9, 0, 0)
    # Second task at 09:15 AM on Nov 1 (min gap 15m)
    assert updated_2.due_at == datetime(2026, 11, 1, 9, 15, 0)

    # Verify scheduler jobs created
    job1 = scheduler.get_job(f"task_{t1_id}")
    job2 = scheduler.get_job(f"task_{t2_id}")
    assert job1 is not None
    assert job2 is not None
    db.close()


def test_demo_data_gated_and_marks_synthetic():
    """Demo data is gated, sets is_synthetic=True, and can be cleared."""
    db = SessionLocal()

    # 1. Disabled by default without force -> raises 403
    with pytest.raises(Exception):
        generate_demo_data(db, now=FROZEN_NOW, enabled=False)

    # 2. When enabled -> generates 7 days
    res = generate_demo_data(db, now=FROZEN_NOW, enabled=True)
    assert res["ok"] is True
    assert res["tasks_generated"] > 0
    assert res["days"] == 7

    # Verify all generated tasks have is_synthetic=True
    synthetic_tasks = db.query(Task).filter(Task.is_synthetic.is_(True)).all()
    assert len(synthetic_tasks) == res["tasks_generated"]

    # 3. Clear demo data
    clear_res = clear_demo_data(db)
    assert clear_res["ok"] is True
    assert clear_res["tasks_deleted"] == res["tasks_generated"]

    remaining = db.query(Task).filter(Task.is_synthetic.is_(True)).count()
    assert remaining == 0
    db.close()


def test_recap_and_demo_api_routes():
    """Test /api/recap and demo data endpoints via HTTP."""
    resp = client.get("/api/recap")
    assert resp.status_code == 200
    data = resp.json()
    assert "seven_day_trend" in data
    assert len(data["seven_day_trend"]) == 7

    # Generate demo data via API
    resp_gen = client.post("/api/dev/generate-demo-data", json={"force_enable": True})
    assert resp_gen.status_code == 200
    gen_data = resp_gen.json()
    assert gen_data["is_synthetic"] is True

    # Clear demo data via API
    resp_clear = client.post("/api/dev/clear-demo-data")
    assert resp_clear.status_code == 200
    assert resp_clear.json()["ok"] is True
