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
from agent.resolver import resolve_time
from timeutil import IST, now_ist, to_ist_naive, ensure_ist
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
- If the user asks to remove, cancel, or delete a task (e.g., "remove the meeting", "cancel gym"), call `cancel_task` with `task_id` or `title`.
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


def _is_question(text: str) -> bool:
    """Check if the user input looks like a question."""
    t = text.strip().lower()
    if "?" in t:
        return True
    question_starts = (
        "why", "what", "where", "when", "how", "who", "which", "whose", "whom",
        "can you", "could you", "is it", "are you", "do you", "will you",
        "kyun", "kyu", "kya", "kaise", "kab", "kaha", "kahan",
        "क्यों", "क्या", "कैसे", "कब", "कहाँ", "किस",
        "enu", "yake", "hege", "yelli", "yavaga", "yaru",
        "ಏನು", "ಯಾಕೆ", "ಹೇಗೆ", "ಎಲ್ಲಿ", "ಯಾವಾಗ", "ಯಾರು"
    )
    for q in question_starts:
        if t.startswith(q + " ") or t == q:
            return True
    return False


async def process_turn(
    user_text: str, language: str = "en",
    now: Optional[datetime] = None
) -> dict:
    """
    Process a user turn through the planner agent.
    """
    from providers.registry import registry
    from agent.lang import detect_language

    if not language or language == "en":
        language = detect_language(user_text, fallback="en")

    if now is None:
        now = now_ist()
    else:
        now = ensure_ist(now)

    db = SessionLocal()
    try:
        # Save user utterance
        user_utt = Utterance(role="user", text=user_text, language=language)
        db.add(user_utt)
        db.commit()

        # Check confirmation / undo rule before anything else
        from agent.replan import (
            parse_confirmation_rule, get_pending_plan, set_pending_plan,
            extract_replan_intent, compute_replan
        )
        from agent.replan_engine import apply_replan_commit, apply_replan_undo
        conf_rule = parse_confirmation_rule(user_text)

        if conf_rule == "undo":
            res = apply_replan_undo(db)
            if res.get("ok"):
                if language == "hi":
                    reply_text = "पिछला बदलाव वापस कर दिया गया है।"
                elif language == "kn":
                    reply_text = "ಹಿಂದಿನ ವೇಳಾಪಟ್ಟಿ ಬದಲಾವಣೆಯನ್ನು ರದ್ದುಗೊಳಿಸಲಾಗಿದೆ."
                else:
                    reply_text = "Reverted your last schedule change."
            else:
                if language == "hi":
                    reply_text = "वापस करने के लिए कोई पिछला बदलाव नहीं मिला।"
                elif language == "kn":
                    reply_text = "ರದ್ದುಗೊಳಿಸಲು ಯಾವುದೇ ಹಿಂದಿನ ಬದಲಾವಣೆಗಳಿಲ್ಲ."
                else:
                    reply_text = "Nothing to undo."
            agent_utt = Utterance(role="assistant", text=reply_text, language=language)
            db.add(agent_utt)
            db.commit()
            log_event("agent_reply", reply_text)
            return {"reply_text": reply_text, "task_changes": [], "language": language}

        # Check evening recap command ("end my day", "aaj ka recap", "wrap up", etc.)
        from agent.recap import is_recap_command, build_evening_recap, apply_carryover_to_tomorrow
        if is_recap_command(user_text):
            recap_data = build_evening_recap(db, now=now, language=language)
            reply_text = recap_data["spoken_text"]
            agent_utt = Utterance(role="assistant", text=reply_text, language=language)
            db.add(agent_utt)
            db.commit()
            log_event("agent_reply", reply_text)
            return {
                "reply_text": reply_text,
                "task_changes": [],
                "recap": recap_data,
                "language": language,
            }

        # Check if previous turn was recap offering carryover and user said yes
        last_turn = db.query(Utterance).filter_by(role="assistant").order_by(Utterance.id.desc()).first()
        if last_turn and ("tomorrow morning" in last_turn.text.lower() or "कल सुबह" in last_turn.text or "ನಾಳೆ ಬೆಳಿಗ್ಗೆ" in last_turn.text):
            if conf_rule == "yes":
                res = apply_carryover_to_tomorrow(db, now=now)
                if language == "hi":
                    reply_text = f"छूटे हुए {res['carried_count']} कार्यों को कल सुबह शिफ्ट कर दिया गया है।"
                elif language == "kn":
                    reply_text = f"ತಪ್ಪಿದ {res['carried_count']} ಕಾರ್ಯಗಳನ್ನು ನಾಳೆ ಬೆಳಿಗ್ಗೆ ಸರಿಸಲಾಗಿದೆ."
                else:
                    reply_text = f"Moved {res['carried_count']} missed tasks to tomorrow morning."
                agent_utt = Utterance(role="assistant", text=reply_text, language=language)
                db.add(agent_utt)
                db.commit()
                log_event("agent_reply", reply_text)
                return {
                    "reply_text": reply_text,
                    "task_changes": res.get("carried_tasks", []),
                    "language": language,
                }

        # Check pending replan confirmation (yes / no)
        pending_plan = get_pending_plan()
        if pending_plan and conf_rule in ("yes", "no"):
            if conf_rule == "yes":
                apply_replan_commit(db, pending_plan, reason=pending_plan.reason)
                set_pending_plan(None)
                if language == "hi":
                    reply_text = "शेड्यूल अपडेट कर दिया गया है।"
                elif language == "kn":
                    reply_text = "ನಿಮ್ಮ ವೇಳಾಪಟ್ಟಿಯನ್ನು ನವೀಕರಿಸಲಾಗಿದೆ."
                else:
                    reply_text = "Done, I've updated your schedule."
            else:
                set_pending_plan(None)
                if language == "hi":
                    reply_text = "ठीक है, शेड्यूल पहले जैसा ही रखा गया है।"
                elif language == "kn":
                    reply_text = "ಸರಿ, ವೇಳಾಪಟ್ಟಿಯನ್ನು ಬದಲಾಯಿಸಿಲ್ಲ."
                else:
                    reply_text = "Okay, I kept your schedule as it was."

            agent_utt = Utterance(role="assistant", text=reply_text, language=language)
            db.add(agent_utt)
            db.commit()
            log_event("agent_reply", reply_text)
            return {"reply_text": reply_text, "task_changes": [], "language": language}

        # Check if user requested replan ("push everything by 45 min", "free after 5", "swap invoice and groceries", etc.)
        replan_intent = await extract_replan_intent(user_text, now)
        if replan_intent:
            plan = compute_replan(db, replan_intent, now=now, language=language)
            set_pending_plan(plan)
            reply_text = plan.summary.get(language, plan.summary.get("en", "I'll update your schedule. Okay?"))
            agent_utt = Utterance(role="assistant", text=reply_text, language=language)
            db.add(agent_utt)
            db.commit()
            log_event("agent_reply", reply_text)
            return {
                "reply_text": reply_text,
                "task_changes": [c.to_dict() for c in plan.changes],
                "replan_preview": plan.to_dict(),
                "language": language,
            }

        # FIX D: Deterministic ambiguity check before LLM acts
        from agent.matcher import find_task_by_title
        from agent.replies import format_ambiguous
        text_lower = user_text.lower().strip()
        action_triggers = [
            "cancel", "remove", "delete", "drop", "hata do", "hatao", "hata de",
            "radd karo", "raddu madi", "snooze", "update", "move", "badal do",
            "shift", "postpone", "aage badhao", "talli haaki"
        ]
        found_action = None
        for act in action_triggers:
            if act in text_lower:
                found_action = act
                break
        if found_action:
            target = text_lower.split(found_action, 1)[1].replace("the", "").replace("my", "").replace("karo", "").strip()
            if not target:
                target = text_lower.split(found_action, 1)[0].replace("the", "").replace("my", "").strip()
            if target:
                active_tasks = db.query(Task).filter(
                    Task.status.in_([TaskStatus.SCHEDULED.value, TaskStatus.SNOOZED.value, TaskStatus.DUE.value])
                ).all()
                status, matched_task, candidates = find_task_by_title(db, target, active_tasks=active_tasks, cutoff=0.6, margin=0.1)
                if status == "ambiguous":
                    reply_text = format_ambiguous(candidates, language)
                    agent_utt = Utterance(role="assistant", text=reply_text, language=language)
                    db.add(agent_utt)
                    db.commit()
                    log_event("agent_reply", reply_text)
                    return {
                        "reply_text": reply_text,
                        "task_changes": [{"type": "ambiguous", "candidates": candidates}],
                        "language": language,
                    }

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
        reply_text = ""

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
            reply_text = _generate_confirmation(task_changes, language, now=now)
        else:
            # Check if user asked to cancel/remove and tool wasn't invoked
            text_lower = user_text.lower()
            cancel_triggers = ["cancel", "remove", "delete", "hata do", "hatao", "radd karo", "raddu madi"]
            found_trigger = None
            for trigger in cancel_triggers:
                if trigger in text_lower:
                    found_trigger = trigger
                    break
            if found_trigger:
                target = text_lower.split(found_trigger, 1)[1].replace("the", "").replace("my", "").strip()
                if not target:
                    target = text_lower.split(found_trigger, 1)[0].replace("the", "").replace("my", "").strip()
                change = _handle_cancel_task(db, {"title": target})
                task_changes.append(change)
                reply_text = _generate_confirmation(task_changes, language, now=now)

        # Fallback when no task actions were detected / performed
        if not task_changes or not reply_text:
            text_lower = user_text.lower().strip()
            greetings = ["hello", "hi", "hey", "namaste", "namaskara", "namaskar"]
            is_greeting = any(text_lower == g or text_lower.startswith(g + " ") for g in greetings)
            if is_greeting:
                if language == "hi":
                    reply_text = "नमस्ते! आज की अपनी योजना बताइए, मैं आपके रिमाइंडर सेट कर दूंगा।"
                elif language == "kn":
                    reply_text = "ನಮಸ್ಕಾರ! ಇಂದಿನ ನಿಮ್ಮ ಯೋಜನೆಯನ್ನು ತಿಳಿಸಿ, ನಾನು ರಿಮೈಂಡರ್‌ಗಳನ್ನು ಹೊಂದಿಸುತ್ತೇನೆ."
                else:
                    reply_text = "Namaste! Tell me what you have planned today, and I'll set up your reminders."
            elif _is_question(user_text):
                from agent.replies import format_question_help
                reply_text = format_question_help(language)
            else:
                from agent.replies import format_fallback
                reply_text = format_fallback(language)

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
        last_resolved_dt = None  # anchor for "on the way back"-style vague phrases
        for t_args in tasks_list:
            c = _handle_add_task(db, t_args, now, language, anchor_dt=last_resolved_dt)
            if c:
                items.append(c)
                # Update anchor to the last successfully resolved time
                if c.get("due_at"):
                    from timeutil import ensure_ist
                    try:
                        from datetime import datetime as _dt
                        last_resolved_dt = _dt.fromisoformat(c["due_at"]).replace(tzinfo=IST)
                    except Exception:
                        pass
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


