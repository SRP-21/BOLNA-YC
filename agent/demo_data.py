"""
Development-only demo data generator for adaptive learning & recap testing.
Gated behind config flag settings.enable_demo_data.
Generates 1 week of realistic tasks and events with is_synthetic=True marker.
"""
from datetime import datetime, timedelta, timezone
from typing import Dict, Any
from fastapi import HTTPException

from db import Task, TaskStatus, Event, LearnedPreference
from config import settings
from timeutil import ensure_ist, to_ist_naive, now_ist, IST


def generate_demo_data(db, now: datetime, enabled: bool = False) -> Dict[str, Any]:
    """
    Generate realistic 7-day task and event history.
    Strictly gated behind enable_demo_data flag.
    Every record has is_synthetic=True.
    """
    if not enabled and not getattr(settings, "enable_demo_data", False):
        raise HTTPException(
            status_code=403,
            detail="Demo data generation is disabled. Set ENABLE_DEMO_DATA=True in config/.env to enable."
        )

    now = ensure_ist(now)
    base_date = now.date()
    created_tasks = []

    # Daily templates for past 7 days (day -7 to day -1)
    daily_schedules = [
        # (title, category, hour, minute, duration, status, snooze_count, snooze_mins)
        ("Morning Standup", "work", 10, 0, 30, TaskStatus.DONE.value, 0, 0),
        ("Client Invoice", "work", 12, 0, 45, TaskStatus.DONE.value, 1, 15),
        ("Gym Workout", "health", 18, 0, 60, TaskStatus.DONE.value, 1, 20),
        ("Buy Groceries", "errands", 19, 30, 30, TaskStatus.DONE.value, 0, 0),
        ("Call with Mom", "family", 20, 30, 20, TaskStatus.DONE.value, 0, 0),
    ]

    for day_offset in range(7, 0, -1):
        day_date = base_date - timedelta(days=day_offset)

        for title, cat, h, m, dur, status, snoozes, s_mins in daily_schedules:
            # Create a couple missed tasks on day -3 and day -1
            curr_status = status
            if day_offset in (1, 3) and title == "Buy Groceries":
                curr_status = TaskStatus.MISSED.value

            task_due = datetime(
                day_date.year, day_date.month, day_date.day,
                h, m, tzinfo=IST
            )

            t = Task(
                title=f"{title}",
                due_at=to_ist_naive(task_due),
                category=cat,
                duration_minutes=dur,
                status=curr_status,
                snooze_count=snoozes,
                is_fixed=True,
                is_synthetic=True,
                resolution_note="Demo data generator",
                created_at=task_due.astimezone(timezone.utc).replace(tzinfo=None),
            )
            db.add(t)
            db.commit()
            db.refresh(t)
            created_tasks.append(t.id)

            # Insert corresponding events for realistic timeline
            db.add(Event(
                ts=task_due.astimezone(timezone.utc).replace(tzinfo=None),
                type="task_created",
                message=f"Reminder set: {title} (synthetic)",
                task_id=t.id,
            ))
            if snoozes > 0:
                db.add(Event(
                    ts=(task_due + timedelta(minutes=s_mins)).astimezone(timezone.utc).replace(tzinfo=None),
                    type="task_snoozed",
                    message=f"Snoozed for {s_mins}m (synthetic)",
                    task_id=t.id,
                ))
            if curr_status == TaskStatus.DONE.value:
                db.add(Event(
                    ts=(task_due + timedelta(minutes=dur)).astimezone(timezone.utc).replace(tzinfo=None),
                    type="task_done",
                    message=f"Done: {title} (synthetic)",
                    task_id=t.id,
                ))
            elif curr_status == TaskStatus.MISSED.value:
                db.add(Event(
                    ts=(task_due + timedelta(minutes=dur + 30)).astimezone(timezone.utc).replace(tzinfo=None),
                    type="task_missed",
                    message=f"Missed: {title} (synthetic)",
                    task_id=t.id,
                ))

    db.commit()

    return {
        "ok": True,
        "is_synthetic": True,
        "tasks_generated": len(created_tasks),
        "days": 7,
        "message": f"Generated {len(created_tasks)} synthetic tasks over past 7 days.",
    }


def clear_demo_data(db) -> Dict[str, Any]:
    """Remove all records marked is_synthetic=True."""
    tasks_deleted = db.query(Task).filter(Task.is_synthetic.is_(True)).delete()
    prefs_deleted = db.query(LearnedPreference).filter(LearnedPreference.is_synthetic.is_(True)).delete()
    db.commit()

    return {
        "ok": True,
        "tasks_deleted": tasks_deleted,
        "prefs_deleted": prefs_deleted,
        "message": f"Cleared {tasks_deleted} synthetic tasks and {prefs_deleted} synthetic preferences.",
    }
