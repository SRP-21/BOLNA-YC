"""
Tests for timezone convention (timeutil.py).
"""
from datetime import datetime, timezone, timedelta
from timeutil import IST, now_ist, to_ist_naive, ensure_ist
from agent.resolver import compute_snooze


def test_utc_aware_to_ist_naive():
    """(a) A UTC-aware input converts to the correct IST-naive value."""
    # 04:30 UTC is 10:00 IST (+5:30)
    utc_dt = datetime(2026, 10, 30, 4, 30, 0, tzinfo=timezone.utc)
    naive_ist = to_ist_naive(utc_dt)

    assert naive_ist.tzinfo is None
    assert naive_ist == datetime(2026, 10, 30, 10, 0, 0)
    assert naive_ist.hour == 10
    assert naive_ist.minute == 0


def test_naive_value_reads_back_as_same_ist_time():
    """(b) A naive value from DB reads back as the same IST time."""
    naive_db_dt = datetime(2026, 10, 30, 18, 45, 0)
    ist_aware = ensure_ist(naive_db_dt)

    assert ist_aware.tzinfo == IST
    assert ist_aware.year == 2026
    assert ist_aware.month == 10
    assert ist_aware.day == 30
    assert ist_aware.hour == 18
    assert ist_aware.minute == 45
    assert ist_aware.second == 0


def test_snooze_10_minutes():
    """(c) 'snooze 10 minutes' producing now_ist() + 10min."""
    now = now_ist()
    snoozed = compute_snooze(now, minutes=10)

    assert snoozed == now + timedelta(minutes=10)
    assert (snoozed - now).total_seconds() == 600

    # Stored to DB as naive IST
    naive_snoozed = to_ist_naive(snoozed)
    assert naive_snoozed.tzinfo is None
    assert naive_snoozed.hour == snoozed.hour
    assert naive_snoozed.minute == snoozed.minute
