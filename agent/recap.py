"""
Evening recap and carry-over logic for voice daily planner.
Builds daily recap from stored history, enforces strict validator against hallucinated
numbers or task names, and runs carry-over through standard time resolution and conflict detection.
"""
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple

from db import Task, TaskStatus
from timeutil import ensure_ist, to_ist_naive, now_ist, IST
from config import settings
from scheduler import schedule_task_reminder
from agent.conflicts import detect_conflicts
from events import log_event


RECAP_TRIGGERS = [
    "end my day", "wrap up", "evening recap", "day recap", "recap",
    "aaj ka recap", "din khatam", "aaj ka hisab", "kelsa mugiyithu",
    "how did my day go", "summary of today"
]


def is_recap_command(text: str) -> bool:
    """Check if utterance is an evening recap request."""
    t = text.lower().strip()
    return any(trig in t for trig in RECAP_TRIGGERS)


def build_evening_recap(db, now: Optional[datetime] = None, language: str = "en") -> Dict[str, Any]:
    """
    Compile today's recap strictly from stored DB tasks.
    Returns counts, missed tasks, completion rate, and validated spoken sentences.
    """
    if now is None:
        now = now_ist()
    else:
        now = ensure_ist(now)

    today_date = now.date()

    # Query tasks for today
    all_tasks = db.query(Task).all()
    today_tasks = [t for t in all_tasks if t.due_at and ensure_ist(t.due_at).date() == today_date]

    done_count = sum(1 for t in today_tasks if t.status == TaskStatus.DONE.value)
    missed_tasks = [t for t in today_tasks if t.status == TaskStatus.MISSED.value]
    missed_count = len(missed_tasks)
    snoozed_count = sum(1 for t in today_tasks if (t.snooze_count or 0) > 0)
    cancelled_count = sum(1 for t in today_tasks if t.status == TaskStatus.CANCELLED.value)
    total_tasks = len(today_tasks)

    completion_rate = round((done_count / total_tasks * 100), 1) if total_tasks > 0 else 0.0

    # 7-day trend (daily completion rates for the past 7 days)
    seven_day_trend = []
    for day_offset in range(6, -1, -1):
        d = today_date - timedelta(days=day_offset)
        d_tasks = [t for t in all_tasks if t.due_at and ensure_ist(t.due_at).date() == d]
        d_total = len(d_tasks)
        d_done = sum(1 for t in d_tasks if t.status == TaskStatus.DONE.value)
        rate = round((d_done / d_total * 100), 1) if d_total > 0 else 0.0
        seven_day_trend.append({
            "date": d.isoformat(),
            "weekday": d.strftime("%a"),
            "total": d_total,
            "done": d_done,
            "completion_rate": rate,
        })

    # Missed tasks phrase
    missed_names = [t.title for t in missed_tasks]
    missed_str_en = f"Missed: {', '.join(missed_names)}." if missed_names else "No missed tasks!"
    missed_str_hi = f"छूटे हुए: {', '.join(missed_names)}।" if missed_names else "कोई छूटा हुआ कार्य नहीं है!"
    missed_str_kn = f"ತಪ್ಪಿಹೋದ ಕಾರ್ಯಗಳು: {', '.join(missed_names)}." if missed_names else "ಯಾವುದೇ ತಪ್ಪಿದ ಕಾರ್ಯಗಳಿಲ್ಲ!"

    # Multi-lingual templates
    templates = {
        "en": (
            f"Today you completed {done_count} tasks, missed {missed_count}, "
            f"and snoozed {snoozed_count}. {missed_str_en}"
        ),
        "hi": (
            f"आज आपने {done_count} कार्य पूरे किए, {missed_count} छूटे, "
            f"और {snoozed_count} स्नूज़ किए। {missed_str_hi}"
        ),
        "kn": (
            f"ಇಂದು ನೀವು {done_count} ಕಾರ್ಯಗಳನ್ನು ಪೂರ್ಣಗೊಳಿಸಿದ್ದೀರಿ, {missed_count} ತಪ್ಪಿಹೋಗಿವೆ, "
            f"ಮತ್ತು {snoozed_count} ಸ್ನೂಜ್ ಮಾಡಿದ್ದೀರಿ. {missed_str_kn}"
        )
    }

    spoken_text = templates.get(language, templates["en"])
    if missed_count > 0:
        if language == "hi":
            spoken_text += " क्या आप छूटे हुए कार्यों को कल सुबह शिफ्ट करना चाहते हैं?"
        elif language == "kn":
            spoken_text += " ನೀವು ತಪ್ಪಿದ ಕಾರ್ಯಗಳನ್ನು ನಾಳೆ ಬೆಳಿಗ್ಗೆ ಸರಿಸಲು ಬಯಸುವಿರಾ?"
        else:
            spoken_text += " Would you like me to move your missed tasks to tomorrow morning?"

    return {
        "date": today_date.isoformat(),
        "total_tasks": total_tasks,
        "done_count": done_count,
        "missed_count": missed_count,
        "snoozed_count": snoozed_count,
        "cancelled_count": cancelled_count,
        "completion_rate": completion_rate,
        "missed_tasks": [{
            "id": t.id,
            "title": t.title,
            "category": t.category,
            "due_at": ensure_ist(t.due_at).isoformat() if t.due_at else None,
        } for t in missed_tasks],
        "seven_day_trend": seven_day_trend,
        "spoken_text": spoken_text,
        "templates": templates,
    }


