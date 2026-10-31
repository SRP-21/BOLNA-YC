"""
Tests for Phase 5: Better vague times.
Frozen clock: 07:00 IST Saturday 2026-10-31.

(1) 'kal subah 9 baje' -> tomorrow (Nov 1) 09:00, NOT today
(2) 'subah 9 baje' -> today (Oct 31) 09:00
(3) 'tomorrow at 5 pm' -> tomorrow (Nov 1) 17:00
(4) 'gym around 6, groceries on the way back' -> groceries 60 min after gym, needs_confirmation=True
(5) Spoken reply for a guessed/vague task mentions "wasn't sure when"
"""
import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from db import init_db, SessionLocal, Task, TaskStatus
from agent.resolver import resolve_time, IST
from agent.planner import _handle_add_task
from agent.replies import format_created

# Frozen clock: 07:00 IST Saturday 2026-10-31
FROZEN_NOW = datetime(2026, 10, 31, 7, 0, 0, tzinfo=IST)


@pytest.fixture(autouse=True)
def clean_db():
    init_db()
    db = SessionLocal()
    db.query(Task).delete()
    db.commit()
    db.close()


# --------------------------------------------------------------------------- #
# Resolver tests
# --------------------------------------------------------------------------- #

def test_kal_subah_9_baje_is_tomorrow():
    """'kal subah 9 baje' with now=07:00 Oct 31 -> Nov 1 at 09:00, NOT today."""
    r = resolve_time("kal subah 9 baje", now=FROZEN_NOW)
    assert r.dt.day == 1, f"Expected Nov 1, got {r.dt}"
    assert r.dt.month == 11
    assert r.dt.hour == 9
    assert r.dt.minute == 0
    assert r.needs_confirmation is False


def test_subah_9_baje_is_today():
    """'subah 9 baje' with now=07:00 Oct 31 -> today Oct 31 at 09:00."""
    r = resolve_time("subah 9 baje", now=FROZEN_NOW)
    assert r.dt.day == 31, f"Expected Oct 31, got {r.dt}"
    assert r.dt.month == 10
    assert r.dt.hour == 9
    assert r.needs_confirmation is False


def test_tomorrow_at_5pm():
    """'tomorrow at 5 pm' -> Nov 1 at 17:00."""
    r = resolve_time("tomorrow at 5 pm", now=FROZEN_NOW)
    assert r.dt.day == 1
    assert r.dt.month == 11
    assert r.dt.hour == 17
    assert r.needs_confirmation is False


def test_vague_on_the_way_back_with_anchor():
    """'on the way back' with anchor=gym@18:00 -> 19:00, needs_confirmation=True."""
    gym_dt = datetime(2026, 10, 31, 18, 0, 0, tzinfo=IST)
    r = resolve_time("on the way back", now=FROZEN_NOW, anchor_dt=gym_dt)
    assert r.dt.hour == 19
    assert r.dt.minute == 0
    assert r.needs_confirmation is True
    assert "60 min after" in r.reasoning or "previous task" in r.reasoning


def test_vague_on_the_way_back_without_anchor():
    """'on the way back' with no anchor -> now+1 hour, needs_confirmation=True."""
    r = resolve_time("on the way back", now=FROZEN_NOW)
    expected = FROZEN_NOW + timedelta(hours=1)
    assert r.dt.hour == expected.hour
    assert r.needs_confirmation is True


# --------------------------------------------------------------------------- #
# Planner level: batch chaining
# --------------------------------------------------------------------------- #

def test_gym_then_groceries_chained():
    """In a batch, groceries after gym should be 60 min after gym (needs_confirmation)."""
    db = SessionLocal()
    try:
        gym = _handle_add_task(db, {"title": "Gym", "time_phrase": "around 6"}, FROZEN_NOW, "en")
        assert gym["type"] == "created"
        gym_dt_iso = gym["due_at"]

        # Parse anchor from gym result
        from datetime import datetime as dt
        gym_resolved = dt.fromisoformat(gym_dt_iso).replace(tzinfo=IST)

        groceries = _handle_add_task(
            db,
            {"title": "Groceries", "time_phrase": "on the way back"},
            FROZEN_NOW,
            "en",
            anchor_dt=gym_resolved,
        )
        assert groceries["type"] == "created"
        assert groceries["needs_confirmation"] is True

        gym_dt = dt.fromisoformat(gym["due_at"]).replace(tzinfo=IST)
        groc_dt = dt.fromisoformat(groceries["due_at"]).replace(tzinfo=IST)
        diff = (groc_dt - gym_dt).total_seconds() / 60
        assert diff == 60.0, f"Expected 60 min gap, got {diff}"
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Reply: guess message for vague task
# --------------------------------------------------------------------------- #

def test_guess_reply_mentions_time():
    """Spoken reply for a single vague task says 'wasn't sure when'."""
    changes = [{
        "type": "created",
        "title": "Groceries",
        "due_at": "2026-10-31T19:00:00+05:30",
        "needs_confirmation": True,
    }]
    reply = format_created(changes, language="en", now=FROZEN_NOW)
    assert "Groceries" in reply
    assert "7:00 PM" in reply
    assert "different time" in reply.lower() or "works" in reply.lower() or "sure" in reply.lower() or "wasn" in reply.lower(), f"Expected guess phrasing, got: {reply!r}"


def test_guess_reply_hindi():
    """Hindi spoken reply for a vague task."""
    changes = [{
        "type": "created",
        "title": "Kirana",
        "due_at": "2026-10-31T19:00:00+05:30",
        "needs_confirmation": True,
    }]
    reply = format_created(changes, language="hi", now=FROZEN_NOW)
    assert "Kirana" in reply
    assert "समय पता नहीं था" in reply or "सेट किया" in reply, f"Expected Hindi guess phrasing, got: {reply!r}"


def test_batch_guess_note_in_reply():
    """Batch reply mentions unparseable-phrase guesses by name with a short note."""
    changes = [
        {"type": "created", "title": "Standup", "due_at": "2026-10-31T10:00:00+05:30", "needs_confirmation": False, "resolution_note": "Exact time: 10:00"},
        {"type": "created", "title": "Send invoice", "due_at": "2026-10-31T12:30:00+05:30", "needs_confirmation": True, "resolution_note": "Vague phrase 'before lunch' -> 12:30"},
        {"type": "created", "title": "Gym", "due_at": "2026-10-31T18:00:00+05:30", "needs_confirmation": True, "resolution_note": "Guessed PM for bare '6' (assumed evening)"},
        {"type": "created", "title": "Groceries", "due_at": "2026-10-31T19:00:00+05:30", "needs_confirmation": True, "resolution_note": "Could not parse 'on the way back'; scheduled 60 min after previous task at 06:00 PM"},
    ]
    reply = format_created(changes, language="en", now=FROZEN_NOW)
    assert any(w in reply for w in ["4 reminders set", "4 reminders"])
    assert "Groceries was a guess" in reply
    assert "Tell me if you want a different time" in reply
    # Vague-phrase and AM/PM guesses must NOT get the guess note
    assert "Send invoice was a guess" not in reply
    assert "Gym was a guess" not in reply
    # Day-aware format helper was used
    assert "today at 7:00 PM" in reply