def _handle_add_task(db, args: dict, now: datetime, language: str, anchor_dt: Optional[datetime] = None) -> dict:
    """Create a new task from add_task or add_tasks tool call."""
    title = args.get("title", "Untitled").strip()
    time_phrase = args.get("time_phrase", "in 1 hour")
    recurrence = args.get("recurrence")
    if recurrence in ("none", "null", "", None):
        recurrence = None

    # Resolve time (pass anchor_dt for chaining vague phrases after a prior task)
    resolved = resolve_time(time_phrase, now=now, anchor_dt=anchor_dt)

    # Categorize task
    category = args.get("category")
    if not category:
        from agent.categorize import categorize_by_rules
        category = categorize_by_rules(title) or "other"

    # Check for active learned preference for this category
    from datetime import timedelta
    from agent.stats import get_active_preference
    active_pref = get_active_preference(db, category)
    if active_pref and active_pref.offset_minutes > 0:
        resolved.dt += timedelta(minutes=active_pref.offset_minutes)
        resolved.reasoning += f"; learned preference applied (+{active_pref.offset_minutes}m)"

    # Check for duplicates: same title within 30 minutes
    from sqlalchemy import and_
    resolved_naive = to_ist_naive(resolved.dt)
    existing = db.query(Task).filter(
        and_(
            Task.title.ilike(f"%{title}%"),
            Task.status.in_([TaskStatus.SCHEDULED.value, TaskStatus.SNOOZED.value]),
            Task.due_at.between(resolved_naive - timedelta(minutes=30),
                                resolved_naive + timedelta(minutes=30)),
        )
    ).first()

    if existing:
        logger.info(f"Duplicate detected: '{title}' near {resolved.dt}, updating existing #{existing.id}")
        existing.due_at = resolved_naive
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
        due_at=resolved_naive,
        recurrence=recurrence,
        status=TaskStatus.SCHEDULED.value,
        needs_confirmation=resolved.needs_confirmation,
        source_phrase=resolved.source_phrase,
        resolution_note=resolved.reasoning,
        language=language,
        is_fixed=getattr(resolved, "is_fixed", True),
        duration_minutes=args.get("duration_minutes"),
        category=category,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    log_event("task_created", f"New reminder: {title} at {resolved.dt.strftime('%I:%M %p')}",
              task_id=task.id)

    # Schedule the reminder
    from scheduler import schedule_task_reminder
    schedule_task_reminder(task.id, resolved.dt)

    # Conflict detection
    from agent.conflicts import detect_conflicts
    active_tasks = db.query(Task).filter(
        Task.status.in_([TaskStatus.SCHEDULED.value, TaskStatus.SNOOZED.value, TaskStatus.DUE.value])
    ).all()
    conflicts = detect_conflicts(active_tasks, default_duration_minutes=settings.default_task_duration_minutes)
    conflict = next((c for c in conflicts if c.task_1.id == task.id or c.task_2.id == task.id), None)

    return {
        "type": "created",
        "task_id": task.id,
        "title": title,
        "due_at": resolved.dt.isoformat(),
        "recurrence": recurrence,
        "needs_confirmation": resolved.needs_confirmation,
        "resolution_note": resolved.reasoning,
        "is_fixed": task.is_fixed,
        "duration_minutes": task.duration_minutes,
        "category": task.category,
        "conflict": conflict.to_dict() if conflict else None,
        "conflict_obj": conflict,
    }


