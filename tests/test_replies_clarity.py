"""
Tests for Phase 3: Clear, day-aware replies.
Covers:
(a) Cancel confirmations say "Cancelled <title>." or name closest candidate when not found.
(b) Questions like "Why is it still there?" get capability guidance, not "I've noted that."
(c) Reschedule replies include the day ("tomorrow at 9:00 AM", not just "09:00 AM").
(d) Updates are announced as "Moved <title> to <when>." instead of "1 reminder set".
Also verifies format_when(dt, now) across today, tomorrow, weekday within 7 days, and full date.
"""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, patch
from starlette.testclient import TestClient

from timeutil import IST, format_when
from db import init_db, SessionLocal, Task, TaskStatus
from providers.registry import registry
from providers.base import TTSResult
from agent.planner import process_turn
from main import app

client = TestClient(app)
FROZEN_NOW = datetime(2026, 10, 30, 7, 0, 0, tzinfo=IST)  # Friday morning 7:00 AM IST


@pytest.fixture(autouse=True)
def clean_db():
    init_db()
    db = SessionLocal()
    db.query(Task).delete()
    db.commit()
    db.close()


def test_format_when_relative_days():
    """Verify format_when produces expected relative strings with a frozen clock."""
    # 1. Today at 7:00 PM (Friday Oct 30)
    today_evening = datetime(2026, 10, 30, 19, 0, 0, tzinfo=IST)
    assert format_when(today_evening, now=FROZEN_NOW, language="en") == "today at 7:00 PM"
    assert format_when(today_evening, now=FROZEN_NOW, language="hi") == "आज 7:00 PM बजे"
    assert format_when(today_evening, now=FROZEN_NOW, language="kn") == "ಇಂದು 7:00 PM ಕ್ಕೆ"

    # 2. Tomorrow at 9:00 AM (Saturday Oct 31)
    tomorrow_morning = datetime(2026, 10, 31, 9, 0, 0, tzinfo=IST)
    assert format_when(tomorrow_morning, now=FROZEN_NOW, language="en") == "tomorrow at 9:00 AM"
    assert format_when(tomorrow_morning, now=FROZEN_NOW, language="hi") == "कल 9:00 AM बजे"
    assert format_when(tomorrow_morning, now=FROZEN_NOW, language="kn") == "ನಾಳೆ 9:00 AM ಕ್ಕೆ"

    # 3. Monday at 10:00 AM (Monday Nov 2, 3 days out < 7)
    monday_morning = datetime(2026, 11, 2, 10, 0, 0, tzinfo=IST)
    assert format_when(monday_morning, now=FROZEN_NOW, language="en") == "Monday at 10:00 AM"
    assert "सोमवार" in format_when(monday_morning, now=FROZEN_NOW, language="hi")
    assert "ಸೋಮವಾರ" in format_when(monday_morning, now=FROZEN_NOW, language="kn")

    # 4. Dates >= 7 days out (Monday Nov 9, 10 days out)
    next_week = datetime(2026, 11, 9, 10, 0, 0, tzinfo=IST)
    res_en = format_when(next_week, now=FROZEN_NOW, language="en")
    assert "Nov 09" in res_en or "Nov 9" in res_en
    assert "10:00 AM" in res_en


