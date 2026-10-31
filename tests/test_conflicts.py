"""
Tests for Conflict Detection (agent/conflicts.py).
Tests:
- Overlap detection with task durations
- Concrete fix recommendation (next available time slot)
- Multi-lingual spoken warnings (en, hi, kn)
"""
import pytest
from datetime import datetime
from db import Task, TaskStatus
from agent.conflicts import detect_conflicts, format_conflict_sentence
from timeutil import IST

FROZEN_NOW = datetime(2026, 10, 31, 9, 0, 0, tzinfo=IST)


def test_conflict_detection_simple_overlap():
    """Two tasks at 10:00 and 10:15 with 30m duration overlap by 15m."""
    t1 = Task(
        id=1,
        title="Standup",
        due_at=datetime(2026, 10, 31, 10, 0, 0),
        duration_minutes=30,
        status=TaskStatus.SCHEDULED.value,
    )
    t2 = Task(
        id=2,
        title="Invoice Review",
        due_at=datetime(2026, 10, 31, 10, 15, 0),
        duration_minutes=30,
        status=TaskStatus.SCHEDULED.value,
    )

    conflicts = detect_conflicts([t1, t2], min_gap_minutes=5)
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c.task_1.title == "Standup"
    assert c.task_2.title == "Invoice Review"
    assert c.overlap_minutes == 15
    # Suggested time = 10:00 + 30m + 5m min_gap = 10:35
    assert c.suggested_time == datetime(2026, 10, 31, 10, 35, 0, tzinfo=IST)


def test_no_conflict_when_spaced_apart():
    """Tasks spaced 45m apart with 30m duration do not conflict."""
    t1 = Task(
        id=1,
        title="Standup",
        due_at=datetime(2026, 10, 31, 10, 0, 0),
        duration_minutes=30,
        status=TaskStatus.SCHEDULED.value,
    )
    t2 = Task(
        id=2,
        title="Gym",
        due_at=datetime(2026, 10, 31, 11, 0, 0),
        duration_minutes=30,
        status=TaskStatus.SCHEDULED.value,
    )
    conflicts = detect_conflicts([t1, t2])
    assert len(conflicts) == 0


def test_format_conflict_sentence_multilingual():
    """Verify single-sentence concrete fix warnings in en, hi, kn."""
    t1 = Task(
        id=1,
        title="Standup",
        due_at=datetime(2026, 10, 31, 10, 0, 0),
        duration_minutes=30,
    )
    t2 = Task(
        id=2,
        title="Gym",
        due_at=datetime(2026, 10, 31, 10, 15, 0),
        duration_minutes=30,
    )
    conflicts = detect_conflicts([t1, t2], min_gap_minutes=5)
    c = conflicts[0]

    s_en = format_conflict_sentence(c, language="en", now=FROZEN_NOW)
    assert "Standup" in s_en
    assert "Gym" in s_en
    assert "overlaps" in s_en
    assert "10:35" in s_en

    s_hi = format_conflict_sentence(c, language="hi", now=FROZEN_NOW)
    assert "Standup" in s_hi
    assert "Gym" in s_hi
    assert "क्लैश" in s_hi

    s_kn = format_conflict_sentence(c, language="kn", now=FROZEN_NOW)
    assert "Standup" in s_kn
    assert "Gym" in s_kn
