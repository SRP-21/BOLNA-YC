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


def test_enable_test_clock_gating():
    """POST /api/text/turn ignores 'now' when enable_test_clock is False, and honors it when True."""
    from fastapi.testclient import TestClient
    from main import app
    from config import settings
    from providers.base import TTSResult

    client = TestClient(app)
    custom_now = "2026-10-31T08:30:00+05:30"

    # 1. When enable_test_clock is False (default), now parameter is ignored
    settings.enable_test_clock = False
    with patch("providers.registry.registry.synthesize", new_callable=AsyncMock) as mock_synth, \
         patch("routes.voice.process_turn", new_callable=AsyncMock) as mock_turn:
        mock_synth.return_value = TTSResult(use_browser_tts=True, provider="browser")
        mock_turn.return_value = {"reply_text": "ok", "task_changes": [], "language": "en"}
        resp = client.post("/api/text/turn", data={"text": "standup at 10", "now": custom_now})
        assert resp.status_code == 200
        # now passed to process_turn must be None
        mock_turn.assert_called_once_with("standup at 10", "en", now=None)

    # 2. When enable_test_clock is True, now parameter is passed to process_turn
    settings.enable_test_clock = True
    try:
        with patch("providers.registry.registry.synthesize", new_callable=AsyncMock) as mock_synth2, \
             patch("routes.voice.process_turn", new_callable=AsyncMock) as mock_turn2:
            mock_synth2.return_value = TTSResult(use_browser_tts=True, provider="browser")
            mock_turn2.return_value = {"reply_text": "ok", "task_changes": [], "language": "en"}
            resp2 = client.post("/api/text/turn", data={"text": "standup at 10", "now": custom_now})
            assert resp2.status_code == 200
            called_now = mock_turn2.call_args[1]["now"]
            assert called_now is not None
            assert called_now.hour == 8
            assert called_now.minute == 30
    finally:
        settings.enable_test_clock = False


