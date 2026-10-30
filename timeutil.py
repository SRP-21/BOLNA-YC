"""
Timezone utilities and conventions.

CONVENTION:
- Task.due_at is stored in SQLite as NAIVE IST (Asia/Kolkata) wall-clock time.
- Task.created_at, Task.updated_at, Event.ts, and Utterance.ts are stored as UTC.
- Use now_ist() for the current time in IST (timezone-aware).
- Use to_ist_naive(dt) when writing due_at to the database.
- Use ensure_ist(dt) when reading due_at from the database or preparing it for scheduler/comparison.
"""
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo
from config import settings

IST = ZoneInfo(settings.default_timezone)


def now_ist() -> datetime:
    """Return the current time in IST (timezone-aware)."""
    return datetime.now(IST)


def to_ist_naive(dt: Optional[datetime]) -> Optional[datetime]:
    """
    Convert any datetime (aware UTC, aware IST, or naive IST) to naive IST wall-clock time.
    If naive, assumes it is already IST wall-clock time and returns it naive.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    # If timezone-aware, convert to IST then remove tzinfo
    return dt.astimezone(IST).replace(tzinfo=None)


def ensure_ist(dt: Optional[datetime]) -> Optional[datetime]:
    """
    Ensure a datetime is timezone-aware in IST.
    If naive, attaches the IST timezone.
    If aware, converts to IST timezone.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=IST)
    return dt.astimezone(IST)


HI_WEEKDAYS = {
    "Monday": "सोमवार", "Tuesday": "मंगलवार", "Wednesday": "बुधवार",
    "Thursday": "गुरुवार", "Friday": "शुक्रवार", "Saturday": "शनिवार", "Sunday": "रविवार"
}
KN_WEEKDAYS = {
    "Monday": "ಸೋಮವಾರ", "Tuesday": "ಮಂಗಳವಾರ", "Wednesday": "ಬುಧವಾರ",
    "Thursday": "ಗುರುವಾರ", "Friday": "ಶುಕ್ರವಾರ", "Saturday": "ಶನಿವಾರ", "Sunday": "ಭಾನುವಾರ"
}


def format_when(dt: Optional[datetime], now: Optional[datetime] = None, language: str = "en") -> str:
    """
    Format a datetime relative to `now`:
    - 'today at 7:00 PM'
    - 'tomorrow at 9:00 AM'
    - 'Monday at 10:00 AM' (for dates within 7 days)
    - Full date for >= 7 days or past dates (e.g. 'Nov 12 at 7:00 PM')
    """
    if dt is None:
        return "now"

    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    if isinstance(now, str):
        now = datetime.fromisoformat(now)

    dt_ist = ensure_ist(dt)
    now_ist_dt = ensure_ist(now) if now is not None else now_ist()

    # Format time without leading zero: e.g. "7:00 PM" or "10:30 AM"
    time_str = dt_ist.strftime('%I:%M %p').lstrip('0')

    days_diff = (dt_ist.date() - now_ist_dt.date()).days

    if days_diff == 0:
        if language == "hi":
            return f"आज {time_str} बजे"
        elif language == "kn":
            return f"ಇಂದು {time_str} ಕ್ಕೆ"
        return f"today at {time_str}"

    if days_diff == 1:
        if language == "hi":
            return f"कल {time_str} बजे"
        elif language == "kn":
            return f"ನಾಳೆ {time_str} ಕ್ಕೆ"
        return f"tomorrow at {time_str}"

    if 1 < days_diff < 7:
        weekday_en = dt_ist.strftime("%A")
        if language == "hi":
            weekday_hi = HI_WEEKDAYS.get(weekday_en, weekday_en)
            return f"{weekday_hi} को {time_str} बजे"
        elif language == "kn":
            weekday_kn = KN_WEEKDAYS.get(weekday_en, weekday_en)
            return f"{weekday_kn} {time_str} ಕ್ಕೆ"
        return f"{weekday_en} at {time_str}"

    # >= 7 days or past
    if language == "hi":
        return f"{dt_ist.strftime('%d %B')} को {time_str} बजे"
    elif language == "kn":
        return f"{dt_ist.strftime('%d %B')} {time_str} ಕ್ಕೆ"
    return f"{dt_ist.strftime('%b %d')} at {time_str}"
