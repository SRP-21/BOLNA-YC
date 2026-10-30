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
