"""
Deterministic behavior statistics and learned preferences engine.
Computes snooze rate, median duration, miss rate, and completion rate per category and hour.
Evaluates learned preferences with configurable thresholds and 14-day decline cooldowns.
"""
import statistics
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any
from sqlalchemy import func

from db import Task, TaskStatus, Event, LearnedPreference
from config import settings
from timeutil import ensure_ist, now_ist


def compute_category_stats(db, category: Optional[str] = None) -> Dict[str, Any]:
    """
    Compute deterministic metrics for a category (or all categories if None):
    - total_tasks, done_count, missed_count, snooze_count
    - completion_rate, miss_rate, snooze_rate
    - median_snooze_duration
    - hourly_distribution (0-23)
    - synthetic_count, is_synthetic
    """
    query = db.query(Task)
    if category:
        query = query.filter(Task.category == category)
    tasks = query.all()

    if not tasks:
        return {
            "category": category or "all",
            "total_tasks": 0,
            "done_count": 0,
            "missed_count": 0,
            "snoozed_count": 0,
            "total_snoozes": 0,
            "completion_rate": 0.0,
            "miss_rate": 0.0,
            "snooze_rate": 0.0,
            "median_snooze_minutes": 10,
            "synthetic_count": 0,
            "is_synthetic": False,
            "hourly_distribution": {h: 0 for h in range(24)},
        }

    total = len(tasks)
    done_count = sum(1 for t in tasks if t.status == TaskStatus.DONE.value)
    missed_count = sum(1 for t in tasks if t.status == TaskStatus.MISSED.value)
    snoozed_count = sum(1 for t in tasks if (t.snooze_count or 0) > 0)
    total_snooze_actions = sum(t.snooze_count or 0 for t in tasks)

    # Calculate median snooze duration from events or task snooze records
    # Query snooze events for these tasks if available, otherwise assume standard snooze
    snooze_events = db.query(Event).filter(
        Event.type == "task_snoozed",
        Event.task_id.in_([t.id for t in tasks])
    ).all()

    snooze_durations = []
    for ev in snooze_events:
        # e.g. "Snoozed for 20m"
        import re
        m = re.search(r"(\d+)\s*(?:m|min|minutes)", ev.message or "")
        if m:
            snooze_durations.append(int(m.group(1)))

    if not snooze_durations:
        snooze_durations = [20 if (t.snooze_count or 0) > 0 else 10 for t in tasks if (t.snooze_count or 0) > 0]

    median_duration = int(statistics.median(snooze_durations)) if snooze_durations else 10

    # Hourly distribution of scheduled tasks
    hourly: Dict[int, int] = {h: 0 for h in range(24)}
    for t in tasks:
        if t.due_at:
            dt = ensure_ist(t.due_at)
            hourly[dt.hour] = hourly.get(dt.hour, 0) + 1

    synthetic_count = sum(1 for t in tasks if t.is_synthetic)
    is_synthetic = (synthetic_count > 0 and synthetic_count == total)

    return {
        "category": category or "all",
        "total_tasks": total,
        "done_count": done_count,
        "missed_count": missed_count,
        "snoozed_count": snoozed_count,
        "total_snoozes": total_snooze_actions,
        "completion_rate": round((done_count / total) * 100, 1),
        "miss_rate": round((missed_count / total) * 100, 1),
        "snooze_rate": round((snoozed_count / total) * 100, 1),
        "median_snooze_minutes": median_duration,
        "synthetic_count": synthetic_count,
        "is_synthetic": is_synthetic,
        "hourly_distribution": hourly,
    }


def evaluate_learned_preferences(
    db, now: Optional[datetime] = None, config=settings
) -> List[Dict[str, Any]]:
    """
    Check if any category has met the snooze threshold (>= 3 snoozes with consistent delay).
    Returns list of eligible preference offers that are not declined or already active.
    """
    if now is None:
        now = now_ist()
    else:
        now = ensure_ist(now)

    categories = ["health", "work", "errands", "family"]
    offers = []

    for cat in categories:
        # Check if already active
        active_pref = db.query(LearnedPreference).filter_by(
            category=cat, is_active=True
        ).first()
        if active_pref:
            continue

        # Check if currently under 14-day decline cooldown
        declined_pref = db.query(LearnedPreference).filter(
            LearnedPreference.category == cat,
            LearnedPreference.declined_until > now.astimezone(timezone.utc).replace(tzinfo=None)
        ).first()
        if declined_pref:
            continue

        # Compute stats for category
        stats = compute_category_stats(db, category=cat)
        if stats["total_snoozes"] >= config.preference_snooze_threshold:
            offset = stats["median_snooze_minutes"]
            is_synth = (stats["synthetic_count"] > 0)
            spoken_offer = (
                f"You usually push {cat} by about {offset} minutes. "
                f"Want me to remind you {offset} minutes later from now on?"
            )
            offers.append({
                "category": cat,
                "offset_minutes": offset,
                "evidence_count": stats["total_snoozes"],
                "is_synthetic": is_synth,
                "spoken_offer": spoken_offer,
                "summary": f"Based on {stats['total_snoozes']} snoozes ({'synthetic' if is_synth else 'real'})",
            })

    return offers


def apply_learned_preference(
    db, category: str, offset_minutes: int, evidence_count: int = 3, is_synthetic: bool = False
) -> LearnedPreference:
    """Persist an accepted learned preference."""
    pref = db.query(LearnedPreference).filter_by(category=category).first()
    if not pref:
        pref = LearnedPreference(
            category=category,
            offset_minutes=offset_minutes,
            evidence_count=evidence_count,
            is_active=True,
            is_synthetic=is_synthetic,
        )
        db.add(pref)
    else:
        pref.offset_minutes = offset_minutes
        pref.evidence_count = evidence_count
        pref.is_active = True
        pref.declined_until = None
        pref.is_synthetic = is_synthetic

    db.commit()
    db.refresh(pref)
    return pref


def decline_learned_preference(
    db, category: str, now: Optional[datetime] = None, cooldown_days: int = 14
) -> None:
    """Decline a learned preference, preventing re-offer for 14 days."""
    if now is None:
        now = now_ist()
    else:
        now = ensure_ist(now)

    pref = db.query(LearnedPreference).filter_by(category=category).first()
    cooldown_until = (now + timedelta(days=cooldown_days)).astimezone(timezone.utc).replace(tzinfo=None)

    if not pref:
        pref = LearnedPreference(
            category=category,
            offset_minutes=0,
            is_active=False,
            declined_until=cooldown_until,
        )
        db.add(pref)
    else:
        pref.is_active = False
        pref.declined_until = cooldown_until

    db.commit()


def reset_learned_preference(db, category: str) -> None:
    """Reset / delete a learned preference."""
    db.query(LearnedPreference).filter_by(category=category).delete()
    db.commit()


def get_active_preference(db, category: str) -> Optional[LearnedPreference]:
    """Get active preference for a category if one exists."""
    return db.query(LearnedPreference).filter_by(
        category=category, is_active=True
    ).first()