def _handle_update_task(db, args: dict, now: datetime) -> dict:
    """Update an existing task."""
    from agent.matcher import find_task_by_title
    task_id = args.get("task_id")
    target_title = (args.get("target_title") or args.get("old_title") or args.get("title") or "").strip()

    active_tasks = db.query(Task).filter(
        Task.status.in_([TaskStatus.SCHEDULED.value, TaskStatus.SNOOZED.value, TaskStatus.DUE.value])
    ).all()

    task = None
    if target_title:
        status, matched, candidates = find_task_by_title(db, target_title, active_tasks=active_tasks, cutoff=0.6, margin=0.1)
        if status == "ambiguous":
            return {
                "type": "update_ambiguous",
                "target": target_title,
                "candidates": candidates,
            }
        elif status == "matched":
            task = matched

    if not task and task_id:
        try:
            task = db.query(Task).filter_by(id=int(task_id)).first()
        except (ValueError, TypeError):
            task = None

    if not task:
        return {"type": "error", "message": f"Task not found"}

    if args.get("new_title"):
        task.title = args["new_title"]

    if args.get("time_phrase"):
        resolved = resolve_time(args["time_phrase"], now=now)
        task.due_at = to_ist_naive(resolved.dt)
        task.needs_confirmation = resolved.needs_confirmation
        task.resolution_note = resolved.reasoning

        from scheduler import schedule_task_reminder
        schedule_task_reminder(task.id, resolved.dt)

    db.commit()
    log_event("task_updated", f"Updated: {task.title}", task_id=task.id)

    # Conflict detection
    from agent.conflicts import detect_conflicts
    active_tasks = db.query(Task).filter(
        Task.status.in_([TaskStatus.SCHEDULED.value, TaskStatus.SNOOZED.value, TaskStatus.DUE.value])
    ).all()
    conflicts = detect_conflicts(active_tasks, default_duration_minutes=settings.default_task_duration_minutes)
    conflict = next((c for c in conflicts if c.task_1.id == task.id or c.task_2.id == task.id), None)

    return {
        "type": "updated",
        "task_id": task.id,
        "title": task.title,
        "due_at": ensure_ist(task.due_at).isoformat() if task.due_at else None,
        "conflict": conflict.to_dict() if conflict else None,
        "conflict_obj": conflict,
    }


