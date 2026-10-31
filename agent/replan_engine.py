"""
Deterministic replanning engine for voice assistant.
Applies user replan intents (shift, block window, move, swap, clear range),
respects fixed vs flexible tasks, quiet hours (22:00-07:00), day end (21:30),
preserves relative order, runs conflict detection, and supports atomic commit and undo.
"""
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, time as dt_time
from typing import List, Optional, Dict, Any, Tuple
from zoneinfo import ZoneInfo

from db import Task, TaskStatus, ReplanSnapshot
from agent.matcher import find_task_by_title
from agent.conflicts import detect_conflicts, Conflict
from timeutil import ensure_ist, to_ist_naive, now_ist, IST
from config import settings
from events import log_event
from scheduler import schedule_task_reminder, remove_task_job

logger = logging.getLogger(__name__)


@dataclass
class ReplanIntent:
    intent_type: str  # 'shift_all' | 'shift_from' | 'block_window' | 'move_task' | 'swap_tasks' | 'clear_range'
    minutes: Optional[int] = None
    from_time: Optional[datetime] = None
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None
    task_identifier: Optional[str] = None
    task_identifier_2: Optional[str] = None
    destination_phrase: Optional[str] = None


@dataclass
class TaskChange:
    task_id: int
    title: str
    old_due_at: datetime
    new_due_at: datetime
    is_fixed: bool
    is_carryover: bool = False

    def to_dict(self):
        return {
            "task_id": self.task_id,
            "title": self.title,
            "old_due_at": ensure_ist(self.old_due_at).isoformat(),
            "new_due_at": ensure_ist(self.new_due_at).isoformat(),
            "is_fixed": self.is_fixed,
            "is_carryover": self.is_carryover,
        }


@dataclass
class ReplanPlan:
    intent: ReplanIntent
    changes: List[TaskChange] = field(default_factory=list)
    conflicts: List[Conflict] = field(default_factory=list)
    summary: Dict[str, str] = field(default_factory=dict)
    reason: str = ""
    created_at: datetime = field(default_factory=now_ist)

    def to_dict(self):
        return {
            "intent_type": self.intent.intent_type,
            "changes": [c.to_dict() for c in self.changes],
            "conflicts": [c.to_dict() for c in self.conflicts],
            "summary": self.summary,
            "reason": self.reason,
        }


def _is_past_day_or_quiet(dt: datetime, config=settings) -> bool:
    """Check if time lands past day end (21:30) or in quiet hours (22:00-07:00)."""
    ist_dt = ensure_ist(dt)
    h, m = ist_dt.hour, ist_dt.minute

    # Quiet hours check: 22:00 - 07:00
    if h >= config.quiet_hours_start or h < config.quiet_hours_end:
        return True

    # Day end check: default 21:30
    if h > config.day_end_hour or (h == config.day_end_hour and m >= config.day_end_minute):
        return True

    return False


def _next_morning_slot(base_date: datetime, offset_minutes: int = 0, config=settings) -> datetime:
    """Return next day's morning window time (default 09:00 IST + offset)."""
    ist_dt = ensure_ist(base_date)
    tomorrow = ist_dt.date() + timedelta(days=1)
    return datetime(
        tomorrow.year, tomorrow.month, tomorrow.day,
        config.morning_window_hour, config.morning_window_minute,
        tzinfo=IST
    ) + timedelta(minutes=offset_minutes)


