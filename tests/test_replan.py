"""
Tests for Replan Engine and Voice Replan Flow.
Requirements tested:
- Shifting with mixed fixed/flexible tasks (fixed tasks stay, flexible move)
- Blocking window spanning lunch (tasks moved after window)
- Overflow into quiet hours carrying over to next day morning
- Swap tasks
- Atomic commit & snapshot undo restoring prior persistence state and scheduler jobs
- Conflict detection after replan
- Hinglish phrasings (rule extraction)
- Confirmation rules (yes/no/undo handled before calling LLM)
- Fixed injected now for determinism
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from db import init_db, SessionLocal, Task, TaskStatus, ReplanSnapshot
from agent.replan_engine import (
    ReplanIntent, compute_replan, apply_replan_commit, apply_replan_undo
)
from agent.replan import (
    parse_confirmation_rule, extract_replan_intent_rules, extract_replan_intent,
    set_pending_plan, get_pending_plan
)
from agent.planner import process_turn
from timeutil import IST, ensure_ist, to_ist_naive
from scheduler import scheduler

FROZEN_NOW = datetime(2026, 10, 31, 10, 0, 0, tzinfo=IST)


@pytest.fixture(autouse=True)
def clean_tasks_and_snapshots():
    init_db()
    db = SessionLocal()
    db.query(Task).delete()
    db.query(ReplanSnapshot).delete()
    db.commit()
    db.close()
    set_pending_plan(None)


def test_mixed_fixed_and_flexible_shift():
    """In shift_all, an explicit command moves all active tasks including fixed ones. In shift_from, fixed tasks stay."""
    db = SessionLocal()
    # Fixed task: exact time standup at 10:30
    t_fixed = Task(
        title="Standup",
        due_at=datetime(2026, 10, 31, 10, 30, 0),
        status=TaskStatus.SCHEDULED.value,
        is_fixed=True,
    )
    # Flexible task: groceries around 11:00
    t_flex = Task(
        title="Groceries",
        due_at=datetime(2026, 10, 31, 11, 0, 0),
        status=TaskStatus.SCHEDULED.value,
        is_fixed=False,
    )
    db.add_all([t_fixed, t_flex])
    db.commit()

    # 1. shift_all moves ALL active tasks (both Standup and Groceries)
    intent_all = ReplanIntent(intent_type="shift_all", minutes=45)
    plan_all = compute_replan(db, intent_all, now=FROZEN_NOW)
    assert len(plan_all.changes) == 2
    titles_moved = [c.title for c in plan_all.changes]
    assert "Standup" in titles_moved
    assert "Groceries" in titles_moved

    # 2. shift_from protects fixed tasks; only flexible tasks move
    intent_from = ReplanIntent(intent_type="shift_from", minutes=45, from_time=FROZEN_NOW)
    plan_from = compute_replan(db, intent_from, now=FROZEN_NOW)
    assert len(plan_from.changes) == 1
    assert plan_from.changes[0].title == "Groceries"
    db.close()


def test_block_window_spanning_lunch():
    """Tasks inside blocked window (12:00 to 14:00) move to after 14:00 with min gap."""
    db = SessionLocal()
    t1 = Task(
        title="Send Invoice",
        due_at=datetime(2026, 10, 31, 12, 30, 0),
        status=TaskStatus.SCHEDULED.value,
        is_fixed=False,
    )
    t2 = Task(
        title="Quick Sync",
        due_at=datetime(2026, 10, 31, 13, 0, 0),
        status=TaskStatus.SCHEDULED.value,
        is_fixed=False,
    )
    db.add_all([t1, t2])
    db.commit()

    w_start = datetime(2026, 10, 31, 12, 0, 0, tzinfo=IST)
    w_end = datetime(2026, 10, 31, 14, 0, 0, tzinfo=IST)
    intent = ReplanIntent(intent_type="block_window", window_start=w_start, window_end=w_end)

    plan = compute_replan(db, intent, now=FROZEN_NOW)
    assert len(plan.changes) == 2

    c1 = plan.changes[0]
    c2 = plan.changes[1]
    assert c1.title == "Send Invoice"
    assert c1.new_due_at == datetime(2026, 10, 31, 14, 0, 0, tzinfo=IST)
    # c2 staggered by min gap (15 min) -> 14:15
    assert c2.title == "Quick Sync"
    assert c2.new_due_at == datetime(2026, 10, 31, 14, 15, 0, tzinfo=IST)
    db.close()


def test_overflow_into_quiet_hours_carries_over_to_tomorrow():
    """Task scheduled for 21:15 shifted by 60 min lands at 22:15 (quiet hours) -> carries to 09:00 tomorrow."""
    db = SessionLocal()
    t = Task(
        title="Gym",
        due_at=datetime(2026, 10, 31, 21, 15, 0),
        status=TaskStatus.SCHEDULED.value,
        is_fixed=False,
    )
    db.add(t)
    db.commit()

    intent = ReplanIntent(intent_type="shift_all", minutes=60)
    plan = compute_replan(db, intent, now=FROZEN_NOW)

    assert len(plan.changes) == 1
    c = plan.changes[0]
    assert c.is_carryover is True
    # Should land at 09:00 AM on 2026-11-01
    assert c.new_due_at == datetime(2026, 11, 1, 9, 0, 0, tzinfo=IST)
    db.close()


def test_overflow_past_day_end_carries_over():
    """Task landing after 21:30 carries over to tomorrow morning."""
    db = SessionLocal()
    t = Task(
        title="Read Book",
        due_at=datetime(2026, 10, 31, 21, 0, 0),
        status=TaskStatus.SCHEDULED.value,
        is_fixed=False,
    )
    db.add(t)
    db.commit()

    intent = ReplanIntent(intent_type="shift_all", minutes=45)
    plan = compute_replan(db, intent, now=FROZEN_NOW)

    assert len(plan.changes) == 1
    assert plan.changes[0].is_carryover is True
    assert plan.changes[0].new_due_at.date() == datetime(2026, 11, 1).date()
    db.close()


def test_swap_tasks():
    """Swapping two tasks exchanges their due_at times."""
    db = SessionLocal()
    t1 = Task(
        title="Invoice",
        due_at=datetime(2026, 10, 31, 11, 0, 0),
        status=TaskStatus.SCHEDULED.value,
    )
    t2 = Task(
        title="Groceries",
        due_at=datetime(2026, 10, 31, 17, 0, 0),
        status=TaskStatus.SCHEDULED.value,
    )
    db.add_all([t1, t2])
    db.commit()

    intent = ReplanIntent(intent_type="swap_tasks", task_identifier="invoice", task_identifier_2="groceries")
    plan = compute_replan(db, intent, now=FROZEN_NOW)

    assert len(plan.changes) == 2
    c_inv = next(c for c in plan.changes if c.title == "Invoice")
    c_groc = next(c for c in plan.changes if c.title == "Groceries")
    assert c_inv.new_due_at == datetime(2026, 10, 31, 17, 0, 0, tzinfo=IST)
    assert c_groc.new_due_at == datetime(2026, 10, 31, 11, 0, 0, tzinfo=IST)
    db.close()


def test_atomic_commit_and_undo():
    """Commit updates DB and scheduler; undo restores exact prior state and jobs."""
    db = SessionLocal()
    t = Task(
        title="Dentist",
        due_at=datetime(2026, 10, 31, 14, 0, 0),
        status=TaskStatus.SCHEDULED.value,
        is_fixed=False,
    )
    db.add(t)
    db.commit()
    task_id = t.id

    intent = ReplanIntent(intent_type="shift_all", minutes=30)
    plan = compute_replan(db, intent, now=FROZEN_NOW)

    # 1. Commit
    snapshot = apply_replan_commit(db, plan, reason="test shift")
    assert snapshot.id is not None
    assert not snapshot.undone

    updated = db.query(Task).filter_by(id=task_id).first()
    assert updated.due_at == datetime(2026, 10, 31, 14, 30, 0)

    # Verify scheduler has job for updated time
    job = scheduler.get_job(f"task_{task_id}")
    assert job is not None

    # 2. Undo
    res = apply_replan_undo(db)
    assert res["ok"] is True

    reverted = db.query(Task).filter_by(id=task_id).first()
    assert reverted.due_at == datetime(2026, 10, 31, 14, 0, 0)
    db.close()


def test_hinglish_and_english_rule_extraction():
    """Verify rule extractor handles English and Hinglish phrases deterministically."""
    # "push everything by 45 minutes"
    i1 = extract_replan_intent_rules("my meeting ran long, push everything by 45 minutes", FROZEN_NOW)
    assert i1 is not None
    assert i1.intent_type == "shift_all"
    assert i1.minutes == 45

    # Hinglish: "sab kuch 45 minute aage kar do"
    i2 = extract_replan_intent_rules("sab kuch 45 minute aage kar do", FROZEN_NOW)
    assert i2 is not None
    assert i2.intent_type == "shift_all"
    assert i2.minutes == 45

    # "only free after 5"
    i3 = extract_replan_intent_rules("I'm only free after 5 pm", FROZEN_NOW)
    assert i3 is not None
    assert i3.intent_type == "block_window"
    assert i3.window_end.hour == 17

    # "swap the invoice and groceries"
    i4 = extract_replan_intent_rules("swap the invoice and groceries", FROZEN_NOW)
    assert i4 is not None
    assert i4.intent_type == "swap_tasks"
    assert i4.task_identifier == "invoice"
    assert i4.task_identifier_2 == "groceries"


def test_confirmation_rules_deterministic():
    """Rules identify yes, no, and undo without LLM."""
    assert parse_confirmation_rule("yes") == "yes"
    assert parse_confirmation_rule("sure, go ahead") == "yes"
    assert parse_confirmation_rule("ha theek hai") == "yes"
    assert parse_confirmation_rule("sari") == "yes"
    assert parse_confirmation_rule("houdu") == "yes"

    assert parse_confirmation_rule("no") == "no"
    assert parse_confirmation_rule("don't do that") == "no"
    assert parse_confirmation_rule("nahi") == "no"
    assert parse_confirmation_rule("beda") == "no"

    assert parse_confirmation_rule("undo") == "undo"
    assert parse_confirmation_rule("undo that") == "undo"
    assert parse_confirmation_rule("wapas kar do") == "undo"


@pytest.mark.asyncio
async def test_voice_turn_replan_preview_and_confirm_flow():
    """Voice turn: 1) asks replan -> speaks preview; 2) answers 'yes' -> commits atomically."""
    db = SessionLocal()
    t = Task(
        title="Workout",
        due_at=datetime(2026, 10, 31, 16, 0, 0),
        status=TaskStatus.SCHEDULED.value,
        is_fixed=False,
    )
    db.add(t)
    db.commit()
    t_id = t.id
    db.close()

    # Step 1: User says "push everything by 30 minutes"
    res1 = await process_turn("push everything by 30 minutes", language="en", now=FROZEN_NOW)
    assert "Okay?" in res1["reply_text"]
    assert "Workout to 4:30 PM" in res1["reply_text"]
    assert get_pending_plan() is not None

    # Step 2: User says "yes" (handled via rule, no LLM call)
    res2 = await process_turn("yes", language="en", now=FROZEN_NOW)
    assert "updated your schedule" in res2["reply_text"]
    assert get_pending_plan() is None

    # Verify task updated in DB
    db = SessionLocal()
    t_updated = db.query(Task).filter_by(id=t_id).first()
    assert t_updated.due_at == datetime(2026, 10, 31, 16, 30, 0)
    db.close()

    # Step 3: User says "undo that"
    res3 = await process_turn("undo that", language="en", now=FROZEN_NOW)
    assert "Reverted your last schedule change" in res3["reply_text"]

    db = SessionLocal()
    t_reverted = db.query(Task).filter_by(id=t_id).first()
    assert t_reverted.due_at == datetime(2026, 10, 31, 16, 0, 0)
    db.close()


def test_spoken_preview_reports_skipped_tasks_en_hi_kn():
    """Spoken preview must explicitly explain if any active task was left alone and why."""
    db = SessionLocal()
    # Task 1: in the past (09:00, while now is 10:00)
    t_past = Task(
        title="Breakfast",
        due_at=datetime(2026, 10, 31, 9, 0, 0),
        status=TaskStatus.SCHEDULED.value,
        is_fixed=True,
    )
    # Task 2: in future (11:00)
    t_future = Task(
        title="Lunch Prep",
        due_at=datetime(2026, 10, 31, 11, 0, 0),
        status=TaskStatus.SCHEDULED.value,
        is_fixed=True,
    )
    db.add_all([t_past, t_future])
    db.commit()

    intent = ReplanIntent(intent_type="shift_all", minutes=30)
    plan = compute_replan(db, intent, now=FROZEN_NOW)

    # 1. Lunch Prep moved, Breakfast skipped because past cutoff
    assert len(plan.changes) == 1
    assert plan.changes[0].title == "Lunch Prep"

    # 2. English preview explains Breakfast was left alone
    assert "I left Breakfast alone because it already passed." in plan.summary["en"]
    assert "Lunch Prep to 11:30 AM" in plan.summary["en"]

    # 3. Hindi preview explains Breakfast was left alone
    assert "Breakfast का समय बीत चुका है इसलिए उसे नहीं बदला गया।" in plan.summary["hi"]
    assert "Lunch Prep" in plan.summary["hi"]

    # 4. Kannada preview explains Breakfast was left alone
    assert "Breakfast ಸಮಯ ಈಗಾಗಲೇ ಮುಗಿದಿರುವುದರಿಂದ ಅದನ್ನು ಬದಲಾಯಿಸಿಲ್ಲ." in plan.summary["kn"]
    assert "Lunch Prep" in plan.summary["kn"]

    # 5. Fixed task left alone in shift_from
    db.query(Task).delete()
    t_fixed = Task(
        title="Board Meeting",
        due_at=datetime(2026, 10, 31, 11, 0, 0),
        status=TaskStatus.SCHEDULED.value,
        is_fixed=True,
    )
    t_flex = Task(
        title="Jogging",
        due_at=datetime(2026, 10, 31, 12, 0, 0),
        status=TaskStatus.SCHEDULED.value,
        is_fixed=False,
    )
    db.add_all([t_fixed, t_flex])
    db.commit()

    intent_from = ReplanIntent(intent_type="shift_from", minutes=30, from_time=FROZEN_NOW)
    plan_from = compute_replan(db, intent_from, now=FROZEN_NOW)
    assert len(plan_from.changes) == 1
    assert plan_from.changes[0].title == "Jogging"
    assert "I left Board Meeting alone because it has a fixed time." in plan_from.summary["en"]
    assert "Board Meeting का निश्चित समय है इसलिए उसे नहीं बदला गया।" in plan_from.summary["hi"]
    assert "Board Meeting ನಿಗದಿತ ಸಮಯದ್ದಾಗಿದೆ ಆದ್ದರಿಂದ ಅದನ್ನು ಬದಲಾಯಿಸಿಲ್ಲ." in plan_from.summary["kn"]
    db.close()


def test_native_replan_intent_rules_and_confirmation():
    """Verify Hindi and Kannada replan utterances and native confirmations."""
    # Hindi
    i_hi = extract_replan_intent_rules("सब कुछ 30 मिनट आगे कर दो", FROZEN_NOW)
    assert i_hi is not None
    assert i_hi.intent_type == "shift_all"
    assert i_hi.minutes == 30

    # Kannada
    i_kn = extract_replan_intent_rules("ಎಲ್ಲವನ್ನೂ 30 ನಿಮಿಷ ಮುಂದೆ ಹಾಕಿ", FROZEN_NOW)
    assert i_kn is not None
    assert i_kn.intent_type == "shift_all"
    assert i_kn.minutes == 30

    # Native confirmations
    assert parse_confirmation_rule("हाँ") == "yes"
    assert parse_confirmation_rule("हां") == "yes"
    assert parse_confirmation_rule("ठीक है") == "yes"
    assert parse_confirmation_rule("ಹೌದು") == "yes"
    assert parse_confirmation_rule("ಸರಿ") == "yes"
    assert parse_confirmation_rule("नहीं") == "no"
    assert parse_confirmation_rule("ಬೇಡ") == "no"
