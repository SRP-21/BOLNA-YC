"""
Deterministic tests for time resolver and recurrence.
Fixed 'now' timestamp injected for 100% reproducibility.
"""
import pytest
from datetime import datetime
from zoneinfo import ZoneInfo
from agent.resolver import resolve_time, compute_snooze, compute_next_recurrence, IST

# Inject fixed now: Friday, 2026-10-30 14:00:00 IST
FIXED_NOW = datetime(2026, 10, 30, 14, 0, 0, tzinfo=IST)


def test_english_exact_time():
    # "10 am" when now is 14:00 (past) -> pushed to tomorrow 10:00
    res = resolve_time("10 am", now=FIXED_NOW)
    assert res.dt.hour == 10
    assert res.dt.minute == 0
    assert res.dt.day == 31  # tomorrow because 10am passed today

    # "6 pm" -> today 18:00
    res2 = resolve_time("6 pm", now=FIXED_NOW)
    assert res2.dt.hour == 18
    assert res2.dt.minute == 0
    assert res2.dt.day == 30


def test_hindi_exact_time():
    # "shaam 6 baje" -> 18:00
    res = resolve_time("shaam 6 baje", now=FIXED_NOW)
    assert res.dt.hour == 18
    assert res.dt.minute == 0

    # "subah 10 baje" -> 10:00 tomorrow
    res2 = resolve_time("subah 10 baje", now=FIXED_NOW)
    assert res2.dt.hour == 10
    assert res2.dt.day == 31


def test_kannada_english_mix():
    # "beligge" = morning (09:00)
    res = resolve_time("beligge", now=FIXED_NOW)
    assert res.dt.hour == 9
    assert res.needs_confirmation is True

    # "sanje" = evening (18:00)
    res2 = resolve_time("sanje", now=FIXED_NOW)
    assert res2.dt.hour == 18
    assert res2.needs_confirmation is True

    # "naale 7" = tomorrow 7 (heuristic: 7 -> 19:00 or tomorrow morning)
    res3 = resolve_time("naale 7", now=FIXED_NOW)
    assert res3.dt.day == 31


def test_hinglish_and_vague_times():
    # "before lunch" / "lunch se pehle" -> 12:30 (from config TimeWindows.BEFORE_LUNCH)
    res = resolve_time("before lunch", now=FIXED_NOW)
    assert res.dt.hour == 12
    assert res.dt.minute == 30
    assert res.needs_confirmation is True
    assert "before lunch" in res.reasoning

    # "lunch se pehle"
    res2 = resolve_time("lunch se pehle", now=FIXED_NOW)
    assert res2.dt.hour == 12
    assert res2.dt.minute == 30
    assert res2.needs_confirmation is True

    # "kal subah" -> tomorrow morning 09:00
    res3 = resolve_time("kal subah", now=FIXED_NOW)
    assert res3.dt.day == 31
    assert res3.dt.hour == 9


def test_relative_times():
    # "in 30 minutes"
    res = resolve_time("in 30 minutes", now=FIXED_NOW)
    assert res.dt.hour == 14
    assert res.dt.minute == 30
    assert res.dt.day == 30

    # "in 2 hours"
    res2 = resolve_time("in 2 hours", now=FIXED_NOW)
    assert res2.dt.hour == 16
    assert res2.dt.minute == 0


def test_snooze_math():
    due = datetime(2026, 10, 30, 10, 0, 0, tzinfo=IST)
    snoozed_10 = compute_snooze(due, minutes=10)
    assert snoozed_10 == datetime(2026, 10, 30, 10, 10, 0, tzinfo=IST)

    snoozed_60 = compute_snooze(due, minutes=60)
    assert snoozed_60 == datetime(2026, 10, 30, 11, 0, 0, tzinfo=IST)


def test_recurrence_computation():
    # Fixed now is Friday (weekday 4), Oct 30, 2026
    due = datetime(2026, 10, 30, 10, 0, 0, tzinfo=IST)

    # Next daily recurrence -> Saturday, Oct 31 at 10:00
    next_daily = compute_next_recurrence(due, "daily", now=FIXED_NOW)
    assert next_daily == datetime(2026, 10, 31, 10, 0, 0, tzinfo=IST)

    # Next "weekly:monday" -> Monday, Nov 2, 2026 at 10:00
    next_monday = compute_next_recurrence(due, "weekly:monday", now=FIXED_NOW)
    assert next_monday.weekday() == 0  # Monday
    assert next_monday.day == 2
    assert next_monday.month == 11
    assert next_monday.hour == 10


