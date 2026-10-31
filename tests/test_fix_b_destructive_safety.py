"""
Tests for Stage 3 (Fix B): Destructive actions safety.
- Questions ("why is it still there?", "yeh abhi bhi kyun hai?", Kannada question) never execute cancel_task.
- Command word + question phrasing ("can you remove the gym?") asks confirmation: "Should I cancel <title>?"
- Plain commands ("remove the standup", "gym cancel karo") execute directly.
- Cancel not-found path never offers "Did you mean" when score is below cutoff.
"""
import pytest
from datetime import datetime
from unittest.mock import patch, AsyncMock

from db import init_db, SessionLocal, Task, TaskStatus
from agent.planner import process_turn
from providers.registry import registry
from timeutil import IST

FROZEN_NOW = datetime(2026, 10, 31, 10, 0, 0, tzinfo=IST)


@pytest.fixture(autouse=True)
def clean_db():
    init_db()
    db = SessionLocal()
    db.query(Task).delete()
    db.commit()
    db.close()


@pytest.mark.asyncio
async def test_question_without_command_why_is_it_still_there():
    """LLM hallucinating cancel_task on 'why is it still there?' must NOT cancel and NOT offer 'Did you mean'."""
    db = SessionLocal()
    t = Task(title="Send invoice", due_at=datetime(2026, 10, 31, 12, 30), status=TaskStatus.SCHEDULED.value)
    db.add(t)
    db.commit()
    task_id = t.id
    db.close()

    # Mock LLM returning cancel_task
    with patch.object(registry.llm, "chat", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {
            "content": "",
            "tool_calls": [{
                "name": "cancel_task",
                "arguments": {"task_id": task_id, "title": "Send invoice"}
            }]
        }
        res = await process_turn("why is it still there?", language="en", now=FROZEN_NOW)

    # 1. Assert task is NOT cancelled
    db = SessionLocal()
    refreshed = db.query(Task).filter_by(id=task_id).first()
    assert refreshed.status == TaskStatus.SCHEDULED.value
    db.close()

    # 2. Assert no "Did you mean" suggestion
    assert "Did you mean" not in res["reply_text"]
    assert "Send invoice" not in res["reply_text"]
    # 3. Assert helpful response
    assert "What would you like to do?" in res["reply_text"]


@pytest.mark.asyncio
async def test_question_without_command_hindi_kyun():
    """Hindi question 'yeh abhi bhi kyun hai?' never executes cancel and gives Hindi help."""
    db = SessionLocal()
    t = Task(title="Send invoice", due_at=datetime(2026, 10, 31, 12, 30), status=TaskStatus.SCHEDULED.value)
    db.add(t)
    db.commit()
    task_id = t.id
    db.close()

    with patch.object(registry.llm, "chat", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {
            "content": "",
            "tool_calls": [{
                "name": "cancel_task",
                "arguments": {"task_id": task_id, "title": "Send invoice"}
            }]
        }
        res = await process_turn("yeh abhi bhi kyun hai?", language="hi", now=FROZEN_NOW)

    db = SessionLocal()
    refreshed = db.query(Task).filter_by(id=task_id).first()
    assert refreshed.status == TaskStatus.SCHEDULED.value
    db.close()

    assert "मतलब" not in res["reply_text"]
    assert "आप क्या करना चाहते हैं?" in res["reply_text"]


@pytest.mark.asyncio
async def test_question_without_command_kannada():
    """Kannada question 'idu innu yake ide?' never executes cancel and gives Kannada help."""
    db = SessionLocal()
    t = Task(title="Send invoice", due_at=datetime(2026, 10, 31, 12, 30), status=TaskStatus.SCHEDULED.value)
    db.add(t)
    db.commit()
    task_id = t.id
    db.close()

    with patch.object(registry.llm, "chat", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {
            "content": "",
            "tool_calls": [{
                "name": "cancel_task",
                "arguments": {"task_id": task_id, "title": "Send invoice"}
            }]
        }
        res = await process_turn("idu innu yake ide?", language="kn", now=FROZEN_NOW)

    db = SessionLocal()
    refreshed = db.query(Task).filter_by(id=task_id).first()
    assert refreshed.status == TaskStatus.SCHEDULED.value
    db.close()

    assert "ಉಲ್ಲೇಖಿಸಿದ್ದೀರಾ" not in res["reply_text"]
    assert "ನೀವು ಏನು ಮಾಡಲು ಬಯಸುತ್ತೀರಿ?" in res["reply_text"]


@pytest.mark.asyncio
async def test_command_word_with_question_phrasing_asks_confirmation():
    """Command word AND question phrasing ('can you remove the gym?') asks 'Should I cancel Gym?' without cancelling."""
    db = SessionLocal()
    t = Task(title="Gym", due_at=datetime(2026, 10, 31, 18, 0), status=TaskStatus.SCHEDULED.value)
    db.add(t)
    db.commit()
    task_id = t.id
    db.close()

    with patch.object(registry.llm, "chat", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {
            "content": "",
            "tool_calls": [{
                "name": "cancel_task",
                "arguments": {"title": "Gym"}
            }]
        }
        res = await process_turn("can you remove the gym?", language="en", now=FROZEN_NOW)

    # 1. Assert task is NOT cancelled
    db = SessionLocal()
    refreshed = db.query(Task).filter_by(id=task_id).first()
    assert refreshed.status == TaskStatus.SCHEDULED.value
    db.close()

    # 2. Assert confirmation question asked
    assert res["reply_text"] == "Should I cancel Gym?"


@pytest.mark.asyncio
async def test_plain_command_remove_the_standup_executes():
    """Plain command 'remove the standup' executes cancellation directly."""
    db = SessionLocal()
    t = Task(title="Standup", due_at=datetime(2026, 10, 31, 10, 0), status=TaskStatus.SCHEDULED.value)
    db.add(t)
    db.commit()
    task_id = t.id
    db.close()

    with patch.object(registry.llm, "chat", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {
            "content": "",
            "tool_calls": [{
                "name": "cancel_task",
                "arguments": {"title": "Standup"}
            }]
        }
        res = await process_turn("remove the standup", language="en", now=FROZEN_NOW)

    # 1. Assert task IS cancelled
    db = SessionLocal()
    refreshed = db.query(Task).filter_by(id=task_id).first()
    assert refreshed.status == TaskStatus.CANCELLED.value
    db.close()

    # 2. Confirmation reply
    assert res["reply_text"] == "Cancelled Standup."


@pytest.mark.asyncio
async def test_plain_command_hindi_gym_cancel_karo_executes():
    """Plain Hindi command 'gym cancel karo' executes cancellation directly."""
    db = SessionLocal()
    t = Task(title="Gym", due_at=datetime(2026, 10, 31, 18, 0), status=TaskStatus.SCHEDULED.value)
    db.add(t)
    db.commit()
    task_id = t.id
    db.close()

    with patch.object(registry.llm, "chat", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {
            "content": "",
            "tool_calls": [{
                "name": "cancel_task",
                "arguments": {"title": "Gym"}
            }]
        }
        res = await process_turn("gym cancel karo", language="hi", now=FROZEN_NOW)

    # 1. Assert task IS cancelled
    db = SessionLocal()
    refreshed = db.query(Task).filter_by(id=task_id).first()
    assert refreshed.status == TaskStatus.CANCELLED.value
    db.close()

    # 2. Confirmation reply in Hindi
    assert "Gym रद्द कर दिया गया है।" in res["reply_text"]


@pytest.mark.asyncio
async def test_cancel_not_found_below_cutoff_has_no_did_you_mean():
    """Unrelated search query ('cancel doctor' with only 'Dentist checkup' active) gives clear not found without suggestion."""
    db = SessionLocal()
    t = Task(title="Dentist checkup", due_at=datetime(2026, 10, 31, 15, 0), status=TaskStatus.SCHEDULED.value)
    db.add(t)
    db.commit()
    db.close()

    with patch.object(registry.llm, "chat", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {
            "content": "",
            "tool_calls": [{
                "name": "cancel_task",
                "arguments": {"title": "doctor"}
            }]
        }
        res = await process_turn("cancel doctor", language="en", now=FROZEN_NOW)

    assert "Did you mean" not in res["reply_text"]
    assert res["reply_text"] == "Could not find that task to cancel."
