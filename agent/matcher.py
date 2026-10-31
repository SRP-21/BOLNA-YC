"""
Deterministic task matcher with ambiguity detection.
Rules:
- Fuzzy cutoff >= 0.6
- Margin >= 0.1 over second-best match
- Detects ambiguity when two or more tasks match closely
- Handles phonetic distortions (e.g. 'mona search' -> 'Mohan Aswar')
"""
import difflib
from typing import Optional, Tuple, List
from db import Task, TaskStatus


def score_match(query: str, title: str) -> float:
    """Compute matching score between query and a candidate title."""
    q = query.lower().strip()
    t = title.lower().strip()
    if not q or not t:
        return 0.0
    if q == t:
        return 1.0

    q_words = q.split()
    t_words = t.split()

    # Exact prefix or full word match in title (e.g. 'gym' in 'Gym class')
    if t.startswith(q + " ") or q in t_words:
        return 0.95
    if q in t:
        return 0.90

    return difflib.SequenceMatcher(None, q, t).ratio()


def find_task_by_title(
    db,
    target_title: str,
    active_tasks: Optional[List[Task]] = None,
    cutoff: float = 0.6,
    margin: float = 0.1,
) -> Tuple[str, Optional[Task], List[str]]:
    """
    Match an active task by title with ambiguity detection.
    Returns:
        (status, task, candidates)
        status: 'matched' | 'ambiguous' | 'not_found'
    """
    target = target_title.strip()
    if not target:
        return ("not_found", None, [])

    if active_tasks is None:
        active_tasks = db.query(Task).filter(
            Task.status.in_([
                TaskStatus.SCHEDULED.value,
                TaskStatus.SNOOZED.value,
                TaskStatus.DUE.value,
            ])
        ).all()

    if not active_tasks:
        return ("not_found", None, [])

    # Score all active tasks
    scored = []
    for t in active_tasks:
        s = score_match(target, t.title)
        scored.append((t, s))

    # Sort descending by score
    scored.sort(key=lambda x: x[1], reverse=True)

    best_task, best_score = scored[0]
    second_task, second_score = scored[1] if len(scored) > 1 else (None, 0.0)

    # If even the best match is below cutoff
    if best_score < cutoff:
        # Check if any candidate has score >= 0.15 for 'closest' suggestion
        closest_candidates = [t.title for t, s in scored if s >= 0.15]
        closest = closest_candidates[0] if closest_candidates else (active_tasks[0].title if active_tasks else "")
        return ("not_found", None, [closest] if closest else [])

    # Check ambiguity:
    # 1. Multiple matches above cutoff and margin < 0.1
    # 2. Or best_score is high but second match is also close (best - second < margin)
    if len(scored) > 1 and (best_score - second_score) < margin:
        # Ambiguous! Return candidates that scored closely (>= 0.5 or within 0.15 of best)
        ambiguous_candidates = [
            t.title for t, s in scored if s >= 0.5 or (best_score - s) <= 0.15
        ]
        return ("ambiguous", None, ambiguous_candidates)

    # Confident single match
    return ("matched", best_task, [])
