"""
Tests for extraction, planning logic, deduplication, and mid-sentence corrections.
Covers 8+ realistic transcripts across English, Hindi, Hinglish, Kannada-English.
"""
import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from db import init_db, SessionLocal, Task, TaskStatus
from agent.resolver import resolve_time, IST
from agent.planner import _handle_add_task, _handle_update_task, _handle_cancel_task

FIXED_NOW = datetime(2026, 10, 30, 14, 0, 0, tzinfo=IST)


@pytest.fixture(autouse=True)
def setup_clean_db():
    init_db()
    db = SessionLocal()
    db.query(Task).delete()
    db.commit()
    db.close()


def test_transcript_1_english_brain_dump():
    """English: standup at 10, invoice before lunch, gym around 6, groceries on the way back"""
    db = SessionLocal()
    # 1. standup at 10 (was 10 am -> pushed to tomorrow 10am)
    t1 = _handle_add_task(db, {"title": "Standup", "time_phrase": "10 am"}, FIXED_NOW, "en")
    assert t1["type"] == "created"
    assert t1["title"] == "Standup"

    # 2. send invoice before lunch (vague phrase -> needs_confirmation)
    t2 = _handle_add_task(db, {"title": "Send invoice", "time_phrase": "before lunch"}, FIXED_NOW, "en")
    assert t2["type"] == "created"
    assert t2["needs_confirmation"] is True
    assert "before lunch" in t2["resolution_note"]

    # 3. gym around 6 (bare 6 -> guessed 6 PM / 18:00)
    t3 = _handle_add_task(db, {"title": "Gym", "time_phrase": "6"}, FIXED_NOW, "en")
    assert t3["type"] == "created"
    assert "18:00" in t3["due_at"]

    db.close()


def test_transcript_2_hindi():
    """Hindi: dopahar 1 baje khana khana hai, shaam 6 baje gym jana hai"""
    db = SessionLocal()
    t1 = _handle_add_task(db, {"title": "Khana khana", "time_phrase": "1 pm"}, FIXED_NOW, "hi")
    assert t1["type"] == "created"

    t2 = _handle_add_task(db, {"title": "Gym", "time_phrase": "shaam 6 baje"}, FIXED_NOW, "hi")
    assert t2["type"] == "created"
    assert "18:00" in t2["due_at"]
    db.close()


def test_transcript_3_kannada_english_mix():
    """Kannada-English: beligge 9 am meeting ide, sanje 6 pm groceries"""
    db = SessionLocal()
    t1 = _handle_add_task(db, {"title": "Team meeting", "time_phrase": "beligge"}, FIXED_NOW, "kn")
    assert t1["type"] == "created"
    assert t1["needs_confirmation"] is True

    t2 = _handle_add_task(db, {"title": "Groceries", "time_phrase": "sanje"}, FIXED_NOW, "kn")
    assert t2["type"] == "created"
    assert "18:00" in t2["due_at"]
    db.close()


def test_transcript_4_hinglish():
    """Hinglish: lunch se pehle review finish karna hai, kal subah invoice send karna hai"""
    db = SessionLocal()
    t1 = _handle_add_task(db, {"title": "Finish review", "time_phrase": "lunch se pehle"}, FIXED_NOW, "hi")
    assert t1["type"] == "created"
    assert t1["needs_confirmation"] is True

    t2 = _handle_add_task(db, {"title": "Send invoice", "time_phrase": "kal subah"}, FIXED_NOW, "hi")
    assert t2["type"] == "created"
    assert "2026-10-31" in t2["due_at"]
    db.close()


def test_transcript_5_recurring_monday():
    """Recurring: every Monday team sync at 10 am"""
    db = SessionLocal()
    t = _handle_add_task(db, {
        "title": "Team sync",
        "time_phrase": "10 am",
        "recurrence": "weekly:monday"
    }, FIXED_NOW, "en")
    assert t["type"] == "created"
    assert t["recurrence"] == "weekly:monday"
    db.close()


def test_transcript_6_time_after_midnight():
    """Tomorrow at 7: naale / tomorrow at 7"""
    db = SessionLocal()
    t = _handle_add_task(db, {"title": "Call mom", "time_phrase": "tomorrow at 7 pm"}, FIXED_NOW, "en")
    assert t["type"] == "created"
    assert "2026-10-31" in t["due_at"]
    assert "19:00" in t["due_at"]
    db.close()


def test_transcript_7_duplicate_detection():
    """Duplicate: adding 'Gym' at 6pm twice within 30 min updates the existing task instead of duplicating"""
    db = SessionLocal()
    t1 = _handle_add_task(db, {"title": "Gym workout", "time_phrase": "6 pm"}, FIXED_NOW, "en")
    assert t1["type"] == "created"
    first_id = t1["task_id"]

    # Same title, nearby time
    t2 = _handle_add_task(db, {"title": "Gym workout", "time_phrase": "6:15 pm"}, FIXED_NOW, "en")
    assert t2["type"] == "updated_duplicate"
    assert t2["task_id"] == first_id

    # Verify DB only has 1 task
    count = db.query(Task).count()
    assert count == 1
    db.close()


def test_transcript_8_correction():
    """Mid-sentence correction: 'gym at 6, no, 7' -> updates existing task"""
    db = SessionLocal()
    t1 = _handle_add_task(db, {"title": "Gym", "time_phrase": "6 pm"}, FIXED_NOW, "en")
    assert t1["type"] == "created"
    task_id = t1["task_id"]

    # User corrected time to 7 pm
    t2 = _handle_update_task(db, {"task_id": task_id, "time_phrase": "7 pm"}, FIXED_NOW)
    assert t2["type"] == "updated"
    assert "19:00" in t2["due_at"]

    task_in_db = db.query(Task).filter_by(id=task_id).first()
    assert task_in_db.due_at.hour == 19
    db.close()

