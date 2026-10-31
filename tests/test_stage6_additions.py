"""
Tests for Stage 6 additions:
1. Ambiguity choice follow-up (title, ordinal in en/hi/kn, expiry, unrelated utterance clears it).
2. Bare 'okay' / 'ಆಯಿತು' / 'ठीक है' with no pending question does not mark tasks done.
3. Deterministic precedence between replan preview and cancel confirmation (newest question wins).
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, AsyncMock

from db import init_db, SessionLocal, Task, TaskStatus
from agent.planner import process_turn
from agent.pending_action import set_pending_action, PendingAction, clear_pending_action
from agent.pending_choice import set_pending_choice, PendingChoice, clear_pending_choice
from agent.replan import set_pending_plan
from agent.replan_engine import ReplanPlan, ReplanIntent, TaskChange
from timeutil import IST

FROZEN_NOW = datetime(2026, 10, 31, 10, 0, 0, tzinfo=IST)


@pytest.fixture(autouse=True)
def clean_state():
    init_db()
    clear_pending_action()
    clear_pending_choice()
    set_pending_plan(None)
    db = SessionLocal()
    db.query(Task).delete()
    db.commit()
    db.close()
    yield
    clear_pending_action()
    clear_pending_choice()
    set_pending_plan(None)
    db = SessionLocal()
    db.query(Task).delete()
    db.commit()
    db.close()


def _setup_gym_tasks():
    db = SessionLocal()
    t1 = Task(title="Gym", due_at=datetime(2026, 10, 31, 17, 0, 0), status=TaskStatus.SCHEDULED.value)
    t2 = Task(title="Gym class", due_at=datetime(2026, 10, 31, 18, 0, 0), status=TaskStatus.SCHEDULED.value)
    db.add_all([t1, t2])
    db.commit()
    id1, id2 = t1.id, t2.id
    db.close()
    return id1, id2


@pytest.mark.asyncio
async def test_ambiguity_followup_title_english():
    """Cancel gym -> ambiguous -> reply 'gym class' -> Gym class cancelled directly."""
    id1, id2 = _setup_gym_tasks()

    q_res = await process_turn("cancel gym", language="en", now=FROZEN_NOW)
    assert "Which one did you mean: Gym or Gym class?" in q_res["reply_text"]

    ans_res = await process_turn("gym class", language="en", now=FROZEN_NOW + timedelta(seconds=5))
    assert "Cancelled Gym class." in ans_res["reply_text"]

    db = SessionLocal()
    t1 = db.query(Task).filter_by(id=id1).first()
    t2 = db.query(Task).filter_by(id=id2).first()
    assert t1.status == TaskStatus.SCHEDULED.value
    assert t2.status == TaskStatus.CANCELLED.value
    db.close()


@pytest.mark.asyncio
async def test_ambiguity_followup_ordinal_english():
    """Cancel gym -> ambiguous -> reply 'the second one' -> Gym class cancelled."""
    id1, id2 = _setup_gym_tasks()

    await process_turn("cancel gym", language="en", now=FROZEN_NOW)
    ans_res = await process_turn("the second one", language="en", now=FROZEN_NOW + timedelta(seconds=5))
    assert "Cancelled Gym class." in ans_res["reply_text"]

    db = SessionLocal()
    t1 = db.query(Task).filter_by(id=id1).first()
    t2 = db.query(Task).filter_by(id=id2).first()
    assert t1.status == TaskStatus.SCHEDULED.value
    assert t2.status == TaskStatus.CANCELLED.value
    db.close()


@pytest.mark.asyncio
async def test_ambiguity_followup_hindi():
    """Cancel gym -> ambiguous -> reply 'doosra wala' and 'दूसरा' -> second task cancelled."""
    id1, id2 = _setup_gym_tasks()

    await process_turn("gym cancel karo", language="hi", now=FROZEN_NOW)
    ans_res = await process_turn("दूसरा", language="hi", now=FROZEN_NOW + timedelta(seconds=5))
    assert "Gym class रद्द कर दिया गया है।" in ans_res["reply_text"]

    db = SessionLocal()
    t1 = db.query(Task).filter_by(id=id1).first()
    t2 = db.query(Task).filter_by(id=id2).first()
    assert t1.status == TaskStatus.SCHEDULED.value
    assert t2.status == TaskStatus.CANCELLED.value
    db.close()


@pytest.mark.asyncio
async def test_ambiguity_followup_kannada():
    """Cancel gym -> ambiguous -> reply 'ಎರಡನೆಯದು' -> second task cancelled."""
    id1, id2 = _setup_gym_tasks()

    await process_turn("ಜಿಮ್ ರದ್ದು ಮಾಡಿ", language="kn", now=FROZEN_NOW)
    ans_res = await process_turn("ಎರಡನೆಯದು", language="kn", now=FROZEN_NOW + timedelta(seconds=5))
    assert "Gym class ರದ್ದುಗೊಳಿಸಲಾಗಿದೆ." in ans_res["reply_text"]

    db = SessionLocal()
    t1 = db.query(Task).filter_by(id=id1).first()
    t2 = db.query(Task).filter_by(id=id2).first()
    assert t1.status == TaskStatus.SCHEDULED.value
    assert t2.status == TaskStatus.CANCELLED.value
    db.close()


@pytest.mark.asyncio
async def test_ambiguity_followup_expiry():
    """Pending choice expires after 60 seconds."""
    id1, id2 = _setup_gym_tasks()

    await process_turn("cancel gym", language="en", now=FROZEN_NOW)

    # 65 seconds later -> expired
    with patch("providers.registry.registry.llm.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "I heard gym class."}}]
        }
        res = await process_turn("gym class", language="en", now=FROZEN_NOW + timedelta(seconds=65))

    db = SessionLocal()
    t1 = db.query(Task).filter_by(id=id1).first()
    t2 = db.query(Task).filter_by(id=id2).first()
    assert t1.status == TaskStatus.SCHEDULED.value
    assert t2.status == TaskStatus.SCHEDULED.value
    db.close()


@pytest.mark.asyncio
async def test_ambiguity_unrelated_utterance_clears_choice():
    """Unrelated utterance clears pending choice and processes normally."""
    id1, id2 = _setup_gym_tasks()

    await process_turn("cancel gym", language="en", now=FROZEN_NOW)

    with patch("providers.registry.registry.llm.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "The weather is sunny."}}]
        }
        res = await process_turn("how is the weather?", language="en", now=FROZEN_NOW + timedelta(seconds=5))

    db = SessionLocal()
    t1 = db.query(Task).filter_by(id=id1).first()
    t2 = db.query(Task).filter_by(id=id2).first()
    assert t1.status == TaskStatus.SCHEDULED.value
    assert t2.status == TaskStatus.SCHEDULED.value
    db.close()


@pytest.mark.asyncio
async def test_bare_affirmative_no_pending_question_never_marks_done():
    """A bare acknowledgment ('okay' / 'ಆಯಿತು' / 'ठीक है') gets a plain 'Okay.' and does not mark tasks done."""
    id1, id2 = _setup_gym_tasks()

    # 1. English "okay"
    res_en = await process_turn("okay", language="en", now=FROZEN_NOW)
    assert res_en["reply_text"] == "Okay."

    # 2. Hindi "ठीक है"
    res_hi = await process_turn("ठीक है", language="hi", now=FROZEN_NOW)
    assert res_hi["reply_text"] == "ठीक है।"

    # 3. Kannada "ಆಯಿತು"
    res_kn = await process_turn("ಆಯಿತು", language="kn", now=FROZEN_NOW)
    assert res_kn["reply_text"] == "ಸರಿ."

    # 4. Bare "yes"
    res_yes = await process_turn("yes", language="en", now=FROZEN_NOW)
    assert "Yes to what? I don't have a pending question." in res_yes["reply_text"]

    # Check tasks: STILL scheduled!
    db = SessionLocal()
    t1 = db.query(Task).filter_by(id=id1).first()
    t2 = db.query(Task).filter_by(id=id2).first()
    assert t1.status == TaskStatus.SCHEDULED.value
    assert t2.status == TaskStatus.SCHEDULED.value
    db.close()


@pytest.mark.asyncio
async def test_deterministic_precedence_replan_vs_cancel_newest_wins():
    """When both replan preview and cancel confirmation are pending, the newest question wins."""
    id1, id2 = _setup_gym_tasks()

    # Case 1: Cancel confirmation asked first, then Replan preview asked -> Replan wins!
    set_pending_action(PendingAction(
        action="cancel",
        task_id=id1,
        title="Gym",
        language="en",
        created_at=FROZEN_NOW,
    ))

    plan = ReplanPlan(
        intent=ReplanIntent(intent_type="shift_all", minutes=30),
        changes=[TaskChange(task_id=id2, title="Gym class", old_due_at=datetime(2026, 10, 31, 18, 0, 0), new_due_at=datetime(2026, 10, 31, 18, 30, 0), is_fixed=False)],
        summary={"en": "I'll shift your tasks by 30 min."},
        created_at=FROZEN_NOW + timedelta(seconds=10),  # Newer!
    )
    set_pending_plan(plan)

    res1 = await process_turn("yes", language="en", now=FROZEN_NOW + timedelta(seconds=12))
    assert "Done, I've updated your schedule." in res1["reply_text"]

    # Gym was NOT cancelled
    db = SessionLocal()
    assert db.query(Task).filter_by(id=id1).first().status == TaskStatus.SCHEDULED.value
    db.close()

    # Case 2: Replan asked first, then Cancel confirmation asked -> Cancel wins!
    clear_pending_choice()
    clear_pending_action()
    set_pending_plan(None)

    plan2 = ReplanPlan(
        intent=ReplanIntent(intent_type="shift_all", minutes=30),
        changes=[],
        summary={"en": "I'll shift your tasks by 30 min."},
        created_at=FROZEN_NOW,  # Older!
    )
    set_pending_plan(plan2)

    set_pending_action(PendingAction(
        action="cancel",
        task_id=id1,
        title="Gym",
        language="en",
        created_at=FROZEN_NOW + timedelta(seconds=10),  # Newer!
    ))

    res2 = await process_turn("yes", language="en", now=FROZEN_NOW + timedelta(seconds=12))
    assert "Cancelled Gym." in res2["reply_text"]

    db = SessionLocal()
    assert db.query(Task).filter_by(id=id1).first().status == TaskStatus.CANCELLED.value
    db.close()


@pytest.mark.asyncio
async def test_native_script_cancel_fallback_to_llm_task_id():
    """
    Hindi native-script cancel with a title not in COMMON_TRANSCRIPT_MAP
    ('मीटिंग कैंसिल कर दो') falls back to LLM tool call's task_id,
    asks 'Should I cancel Team meeting?' and sets pending confirmation state.
    """
    db = SessionLocal()
    t = Task(title="Team meeting", due_at=datetime(2026, 10, 31, 16, 0, 0), status=TaskStatus.SCHEDULED.value)
    db.add(t)
    db.commit()
    t_id = t.id
    db.close()

    # Mock LLM calling cancel_task with task_id and non-mapped Hindi title
    mock_tool_call = {
        "id": "call_cancel_1",
        "name": "cancel_task",
        "arguments": {"task_id": t_id, "title": "मीटिंग"}
    }

    with patch("providers.registry.registry.llm.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.return_value = {
            "content": None,
            "tool_calls": [mock_tool_call],
            "finish_reason": "tool_calls",
            "model": "llama-3.3-70b-versatile"
        }
        res = await process_turn("मीटिंग कैंसिल कर दो", language="hi", now=FROZEN_NOW)

    assert "क्या मैं Team meeting को रद्द कर दूँ?" in res["reply_text"]

    # Confirm with "हाँ"
    res_confirm = await process_turn("हाँ", language="hi", now=FROZEN_NOW + timedelta(seconds=5))
    assert "Team meeting रद्द कर दिया गया है।" in res_confirm["reply_text"]

    db = SessionLocal()
    assert db.query(Task).filter_by(id=t_id).first().status == TaskStatus.CANCELLED.value
    db.close()