def test_native_script_kannada_and_hindi_resolution():
    """
    Regression tests for commit de739ad:
    - 'ನಾಳೆ ಸಂಜೆ 5 ಗಂಟೆಗೆ' resolves to tomorrow 17:00
    - 'कल शाम 5 बजे' resolves to tomorrow 17:00
    - 'कल सुबह 9 बजे' resolves to tomorrow 09:00
    - 'ನಾಳೆ ಬೆಳಿಗ್ಗೆ 9 ಗಂಟೆಗೆ' resolves to tomorrow 09:00
    """
    # 1. Kannada: "ನಾಳೆ ಸಂಜೆ 5 ಗಂಟೆಗೆ" -> tomorrow 17:00
    res_kn_eve = resolve_time("ನಾಳೆ ಸಂಜೆ 5 ಗಂಟೆಗೆ", now=FIXED_NOW)
    assert res_kn_eve.dt.day == 31
    assert res_kn_eve.dt.hour == 17
    assert res_kn_eve.dt.minute == 0

    # 2. Kannada: "ನಾಳೆ ಬೆಳಿಗ್ಗೆ 9 ಗಂಟೆಗೆ" -> tomorrow 09:00
    res_kn_morn = resolve_time("ನಾಳೆ ಬೆಳಿಗ್ಗೆ 9 ಗಂಟೆಗೆ", now=FIXED_NOW)
    assert res_kn_morn.dt.day == 31
    assert res_kn_morn.dt.hour == 9
    assert res_kn_morn.dt.minute == 0

    # 3. Hindi: "कल शाम 5 बजे" -> tomorrow 17:00
    res_hi_eve = resolve_time("कल शाम 5 बजे", now=FIXED_NOW)
    assert res_hi_eve.dt.day == 31
    assert res_hi_eve.dt.hour == 17
    assert res_hi_eve.dt.minute == 0

    # 4. Hindi: "कल सुबह 9 बजे" -> tomorrow 09:00
    res_hi_morn = resolve_time("कल सुबह 9 बजे", now=FIXED_NOW)
    assert res_hi_morn.dt.day == 31
    assert res_hi_morn.dt.hour == 9
    assert res_hi_morn.dt.minute == 0


def test_context_enrichment_from_user_text():
    """
    Regression test for _handle_add_task context enrichment when LLM truncates
    date/period indicators from time_phrase.
    """
    from db import init_db, SessionLocal, Task
    from agent.planner import _handle_add_task
    import os

    init_db()
    db = SessionLocal()
    db.query(Task).delete()
    db.commit()

    try:
        # Kannada: LLM only extracted "5 ಗಂಟೆಗೆ" but user_text has "ನಾಳೆ ಸಂಜೆ 5 ಗಂಟೆಗೆ ಜಿಮ್ ಹೋಗಬೇಕು"
        args_kn = {"title": "Gym", "time_phrase": "5 ಗಂಟೆಗೆ"}
        created_kn = _handle_add_task(
            db, args_kn, now=FIXED_NOW, language="kn",
            user_text="ನಾಳೆ ಸಂಜೆ 5 ಗಂಟೆಗೆ ಜಿಮ್ ಹೋಗಬೇಕು"
        )
        task_kn = db.query(Task).filter_by(id=created_kn["task_id"]).first()
        assert task_kn.due_at.day == 31
        assert task_kn.due_at.hour == 17

        # Hindi: LLM only extracted "5 बजे" but user_text has "कल शाम 5 बजे जिम जाना है"
        args_hi = {"title": "Gym Hindi", "time_phrase": "5 बजे"}
        created_hi = _handle_add_task(
            db, args_hi, now=FIXED_NOW, language="hi",
            user_text="कल शाम 5 बजे जिम जाना है"
        )
        task_hi = db.query(Task).filter_by(id=created_hi["task_id"]).first()
        assert task_hi.due_at.day == 31
        assert task_hi.due_at.hour == 17
    finally:
        db.close()

