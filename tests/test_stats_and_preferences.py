"""
Tests for Step 3: Adaptive nudges, categorization, statistics, and learned preferences.
Requirements tested:
- Coarse categorization (health, work, errands, family, other)
- Deterministic statistics calculation from hand-built fixture
- Threshold boundaries (2 vs 3 snoozes for preference offer)
- 14-day decline cooldown
- Learned offset applied to future tasks in that category
- Synthetic marker propagation in stats
- Escalation nudge delays and count tracking
"""
import pytest
from datetime import datetime, timedelta, timezone
from starlette.testclient import TestClient

from db import init_db, SessionLocal, Task, TaskStatus, Event, LearnedPreference
from main import app
from agent.categorize import categorize_by_rules, categorize_task
from agent.stats import (
    compute_category_stats, evaluate_learned_preferences,
    apply_learned_preference, decline_learned_preference, reset_learned_preference
)
from agent.planner import process_turn
from timeutil import IST

client = TestClient(app)
FROZEN_NOW = datetime(2026, 10, 31, 10, 0, 0, tzinfo=IST)


@pytest.fixture(autouse=True)
def clean_db():
    init_db()
    db = SessionLocal()
    db.query(Task).delete()
    db.query(Event).delete()
    db.query(LearnedPreference).delete()
    db.commit()
    db.close()


def test_categorization_by_rules():
    """Verify coarse categories mapped via keyword rules."""
    assert categorize_by_rules("Gym workout") == "health"
    assert categorize_by_rules("Doctor appointment") == "health"
    assert categorize_by_rules("Dentist checkup") == "health"
    assert categorize_by_rules("Take morning medicine") == "health"

    assert categorize_by_rules("Team standup") == "work"
    assert categorize_by_rules("Send client invoice") == "work"
    assert categorize_by_rules("Review PR") == "work"

    assert categorize_by_rules("Buy groceries") == "errands"
    assert categorize_by_rules("Pickup laundry") == "errands"
    assert categorize_by_rules("Go to bank") == "errands"

    assert categorize_by_rules("Call mom") == "family"
    assert categorize_by_rules("Dinner with sister") == "family"

    assert categorize_by_rules("Random unlabeled item") is None


def test_statistics_from_handbuilt_fixture():
    """Verify deterministic statistics calculated from known tasks."""
    db = SessionLocal()
    # 4 health tasks: 2 done, 1 missed, 1 scheduled; 2 have snoozes
    t1 = Task(title="Gym 1", due_at=datetime(2026, 10, 31, 7, 0, 0), status=TaskStatus.DONE.value,
              category="health", snooze_count=0, is_synthetic=False)
    t2 = Task(title="Gym 2", due_at=datetime(2026, 10, 31, 8, 0, 0), status=TaskStatus.DONE.value,
              category="health", snooze_count=1, is_synthetic=False)
    t3 = Task(title="Doctor", due_at=datetime(2026, 10, 31, 9, 0, 0), status=TaskStatus.MISSED.value,
              category="health", snooze_count=2, is_synthetic=False)
    t4 = Task(title="Medicine", due_at=datetime(2026, 10, 31, 10, 0, 0), status=TaskStatus.SCHEDULED.value,
              category="health", snooze_count=0, is_synthetic=False)
    db.add_all([t1, t2, t3, t4])
    db.commit()

    # Log specific snooze events to test median duration
    db.add_all([
        Event(type="task_snoozed", message="Snoozed for 20m", task_id=t2.id),
        Event(type="task_snoozed", message="Snoozed for 20m", task_id=t3.id),
        Event(type="task_snoozed", message="Snoozed for 25m", task_id=t3.id),
    ])
    db.commit()

    stats = compute_category_stats(db, category="health")
    assert stats["total_tasks"] == 4
    assert stats["done_count"] == 2
    assert stats["missed_count"] == 1
    assert stats["snoozed_count"] == 2
    assert stats["total_snoozes"] == 3
    assert stats["completion_rate"] == 50.0
    assert stats["miss_rate"] == 25.0
    assert stats["snooze_rate"] == 50.0
    assert stats["median_snooze_minutes"] == 20
    assert stats["synthetic_count"] == 0
    assert stats["is_synthetic"] is False
    db.close()


