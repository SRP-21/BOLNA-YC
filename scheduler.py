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
        task.nudge_count = 0
        db.commit()

        due_str = task.due_at.strftime('%I:%M %p') if task.due_at else "now"
        from agent.replies import format_reminder_prompt
        task_lang = task.language or "en"
        log_event(
            "reminder_fired",
            format_reminder_prompt(task.title, due_str, task_lang),
            task_id=task.id
        )
        logger.info(f"🔔 Reminder fired: #{task.id} {task.title}")

        # Schedule nudge 1 (configurable delay, default 2 min)
        retry_delay = getattr(settings, "nudge_delay_1_seconds", settings.reminder_retry_delay_seconds)
        retry_time = now_ist() + timedelta(seconds=retry_delay)
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
    Second attempt after no response (nudge 1).
    Schedules final miss escalation after nudge_delay_2_seconds (default 5 min).
    """
    db = SessionLocal()
    try:
        task = db.query(Task).filter_by(id=task_id).first()
        if not task:
            return

        if task.status == TaskStatus.DUE.value:
            task.nudge_count = (task.nudge_count or 0) + 1
            db.commit()

            log_event(
                "reminder_retry",
                f"Reminder again: {task.title}. Are you done with this?",
                task_id=task.id
            )
            logger.info(f"🔔 Retry reminder: #{task.id} {task.title} (nudge #{task.nudge_count})")

            # Schedule mark_missed after second nudge delay (default 5 min)
            miss_delay = getattr(settings, "nudge_delay_2_seconds", settings.reminder_retry_delay_seconds)
            miss_time = now_ist() + timedelta(seconds=miss_delay)
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
    from timeutil import format_when
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
        when_str = format_when(next_dt, now_ist(), task.language or "en")
        log_event("task_recurring", f"Next: {new_task.title} {when_str}",
                  task_id=new_task.id)
        return new_task
    return None


def reload_pending_tasks():
    """
    On startup: reload all pending and DUE tasks and schedule their reminders.
    Future tasks are scheduled at their normal due_at.
    Overdue tasks and tasks in DUE status are staggered (2s, 12s, 22s...)
    so a restart does not trigger a burst of simultaneous reminders.
    """
    db = SessionLocal()
    try:
        tasks = db.query(Task).filter(
            Task.status.in_([
                TaskStatus.SCHEDULED.value,
                TaskStatus.SNOOZED.value,
                TaskStatus.DUE.value,
            ])
        ).all()

        now = now_ist()
        future_tasks = []
        overdue_or_due_tasks = []

        for task in tasks:
            task_due = ensure_ist(task.due_at)
            if task.status == TaskStatus.DUE.value or task_due <= now:
                overdue_or_due_tasks.append(task)
            else:
                future_tasks.append(task)

        # Schedule future tasks directly
        for task in future_tasks:
            schedule_task_reminder(task.id, task.due_at)

        # Stagger overdue and DUE tasks if policy is fire_now
        if settings.overdue_policy == "fire_now":
            overdue_or_due_tasks.sort(key=lambda t: ensure_ist(t.due_at))
            for i, task in enumerate(overdue_or_due_tasks):
                offset = 2 + (i * settings.reminder_stagger_seconds)
                run_date = now + timedelta(seconds=offset)
                remove_task_job(task.id)
                try:
                    scheduler.add_job(
                        fire_reminder,
                        trigger=DateTrigger(run_date=run_date, timezone=IST),
                        args=[task.id],
                        id=f"task_{task.id}",
                        replace_existing=True,
                    )
                    logger.info(
                        f"⏰ Staggered overdue reminder #{task.id} at {run_date.strftime('%I:%M:%S %p')} (+{offset}s)"
                    )
                except Exception as e:
                    logger.warning(f"Failed to stagger job for task #{task.id}: {e}")
        else:
            for task in overdue_or_due_tasks:
                logger.info(f"Task #{task.id} is overdue, marking missed per policy")

        logger.info(
            f"Reloaded {len(tasks)} pending/due tasks "
            f"({len(future_tasks)} future, {len(overdue_or_due_tasks)} staggered overdue/due)"
        )
    finally:
        db.close()
