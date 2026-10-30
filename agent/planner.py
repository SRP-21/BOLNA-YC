"""
Planner agent: LLM with tool calling for task management.
Keeps prompts small (only today's pending + last 3-4 turns).
Mirrors user's language, confirms in one spoken sentence.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from db import SessionLocal, Task, Utterance, TaskStatus
from agent.tools import TOOLS
from agent.resolver import resolve_time, IST
from events import log_event
from config import settings

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are a warm, efficient daily planner voice assistant. You help users manage their day through voice.

CRITICAL INSTRUCTIONS:
- Whenever the user lists tasks, plans, or things to do (e.g., "standup at 10, send invoice before lunch, gym around 6, groceries on the way back"), you MUST call `add_tasks` with ALL of the tasks in the `tasks` array.
- For each task, extract:
  * `title`: short title in the user's language (e.g. "Standup", "Send invoice", "Gym", "Groceries")
  * `time_phrase`: the time expression spoken (e.g. "10", "before lunch", "around 6", "on the way back")
- Omit `recurrence` for regular one-time tasks.
- If the user is just saying hello or greeting without tasks ("Hello", "Hi, can you help me?"), do NOT call add_tasks. Greet them warmly and ask what they would like to plan.
- If the user is correcting an existing task ("gym at 6, no, 7"), call `update_task`.
- Mirror the user's language (English, Hindi, Hinglish, Kannada-English mix).
"""


def _get_context(db, now: datetime) -> str:
    """Build minimal context: today's pending tasks + current time."""
    tasks = db.query(Task).filter(
        Task.status.in_([TaskStatus.SCHEDULED.value, TaskStatus.SNOOZED.value, TaskStatus.DUE.value]),
    ).order_by(Task.due_at).all()

    if not tasks:
        return f"Current time: {now.strftime('%I:%M %p, %A %d %B %Y')} (Asia/Kolkata)\nNo active tasks scheduled yet."

    task_lines = []
    for t in tasks:
        status_note = f" [NEEDS CONFIRMATION]" if t.needs_confirmation else ""
        due_str = t.due_at.strftime('%I:%M %p') if t.due_at else "?"
        rec = f" (recurring: {t.recurrence})" if t.recurrence else ""
        task_lines.append(f"  #{t.id}: {t.title} at {due_str}{rec}{status_note} — status: {t.status}")

    return (
        f"Current time: {now.strftime('%I:%M %p, %A %d %B %Y')} (Asia/Kolkata)\n"
        f"Today's active tasks:\n" + "\n".join(task_lines)
    )


def _get_recent_turns(db, limit: int = 4) -> list[dict]:
    """Get last N conversation turns for context."""
    utterances = db.query(Utterance).order_by(
        Utterance.ts.desc()
    ).limit(limit).all()

    turns = []
    for u in reversed(utterances):
        role = "assistant" if u.role in ("assistant", "agent") else "user"
        turns.append({
            "role": role,
            "content": u.text,
        })
    return turns


async def process_turn(
    user_text: str, language: str = "en",
    now: Optional[datetime] = None
) -> dict:
    """
    Process a user turn through the planner agent.
    """
    from providers.registry import registry

    if now is None:
        now = datetime.now(IST)

    db = SessionLocal()
    try:
        # Save user utterance
        user_utt = Utterance(role="user", text=user_text, language=language)
        db.add(user_utt)
        db.commit()

        # Build messages
        context = _get_context(db, now)
        recent_turns = _get_recent_turns(db, limit=4)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT + "\n\n" + context},
        ]
        for t in recent_turns[:-1]:
            messages.append(t)
        messages.append({"role": "user", "content": user_text})

        # Call LLM with tools
        response = await registry.llm.chat(messages, tools=TOOLS)

        task_changes = []
        reply_text = response.get("content") or ""

        # Process tool calls
        if response.get("tool_calls"):
            for tc in response["tool_calls"]:
                change = await _execute_tool(db, tc, now, language)
                if change:
                    if change.get("type") == "batch_created":
                        task_changes.extend(change.get("items", []))
                    else:
                        task_changes.append(change)

            # Generate natural spoken confirmation
            reply_text = _generate_confirmation(task_changes, language)

        # Fallback for conversational turns when no tools were called
        if not reply_text:
            text_lower = user_text.lower()
            if any(w in text_lower for w in ["hello", "hi", "hey", "help", "kya kar sakte ho", "namaste"]):
                reply_text = "Namaste! Tell me what you have planned today, and I'll set up your reminders."
            else:
                reply_text = "I'm listening. Tell me what tasks you'd like to schedule!"

        # Save agent utterance
        agent_utt = Utterance(role="assistant", text=reply_text, language=language)
        db.add(agent_utt)
        db.commit()

        log_event("agent_reply", reply_text)

        return {
            "reply_text": reply_text,
            "task_changes": task_changes,
            "language": language,
        }
    finally:
        db.close()


