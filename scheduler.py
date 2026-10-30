"""
APScheduler-based reminder scheduler.
Real DB-backed jobs that survive restart.
Uses shared SQLAlchemy engine with WAL mode.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.date import DateTrigger
from db import SessionLocal, Task, TaskStatus, engine
from events import log_event
from config import settings
from timeutil import IST, now_ist, ensure_ist, to_ist_naive

logger = logging.getLogger(__name__)

IST = ZoneInfo(settings.default_timezone)

# Reuse the shared database engine to prevent SQLite file-locking conflicts
jobstores = {
    'default': SQLAlchemyJobStore(engine=engine, tablename='apscheduler_jobs')
}

scheduler = AsyncIOScheduler(
    jobstores=jobstores,
    job_defaults={'misfire_grace_time': 300},
    timezone=IST,
)


async def fire_reminder(task_id: int):
    """
    Called by APScheduler when a reminder is due.
    Updates task status and broadcasts via SSE so the frontend can speak it.
    """
    db = SessionLocal()
    try:
        task = db.query(Task).filter_by(id=task_id).first()
        if not task:
            logger.warning(f"Reminder fired for missing task #{task_id}")
            return

        if task.status in (TaskStatus.DONE.value, TaskStatus.CANCELLED.value):
            logger.info(f"Skipping reminder for {task.status} task #{task_id}")
            return

        task.status = TaskStatus.DUE.value
        db.commit()

        due_str = task.due_at.strftime('%I:%M %p') if task.due_at else "now"
        log_event(
            "reminder_fired",
            f"{task.title} — it's {due_str}. Done, snooze, or move to tomorrow?",
            task_id=task.id
        )
        logger.info(f"🔔 Reminder fired: #{task.id} {task.title}")

        # Schedule a retry if no response after configured delay
        retry_time = now_ist() + timedelta(
            seconds=settings.reminder_retry_delay_seconds
        )
        try:
            scheduler.add_job(
                fire_reminder_retry,
                trigger=DateTrigger(run_date=retry_time, timezone=IST),
                args=[task_id],
                id=f"retry_{task_id}",
                replace_existing=True,
            )
        except Exception as e:
            logger.warning(f"Scheduler add_job warning: {e}")
    finally:
        db.close()


async def fire_reminder_retry(task_id: int):
    """
    Second attempt after no response.
    If still no response, mark as missed.
    """
    db = SessionLocal()
    try:
        task = db.query(Task).filter_by(id=task_id).first()
        if not task:
            return

        if task.status == TaskStatus.DUE.value:
            log_event(
                "reminder_retry",
                f"Reminder again: {task.title}. Are you done with this?",
                task_id=task.id
            )
            logger.info(f"🔔 Retry reminder: #{task.id} {task.title}")

            miss_time = now_ist() + timedelta(
                seconds=settings.reminder_retry_delay_seconds
            )
            try:
                scheduler.add_job(
                    mark_missed,
                    trigger=DateTrigger(run_date=miss_time, timezone=IST),
                    args=[task_id],
                    id=f"miss_{task_id}",
                    replace_existing=True,
                )
            except Exception as e:
                logger.warning(f"Scheduler retry add_job warning: {e}")
    finally:
        db.close()


async def mark_missed(task_id: int):
    """Mark a task as missed if still in DUE status."""
    db = SessionLocal()
    try:
        task = db.query(Task).filter_by(id=task_id).first()
        if not task:
            return
        if task.status == TaskStatus.DUE.value:
            task.status = TaskStatus.MISSED.value
            db.commit()
            log_event("task_missed", f"Missed: {task.title}", task_id=task.id)
            logger.info(f"❌ Task missed: #{task.id} {task.title}")

            if task.recurrence:
                _schedule_next_recurrence(db, task)
    finally:
        db.close()


def schedule_task_reminder(task_id: int, due_at: datetime):
    """Schedule (or reschedule) a reminder for a task."""
    remove_task_job(task_id)

    due_at = ensure_ist(due_at)
    now = now_ist()
    if due_at <= now:
        if settings.overdue_policy == "fire_now":
            due_at = now + timedelta(seconds=2)
        else:
            logger.info(f"Task #{task_id} is overdue, marking missed per policy")
            return

    try:
        scheduler.add_job(
            fire_reminder,
            trigger=DateTrigger(run_date=due_at, timezone=IST),
            args=[task_id],
            id=f"task_{task_id}",
            replace_existing=True,
        )
        logger.info(f"⏰ Scheduled reminder #{task_id} at {due_at.strftime('%I:%M %p')}")
    except Exception as e:
        logger.warning(f"Failed to add job to scheduler: {e}")


def remove_task_job(task_id: int):
    """Remove all scheduler jobs for a task."""
    for prefix in ("task_", "retry_", "miss_"):
        job_id = f"{prefix}{task_id}"
        try:
            scheduler.remove_job(job_id)
        except Exception:
            pass


def _schedule_next_recurrence(db, task: Task):
    """Create a new task instance for the next recurrence."""
    from agent.resolver import compute_next_recurrence
    next_dt = compute_next_recurrence(task.due_at, task.recurrence)
    if next_dt:
        new_task = Task(
            title=task.title,
            due_at=to_ist_naive(next_dt),
            recurrence=task.recurrence,
            status=TaskStatus.SCHEDULED.value,
            language=task.language,
            source_phrase=task.source_phrase,
            resolution_note=f"Recurring from #{task.id}",
        )
        db.add(new_task)
        db.commit()
        db.refresh(new_task)
        schedule_task_reminder(new_task.id, next_dt)
        log_event("task_recurring", f"Next: {new_task.title} at {next_dt.strftime('%I:%M %p')}",
                  task_id=new_task.id)


def reload_pending_tasks():
    """
    On startup: reload all pending tasks and schedule their reminders.
    Handles overdue tasks according to config (fire_now or mark_missed).
    """
    db = SessionLocal()
    try:
        pending = db.query(Task).filter(
            Task.status.in_([TaskStatus.SCHEDULED.value, TaskStatus.SNOOZED.value])
        ).all()

        for task in pending:
            schedule_task_reminder(task.id, task.due_at)

        logger.info(f"Reloaded {len(pending)} pending tasks")
    finally:
        db.close()
