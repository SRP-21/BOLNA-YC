"""
Time resolver: converts natural language time phrases to actual datetimes.
Central place for all time resolution logic.

WHY this design:
- Vague phrases ("before lunch", "evening") resolve using config.TimeWindows
- Exact time expressions ("10 am", "tomorrow at 7 pm", "subah 10 baje") take precedence over vague words
- Longer vague phrases ("lunch se pehle") are matched before shorter substrings ("lunch")
- Results flagged needs_confirmation=True include the reasoning
- All times are in Asia/Kolkata timezone
"""
from datetime import datetime, timedelta, timezone, time as dt_time
from typing import Optional, Tuple
from zoneinfo import ZoneInfo
from config import time_windows, settings
from timeutil import IST, now_ist, ensure_ist, to_ist_naive
import re
import logging

logger = logging.getLogger(__name__)


class ResolvedTime:
    def __init__(self, dt: datetime, needs_confirmation: bool = False,
                 reasoning: str = "", source_phrase: str = ""):
        self.dt = dt
        self.needs_confirmation = needs_confirmation
        self.reasoning = reasoning
        self.source_phrase = source_phrase

    def to_dict(self):
        return {
            "due_at": self.dt.isoformat(),
            "needs_confirmation": self.needs_confirmation,
            "resolution_note": self.reasoning,
            "source_phrase": self.source_phrase,
        }


def resolve_time(
    phrase: str,
    now: Optional[datetime] = None,
    reference_date: Optional[datetime] = None,
) -> ResolvedTime:
    """
    Resolve a time phrase to a datetime in IST.

    Args:
        phrase: The time expression (e.g., "10 am", "before lunch", "kal subah", "in an hour")
        now: Current time (injectable for testing). Defaults to real now in IST.
        reference_date: Base date for resolution. Defaults to today.

    Returns:
        ResolvedTime with the resolved datetime and metadata.
    """
    if now is None:
        now = now_ist()
    else:
        now = ensure_ist(now)
    if reference_date is None:
        reference_date = now
    else:
        reference_date = ensure_ist(reference_date)

    phrase_lower = phrase.lower().strip()
    original_phrase = phrase

    # --- 1. Relative time: "in N minutes/hours" ---
    relative_match = re.search(
        r"(?:in\s+)?(\d+)\s*(min(?:utes?)?|mins?|hr|hours?|ghante?)",
        phrase_lower
    )
    if relative_match:
        amount = int(relative_match.group(1))
        unit = relative_match.group(2)
        if unit.startswith(("hr", "hour", "ghant")):
            delta = timedelta(hours=amount)
        else:
            delta = timedelta(minutes=amount)
        resolved = now + delta
        return ResolvedTime(
            dt=resolved, needs_confirmation=False,
            reasoning=f"Relative: {amount} {unit} from now",
            source_phrase=original_phrase
        )

    # --- 2. Check for tomorrow / kal indicators ---
    is_tomorrow = False
    tomorrow_patterns = ["tomorrow", "kal", "naale"]  # naale = Kannada for tomorrow
    for tp in tomorrow_patterns:
        if tp in phrase_lower:
            is_tomorrow = True
            break

    # Context indicators for AM/PM from surrounding words
    has_morning = any(w in phrase_lower for w in ["subah", "morning", "beligge", "am"])
    has_evening = any(w in phrase_lower for w in ["shaam", "evening", "sanje", "pm", "raat", "night"])

    # --- 3. Exact time: digits like "10", "10:30", "10 am", "7 pm", "6 baje" ---
    # Using re.search so phrases like "tomorrow at 7 pm" or "subah 10 baje" match
    time_match = re.search(
        r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|baje)?",
        phrase_lower
    )
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or 0)
        ampm = time_match.group(3)

        if ampm == "pm":
            if hour < 12:
                hour += 12
            needs_conf = False
            reasoning = f"Exact time: {hour:02d}:{minute:02d}"
        elif ampm == "am":
            if hour == 12:
                hour = 0
            needs_conf = False
            reasoning = f"Exact time: {hour:02d}:{minute:02d}"
        elif has_evening and hour < 12:
            hour += 12
            needs_conf = False
            reasoning = f"Resolved {hour:02d}:{minute:02d} from evening context"
        elif has_morning:
            if hour == 12:
                hour = 0
            needs_conf = False
            reasoning = f"Resolved {hour:02d}:{minute:02d} from morning context"
        elif not time_match.group(2):
            # Bare number like "6" with no AM/PM
            if hour <= 7:
                hour += 12
                needs_conf = True
                reasoning = f"Guessed PM for bare '{hour-12}' (assumed evening)"
            elif hour >= 9:
                needs_conf = False
                reasoning = f"Assumed AM for '{hour}'"
            else:  # 8
                needs_conf = True
                reasoning = f"Ambiguous: '{hour}' could be AM or PM"
        else:
            needs_conf = False
            reasoning = f"Exact time: {hour:02d}:{minute:02d}"

        resolved_date = reference_date.date()
        if is_tomorrow:
            resolved_date += timedelta(days=1)
        resolved = datetime(
            resolved_date.year, resolved_date.month, resolved_date.day,
            hour, minute, tzinfo=IST
        )
        # If the resolved time is in the past today, push to tomorrow
        if resolved <= now and not is_tomorrow:
            resolved += timedelta(days=1)
            reasoning += "; pushed to tomorrow (was in past)"

        return ResolvedTime(
            dt=resolved, needs_confirmation=needs_conf,
            reasoning=reasoning, source_phrase=original_phrase
        )

    # --- 4. Vague phrase lookup from config (sorted longest phrase first) ---
    sorted_phrases = sorted(time_windows.PHRASE_MAP.keys(), key=len, reverse=True)
    for vague_phrase in sorted_phrases:
        if vague_phrase in phrase_lower:
            h, m = time_windows.PHRASE_MAP[vague_phrase]
            resolved_date = reference_date.date()
            if is_tomorrow or vague_phrase.startswith(("kal ", "tomorrow ")):
                resolved_date += timedelta(days=1)
            resolved = datetime(
                resolved_date.year, resolved_date.month, resolved_date.day,
                h, m, tzinfo=IST
            )
            # If the resolved time is in the past today, push to tomorrow
            if resolved <= now and not is_tomorrow:
                resolved += timedelta(days=1)
                extra = "; pushed to tomorrow (was in past)"
            else:
                extra = ""
            return ResolvedTime(
                dt=resolved, needs_confirmation=True,
                reasoning=f"Vague phrase '{vague_phrase}' -> {h:02d}:{m:02d}{extra}",
                source_phrase=original_phrase
            )

    # --- 5. Fallback: couldn't parse, mark for confirmation ---
    resolved = now + timedelta(hours=1)
    return ResolvedTime(
        dt=resolved, needs_confirmation=True,
        reasoning=f"Could not parse '{original_phrase}', defaulted to 1 hour from now",
        source_phrase=original_phrase
    )


