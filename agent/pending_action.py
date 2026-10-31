"""
Pending single-task confirmation state for destructive actions.
Stores {action, task_id, title, language, created_at} with a 60-second expiration.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from timeutil import ensure_ist, now_ist

@dataclass
class PendingAction:
    action: str  # e.g. "cancel" or "move_to_tomorrow"
    task_id: int
    title: str
    language: str
    created_at: datetime  # IST aware datetime
    target_dt: Optional[datetime] = None


_current_pending_action: Optional[PendingAction] = None


def get_pending_action(now: Optional[datetime] = None) -> Optional[PendingAction]:
    """Return active pending action if not expired (60s limit)."""
    global _current_pending_action
    if _current_pending_action is None:
        return None

    ref_now = ensure_ist(now) if now is not None else now_ist()
    age_seconds = (ref_now - _current_pending_action.created_at).total_seconds()
    if age_seconds > 60:
        _current_pending_action = None
        return None

    return _current_pending_action


def set_pending_action(action: Optional[PendingAction]):
    """Set or clear the active pending action."""
    global _current_pending_action
    _current_pending_action = action


def clear_pending_action():
    """Clear active pending action."""
    global _current_pending_action
    _current_pending_action = None