def _handle_cancel_task(db, args: dict) -> dict:
    """Cancel a task."""
    from agent.matcher import find_task_by_title
    task_id = args.get("task_id")
    target_title = (args.get("title") or "").strip()

    active_tasks = db.query(Task).filter(
        Task.status.in_([TaskStatus.SCHEDULED.value, TaskStatus.SNOOZED.value, TaskStatus.DUE.value])
    ).all()

    # Prioritize matching target_title if provided (avoids arbitrary LLM task_id on ambiguous queries)
    if target_title:
        status, task, candidates = find_task_by_title(db, target_title, active_tasks=active_tasks, cutoff=0.6, margin=0.1)
        if status == "ambiguous":
            return {
                "type": "cancel_ambiguous",
                "target": target_title,
                "candidates": candidates,
            }
        elif status == "not_found":
            return {
                "type": "cancel_not_found",
                "target": target_title,
                "closest": candidates[0] if candidates else (active_tasks[0].title if active_tasks else None),
            }
    elif task_id:
        try:
            task = db.query(Task).filter_by(id=int(task_id)).first()
            if task and task.status == TaskStatus.CANCELLED.value:
                task = None
        except (ValueError, TypeError):
            task = None
        if not task:
            return {
                "type": "cancel_not_found",
                "target": str(task_id),
                "closest": active_tasks[0].title if active_tasks else None,
            }
    else:
        return {
            "type": "cancel_not_found",
            "target": "",
            "closest": active_tasks[0].title if active_tasks else None,
        }

    task.status = TaskStatus.CANCELLED.value
    db.commit()

    from scheduler import remove_task_job
    remove_task_job(task.id)

    log_event("task_cancelled", f"Cancelled: {task.title}", task_id=task.id)
    return {"type": "cancelled", "task_id": task.id, "title": task.title}


