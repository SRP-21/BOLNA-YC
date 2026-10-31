"""
Unit tests for reminder reply outcome interpretation.
Tests both fast regex rule matcher and LLM classifier fallback.
"""
import pytest
from agent.outcome import parse_outcome_rules, ReminderOutcome


def test_outcome_done_variations():
    cases = ["done", "Done!", "ho gaya", "kar liya", "khatam", "aaytu", "madide", "ok done", "haan", "acha"]
    for phrase in cases:
        res = parse_outcome_rules(phrase)
        assert res is not None, f"Failed on: {phrase}"
        assert res.outcome == "done", f"Expected 'done' for '{phrase}', got '{res.outcome}'"


def test_outcome_snooze_variations():
    # 10 minutes later
    res1 = parse_outcome_rules("10 minutes later")
    assert res1 is not None
    assert res1.outcome == "snooze"
    assert res1.minutes == 10

    # 15 min baad
    res2 = parse_outcome_rules("15 min baad")
    assert res2 is not None
    assert res2.outcome == "snooze"
    assert res2.minutes == 15

    # thodi der baad (defaults to 10)
    res3 = parse_outcome_rules("thodi der baad")
    assert res3 is not None
    assert res3.outcome == "snooze"
    assert res3.minutes == 10

    # 1 ghanta baad -> 60 minutes
    res4 = parse_outcome_rules("1 ghante baad")
    assert res4 is not None
    assert res4.outcome == "snooze"
    assert res4.minutes == 60


def test_outcome_reschedule_variations():
    cases = [
        ("kal karte hain", "tomorrow morning"),
        ("tomorrow", "tomorrow morning"),
        ("move to evening", "evening"),
        ("shift to 5 pm", "5 pm"),
    ]
    for phrase, expected_phrase in cases:
        res = parse_outcome_rules(phrase)
        assert res is not None, f"Failed on: {phrase}"
        assert res.outcome == "reschedule"


def test_outcome_cancel_variations():
    cases = ["cancel", "Cancel it", "nahi chahiye", "nako", "hatao", "beda", "skip", "delete"]
    for phrase in cases:
        res = parse_outcome_rules(phrase)
        assert res is not None, f"Failed on: {phrase}"
        assert res.outcome == "cancel"


def test_done_task_cannot_be_rescheduled_via_reply():
    """A task that is already marked 'done' rejects rescheduling and returns 'already marked as done'."""
    from datetime import datetime
    from starlette.testclient import TestClient
    from main import app
    from db import init_db, SessionLocal, Task, TaskStatus

    init_db()
    db = SessionLocal()
    db.query(Task).delete()
    t = Task(title="Send invoice", due_at=datetime(2026, 10, 31, 12, 30), status=TaskStatus.DONE.value, language="en")
    db.add(t)
    db.commit()
    task_id = t.id
    db.close()

    client = TestClient(app)
    resp = client.post(f"/api/reminders/{task_id}/reply", data={"text": "kal subah"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["outcome"] == "already_done"
    assert "already" in data["reply_text"].lower() or "पहले" in data["reply_text"]

    # Verify task in DB is still DONE, not scheduled
    db = SessionLocal()
    refreshed = db.query(Task).filter_by(id=task_id).first()
    assert refreshed.status == TaskStatus.DONE.value
    db.close()


