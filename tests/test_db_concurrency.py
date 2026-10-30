"""
Tests for database SQLite concurrency and WAL mode.
"""
import threading
from datetime import datetime, timezone
import pytest
from db import engine, SessionLocal, Event


def test_sqlite_wal_mode():
    """Verify engine connections activate WAL mode and 20s busy timeout."""
    with engine.connect() as conn:
        journal_mode = conn.exec_driver_sql("PRAGMA journal_mode;").scalar()
        assert str(journal_mode).lower() == "wal"

        busy_timeout = conn.exec_driver_sql("PRAGMA busy_timeout;").scalar()
        assert busy_timeout == 20000


def test_concurrent_event_writes():
    """Spawn 10 threads each writing an Event, asserting none raise 'database is locked'."""
    errors = []

    def write_event(thread_idx: int):
        try:
            db = SessionLocal()
            try:
                event = Event(
                    ts=datetime.now(timezone.utc),
                    type="concurrency_test",
                    message=f"Event written by thread {thread_idx}",
                    task_id=None
                )
                db.add(event)
                db.commit()
            finally:
                db.close()
        except Exception as e:
            errors.append(e)

    threads = [
        threading.Thread(target=write_event, args=(i,))
        for i in range(10)
    ]

    for t in threads:
        t.start()

    for t in threads:
        t.join(timeout=10.0)

    # Assert no errors occurred, especially 'database is locked'
    assert len(errors) == 0, f"Concurrent writes failed with errors: {errors}"
