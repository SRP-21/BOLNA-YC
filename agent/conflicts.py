"""
Deterministic conflict detection for daily planner tasks.
Detects overlapping tasks based on due_at and duration_minutes,
and generates spoken concise suggestions to fix them.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
from db import Task
from timeutil import ensure_ist, format_when, IST


@dataclass
class Conflict:
    task_1: Task
    task_2: Task
    overlap_minutes: int
    suggested_time: datetime

    def to_dict(self):
        return {
            "task_1_id": self.task_1.id,
            "task_1_title": self.task_1.title,
            "task_1_due": ensure_ist(self.task_1.due_at).isoformat(),
            "task_2_id": self.task_2.id,
            "task_2_title": self.task_2.title,
            "task_2_due": ensure_ist(self.task_2.due_at).isoformat(),
            "overlap_minutes": self.overlap_minutes,
            "suggested_time": ensure_ist(self.suggested_time).isoformat(),
        }


def get_task_duration(task: Task, default_duration: int = 30) -> int:
    """Return task duration in minutes, defaulting to 30 if unspecified."""
    if task.duration_minutes and task.duration_minutes > 0:
        return task.duration_minutes
    return default_duration


def detect_conflicts(
    tasks: List[Task],
    default_duration_minutes: int = 30,
    min_gap_minutes: int = 5,
) -> List[Conflict]:
    """
    Detect overlapping active tasks in chronological order.
    Returns list of Conflict objects proposing concrete resolution times.
    """
    # Filter tasks that have due_at
    valid_tasks = [t for t in tasks if t.due_at is not None]
    # Sort chronologically by due_at
    sorted_tasks = sorted(valid_tasks, key=lambda t: ensure_ist(t.due_at))

    conflicts: List[Conflict] = []

    for i in range(len(sorted_tasks) - 1):
        t1 = sorted_tasks[i]
        t2 = sorted_tasks[i + 1]

        t1_start = ensure_ist(t1.due_at)
        t1_duration = get_task_duration(t1, default_duration_minutes)
        t1_end = t1_start + timedelta(minutes=t1_duration)

        t2_start = ensure_ist(t2.due_at)

        # Check overlap
        if t1_end > t2_start:
            overlap = int((t1_end - t2_start).total_seconds() / 60)
            # Propose moving t2 to end of t1 + min_gap
            suggested = t1_end + timedelta(minutes=min_gap_minutes)
            conflicts.append(
                Conflict(
                    task_1=t1,
                    task_2=t2,
                    overlap_minutes=max(1, overlap),
                    suggested_time=suggested,
                )
            )

    return conflicts


def format_conflict_sentence(conflict: Conflict, language: str = "en", now: Optional[datetime] = None) -> str:
    """
    Format a concise single-sentence spoken warning and concrete fix proposal.
    """
    from timeutil import now_ist, format_when
    if now is None:
        now = now_ist()
    else:
        now = ensure_ist(now)

    t1_title = conflict.task_1.title
    t2_title = conflict.task_2.title

    t1_when = format_when(conflict.task_1.due_at, now, language)
    suggested_when = format_when(conflict.suggested_time, now, language)

    if language == "hi":
        return f"{t1_title} {t1_when} {t2_title} से क्लैश हो रहा है। क्या {t2_title} को {suggested_when} कर दें?"
    elif language == "kn":
        return f"{t1_title} ({t1_when}) ಮತ್ತು {t2_title} ಒಂದೇ ಸಮಯಕ್ಕೆ ಬರುತ್ತವೆ. {t2_title} ಅನ್ನು {suggested_when} ಬದಲಾಯಿಸುವುದೇ?"
    else:
        t1_time_str = ensure_ist(conflict.task_1.due_at).strftime("%I:%M %p").lstrip("0")
        suggested_str = ensure_ist(conflict.suggested_time).strftime("%I:%M %p").lstrip("0")
        return f"{t1_title} at {t1_time_str} overlaps with {t2_title}. Move {t2_title} to {suggested_str}?"
