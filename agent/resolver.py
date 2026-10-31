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

WORD_NUMS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}


def normalize_time_phrase(phrase: str) -> str:
    """Normalize Whisper time transcriptions (e.g., '5 p.m.', '6 o'clock', 'half past 5', 'five pm')
    into standard clean time expressions before resolution."""
    if not phrase:
        return ""
    p = phrase.strip()

    # 1. Normalize p.m. / a.m. with optional spaces or dots
    p = re.sub(r"(?i)\bp\.?\s*m\.?", "pm", p)
    p = re.sub(r"(?i)\ba\.?\s*m\.?", "am", p)

    # 2. Time of day expressions
    p = re.sub(r"(?i)\bin\s+the\s+evening\b", "pm", p)
    p = re.sub(r"(?i)\bin\s+the\s+morning\b", "am", p)
    p = re.sub(r"(?i)\bin\s+the\s+afternoon\b", "pm", p)
    p = re.sub(r"(?i)\bat\s+night\b", "pm", p)

    # 3. Normalize o'clock / oclock
    p = re.sub(r"(?i)\b(?:o'\s*clock|oclock|o’\s*clock)\b", "", p)

    # 4. Half past / quarter past / quarter to
    def repl_half_past(m):
        raw_h = m.group(1).lower()
        h = WORD_NUMS.get(raw_h, raw_h)
        suffix = f" {m.group(2)}" if m.group(2) else ""
        return f"{h}:30{suffix}"

    p = re.sub(r"(?i)\bhalf\s+past\s+(\w+)(?:\s+(pm|am))?", repl_half_past, p)

    def repl_quarter_past(m):
        raw_h = m.group(1).lower()
        h = WORD_NUMS.get(raw_h, raw_h)
        suffix = f" {m.group(2)}" if m.group(2) else ""
        return f"{h}:15{suffix}"

    p = re.sub(r"(?i)\bquarter\s+past\s+(\w+)(?:\s+(pm|am))?", repl_quarter_past, p)

    def repl_quarter_to(m):
        raw_h = m.group(1).lower()
        h = int(WORD_NUMS.get(raw_h, raw_h))
        prev_h = 12 if h == 1 else h - 1
        suffix = f" {m.group(2)}" if m.group(2) else ""
        return f"{prev_h}:45{suffix}"

    p = re.sub(r"(?i)\bquarter\s+to\s+(\w+)(?:\s+(pm|am))?", repl_quarter_to, p)

    # 5. Spoken number words before am/pm or standalone hour
    def repl_word_num(m):
        w = m.group(1).lower()
        num = WORD_NUMS.get(w)
        if num is not None:
            rest = m.group(2) or ""
            return f"{num}{rest}"
        return m.group(0)

    p = re.sub(
        r"(?i)\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b(\s*(?:am|pm))?",
        repl_word_num,
        p,
    )

    return re.sub(r"\s+", " ", p).strip()


class ResolvedTime:
    def __init__(self, dt: datetime, needs_confirmation: bool = False,
                 reasoning: str = "", source_phrase: str = "", is_fixed: bool = True):
        self.dt = dt
        self.needs_confirmation = needs_confirmation
        self.reasoning = reasoning
        self.source_phrase = source_phrase
        self.is_fixed = is_fixed

    def to_dict(self):
        return {
            "due_at": self.dt.isoformat(),
            "needs_confirmation": self.needs_confirmation,
            "resolution_note": self.reasoning,
            "source_phrase": self.source_phrase,
            "is_fixed": self.is_fixed,
        }


def resolve_time(
    phrase: str,
    now: Optional[datetime] = None,
    reference_date: Optional[datetime] = None,
    anchor_dt: Optional[datetime] = None,
) -> ResolvedTime:
    """
    Resolve a time phrase to a datetime in IST.

    Args:
        phrase: The time expression (e.g., "10 am", "before lunch", "kal subah", "in an hour")
        now: Current time (injectable for testing). Defaults to real now in IST.
        reference_date: Base date for resolution. Defaults to today.
        anchor_dt: Optional anchor time from a prior task in the same utterance.
                   Used when the phrase cannot be resolved: falls back to anchor+60 min
                   (rather than now+1 hour) and sets needs_confirmation=True.

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
    if anchor_dt is not None:
        anchor_dt = ensure_ist(anchor_dt)

    phrase = normalize_time_phrase(phrase)
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
            source_phrase=original_phrase,
            is_fixed=True
        )

    # --- 2. Check for tomorrow / kal indicators ---
    is_tomorrow = False
    tomorrow_patterns = ["tomorrow", "kal", "naale", "कल", "ನಾಳೆ"]  # naale / ನಾಳೆ = Kannada for tomorrow
    for tp in tomorrow_patterns:
        if tp in phrase_lower:
            is_tomorrow = True
            break

    is_today = any(w in phrase_lower for w in ["today", "aaj", "आज", "indu", "ಇಂದು"])

    # Context indicators for AM/PM from surrounding words
    has_morning = any(w in phrase_lower for w in ["subah", "morning", "beligge", "am", "सुबह", "ಬೆಳಿಗ್ಗೆ"])
    has_evening = any(w in phrase_lower for w in ["shaam", "evening", "sanje", "pm", "raat", "night", "शाम", "रात", "ಸಂಜೆ", "ರಾತ್ರಿ"])

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
            # Bare number like "6" with no AM/PM (resolved to AM/PM without guess note or confirmation badge)
            if hour <= 7:
                hour += 12
                needs_conf = False
                reasoning = f"Resolved {hour:02d}:00 (assumed evening PM)"
            elif hour >= 9:
                needs_conf = False
                reasoning = f"Resolved {hour:02d}:00 (assumed morning AM)"
            else:  # 8
                needs_conf = False
                reasoning = f"Resolved {hour:02d}:00 (assumed morning AM)"
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
        # If the resolved time is in the past today, push to tomorrow (unless explicitly marked today)
        if resolved <= now and not is_tomorrow and not is_today:
            resolved += timedelta(days=1)
            reasoning += "; pushed to tomorrow (was in past)"

        is_approx = any(w in phrase_lower for w in ["around", "approx", "about", "lagbhag", "sumaru", "hathira", "samay", "kareeb", "karib"])
        is_fixed = not is_approx

        return ResolvedTime(
            dt=resolved, needs_confirmation=needs_conf,
            reasoning=reasoning, source_phrase=original_phrase,
            is_fixed=is_fixed
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
                source_phrase=original_phrase,
                is_fixed=False
            )

    # --- 5. Fallback: couldn't parse, mark for confirmation ---
    # If a prior task in the same utterance was resolved, chain 60 min after it.
    # Otherwise fall back to now + 1 hour.
    if anchor_dt is not None:
        resolved = ensure_ist(anchor_dt) + timedelta(hours=1)
        reasoning = (
            f"Could not parse '{original_phrase}'; "
            f"scheduled 60 min after previous task at "
            f"{ensure_ist(anchor_dt).strftime('%I:%M %p')}"
        )
    else:
        resolved = now + timedelta(hours=1)
        reasoning = f"Could not parse '{original_phrase}', defaulted to 1 hour from now"
    return ResolvedTime(
        dt=resolved, needs_confirmation=True,
        reasoning=reasoning,
        source_phrase=original_phrase,
        is_fixed=False
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
