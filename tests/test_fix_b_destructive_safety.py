"""
Tests for Stage 3 & 3b (Fix B): Destructive actions safety & pending confirmation.
- Questions ("why is it still there?", "yeh abhi bhi kyun hai?", "यह अभी भी क्यों है?", "ಇದು ಇನ್ನೂ ಯಾಕೆ ಇದೆ?") never execute cancel_task.
- Command word + question phrasing ("can you remove the gym?") asks confirmation: "Should I cancel <title>?"
- Non-question, no-command phrasing ("forget the gym") asks confirmation: "Do you want me to cancel <title>?"
- Plain commands in EN, HI ("जिम कैंसिल कर दो", "जिम हटा दीजिए", "जिम हटाओ"), and KN ("ಜಿಮ್ ರದ್ದು ಮಾಡಿ", "ಜಿಮ್ ತೆಗೆದುಹಾಕು") execute directly.
- Pending confirmation handling:
  - 'yes' executes cancel using stored task_id.
  - 'no' aborts and returns "Okay, I'll leave <title>."
  - Expiry after 60s (freeze clock): bare yes gets "Yes to what? I don't have a pending question."
  - Another command clears state and executes its own action.
  - Task already done when 'yes' arrives returns already done message.
  - Bare 'yes' with no pending state returns "Yes to what? I don't have a pending question."
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, AsyncMock

from db import init_db, SessionLocal, Task, TaskStatus
from agent.planner import process_turn
from agent.pending_action import clear_pending_action, get_pending_action
from providers.registry import registry
from timeutil import IST

FROZEN_NOW = datetime(2026, 10, 31, 10, 0, 0, tzinfo=IST)


@pytest.fixture(autouse=True)
def clean_db():
    init_db()
    clear_pending_action()
    db = SessionLocal()
    db.query(Task).delete()
    db.commit()
    db.close()
    yield
    clear_pending_action()


@pytest.mark.asyncio
async def test_question_without_command_why_is_it_still_there():
    """LLM hallucinating cancel_task on 'why is it still there?' must NOT cancel and NOT offer 'Did you mean'."""
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
        res = await process_turn("why is it still there?", language="en", now=FROZEN_NOW)

    db = SessionLocal()
    refreshed = db.query(Task).filter_by(id=task_id).first()
    assert refreshed.status == TaskStatus.SCHEDULED.value
    db.close()

    assert "Did you mean" not in res["reply_text"]
    assert "Send invoice" not in res["reply_text"]
    assert "What would you like to do?" in res["reply_text"]


@pytest.mark.asyncio
async def test_question_without_command_hindi():
    """Hindi questions ('yeh abhi bhi kyun hai?' & 'यह अभी भी क्यों है?') never execute cancel and give Hindi help."""
    db = SessionLocal()
    t = Task(title="Send invoice", due_at=datetime(2026, 10, 31, 12, 30), status=TaskStatus.SCHEDULED.value)
    db.add(t)
    db.commit()
    task_id = t.id
    db.close()

    for q_text in ["yeh abhi bhi kyun hai?", "यह अभी भी क्यों है?"]:
        with patch.object(registry.llm, "chat", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = {
                "content": "",
                "tool_calls": [{
                    "name": "cancel_task",
                    "arguments": {"task_id": task_id, "title": "Send invoice"}
                }]
            }
            res = await process_turn(q_text, language="hi", now=FROZEN_NOW)

        db = SessionLocal()
        refreshed = db.query(Task).filter_by(id=task_id).first()
        assert refreshed.status == TaskStatus.SCHEDULED.value
        db.close()

        assert "मतलब" not in res["reply_text"]
        assert "आप क्या करना चाहते हैं?" in res["reply_text"]


@pytest.mark.asyncio
async def test_question_without_command_kannada_native():
    """Kannada question in native script ('ಇದು ಇನ್ನೂ ಯಾಕೆ ಇದೆ?') never executes cancel and gives Kannada help."""
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
        res = await process_turn("ಇದು ಇನ್ನೂ ಯಾಕೆ ಇದೆ?", language="kn", now=FROZEN_NOW)

    db = SessionLocal()
    refreshed = db.query(Task).filter_by(id=task_id).first()
    assert refreshed.status == TaskStatus.SCHEDULED.value
    db.close()

    assert "ಉಲ್ಲೇಖಿಸಿದ್ದೀರಾ" not in res["reply_text"]
    assert "ನೀವು ಏನು ಮಾಡಲು ಬಯಸುತ್ತೀರಿ?" in res["reply_text"]


@pytest.mark.asyncio
async def test_command_word_with_question_phrasing_asks_confirmation():
    """Command word AND question phrasing ('can you remove the gym?') asks 'Should I cancel Gym?' and sets pending state."""
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

    # 1. Assert task is NOT cancelled yet
    db = SessionLocal()
    refreshed = db.query(Task).filter_by(id=task_id).first()
    assert refreshed.status == TaskStatus.SCHEDULED.value
    db.close()

    # 2. Confirmation question asked
    assert res["reply_text"] == "Should I cancel Gym?"

    # 3. Pending action is set
    pending = get_pending_action(now=FROZEN_NOW)
    assert pending is not None
    assert pending.task_id == task_id
    assert pending.title == "Gym"


@pytest.mark.asyncio
async def test_no_command_not_question_forget_the_gym_prompts_want_confirm():
    """Non-question, no-command phrasing ('forget the gym') asks 'Do you want me to cancel Gym?' and sets pending state."""
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
        res = await process_turn("forget the gym", language="en", now=FROZEN_NOW)

    # 1. Assert task is NOT cancelled yet
    db = SessionLocal()
    refreshed = db.query(Task).filter_by(id=task_id).first()
    assert refreshed.status == TaskStatus.SCHEDULED.value
    db.close()

    # 2. Asks 'Do you want me to cancel Gym?'
    assert res["reply_text"] == "Do you want me to cancel Gym?"

    # 3. Pending action is set
    pending = get_pending_action(now=FROZEN_NOW)
    assert pending is not None
    assert pending.task_id == task_id


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

    db = SessionLocal()
    refreshed = db.query(Task).filter_by(id=task_id).first()
    assert refreshed.status == TaskStatus.CANCELLED.value
    db.close()

    assert res["reply_text"] == "Cancelled Standup."


@pytest.mark.asyncio
async def test_plain_commands_hindi_native_execute():
    """Hindi commands ('जिम कैंसिल कर दो', 'जिम हटा दीजिए', 'जिम हटाओ') execute directly."""
    for cmd in ["जिम कैंसिल कर दो", "जिम हटा दीजिए", "जिम हटाओ"]:
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
            res = await process_turn(cmd, language="hi", now=FROZEN_NOW)

        db = SessionLocal()
        refreshed = db.query(Task).filter_by(id=task_id).first()
        assert refreshed.status == TaskStatus.CANCELLED.value
        db.close()

        assert "रद्द कर दिया गया है।" in res["reply_text"]


@pytest.mark.asyncio
async def test_plain_commands_kannada_native_execute():
    """Kannada commands ('ಜಿಮ್ ರದ್ದು ಮಾಡಿ', 'ಜಿಮ್ ತೆಗೆದುಹಾಕು') execute directly."""
    for cmd in ["ಜಿಮ್ ರದ್ದು ಮಾಡಿ", "ಜಿಮ್ ತೆಗೆದುಹಾಕು"]:
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
            res = await process_turn(cmd, language="kn", now=FROZEN_NOW)

        db = SessionLocal()
        refreshed = db.query(Task).filter_by(id=task_id).first()
        assert refreshed.status == TaskStatus.CANCELLED.value
        db.close()

        assert "ರದ್ದುಗೊಳಿಸಲಾಗಿದೆ." in res["reply_text"]


@pytest.mark.asyncio
async def test_pending_confirmation_yes_executes():
    """Follow-up 'yes' executes pending cancel."""
    db = SessionLocal()
    t = Task(title="Gym", due_at=datetime(2026, 10, 31, 18, 0), status=TaskStatus.SCHEDULED.value)
    db.add(t)
    db.commit()
    task_id = t.id
    db.close()

    # Step 1: Prompt confirmation
    with patch.object(registry.llm, "chat", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {
            "content": "",
            "tool_calls": [{"name": "cancel_task", "arguments": {"title": "Gym"}}]
        }
        await process_turn("can you remove the gym?", language="en", now=FROZEN_NOW)

    # Step 2: User responds 'yes'
    res = await process_turn("yes", language="en", now=FROZEN_NOW + timedelta(seconds=5))

    db = SessionLocal()
    refreshed = db.query(Task).filter_by(id=task_id).first()
    assert refreshed.status == TaskStatus.CANCELLED.value
    db.close()

    assert res["reply_text"] == "Cancelled Gym."
    assert get_pending_action(now=FROZEN_NOW + timedelta(seconds=5)) is None


@pytest.mark.asyncio
async def test_pending_confirmation_no_aborts_and_keeps_task():
    """Follow-up 'no' clears pending state and keeps the task."""
    db = SessionLocal()
    t = Task(title="Gym", due_at=datetime(2026, 10, 31, 18, 0), status=TaskStatus.SCHEDULED.value)
    db.add(t)
    db.commit()
    task_id = t.id
    db.close()

    with patch.object(registry.llm, "chat", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {
            "content": "",
            "tool_calls": [{"name": "cancel_task", "arguments": {"title": "Gym"}}]
        }
        await process_turn("can you remove the gym?", language="en", now=FROZEN_NOW)

    res = await process_turn("no", language="en", now=FROZEN_NOW + timedelta(seconds=5))

    db = SessionLocal()
    refreshed = db.query(Task).filter_by(id=task_id).first()
    assert refreshed.status == TaskStatus.SCHEDULED.value
    db.close()

    assert res["reply_text"] == "Okay, I'll leave Gym."
    assert get_pending_action(now=FROZEN_NOW + timedelta(seconds=5)) is None


@pytest.mark.asyncio
async def test_pending_confirmation_expiry_after_60s():
    """Pending confirmation expires after 60s; bare 'yes' afterwards changes nothing."""
    db = SessionLocal()
    t = Task(title="Gym", due_at=datetime(2026, 10, 31, 18, 0), status=TaskStatus.SCHEDULED.value)
    db.add(t)
    db.commit()
    task_id = t.id
    db.close()

    with patch.object(registry.llm, "chat", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {
            "content": "",
            "tool_calls": [{"name": "cancel_task", "arguments": {"title": "Gym"}}]
        }
        await process_turn("can you remove the gym?", language="en", now=FROZEN_NOW)

    # 65 seconds later
    res = await process_turn("yes", language="en", now=FROZEN_NOW + timedelta(seconds=65))

    db = SessionLocal()
    refreshed = db.query(Task).filter_by(id=task_id).first()
    assert refreshed.status == TaskStatus.SCHEDULED.value
    db.close()

    assert res["reply_text"] == "Yes to what? I don't have a pending question."


@pytest.mark.asyncio
async def test_pending_confirmation_another_command_clears_state():
    """Any non-yes/no utterance clears pending confirmation and processes normally."""
    db = SessionLocal()
    t = Task(title="Gym", due_at=datetime(2026, 10, 31, 18, 0), status=TaskStatus.SCHEDULED.value)
    db.add(t)
    db.commit()
    task_id = t.id
    db.close()

    with patch.object(registry.llm, "chat", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {
            "content": "",
            "tool_calls": [{"name": "cancel_task", "arguments": {"title": "Gym"}}]
        }
        await process_turn("can you remove the gym?", language="en", now=FROZEN_NOW)

    # User issues a new add_task command instead of answering yes/no
    with patch.object(registry.llm, "chat", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {
            "content": "",
            "tool_calls": [{"name": "add_task", "arguments": {"title": "Standup", "time_phrase": "10:00 AM"}}]
        }
        res = await process_turn("standup at 10", language="en", now=FROZEN_NOW + timedelta(seconds=5))

    db = SessionLocal()
    gym = db.query(Task).filter_by(id=task_id).first()
    standup = db.query(Task).filter_by(title="Standup").first()
    assert gym.status == TaskStatus.SCHEDULED.value
    assert standup is not None
    db.close()

    assert get_pending_action(now=FROZEN_NOW + timedelta(seconds=5)) is None
    assert "Standup" in res["reply_text"]


@pytest.mark.asyncio
async def test_pending_confirmation_task_already_done_when_yes_arrives():
    """If task is completed before 'yes' arrives, reject cancellation and report already done."""
    db = SessionLocal()
    t = Task(title="Gym", due_at=datetime(2026, 10, 31, 18, 0), status=TaskStatus.SCHEDULED.value)
    db.add(t)
    db.commit()
    task_id = t.id
    db.close()

    with patch.object(registry.llm, "chat", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {
            "content": "",
            "tool_calls": [{"name": "cancel_task", "arguments": {"title": "Gym"}}]
        }
        await process_turn("can you remove the gym?", language="en", now=FROZEN_NOW)

    # In background, task marked DONE
    db = SessionLocal()
    t_mod = db.query(Task).filter_by(id=task_id).first()
    t_mod.status = TaskStatus.DONE.value
    db.commit()
    db.close()

    res = await process_turn("yes", language="en", now=FROZEN_NOW + timedelta(seconds=5))

    db = SessionLocal()
    refreshed = db.query(Task).filter_by(id=task_id).first()
    assert refreshed.status == TaskStatus.DONE.value
    db.close()

    assert res["reply_text"] == "Gym is already marked as done."
    assert get_pending_action(now=FROZEN_NOW + timedelta(seconds=5)) is None


@pytest.mark.asyncio
async def test_bare_yes_with_no_pending_state():
    """Bare 'yes' with no active confirmation question answers clearly and changes nothing."""
    res = await process_turn("yes", language="en", now=FROZEN_NOW)
    assert res["reply_text"] == "Yes to what? I don't have a pending question."
    assert res["task_changes"] == []


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