def compute_snooze(current_due: datetime, minutes: int = 10) -> datetime:
    """Compute new due time after snooze."""
    return current_due + timedelta(minutes=minutes)


def compute_next_recurrence(
    task_due: datetime, recurrence: str, now: Optional[datetime] = None
) -> Optional[datetime]:
    """
    Compute next occurrence for recurring tasks.
    Recurrence formats: "daily", "weekly:monday", "weekdays"
    """
    if now is None:
        now = now_ist()
    else:
        now = ensure_ist(now)
    task_due = ensure_ist(task_due)

    if recurrence == "daily":
        next_dt = task_due + timedelta(days=1)
        while next_dt <= now:
            next_dt += timedelta(days=1)
        return next_dt

    if recurrence.startswith("weekly:"):
        day_name = recurrence.split(":")[1].lower()
        target_day = {
            "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
            "friday": 4, "saturday": 5, "sunday": 6,
        }.get(day_name)
        if target_day is None:
            return None
        next_dt = task_due + timedelta(days=1)
        while next_dt.weekday() != target_day or next_dt <= now:
            next_dt += timedelta(days=1)
        return next_dt.replace(
            hour=task_due.hour, minute=task_due.minute,
            second=0, microsecond=0
        )

    if recurrence == "weekdays":
        next_dt = task_due + timedelta(days=1)
        while next_dt.weekday() >= 5 or next_dt <= now:
            next_dt += timedelta(days=1)
        return next_dt

    return None