def compute_replan(
    db,
    intent: ReplanIntent,
    now: Optional[datetime] = None,
    config=settings,
    language: str = "en",
) -> ReplanPlan:
    """
    Compute preview plan without altering DB or scheduler.
    """
    if now is None:
        now = now_ist()
    else:
        now = ensure_ist(now)

    active_tasks = db.query(Task).filter(
        Task.status.in_([
            TaskStatus.SCHEDULED.value,
            TaskStatus.SNOOZED.value,
            TaskStatus.DUE.value,
        ])
    ).order_by(Task.due_at).all()

    if not active_tasks:
        return ReplanPlan(
            intent=intent,
            summary={
                "en": "You don't have any pending reminders to reschedule.",
                "hi": "पुनर्निर्धारित करने के लिए कोई सक्रिय रिमाइंडर नहीं है।",
                "kn": "ಮರುಹೊಂದಿಸಲು ಯಾವುದೇ ಸಕ್ರಿಯ ರಿಮೈಂಡರ್‌ಗಳಿಲ್ಲ.",
            },
            reason="no_active_tasks"
        )

    changes: List[TaskChange] = []
    skipped: List[Tuple[Task, str]] = []
    min_gap = timedelta(minutes=config.replan_min_gap_minutes)
    carryover_offset = 0

    # 1. SHIFT ALL / SHIFT FROM
    if intent.intent_type in ("shift_all", "shift_from"):
        shift_delta = timedelta(minutes=intent.minutes or 45)
        cutoff_time = intent.from_time or now
        is_shift_all = (intent.intent_type == "shift_all")

        # In shift_all, all active tasks move (is_fixed does not protect against explicit shift command).
        # In shift_from, fixed tasks stay in place.
        for t in active_tasks:
            t_due = ensure_ist(t.due_at)
            if t_due < cutoff_time:
                skipped.append((t, "past"))
                continue

            if t.is_fixed and not is_shift_all:
                # Fixed tasks do not move automatically on partial / shift_from shifts
                skipped.append((t, "fixed"))
                continue

            target_due = t_due + shift_delta
            is_carryover = False

            # Check quiet hours / day end overflow
            if _is_past_day_or_quiet(target_due, config):
                target_due = _next_morning_slot(t_due, carryover_offset, config)
                carryover_offset += config.replan_min_gap_minutes
                is_carryover = True

            changes.append(
                TaskChange(
                    task_id=t.id,
                    title=t.title,
                    old_due_at=t_due,
                    new_due_at=target_due,
                    is_fixed=bool(t.is_fixed),
                    is_carryover=is_carryover,
                )
            )

    # 2. BLOCK WINDOW
    elif intent.intent_type == "block_window":
        w_start = intent.window_start or now
        w_end = intent.window_end or (w_start + timedelta(hours=2))

        # Tasks currently inside the window must be moved to the nearest free slot after w_end
        next_free_slot = w_end
        for t in active_tasks:
            t_due = ensure_ist(t.due_at)
            # If task falls inside the blocked window
            if w_start <= t_due < w_end:
                target_due = next_free_slot
                is_carryover = False

                if _is_past_day_or_quiet(target_due, config):
                    target_due = _next_morning_slot(t_due, carryover_offset, config)
                    carryover_offset += config.replan_min_gap_minutes
                    is_carryover = True

                changes.append(
                    TaskChange(
                        task_id=t.id,
                        title=t.title,
                        old_due_at=t_due,
                        new_due_at=target_due,
                        is_fixed=bool(t.is_fixed),
                        is_carryover=is_carryover,
                    )
                )
                next_free_slot = target_due + min_gap

    # 3. SWAP TASKS
    elif intent.intent_type == "swap_tasks":
        t1_id = intent.task_identifier
        t2_id = intent.task_identifier_2
        if t1_id and t2_id:
            st1, task_1, _ = find_task_by_title(db, t1_id, active_tasks=active_tasks, cutoff=0.5)
            st2, task_2, _ = find_task_by_title(db, t2_id, active_tasks=active_tasks, cutoff=0.5)
            if task_1 and task_2 and task_1.id != task_2.id:
                t1_due = ensure_ist(task_1.due_at)
                t2_due = ensure_ist(task_2.due_at)
                changes.append(
                    TaskChange(
                        task_id=task_1.id,
                        title=task_1.title,
                        old_due_at=t1_due,
                        new_due_at=t2_due,
                        is_fixed=bool(task_1.is_fixed),
                    )
                )
                changes.append(
                    TaskChange(
                        task_id=task_2.id,
                        title=task_2.title,
                        old_due_at=t2_due,
                        new_due_at=t1_due,
                        is_fixed=bool(task_2.is_fixed),
                    )
                )

    # 4. MOVE ONE TASK
    elif intent.intent_type == "move_task":
        target = intent.task_identifier or ""
        status, matched_task, _ = find_task_by_title(db, target, active_tasks=active_tasks, cutoff=0.5)
        if matched_task:
            from agent.resolver import resolve_time
            dest_phrase = intent.destination_phrase or "tomorrow morning"
            resolved = resolve_time(dest_phrase, now=now)
            t_due = ensure_ist(matched_task.due_at)
            changes.append(
                TaskChange(
                    task_id=matched_task.id,
                    title=matched_task.title,
                    old_due_at=t_due,
                    new_due_at=resolved.dt,
                    is_fixed=True,  # user explicitly set time
                    is_carryover=(resolved.dt.date() > t_due.date()),
                )
            )

    # 5. CLEAR RANGE
    elif intent.intent_type == "clear_range":
        w_start = intent.window_start or now
        w_end = intent.window_end or (w_start + timedelta(hours=3))
        for t in active_tasks:
            t_due = ensure_ist(t.due_at)
            if w_start <= t_due < w_end:
                # Move to tomorrow morning
                target_due = _next_morning_slot(t_due, carryover_offset, config)
                carryover_offset += config.replan_min_gap_minutes
                changes.append(
                    TaskChange(
                        task_id=t.id,
                        title=t.title,
                        old_due_at=t_due,
                        new_due_at=target_due,
                        is_fixed=bool(t.is_fixed),
                        is_carryover=True,
                    )
                )

    # Run conflict detection on the proposed schedule
    # Create simulated tasks list
    simulated_tasks = []
    changes_map = {c.task_id: c.new_due_at for c in changes}
    for t in active_tasks:
        sim_due = changes_map.get(t.id, ensure_ist(t.due_at))
        # Clone a lightweight object for conflict detector
        sim_t = Task(
            id=t.id,
            title=t.title,
            due_at=to_ist_naive(sim_due),
            duration_minutes=t.duration_minutes,
        )
        simulated_tasks.append(sim_t)

    conflicts = detect_conflicts(
        simulated_tasks,
        default_duration_minutes=config.default_task_duration_minutes,
        min_gap_minutes=config.replan_min_gap_minutes,
    )

    # Generate multi-language spoken summaries
    summaries = _generate_plan_summary(changes, intent, language, now, skipped=skipped)

    return ReplanPlan(
        intent=intent,
        changes=changes,
        conflicts=conflicts,
        summary=summaries,
        reason=f"intent:{intent.intent_type}",
    )