def _generate_confirmation(task_changes: list, language: str, now: Optional[datetime] = None) -> str:
    """Generate a clean, spoken confirmation sentence in the user's language."""
    from agent.replies import (
        format_created, format_cancelled, format_cancel_not_found,
        format_fallback, format_ambiguous
    )
    if not task_changes:
        return format_fallback(language)

    # Check for ambiguity first!
    ambig_changes = [c for c in task_changes if c.get("type") in ("cancel_ambiguous", "update_ambiguous", "ambiguous")]
    if ambig_changes:
        return format_ambiguous(ambig_changes[0].get("candidates", []), language)

    # Check for cancel actions
    cancel_changes = [c for c in task_changes if c.get("type") in ("cancelled", "cancel_not_found")]
    if cancel_changes:
        c = cancel_changes[0]
        if c.get("type") == "cancelled":
            return format_cancelled(c.get("title", "Task"), language)
        else:
            return format_cancel_not_found(c.get("closest"), language)

    # Check for clarification
    clarifications = [c for c in task_changes if c.get("type") == "clarification"]
    if clarifications:
        return clarifications[0].get("question", "")

    # Check for conflict warning
    conflict_change = next((c for c in task_changes if c.get("conflict_obj")), None)
    if conflict_change and conflict_change.get("conflict_obj"):
        from agent.conflicts import format_conflict_sentence
        return format_conflict_sentence(conflict_change["conflict_obj"], language=language, now=now)

    return format_created(task_changes, language, now=now)
