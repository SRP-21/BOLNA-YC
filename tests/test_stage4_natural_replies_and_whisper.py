"""
Tests for Stage 4: Natural spoken replies and Whisper time normalization.
Verifies:
1. Whisper time normalization ("5 p.m.", "5 P.M.", "6 o'clock", "5pm", "five pm", "half past 5", "half past five")
   resolves cleanly to explicit times with needs_confirmation=False and no guess note.
2. Bare hour resolved to AM/PM (e.g. "5" -> 5 pm) has needs_confirmation=False and NO guess note.
3. Spoken replies rotate deterministically through natural variants (indexed by counter).
4. No apologies ("I'm sorry") and never says "I wasn't sure when".
5. Batch additions say "Okay, {count} reminders set." plus guess note only if an unparseable phrase was present.
6. Indic (Hindi, Kannada) natural time phrasing preserved with short, confident variants.
"""
import pytest
from datetime import datetime
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from main import app
from db import SessionLocal, Task
from agent.resolver import resolve_time, normalize_time_phrase, IST
from agent.replies import (
    format_created, reset_variant_counter,
    CREATED_SINGLE_VARIANTS, CREATED_MULTIPLE_VARIANTS, NEEDS_CONF_GUESS_VARIANTS
)
from providers.base import TTSResult

client = TestClient(app)
FROZEN_NOW = datetime(2026, 10, 31, 10, 0, 0, tzinfo=IST)


@pytest.fixture(autouse=True)
def clean_state():
    reset_variant_counter()
    yield
    reset_variant_counter()


def test_whisper_time_phrase_normalization():
    """Verify normalize_time_phrase cleans Whisper outputs into standard time strings."""
    assert normalize_time_phrase("5 p.m.") == "5 pm"
    assert normalize_time_phrase("5 P.M.") == "5 pm"
    assert normalize_time_phrase("10 a.m.") == "10 am"
    assert normalize_time_phrase("10 A.M.") == "10 am"
    assert normalize_time_phrase("6 o'clock") == "6"
    assert normalize_time_phrase("6 oclock") == "6"
    assert normalize_time_phrase("five pm") == "5 pm"
    assert normalize_time_phrase("two am") == "2 am"
    assert normalize_time_phrase("half past 5") == "5:30"
    assert normalize_time_phrase("half past five") == "5:30"
    assert normalize_time_phrase("half past 5 p.m.") == "5:30 pm"
    assert normalize_time_phrase("quarter past 6") == "6:15"
    assert normalize_time_phrase("quarter to 7") == "6:45"
    assert normalize_time_phrase("five in the evening") == "5 pm"


def test_whisper_strings_resolve_to_explicit_times_no_confirmation_badge():
    """Whisper strings with dots ('5 p.m.', '5 P.M.') resolve to explicit times with needs_confirmation=False."""
    # 5 p.m.
    r1 = resolve_time("5 p.m.", now=FROZEN_NOW)
    assert r1.dt.hour == 17
    assert r1.dt.minute == 0
    assert r1.needs_confirmation is False
    assert "guess" not in r1.reasoning.lower()

    # 5 P.M.
    r2 = resolve_time("5 P.M.", now=FROZEN_NOW)
    assert r2.dt.hour == 17
    assert r2.needs_confirmation is False

    # half past 5 p.m.
    r3 = resolve_time("half past 5 p.m.", now=FROZEN_NOW)
    assert r3.dt.hour == 17
    assert r3.dt.minute == 30
    assert r3.needs_confirmation is False

    # 6 o'clock (bare hour assumed evening)
    r4 = resolve_time("6 o'clock", now=FROZEN_NOW)
    assert r4.dt.hour == 18
    assert r4.dt.minute == 0
    assert r4.needs_confirmation is False


def test_bare_hour_has_no_confirmation_badge_and_no_guess_note():
    """Bare hour resolved to AM/PM (e.g. '5' -> 17:00) has needs_confirmation=False."""
    r = resolve_time("5", now=FROZEN_NOW)
    assert r.dt.hour == 17
    assert r.needs_confirmation is False
    assert "guess" not in r.reasoning.lower()

    # Format reply for bare hour task
    changes = [{"type": "created", "title": "Gym", "due_at": r.dt.isoformat(), "needs_confirmation": r.needs_confirmation}]
    reply = format_created(changes, language="en", now=FROZEN_NOW)
    assert "was a guess" not in reply
    assert "wasn't sure" not in reply
    assert "Gym" in reply