def _format_skipped_notice(skipped: List[Tuple[Task, str]], language: str) -> str:
    """Format explanation for skipped tasks by reason in en, hi, kn."""
    if not skipped:
        return ""

    past_titles = [t.title for t, r in skipped if r == "past"]
    fixed_titles = [t.title for t, r in skipped if r == "fixed"]

    parts = []
    if language == "hi":
        if past_titles:
            t_str = ", ".join(past_titles)
            verb = "उन्हें" if len(past_titles) > 1 else "उसे"
            parts.append(f"{t_str} का समय बीत चुका है इसलिए {verb} नहीं बदला गया।")
        if fixed_titles:
            t_str = ", ".join(fixed_titles)
            verb = "उन्हें" if len(fixed_titles) > 1 else "उसे"
            parts.append(f"{t_str} का निश्चित समय है इसलिए {verb} नहीं बदला गया।")
    elif language == "kn":
        if past_titles:
            t_str = ", ".join(past_titles)
            pron = "ಅವುಗಳನ್ನು" if len(past_titles) > 1 else "ಅದನ್ನು"
            parts.append(f"{t_str} ಸಮಯ ಈಗಾಗಲೇ ಮುಗಿದಿರುವುದರಿಂದ {pron} ಬದಲಾಯಿಸಿಲ್ಲ.")
        if fixed_titles:
            t_str = ", ".join(fixed_titles)
            pron = "ಅವುಗಳನ್ನು" if len(fixed_titles) > 1 else "ಅದನ್ನು"
            parts.append(f"{t_str} ನಿಗದಿತ ಸಮಯದ್ದಾಗಿದೆ ಆದ್ದರಿಂದ {pron} ಬದಲಾಯಿಸಿಲ್ಲ.")
    else:  # English
        if past_titles:
            t_str = ", ".join(past_titles)
            verb = "they already passed" if len(past_titles) > 1 else "it already passed"
            parts.append(f"I left {t_str} alone because {verb}.")
        if fixed_titles:
            t_str = ", ".join(fixed_titles)
            verb = "they have fixed times" if len(fixed_titles) > 1 else "it has a fixed time"
            parts.append(f"I left {t_str} alone because {verb}.")

    return " ".join(parts)