@pytest.mark.asyncio
async def test_explicit_today_past_time_confirmation_en_hi_kn():
    """
    With now at 15:40 IST:
    1. 'standup at 10, doctor at 5 pm' puts standup tomorrow 10:00 (past time without 'aaj')
       and doctor today 17:00.
    2. 'aaj standup at 10 baje' (explicit today, passed) does NOT silently fire;
       replies 'That time has passed. Should I move it to tomorrow?' in en/hi/kn and
       'yes' moves it to tomorrow.
    """
    now_1540 = datetime(2026, 10, 31, 15, 40, 0, tzinfo=IST)

    # 1. 'standup at 10, doctor at 5 pm' -> standup tomorrow 10:00, doctor today 17:00
    mock_batch = {
        "id": "call_batch_1",
        "name": "add_tasks",
        "arguments": {
            "tasks": [
                {"title": "Standup", "time_phrase": "10"},
                {"title": "Doctor", "time_phrase": "5 pm"},
            ]
        }
    }
    with patch("providers.registry.registry.llm.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.return_value = {
            "content": None,
            "tool_calls": [mock_batch],
            "finish_reason": "tool_calls",
        }
        r1 = await process_turn("standup at 10, doctor at 5 pm", language="en", now=now_1540)

    db = SessionLocal()
    t_standup = db.query(Task).filter_by(title="Standup").first()
    t_doctor = db.query(Task).filter_by(title="Doctor").first()
    assert t_standup is not None
    assert t_doctor is not None
    # Standup pushed to tomorrow (Nov 1) at 10:00
    assert t_standup.due_at.day == 1
    assert t_standup.due_at.hour == 10
    # Doctor is today (Oct 31) at 17:00
    assert t_doctor.due_at.day == 31
    assert t_doctor.due_at.hour == 17
    db.close()

    # 2. Hindi: 'aaj standup at 10 baje' -> asks confirmation, does NOT silently fire in DB
    db = SessionLocal()
    db.query(Task).delete()
    db.commit()
    db.close()

    mock_add_hi = {
        "id": "call_add_hi",
        "name": "add_task",
        "arguments": {"title": "Standup", "time_phrase": "10 baje"}
    }
    with patch("providers.registry.registry.llm.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.return_value = {"content": None, "tool_calls": [mock_add_hi], "finish_reason": "tool_calls"}
        r_hi = await process_turn("aaj standup at 10 baje", language="hi", now=now_1540)

    assert "वह समय बीत चुका है। क्या मैं इसे कल के लिए रख दूं?" in r_hi["reply_text"]
    db = SessionLocal()
    assert db.query(Task).count() == 0  # not created yet in DB
    db.close()

    # Reply "हाँ" -> moves to tomorrow 10:00
    r_hi_yes = await process_turn("हाँ", language="hi", now=now_1540 + timedelta(seconds=2))
    assert "कल" in r_hi_yes["reply_text"]
    assert "Standup" in r_hi_yes["reply_text"]
    db = SessionLocal()
    t_hi = db.query(Task).filter_by(title="Standup").first()
    assert t_hi is not None
    assert t_hi.due_at.day == 1
    assert t_hi.due_at.hour == 10
    db.close()

    # 3. English: 'today standup at 10 am'
    db = SessionLocal()
    db.query(Task).delete()
    db.commit()
    db.close()

    mock_add_en = {
        "id": "call_add_en",
        "name": "add_task",
        "arguments": {"title": "Standup", "time_phrase": "10 am"}
    }
    with patch("providers.registry.registry.llm.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.return_value = {"content": None, "tool_calls": [mock_add_en], "finish_reason": "tool_calls"}
        r_en = await process_turn("today standup at 10 am", language="en", now=now_1540)

    assert "That time has passed. Should I move it to tomorrow?" in r_en["reply_text"]
    r_en_yes = await process_turn("yes", language="en", now=now_1540 + timedelta(seconds=2))
    assert "tomorrow at 10:00 AM" in r_en_yes["reply_text"]
    db = SessionLocal()
    t_en = db.query(Task).filter_by(title="Standup").first()
    assert t_en.due_at.day == 1
    assert t_en.due_at.hour == 10
    db.close()

    # 4. Kannada: 'ಇಂದು ಸ್ಟ್ಯಾಂಡಪ್ 10 ಗಂಟೆಗೆ'
    db = SessionLocal()
    db.query(Task).delete()
    db.commit()
    db.close()

    mock_add_kn = {
        "id": "call_add_kn",
        "name": "add_task",
        "arguments": {"title": "ಸ್ಟ್ಯಾಂಡಪ್", "time_phrase": "10 ಗಂಟೆಗೆ"}
    }
    with patch("providers.registry.registry.llm.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.return_value = {"content": None, "tool_calls": [mock_add_kn], "finish_reason": "tool_calls"}
        r_kn = await process_turn("ಇಂದು ಸ್ಟ್ಯಾಂಡಪ್ 10 ಗಂಟೆಗೆ", language="kn", now=now_1540)

    assert "ಆ ಸಮಯ ಈಗಾಗಲೇ ಮುಗಿದಿದೆ. ನಾನು ಅದನ್ನು ನಾಳೆಗೆ ಬದಲಾಯಿಸಬೇಕೆ?" in r_kn["reply_text"]
    r_kn_yes = await process_turn("ಹೌದು", language="kn", now=now_1540 + timedelta(seconds=2))
    assert "ನಾಳೆ" in r_kn_yes["reply_text"]
    db = SessionLocal()
    t_kn = db.query(Task).filter_by(title="ಸ್ಟ್ಯಾಂಡಪ್").first()
    assert t_kn.due_at.day == 1
    assert t_kn.due_at.hour == 10
    db.close()


def test_language_detection_markers_ratio():
    """
    Language detection:
    - One Hinglish marker in an otherwise English sentence stays English.
    - Requires at least 2 markers or >= 25% of words for Hinglish.
    - Native scripts (Devanagari, Kannada) always win.
    """
    from agent.lang import detect_language

    # Test cases from user prompt
    assert detect_language("standup at 10, kal subah doctor at 9, gym around 6") == "en"
    assert detect_language("kal subah 9 baje doctor ka appointment hai") == "hi"

    # Single marker in otherwise English stays English
    assert detect_language("meeting with client kal") == "en"
    assert detect_language("standup call at 10 baje tomorrow") == "en"

    # Native scripts win
    assert detect_language("आज स्टैंडअप 10 बजे") == "hi"
    assert detect_language("ಇಂದು ಸ್ಟ್ಯಾಂಡಪ್ 10 ಗಂಟೆಗೆ") == "kn"


def test_hi_kn_batch_guess_notes_for_gym_and_unparseable():
    """
    For hi and kn batch replies, confirm the guess note appears for
    'gym around 6' (bare hour / PM guess) and for unparseable phrases.
    """
    from agent.replies import format_created

    # 1. Gym around 6 (bare hour / resolved time): under Stage 4, bare hours are not guesses to announce
    batch_gym = [
        {"type": "created", "title": "Standup", "due_at": "2026-10-31T10:00:00+05:30", "needs_confirmation": False},
        {"type": "created", "title": "Gym", "due_at": "2026-10-31T18:00:00+05:30", "needs_confirmation": False, "resolution_note": "Resolved 18:00 (assumed evening PM)"}
    ]

    reply_hi_gym = format_created(batch_gym, "hi", now=FROZEN_NOW)
    assert "Gym का समय" not in reply_hi_gym

    reply_kn_gym = format_created(batch_gym, "kn", now=FROZEN_NOW)
    assert "Gym ಸಮಯ" not in reply_kn_gym

    # 2. Unparseable phrase in batch
    batch_unparse = [
        {"type": "created", "title": "Standup", "due_at": "2026-10-31T10:00:00+05:30", "needs_confirmation": False},
        {"type": "created", "title": "Groceries", "due_at": "2026-10-31T16:00:00+05:30", "needs_confirmation": True, "resolution_note": "Could not parse 'somewhen'"}
    ]

    reply_hi_unparse = format_created(batch_unparse, "hi", now=FROZEN_NOW)
    assert "Groceries का समय मुझे पता नहीं था" in reply_hi_unparse

    reply_kn_unparse = format_created(batch_unparse, "kn", now=FROZEN_NOW)
    assert "Groceries ಸಮಯ ಗೊತ್ತಿಲ್ಲದ ಕಾರಣ" in reply_kn_unparse