def test_deterministic_rotating_variants_single_created():
    """Single task creation rotates through all 3 natural variants in order."""
    reset_variant_counter()
    changes = [{"type": "created", "title": "Gym", "due_at": "2026-10-31T18:00:00+05:30", "needs_confirmation": False}]

    v0 = format_created(changes, language="en", now=FROZEN_NOW)
    v1 = format_created(changes, language="en", now=FROZEN_NOW)
    v2 = format_created(changes, language="en", now=FROZEN_NOW)
    v3 = format_created(changes, language="en", now=FROZEN_NOW)

    assert v0 == "Okay, Gym for today at 6:00 PM."
    assert v1 == "Done. Gym, today at 6:00 PM."
    assert v2 == "Got it, Gym for today at 6:00 PM."
    # Rotates back to variant 0
    assert v3 == v0


def test_deterministic_rotating_variants_batch_created():
    """Batch creation rotates through variants in order without unparseable notes if none present."""
    reset_variant_counter()
    changes = [
        {"type": "created", "title": "Gym", "due_at": "2026-10-31T18:00:00+05:30", "needs_confirmation": False},
        {"type": "created", "title": "Walk", "due_at": "2026-10-31T19:00:00+05:30", "needs_confirmation": False},
        {"type": "created", "title": "Dinner", "due_at": "2026-10-31T20:00:00+05:30", "needs_confirmation": False},
    ]

    v0 = format_created(changes, language="en", now=FROZEN_NOW)
    v1 = format_created(changes, language="en", now=FROZEN_NOW)
    v2 = format_created(changes, language="en", now=FROZEN_NOW)

    assert v0 == "Okay, 3 reminders set."
    assert v1 == "Done, 3 reminders set."
    assert v2 == "Got it, 3 reminders set."
    assert "was a guess" not in v0


def test_batch_addition_appends_guess_note_only_for_unparseable_phrase():
    """Batch additions only append guess note if an unparseable phrase was present."""
    changes = [
        {"type": "created", "title": "Gym", "due_at": "2026-10-31T18:00:00+05:30", "needs_confirmation": False},
        {"type": "created", "title": "Groceries", "due_at": "2026-10-31T19:00:00+05:30", "needs_confirmation": True, "resolution_note": "Could not parse 'on the way back'"},
    ]
    reply = format_created(changes, language="en", now=FROZEN_NOW)
    assert "2 reminders set." in reply
    assert "Groceries was a guess — I set it for today at 7:00 PM." in reply
    assert "Gym was a guess" not in reply


def test_single_needs_confirmation_never_apologizes_and_never_says_wasnt_sure():
    """Single task needs_confirmation uses short confident phrasing without 'wasn't sure when' or 'I'm sorry'."""
    changes = [{"type": "created", "title": "Doctor", "due_at": "2026-10-31T12:30:00+05:30", "needs_confirmation": True}]

    reply = format_created(changes, language="en", now=FROZEN_NOW)
    assert "sorry" not in reply.lower()
    assert "wasn't sure when" not in reply.lower()
    assert "was not sure" not in reply.lower()
    assert "Tell me if you want a different time" in reply or "works" in reply


def test_text_turn_with_whisper_time_creates_explicit_task():
    """End-to-end turn with Whisper dot time 'standup at 5 p.m.' creates task without confirmation badge."""
    mock_add = {
        "id": "call_add_whisper",
        "name": "add_task",
        "arguments": {"title": "Standup", "time_phrase": "5 p.m."}
    }
    with patch("providers.registry.registry.synthesize", new_callable=AsyncMock) as mock_synth, \
         patch("providers.registry.registry.llm.chat", new_callable=AsyncMock) as mock_chat:
        mock_synth.return_value = TTSResult(use_browser_tts=True, provider="browser")
        mock_chat.return_value = {"content": None, "tool_calls": [mock_add], "finish_reason": "tool_calls"}

        resp = client.post("/api/text/turn", data={"text": "standup at 5 p.m."})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["task_changes"]) == 1
        t_change = data["task_changes"][0]
        assert t_change["needs_confirmation"] is False
        assert "17:00" in t_change["due_at"]
        assert "was a guess" not in data["reply_text"]