async def _execute_tool(db, tool_call: dict, now: datetime, language: str) -> Optional[dict]:
    """Execute a single tool call and return the result."""
    name = tool_call["name"]
    args = tool_call["arguments"]

    if name == "add_tasks":
        tasks_list = args.get("tasks") or []
        items = []
        for t_args in tasks_list:
            c = _handle_add_task(db, t_args, now, language)
            if c:
                items.append(c)
        return {"type": "batch_created", "items": items}
    elif name == "add_task":
        return _handle_add_task(db, args, now, language)
    elif name == "update_task":
        return _handle_update_task(db, args, now)
    elif name == "cancel_task":
        return _handle_cancel_task(db, args)
    elif name == "ask_clarification":
        return {"type": "clarification", "question": args.get("question", "")}

    logger.warning(f"Unknown tool: {name}")
    return None


def _handle_add_task(db, args: dict, now: datetime, language: str) -> dict:
    """Create a new task from add_task or add_tasks tool call."""
    title = args.get("title", "Untitled").strip()
    time_phrase = args.get("time_phrase", "in 1 hour")
    recurrence = args.get("recurrence")
    if recurrence in ("none", "null", "", None):
        recurrence = None

    # Resolve time
    resolved = resolve_time(time_phrase, now=now)

    # Check for duplicates: same title within 30 minutes
    from sqlalchemy import and_
    from datetime import timedelta
    existing = db.query(Task).filter(
        and_(
            Task.title.ilike(f"%{title}%"),
            Task.status.in_([TaskStatus.SCHEDULED.value, TaskStatus.SNOOZED.value]),
            Task.due_at.between(resolved.dt - timedelta(minutes=30),
                                resolved.dt + timedelta(minutes=30)),
        )
    ).first()

    if existing:
        logger.info(f"Duplicate detected: '{title}' near {resolved.dt}, updating existing #{existing.id}")
        existing.due_at = resolved.dt
        existing.resolution_note = resolved.reasoning
        existing.needs_confirmation = resolved.needs_confirmation
        db.commit()
        log_event("task_updated", f"Updated duplicate: {title} -> {resolved.dt.strftime('%I:%M %p')}",
                  task_id=existing.id)
        return {
            "type": "updated_duplicate",
            "task_id": existing.id,
            "title": title,
            "due_at": resolved.dt.isoformat(),
            "needs_confirmation": resolved.needs_confirmation,
            "resolution_note": resolved.reasoning,
        }

    task = Task(
        title=title,
        due_at=resolved.dt,
        recurrence=recurrence,
        status=TaskStatus.SCHEDULED.value,
        needs_confirmation=resolved.needs_confirmation,
        source_phrase=resolved.source_phrase,
        resolution_note=resolved.reasoning,
        language=language,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    log_event("task_created", f"New reminder: {title} at {resolved.dt.strftime('%I:%M %p')}",
              task_id=task.id)

    # Schedule the reminder
    from scheduler import schedule_task_reminder
    schedule_task_reminder(task.id, resolved.dt)

    return {
        "type": "created",
        "task_id": task.id,
        "title": title,
        "due_at": resolved.dt.isoformat(),
        "recurrence": recurrence,
        "needs_confirmation": resolved.needs_confirmation,
        "resolution_note": resolved.reasoning,
    }


def _handle_update_task(db, args: dict, now: datetime) -> dict:
    """Update an existing task."""
    task_id = args.get("task_id")
    task = db.query(Task).filter_by(id=task_id).first()
    if not task:
        return {"type": "error", "message": f"Task #{task_id} not found"}

    if args.get("title"):
        task.title = args["title"]
    if args.get("time_phrase"):
        resolved = resolve_time(args["time_phrase"], now=now)
        task.due_at = resolved.dt
        task.needs_confirmation = resolved.needs_confirmation
        task.resolution_note = resolved.reasoning

        from scheduler import schedule_task_reminder
        schedule_task_reminder(task.id, resolved.dt)

    db.commit()
    log_event("task_updated", f"Updated: {task.title}", task_id=task.id)

    return {
        "type": "updated",
        "task_id": task.id,
        "title": task.title,
        "due_at": task.due_at.isoformat(),
    }


def _handle_cancel_task(db, args: dict) -> dict:
    """Cancel a task."""
    task_id = args.get("task_id")
    task = db.query(Task).filter_by(id=task_id).first()
    if not task:
        return {"type": "error", "message": f"Task #{task_id} not found"}

    task.status = TaskStatus.CANCELLED.value
    db.commit()

    from scheduler import remove_task_job
    remove_task_job(task.id)

    log_event("task_cancelled", f"Cancelled: {task.title}", task_id=task.id)
    return {"type": "cancelled", "task_id": task.id, "title": task.title}


def _generate_confirmation(task_changes: list, language: str) -> str:
    """Generate a clean, spoken confirmation sentence."""
    created = [c for c in task_changes if c.get("type") == "created"]
    updated = [c for c in task_changes if c.get("type") in ("updated", "updated_duplicate")]

    if not created and not updated:
        return "I've noted that."

    summaries = []
    for c in created:
        from datetime import datetime as dt
        due = dt.fromisoformat(c["due_at"])
        summaries.append(f"{c['title']} at {due.strftime('%I:%M %p')}")

    for c in updated:
        from datetime import datetime as dt
        due = dt.fromisoformat(c["due_at"])
        summaries.append(f"{c['title']} moved to {due.strftime('%I:%M %p')}")

    count = len(created) + len(updated)
    return f"Got it, {count} reminder{'s' if count > 1 else ''} set: {', '.join(summaries)}."
