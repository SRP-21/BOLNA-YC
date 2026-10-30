"""
Tests for scheduler staggered overdue reminders and DUE task reloading.
"""
from datetime import timedelta
import pytest
from db import init_db, SessionLocal, Task, TaskStatus
from timeutil import now_ist, to_ist_naive
from scheduler import reload_pending_tasks, scheduler, remove_task_job
from config import settings


def test_staggered_overdue_reminders():
    """Verify 3 overdue tasks are scheduled with run times at least 10s apart."""
    init_db()
    db = SessionLocal()
    db.query(Task).delete()
    db.commit()

    now = now_ist()

    # 3 overdue tasks in arbitrary order
    t1 = Task(
        title="Overdue task 1 (30m ago)",
        due_at=to_ist_naive(now - timedelta(minutes=30)),
        status=TaskStatus.SCHEDULED.value,
    )
    t2 = Task(
        title="Overdue task 2 (10m ago)",
        due_at=to_ist_naive(now - timedelta(minutes=10)),
        status=TaskStatus.SCHEDULED.value,
    )
    t3 = Task(
        title="Overdue task 3 (20m ago)",
        due_at=to_ist_naive(now - timedelta(minutes=20)),
        status=TaskStatus.SCHEDULED.value,
    )
    db.add_all([t1, t2, t3])
    db.commit()

    # Clear any leftover jobs
    for t in (t1, t2, t3):
        remove_task_job(t.id)

    try:
        reload_pending_tasks()

        job1 = scheduler.get_job(f"task_{t1.id}")
        job2 = scheduler.get_job(f"task_{t2.id}")
        job3 = scheduler.get_job(f"task_{t3.id}")

        assert job1 is not None, f"Job for task {t1.id} not scheduled"
        assert job2 is not None, f"Job for task {t2.id} not scheduled"
        assert job3 is not None, f"Job for task {t3.id} not scheduled"

        # Tasks should be sorted by due_at: t1 (30m ago) -> t3 (20m ago) -> t2 (10m ago)
        run_times = sorted([job1.trigger.run_date, job2.trigger.run_date, job3.trigger.run_date])

        diff_0_1 = (run_times[1] - run_times[0]).total_seconds()
        diff_1_2 = (run_times[2] - run_times[1]).total_seconds()

        assert diff_0_1 >= settings.reminder_stagger_seconds, (
            f"Expected stagger >= {settings.reminder_stagger_seconds}s, got {diff_0_1}s"
        )
        assert diff_1_2 >= settings.reminder_stagger_seconds, (
            f"Expected stagger >= {settings.reminder_stagger_seconds}s, got {diff_1_2}s"
        )
    finally:
        for t in (t1, t2, t3):
            remove_task_job(t.id)
        db.close()


def test_due_task_rescheduled_on_reload():
    """Verify a task in DUE status is re-surfaced and scheduled on restart."""
    init_db()
    db = SessionLocal()
    db.query(Task).delete()
    db.commit()

    now = now_ist()
    due_task = Task(
        title="Task awaiting reply",
        due_at=to_ist_naive(now - timedelta(minutes=5)),
        status=TaskStatus.DUE.value,
    )
    db.add(due_task)
    db.commit()

    remove_task_job(due_task.id)

    try:
        reload_pending_tasks()

        job = scheduler.get_job(f"task_{due_task.id}")
        assert job is not None, "DUE task was not rescheduled on reload"
        assert job.trigger.run_date is not None
        # Job should be scheduled in the immediate future
        assert job.trigger.run_date >= now
    finally:
        remove_task_job(due_task.id)
        db.close()