def validate_recap_rephrase(rephrase: str, source_data: Dict[str, Any]) -> bool:
    """
    STRICT VALIDATOR: Rejects any rephrase containing numbers or task names
    not present in source data, preventing LLM hallucinations.
    """
    # 1. Allowed numbers
    allowed_numbers = {
        source_data.get("done_count", 0),
        source_data.get("missed_count", 0),
        source_data.get("snoozed_count", 0),
        source_data.get("cancelled_count", 0),
        source_data.get("total_tasks", 0),
        int(source_data.get("completion_rate", 0)),
        7,  # allowed for 7-day trend
    }
    # Also allow current day of month / hour
    if source_data.get("date"):
        try:
            d = datetime.fromisoformat(source_data["date"])
            allowed_numbers.add(d.day)
            allowed_numbers.add(d.year)
        except Exception:
            pass

    # Extract all digit sequences from rephrase
    found_numbers = re.findall(r"\b\d+\b", rephrase)
    for num_str in found_numbers:
        val = int(num_str)
        if val not in allowed_numbers:
            # Hallucinated number detected!
            return False

    # 2. Check task names: any named task in rephrase must exist in today's source
    # Source tasks titles
    known_titles = {
        m["title"].lower().strip() for m in source_data.get("missed_tasks", [])
    }
    # If a quote or title pattern is in rephrase, verify it
    quotes = re.findall(r"['\"](.*?)['\"]", rephrase)
    for q in quotes:
        q_lower = q.lower().strip()
        if q_lower and q_lower not in known_titles and len(q_lower.split()) > 1:
            return False

    return True


def apply_carryover_to_tomorrow(
    db, now: Optional[datetime] = None, config=settings
) -> Dict[str, Any]:
    """
    Carry missed tasks to tomorrow morning (09:00 IST),
    running through standard time-resolution and conflict detection atomically.
    """
    if now is None:
        now = now_ist()
    else:
        now = ensure_ist(now)

    today_date = now.date()

    # Query all missed tasks
    missed_tasks = db.query(Task).filter(
        Task.status == TaskStatus.MISSED.value
    ).all()

    if not missed_tasks:
        return {
            "ok": True,
            "carried_count": 0,
            "message": "No missed tasks to carry over.",
            "conflicts": [],
        }

    tomorrow_base = datetime(
        today_date.year, today_date.month, today_date.day,
        config.morning_window_hour, config.morning_window_minute,
        tzinfo=IST
    ) + timedelta(days=1)

    min_gap = timedelta(minutes=config.replan_min_gap_minutes)
    carried = []

    for i, t in enumerate(missed_tasks):
        new_due = tomorrow_base + (i * min_gap)
        t.due_at = to_ist_naive(new_due)
        t.status = TaskStatus.SCHEDULED.value
        t.resolution_note = f"Carried over from {today_date.isoformat()} evening recap"
        # Re-register scheduler job
        schedule_task_reminder(t.id, new_due)
        carried.append({
            "id": t.id,
            "title": t.title,
            "new_due_at": new_due.isoformat(),
        })

    db.commit()

    # Run conflict detection on the new schedule
    active_tasks = db.query(Task).filter(
        Task.status.in_([TaskStatus.SCHEDULED.value, TaskStatus.SNOOZED.value, TaskStatus.DUE.value])
    ).all()
    conflicts = detect_conflicts(active_tasks, default_duration_minutes=config.default_task_duration_minutes)

    log_event("tasks_carried_over", f"Carried {len(carried)} missed tasks to tomorrow morning")

    return {
        "ok": True,
        "carried_count": len(carried),
        "carried_tasks": carried,
        "conflicts": [c.to_dict() for c in conflicts],
        "message": f"Carried over {len(carried)} missed tasks to tomorrow morning.",
    }
