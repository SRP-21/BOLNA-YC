"""
Pending choice state for ambiguity resolution.
Stores {action, candidate_task_ids, language, created_at} with a 60-second expiration.
Resolves the next utterance by title or ordinal and executes the originally requested action.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any
import re
from db import Task, TaskStatus
from timeutil import ensure_ist, now_ist
from agent.matcher import score_match


@dataclass
class PendingChoice:
    action: str  # "cancel", "done", "snooze", "move"
    candidate_task_ids: List[int]
    language: str
    created_at: datetime  # IST aware datetime
    extra_data: Optional[Dict[str, Any]] = None


_current_pending_choice: Optional[PendingChoice] = None


def get_pending_choice(now: Optional[datetime] = None) -> Optional[PendingChoice]:
    """Return active pending choice if not expired (60s limit)."""
    global _current_pending_choice
    if _current_pending_choice is None:
        return None

    ref_now = ensure_ist(now) if now is not None else now_ist()
    age_seconds = (ref_now - _current_pending_choice.created_at).total_seconds()
    if age_seconds > 60:
        _current_pending_choice = None
        return None

    return _current_pending_choice


def set_pending_choice(choice: Optional[PendingChoice]):
    """Set or clear active pending choice."""
    global _current_pending_choice
    _current_pending_choice = choice


def clear_pending_choice():
    """Clear active pending choice."""
    global _current_pending_choice
    _current_pending_choice = None


ORDINAL_MAP = {
    # 1st
    1: {
        "1", "1st", "first", "the first", "the first one", "first one", "former",
        "pehla", "pehli", "pehla wala", "pehle wala", "पहला", "पहली", "पहले वाला", "पहला वाला",
        "modalane", "modalaneyadu", "modalne", "ಮೊದಲನೆಯದು", "ಮೊದಲನೆ"
    },
    # 2nd
    2: {
        "2", "2nd", "second", "the second", "the second one", "second one", "latter",
        "doosra", "doosri", "dusra", "dusri", "doosra wala", "dusra wala", "doosre wala",
        "दूसरा", "दूसरी", "दूसरे वाला", "दूसरा वाला",
        "eradane", "eradaneyadu", "eradne", "ಎರಡನೆಯದು", "ಎರಡನೆ"
    },
    # 3rd
    3: {
        "3", "3rd", "third", "the third", "the third one", "third one",
        "teesra", "teesri", "teesra wala", "तीसरा", "तीसरी",
        "moorane", "mooraneyadu", "ಮೂರನೆಯದು", "ಮೂರನೆ"
    }
}


def resolve_candidate_choice(db, user_text: str, candidate_task_ids: List[int], language: str = "en") -> Optional[Task]:
    """
    Resolve utterance by ordinal or title match against candidate task IDs.
    Returns the chosen Task if matched, else None.
    """
    t_clean = user_text.strip().lower()
    t_clean_nopunct = re.sub(r"[^\w\s]", "", t_clean).strip()

    # Fetch active candidate tasks in order
    tasks = []
    for tid in candidate_task_ids:
        task = db.query(Task).filter_by(id=tid).first()
        if task and task.status in (TaskStatus.SCHEDULED.value, TaskStatus.SNOOZED.value, TaskStatus.DUE.value):
            tasks.append(task)

    if not tasks:
        return None

    # 1. Check ordinal
    for ordinal_idx, triggers in ORDINAL_MAP.items():
        if t_clean in triggers or t_clean_nopunct in triggers:
            target_idx = ordinal_idx - 1
            if 0 <= target_idx < len(tasks):
                return tasks[target_idx]

    # 2. Check title matching
    best_task = None
    best_score = 0.0
    second_score = 0.0

    for task in tasks:
        score = score_match(t_clean, task.title)
        if score > best_score:
            second_score = best_score
            best_score = score
            best_task = task
        elif score > second_score:
            second_score = score

    if best_task and best_score >= 0.6 and (best_score - second_score) >= 0.05:
        return best_task

    return None
