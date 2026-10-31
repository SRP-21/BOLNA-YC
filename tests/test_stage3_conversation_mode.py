"""
Server tests for Conversation Mode and expects_reply semantics (Stage 3).
Verifies:
1. expects_reply is False after plain task creation.
2. expects_reply is True when cancel confirmation is pending.
3. expects_reply is True when ambiguity choice is pending.
4. expects_reply is True when replan preview is pending.
5. expects_reply is True when past-time confirmation is pending.
6. expects_reply is False for completed reminder reply ('done') and True for unclear reminder reply ('huh').
7. Stop words ('stop', 'that's all', 'bas') do not create tasks and return expects_reply=False.
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from main import app
from db import SessionLocal, Task, TaskStatus
from config import settings
from timeutil import ensure_ist, now_ist, to_ist_naive
from providers.base import TTSResult

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_db():
    from agent.pending_action import clear_pending_action
    from agent.pending_choice import clear_pending_choice
    from agent.replan import set_pending_plan
    from db import Utterance
    clear_pending_action()
    clear_pending_choice()
    set_pending_plan(None)
    db = SessionLocal()
    db.query(Task).delete()
    db.query(Utterance).delete()
    db.commit()
    db.close()
    yield
    clear_pending_action()
    clear_pending_choice()
    set_pending_plan(None)
    db = SessionLocal()
    db.query(Task).delete()
    db.query(Utterance).delete()
    db.commit()
    db.close()


def test_plain_task_creation_expects_reply_false():
    """Plain task creation ('standup at 10 am') has no pending questions -> expects_reply=False."""
    with patch("providers.registry.registry.synthesize", new_callable=AsyncMock) as mock_synth:
        mock_synth.return_value = TTSResult(use_browser_tts=True, provider="browser")
        resp = client.post("/api/text/turn", data={"text": "standup at 10 am"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["expects_reply"] is False
        assert len(data["task_changes"]) >= 1


def test_cancel_confirmation_expects_reply_true():
    """Cancel confirmation flow ('can you remove the gym?') sets pending action -> expects_reply=True."""
    # 1. Create task first
    db = SessionLocal()
    t = Task(title="Gym", due_at=to_ist_naive(now_ist() + timedelta(hours=2)), status=TaskStatus.SCHEDULED.value)
    db.add(t)
    db.commit()
    task_id = t.id
    db.close()

    mock_cancel = {
        "id": "call_cancel_1",
        "name": "cancel_task",
        "arguments": {"task_id": task_id, "title": "Gym"}
    }
    with patch("providers.registry.registry.synthesize", new_callable=AsyncMock) as mock_synth, \
         patch("providers.registry.registry.llm.chat", new_callable=AsyncMock) as mock_chat:
        mock_synth.return_value = TTSResult(use_browser_tts=True, provider="browser")
        mock_chat.return_value = {"content": None, "tool_calls": [mock_cancel], "finish_reason": "tool_calls"}
        resp = client.post("/api/text/turn", data={"text": "can you remove the gym?"})
        assert resp.status_code == 200
        data = resp.json()
        assert "Should I cancel Gym?" in data["reply_text"]
        assert data["expects_reply"] is True


def test_ambiguity_choice_expects_reply_true():
    """Ambiguity choice flow ('cancel gym' with Gym and Gym class active) -> expects_reply=True."""
    db = SessionLocal()
    t1 = Task(title="Gym", due_at=to_ist_naive(now_ist() + timedelta(hours=2)), status=TaskStatus.SCHEDULED.value)
    t2 = Task(title="Gym class", due_at=to_ist_naive(now_ist() + timedelta(hours=3)), status=TaskStatus.SCHEDULED.value)
    db.add_all([t1, t2])
    db.commit()
    db.close()

    with patch("providers.registry.registry.synthesize", new_callable=AsyncMock) as mock_synth:
        mock_synth.return_value = TTSResult(use_browser_tts=True, provider="browser")
        resp = client.post("/api/text/turn", data={"text": "cancel gym"})
        assert resp.status_code == 200
        data = resp.json()
        assert "Which one" in data["reply_text"]
        assert data["expects_reply"] is True


def test_replan_preview_expects_reply_true():
    """Replan preview ('push everything by 30 minutes') sets replan preview -> expects_reply=True."""
    db = SessionLocal()
    t1 = Task(title="Gym", due_at=to_ist_naive(now_ist() + timedelta(hours=1)), status=TaskStatus.SCHEDULED.value)
    t2 = Task(title="Doctor", due_at=to_ist_naive(now_ist() + timedelta(hours=2)), status=TaskStatus.SCHEDULED.value)
    db.add_all([t1, t2])
    db.commit()
    db.close()

    with patch("providers.registry.registry.synthesize", new_callable=AsyncMock) as mock_synth:
        mock_synth.return_value = TTSResult(use_browser_tts=True, provider="browser")
        resp = client.post("/api/text/turn", data={"text": "push everything by 30 minutes"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["expects_reply"] is True


def test_past_time_confirmation_expects_reply_true():
    """Past-time confirmation ('aaj standup at 10 baje' at 15:40) -> expects_reply=True."""
    settings.enable_test_clock = True
    now_1540 = "2026-10-31T15:40:00+05:30"
    try:
        mock_add = {
            "id": "call_add_1",
            "name": "add_task",
            "arguments": {"title": "स्टैंडअप", "time_phrase": "10 बजे"}
        }
        with patch("providers.registry.registry.synthesize", new_callable=AsyncMock) as mock_synth, \
             patch("providers.registry.registry.llm.chat", new_callable=AsyncMock) as mock_chat:
            mock_synth.return_value = TTSResult(use_browser_tts=True, provider="browser")
            mock_chat.return_value = {"content": None, "tool_calls": [mock_add], "finish_reason": "tool_calls"}
            resp = client.post("/api/text/turn", data={"text": "आज स्टैंडअप 10 बजे", "now": now_1540})
            assert resp.status_code == 200
            data = resp.json()
            assert "वह समय बीत चुका है" in data["reply_text"]
            assert data["expects_reply"] is True
    finally:
        settings.enable_test_clock = False


def test_reminder_reply_expects_reply():
    """Reminder reply: 'done' resolves task -> expects_reply=False; 'huh' asks question -> expects_reply=True."""
    db = SessionLocal()
    t = Task(title="Standup", due_at=to_ist_naive(now_ist()), status=TaskStatus.DUE.value)
    db.add(t)
    db.commit()
    task_id = t.id
    db.close()

    with patch("providers.registry.registry.synthesize", new_callable=AsyncMock) as mock_synth:
        mock_synth.return_value = TTSResult(use_browser_tts=True, provider="browser")
        # 1. Unclear reply -> expects_reply=True
        r1 = client.post(f"/api/reminders/{task_id}/reply", data={"text": "huh?"})
        assert r1.status_code == 200
        assert r1.json()["expects_reply"] is True

        # 2. Clear reply 'done' -> expects_reply=False
        r2 = client.post(f"/api/reminders/{task_id}/reply", data={"text": "done"})
        assert r2.status_code == 200
        assert r2.json()["expects_reply"] is False


def test_stop_commands_handled_cleanly():
    """Stop words ('stop', 'that's all', 'bas') go idle without creating tasks and return expects_reply=False."""
    with patch("providers.registry.registry.synthesize", new_callable=AsyncMock) as mock_synth:
        mock_synth.return_value = TTSResult(use_browser_tts=True, provider="browser")
        for word in ["stop", "Stop.", "that's all", "that is all", "bas", "बस", "ಸಾಕು"]:
            resp = client.post("/api/text/turn", data={"text": word})
            assert resp.status_code == 200
            data = resp.json()
            assert data["expects_reply"] is False
            assert data.get("stopped") is True
            assert "Okay, going idle." in data["reply_text"]
            assert len(data["task_changes"]) == 0

    db = SessionLocal()
    assert db.query(Task).count() == 0
    db.close()


def test_trailing_stop_creates_task_first_then_stops():
    """A stop phrase at the END of a longer utterance ('gym at 6, that's all') creates task first and then stops."""
    mock_add = {
        "id": "call_add_gym",
        "name": "add_task",
        "arguments": {"title": "Gym", "time_phrase": "6 pm"}
    }
    with patch("providers.registry.registry.synthesize", new_callable=AsyncMock) as mock_synth, \
         patch("providers.registry.registry.llm.chat", new_callable=AsyncMock) as mock_chat:
        mock_synth.return_value = TTSResult(use_browser_tts=True, provider="browser")
        mock_chat.return_value = {"content": None, "tool_calls": [mock_add], "finish_reason": "tool_calls"}
        resp = client.post("/api/text/turn", data={"text": "gym at 6, that's all"})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("stopped") is True
        assert data["expects_reply"] is False
        assert len(data["task_changes"]) >= 1

    db = SessionLocal()
    tasks = db.query(Task).all()
    assert len(tasks) == 1
    assert "gym" in tasks[0].title.lower()
    db.close()


def test_stop_by_the_store_stays_task():
    """'stop by the store at 5' contains 'stop' at the beginning, so it must stay a task and not stop."""
    mock_add = {
        "id": "call_add_store",
        "name": "add_task",
        "arguments": {"title": "Stop by the store", "time_phrase": "5 pm"}
    }
    with patch("providers.registry.registry.synthesize", new_callable=AsyncMock) as mock_synth, \
         patch("providers.registry.registry.llm.chat", new_callable=AsyncMock) as mock_chat:
        mock_synth.return_value = TTSResult(use_browser_tts=True, provider="browser")
        mock_chat.return_value = {"content": None, "tool_calls": [mock_add], "finish_reason": "tool_calls"}
        resp = client.post("/api/text/turn", data={"text": "stop by the store at 5"})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("stopped") is False
        assert len(data["task_changes"]) >= 1

    db = SessionLocal()
    tasks = db.query(Task).all()
    assert len(tasks) == 1
    assert "store" in tasks[0].title.lower() or "stop" in tasks[0].title.lower()
    db.close()


def test_hindi_bas_5_baje_stays_task():
    """'बस 5 बजे' begins with 'बस' followed by a time phrase; it must create a task at 5:00 and not stop."""
    mock_add = {
        "id": "call_add_hi",
        "name": "add_task",
        "arguments": {"title": "बस", "time_phrase": "5 बजे"}
    }
    with patch("providers.registry.registry.synthesize", new_callable=AsyncMock) as mock_synth, \
         patch("providers.registry.registry.llm.chat", new_callable=AsyncMock) as mock_chat:
        mock_synth.return_value = TTSResult(use_browser_tts=True, provider="browser")
        mock_chat.return_value = {"content": None, "tool_calls": [mock_add], "finish_reason": "tool_calls"}
        resp = client.post("/api/text/turn", data={"text": "बस 5 बजे"})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("stopped") is False
        assert len(data["task_changes"]) >= 1

    db = SessionLocal()
    tasks = db.query(Task).all()
    assert len(tasks) == 1
    db.close()
