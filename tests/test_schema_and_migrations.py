"""
Tests for Step 1: Schema migrations and foundations.
Verifies backwards-compatible migration, new task fields (is_fixed, duration, category, synthetic),
ReplanSnapshot, and LearnedPreference models.
"""
import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, Integer, String, DateTime, text
from sqlalchemy.orm import declarative_base, sessionmaker

from db import init_db, migrate_db, SessionLocal, Task, TaskStatus, ReplanSnapshot, LearnedPreference
from agent.resolver import resolve_time
from starlette.testclient import TestClient
from main import app

client = TestClient(app)


def test_schema_columns_exist():
    """Verify new fields exist on Task model and DB schema."""
    init_db()
    db = SessionLocal()
    task = Task(
        title="Dentist Checkup",
        due_at=datetime(2026, 10, 31, 14, 0, 0),
        status=TaskStatus.SCHEDULED.value,
        is_fixed=True,
        duration_minutes=45,
        category="health",
        is_synthetic=False,
        nudge_count=1,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    assert task.id is not None
    assert task.is_fixed is True
    assert task.duration_minutes == 45
    assert task.category == "health"
    assert task.is_synthetic is False
    assert task.nudge_count == 1
    db.close()


def test_migration_adds_columns_to_existing_table(tmp_path):
    """Test that migrate_db adds missing columns to an existing SQLite table without losing data."""
    test_db_path = tmp_path / "legacy.db"
    legacy_engine = create_engine(f"sqlite:///{test_db_path}")

    # Create a legacy tasks table without the new columns
    with legacy_engine.connect() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title VARCHAR NOT NULL,
                due_at DATETIME NOT NULL,
                status VARCHAR DEFAULT 'scheduled'
            );
        """)
        conn.exec_driver_sql("""
            INSERT INTO tasks (title, due_at, status)
            VALUES ('Legacy Meeting', '2026-10-31 10:00:00', 'scheduled');
        """)
        conn.commit()

    # Run migration
    migrate_db(legacy_engine)

    # Verify existing data preserved and new columns accessible
    with legacy_engine.connect() as conn:
        row = conn.exec_driver_sql("SELECT id, title, is_fixed, duration_minutes, category, is_synthetic FROM tasks WHERE title='Legacy Meeting';").fetchone()
        assert row is not None
        assert row[1] == "Legacy Meeting"
        assert row[2] == 0  # default False
        assert row[3] is None
        assert row[4] is None
        assert row[5] == 0  # default False


def test_models_replan_snapshot_and_learned_preference():
    """Verify ReplanSnapshot and LearnedPreference can be stored and queried."""
    init_db()
    db = SessionLocal()

    snapshot = ReplanSnapshot(
        reason="shift all by 45m",
        before_state='[{"id": 1, "title": "Gym", "due_at": "2026-10-31T18:00:00"}]',
        after_state='[{"id": 1, "title": "Gym", "due_at": "2026-10-31T18:45:00"}]',
        undone=False,
    )
    pref = LearnedPreference(
        category="health",
        offset_minutes=20,
        evidence_count=3,
        is_active=True,
    )
    db.add_all([snapshot, pref])
    db.commit()

    s = db.query(ReplanSnapshot).filter_by(reason="shift all by 45m").first()
    assert s is not None
    assert not s.undone
    assert "Gym" in s.before_state

    p = db.query(LearnedPreference).filter_by(category="health").first()
    assert p is not None
    assert p.offset_minutes == 20
    assert p.evidence_count == 3
    db.close()


def test_resolver_distinguishes_fixed_from_flexible():
    """Exact times are is_fixed=True; approximate, vague, or fallback times are is_fixed=False."""
    now = datetime(2026, 10, 31, 8, 0, 0)

    # Exact time
    res_exact = resolve_time("10 am", now=now)
    assert res_exact.is_fixed is True

    res_exact_hi = resolve_time("subah 10 baje", now=now)
    assert res_exact_hi.is_fixed is True

    # Approximate time with 'around' / 'lagbhag'
    res_approx = resolve_time("around 6", now=now)
    assert res_approx.is_fixed is False

    res_approx_hi = resolve_time("lagbhag 7 baje", now=now)
    assert res_approx_hi.is_fixed is False

    # Vague phrase
    res_vague = resolve_time("before lunch", now=now)
    assert res_vague.is_fixed is False

    # Unparseable fallback
    res_fallback = resolve_time("groceries on the way back", now=now)
    assert res_fallback.is_fixed is False


def test_tasks_api_includes_new_fields():
    """Verify GET /api/tasks returns is_fixed, duration_minutes, category, is_synthetic."""
    init_db()
    db = SessionLocal()
    task = Task(
        title="Workout",
        due_at=datetime(2026, 10, 31, 19, 0, 0),
        status=TaskStatus.SCHEDULED.value,
        is_fixed=True,
        duration_minutes=60,
        category="health",
        is_synthetic=True,
    )
    db.add(task)
    db.commit()
    task_id = task.id
    db.close()

    resp = client.get("/api/tasks")
    assert resp.status_code == 200
    tasks = resp.json()
    match = next((t for t in tasks if t["id"] == task_id), None)
    assert match is not None
    assert match["is_fixed"] is True
    assert match["duration_minutes"] == 60
    assert match["category"] == "health"
    assert match["is_synthetic"] is True