@pytest.mark.asyncio
async def test_problem_a_cancel_success_and_closest_match():
    """(a) Cancel says 'Cancelled <title>.' and closest candidate if not found."""
    db = SessionLocal()
    task = Task(title="Team Meeting", due_at=datetime(2026, 10, 30, 15, 0, 0),
                status=TaskStatus.SCHEDULED.value, language="en")
    db.add(task)
    db.commit()
    db.close()

    # Cancel existing task
    with patch.object(registry.llm, "chat", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {
            "content": "",
            "tool_calls": [
                {
                    "name": "cancel_task",
                    "arguments": {"title": "Team Meeting"}
                }
            ]
        }
        res = await process_turn("remove the meeting", language="en", now=FROZEN_NOW)
        assert res["reply_text"] == "Cancelled Team Meeting."
        assert "I've noted that" not in res["reply_text"]

    # Target task cannot be found -> suggests closest candidate
    db = SessionLocal()
    t2 = Task(title="Dentist Checkup", due_at=datetime(2026, 10, 30, 17, 0, 0),
              status=TaskStatus.SCHEDULED.value, language="en")
    db.add(t2)
    db.commit()
    db.close()

    with patch.object(registry.llm, "chat", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {
            "content": "",
            "tool_calls": [
                {
                    "name": "cancel_task",
                    "arguments": {"title": "Doctor"}
                }
            ]
        }
        res_not_found = await process_turn("cancel doctor", language="en", now=FROZEN_NOW)
        assert "Could not find that task" in res_not_found["reply_text"]
        assert "Dentist Checkup" in res_not_found["reply_text"]


@pytest.mark.asyncio
async def test_problem_b_question_guidance():
    """(b) Questions like 'Why is it still there?' get guidance, not 'I've noted that.'."""
    with patch.object(registry.llm, "chat", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {
            "content": "I've noted that.",  # Simulate generic LLM content
            "tool_calls": []
        }
        res = await process_turn("Why is it still there?", language="en", now=FROZEN_NOW)
        assert "I can set, move, snooze or cancel reminders" in res["reply_text"]
        assert "I've noted that" not in res["reply_text"]

        # Hindi question
        res_hi = await process_turn("क्या कर सकते हो?", language="hi", now=FROZEN_NOW)
        assert "मैं रिमाइंडर सेट, आगे बढ़ा, स्नूज़ या रद्द कर सकता हूँ" in res_hi["reply_text"]
        assert "I've noted that" not in res_hi["reply_text"]

        # Non-task, non-question fallback
        res_fallback = await process_turn("something random not a task", language="en", now=FROZEN_NOW)
        assert "I didn't catch a task or time in that" in res_fallback["reply_text"]
        assert "I've noted that" not in res_fallback["reply_text"]


def test_problem_c_reschedule_reply_includes_day():
    """(c) Reschedule reply includes the day (e.g. 'tomorrow at 9:00 AM', not just '09:00 AM')."""
    db = SessionLocal()
    task = Task(title="Gym Workout", due_at=datetime(2026, 10, 30, 18, 0, 0),
                status=TaskStatus.DUE.value, language="en")
    db.add(task)
    db.commit()
    task_id = task.id
    db.close()

    with patch.object(registry, "synthesize", new_callable=AsyncMock) as mock_synth, \
         patch("routes.tasks.now_ist", return_value=FROZEN_NOW):
        mock_synth.return_value = TTSResult(use_browser_tts=True, provider="browser")

        resp = client.post(f"/api/reminders/{task_id}/reply", data={"text": "move to tomorrow at 9 am"})
        assert resp.status_code == 200
        data = resp.json()

        assert data["outcome"] == "reschedule"
        # Reply must include day and time
        assert "tomorrow at 9:00 AM" in data["reply_text"]
        assert "Moved Gym Workout to tomorrow at 9:00 AM." in data["reply_text"]


@pytest.mark.asyncio
async def test_problem_d_update_announced_as_moved():
    """(d) Updates are announced as 'Moved <title> to <when>.' instead of '1 reminder set'."""
    db = SessionLocal()
    task = Task(title="Gym", due_at=datetime(2026, 10, 30, 18, 0, 0),
                status=TaskStatus.SCHEDULED.value, language="en")
    db.add(task)
    db.commit()
    task_id = task.id
    db.close()

    with patch.object(registry.llm, "chat", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {
            "content": "",
            "tool_calls": [
                {
                    "name": "update_task",
                    "arguments": {
                        "task_id": task_id,
                        "time_phrase": "tomorrow at 7 pm"
                    }
                }
            ]
        }
        res = await process_turn("gym at 6, no 7 pm tomorrow", language="en", now=FROZEN_NOW)
        assert "Moved Gym to tomorrow at 7:00 PM." in res["reply_text"]
        assert "1 reminder set" not in res["reply_text"]