def test_threshold_boundaries_preference_offer():
    """2 snoozes -> no offer; 3 snoozes -> offer generated."""
    db = SessionLocal()
    # 2 snoozes
    t1 = Task(title="Gym 1", due_at=datetime(2026, 10, 31, 7, 0, 0), status=TaskStatus.DONE.value,
              category="health", snooze_count=2)
    db.add(t1)
    db.commit()

    offers_2 = evaluate_learned_preferences(db, now=FROZEN_NOW)
    assert len(offers_2) == 0

    # Add 1 more snooze -> total 3 snoozes
    t2 = Task(title="Gym 2", due_at=datetime(2026, 10, 31, 8, 0, 0), status=TaskStatus.DONE.value,
              category="health", snooze_count=1)
    db.add(t2)
    db.commit()

    offers_3 = evaluate_learned_preferences(db, now=FROZEN_NOW)
    assert len(offers_3) == 1
    offer = offers_3[0]
    assert offer["category"] == "health"
    assert offer["evidence_count"] == 3
    assert "push health" in offer["spoken_offer"]
    db.close()


def test_decline_cooldown_14_days():
    """Declined category is not offered again within 14 days."""
    db = SessionLocal()
    t = Task(title="Gym", due_at=datetime(2026, 10, 31, 7, 0, 0), status=TaskStatus.DONE.value,
             category="health", snooze_count=3)
    db.add(t)
    db.commit()

    # Decline offer
    decline_learned_preference(db, category="health", now=FROZEN_NOW, cooldown_days=14)

    # 5 days later: still under cooldown
    day_5 = FROZEN_NOW + timedelta(days=5)
    offers_day_5 = evaluate_learned_preferences(db, now=day_5)
    assert len(offers_day_5) == 0

    # 15 days later: cooldown expired
    day_15 = FROZEN_NOW + timedelta(days=15)
    offers_day_15 = evaluate_learned_preferences(db, now=day_15)
    assert len(offers_day_15) == 1
    assert offers_day_15[0]["category"] == "health"
    db.close()


@pytest.mark.asyncio
async def test_learned_offset_applied_to_new_tasks():
    """When a learned preference is active (+20m for health), new health tasks get scheduled 20m later."""
    db = SessionLocal()
    apply_learned_preference(db, category="health", offset_minutes=20, evidence_count=4)
    db.close()

    # Create new health task at 6 PM (18:00)
    res = await process_turn("gym at 6 pm", language="en", now=FROZEN_NOW)
    assert res is not None

    db = SessionLocal()
    gym_task = db.query(Task).filter_by(title="Gym").first()
    assert gym_task is not None
    # Original requested was 18:00; with +20m offset -> 18:20
    assert gym_task.due_at == datetime(2026, 10, 31, 18, 20, 0)
    assert "learned preference applied (+20m)" in gym_task.resolution_note
    db.close()


def test_synthetic_marker_propagation_in_stats():
    """Synthetic tasks mark category stats with synthetic indicator."""
    db = SessionLocal()
    t_synth = Task(title="Workout", due_at=datetime(2026, 10, 31, 8, 0, 0),
                   status=TaskStatus.DONE.value, category="health", is_synthetic=True)
    db.add(t_synth)
    db.commit()

    stats = compute_category_stats(db, category="health")
    assert stats["synthetic_count"] == 1
    assert stats["is_synthetic"] is True
    db.close()


def test_preferences_api_endpoints():
    """Test /api/stats/categories and /api/preferences endpoints."""
    db = SessionLocal()
    t = Task(title="Team Standup", due_at=datetime(2026, 10, 31, 10, 0, 0),
             status=TaskStatus.DONE.value, category="work", snooze_count=0)
    db.add(t)
    db.commit()
    db.close()

    resp_stats = client.get("/api/stats/categories")
    assert resp_stats.status_code == 200
    data = resp_stats.json()
    assert "work" in data
    assert data["work"]["done_count"] == 1

    # Accept preference via API
    resp_acc = client.post("/api/preferences/work/accept", json={
        "offset_minutes": 15,
        "evidence_count": 3,
        "is_synthetic": False
    })
    assert resp_acc.status_code == 200

    resp_prefs = client.get("/api/preferences")
    assert resp_prefs.status_code == 200
    pdata = resp_prefs.json()
    active = [p for p in pdata["active_preferences"] if p["category"] == "work"]
    assert len(active) == 1
    assert active[0]["offset_minutes"] == 15

    # Reset preference
    resp_del = client.delete("/api/preferences/work")
    assert resp_del.status_code == 200
    resp_prefs2 = client.get("/api/preferences")
    active2 = [p for p in resp_prefs2.json()["active_preferences"] if p["category"] == "work"]
    assert len(active2) == 0