def _generate_plan_summary(
    changes: List[TaskChange],
    intent: ReplanIntent,
    language: str,
    now: datetime,
    skipped: Optional[List[Tuple[Task, str]]] = None,
) -> Dict[str, str]:
    """Generate concise spoken summary in en, hi, kn."""
    skipped = skipped or []
    skip_en = _format_skipped_notice(skipped, "en")
    skip_hi = _format_skipped_notice(skipped, "hi")
    skip_kn = _format_skipped_notice(skipped, "kn")

    if not changes:
        en_base = "No tasks needed to be moved."
        hi_base = "किसी भी कार्य को बदलने की आवश्यकता नहीं पड़ी।"
        kn_base = "ಯಾವುದೇ ಕಾರ್ಯಗಳನ್ನು ಬದಲಾಯಿಸುವ ಅಗತ್ಯವಿಲ್ಲ."
        return {
            "en": f"{en_base} {skip_en}".strip() if skip_en else en_base,
            "hi": f"{hi_base} {skip_hi}".strip() if skip_hi else hi_base,
            "kn": f"{kn_base} {skip_kn}".strip() if skip_kn else kn_base,
        }

    n = len(changes)
    # Build per-task spoken preview (e.g. "invoice to 1:15, gym to 7:00")
    parts_en = []
    parts_hi = []
    parts_kn = []

    for c in changes[:3]:  # limit spoken details to first 3
        dt = ensure_ist(c.new_due_at)
        time_str = dt.strftime("%I:%M %p").lstrip("0")
        parts_en.append(f"{c.title} to {time_str}")

        from timeutil import format_when
        when_hi = format_when(dt, now, "hi")
        parts_hi.append(f"{c.title} {when_hi}")

        when_kn = format_when(dt, now, "kn")
        parts_kn.append(f"{c.title} {when_kn}")

    preview_en = ", ".join(parts_en)
    preview_hi = ", ".join(parts_hi)
    preview_kn = ", ".join(parts_kn)

    item_str_en = f"{n} things" if n > 1 else "1 reminder"
    item_str_hi = f"{n} रिमाइंडर" if n > 1 else "1 रिमाइंडर"
    item_str_kn = f"{n} ಕಾರ್ಯಗಳು" if n > 1 else "1 ಕಾರ್ಯ"

    skip_suffix_en = f" {skip_en}" if skip_en else ""
    skip_suffix_hi = f" {skip_hi}" if skip_hi else ""
    skip_suffix_kn = f" {skip_kn}" if skip_kn else ""

    return {
        "en": f"I'll move {item_str_en}: {preview_en}.{skip_suffix_en} Okay?",
        "hi": f"मैं {item_str_hi} शिफ्ट कर दूंगा: {preview_hi}।{skip_suffix_hi} ठीक है?",
        "kn": f"ನಾನು {item_str_kn} ಬದಲಾಯಿಸುತ್ತೇನೆ: {preview_kn}.{skip_suffix_kn} ಸರಿಯೇ?",
    }


def apply_replan_commit(db, plan: ReplanPlan, reason: str = "") -> ReplanSnapshot:
    """
    Atomically commit plan changes to SQLite and re-register scheduler jobs.
    """
    if not plan.changes:
        raise ValueError("Cannot commit empty plan")

    task_ids = [c.task_id for c in plan.changes]
    tasks = db.query(Task).filter(Task.id.in_(task_ids)).all()
    tasks_by_id = {t.id: t for t in tasks}

    before_state = []
    after_state = []

    for c in plan.changes:
        t = tasks_by_id.get(c.task_id)
        if not t:
            continue

        before_state.append({
            "task_id": t.id,
            "title": t.title,
            "due_at": ensure_ist(t.due_at).isoformat() if t.due_at else None,
            "status": t.status,
            "is_fixed": t.is_fixed,
        })

        # Update task due_at
        new_due_naive = to_ist_naive(c.new_due_at)
        t.due_at = new_due_naive
        if c.is_fixed:
            t.is_fixed = True

        after_state.append({
            "task_id": t.id,
            "title": t.title,
            "due_at": ensure_ist(c.new_due_at).isoformat(),
            "status": t.status,
            "is_fixed": t.is_fixed,
        })

    # Save snapshot
    snapshot = ReplanSnapshot(
        reason=reason or plan.reason or "replan",
        before_state=json.dumps(before_state),
        after_state=json.dumps(after_state),
        undone=False,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)

    # Re-register scheduler jobs for each task
    for c in plan.changes:
        schedule_task_reminder(c.task_id, c.new_due_at)

    log_event("replan_committed", f"Replanned {len(plan.changes)} tasks ({snapshot.reason})")
    return snapshot


def apply_replan_undo(db, snapshot_id: Optional[int] = None) -> dict:
    """
    Restore previous schedule state from snapshot and reschedule jobs.
    """
    query = db.query(ReplanSnapshot).filter(ReplanSnapshot.undone.is_(False))
    if snapshot_id:
        snapshot = query.filter_by(id=snapshot_id).first()
    else:
        snapshot = query.order_by(ReplanSnapshot.id.desc()).first()

    if not snapshot:
        return {"ok": False, "message": "No replan snapshot available to undo"}

    before_records = json.loads(snapshot.before_state)
    restored_tasks = []

    for item in before_records:
        tid = item["task_id"]
        task = db.query(Task).filter_by(id=tid).first()
        if not task:
            continue

        if item.get("due_at"):
            dt = datetime.fromisoformat(item["due_at"])
            task.due_at = to_ist_naive(dt)
            schedule_task_reminder(task.id, dt)
        if item.get("status"):
            task.status = item["status"]
        if "is_fixed" in item:
            task.is_fixed = item["is_fixed"]

        restored_tasks.append(task.title)

    snapshot.undone = True
    db.commit()

    log_event("replan_undone", f"Reverted replan #{snapshot.id} ({len(restored_tasks)} tasks restored)")
    return {
        "ok": True,
        "snapshot_id": snapshot.id,
        "restored_tasks": restored_tasks,
        "message": f"Restored {len(restored_tasks)} reminders to prior schedule.",
    }
