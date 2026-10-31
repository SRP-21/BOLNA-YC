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


DESTRUCTIVE_STEMS = [
    # English
    "cancel", "remove", "delete", "drop", "scrap", "get rid of",
    # Hindi stems
    "हटा", "रद्द", "कैंसिल", "hata", "radd",
    # Kannada stems
    "ರದ್ದು", "ತೆಗೆ",
]


def has_destructive_command(text: str) -> bool:
    """Match command words by stems across English, Hindi, Hinglish, and Kannada."""
    import re
    t = text.strip().lower()

    # Indic stems (Devanagari and Kannada)
    indic_stems = ["हटा", "रद्द", "कैंसिल", "ರದ್ದು", "ತೆಗೆ"]
    for stem in indic_stems:
        if stem in text:
            return True

    # Latin stems
    if re.search(r'\b(cancel\w*|remov\w*|delet\w*|drop\w*|scrap\w*|get\s+rid\s+of|hata\w*|radd\w*)', t):
        return True

    # forget about (only with a task title, not with it/this/that)
    if re.search(r'\bforget\s+about\s+(?:the\s+|my\s+)?(?!it\b|this\b|that\b)\w+', t):
        return True

    # Special rule for 'clear': only destructive if followed by a task title (e.g. 'clear gym')
    if re.search(r'\bclear\s+(?:the\s+|my\s+)?(?!all\b|everything\b|screen\b|schedule\b|it\b|this\b|that\b)\w+', t):
        return True

    return False


def _is_question(text: str) -> bool:
    """Check if the user input looks like a question in en, hi, kn."""
    import re
    t = text.strip().lower()
    if "?" in t:
        return True
    question_starts = (
        "why", "what", "where", "when", "how", "who", "which", "whose", "whom",
        "can you", "could you", "would you", "is it", "are you", "do you", "will you",
        "kyun", "kyu", "kya", "kaise", "kab", "kaha", "kahan",
        "क्यों", "क्या", "कैसे", "कब", "कहाँ", "किस",
        "enu", "yake", "eke", "hege", "yelli", "yavaga", "yaru",
        "ಏನು", "ಯಾಕೆ", "ಏಕೆ", "ಹೇಗೆ", "ಎಲ್ಲಿ", "ಯಾವಾಗ", "ಯಾರು"
    )
    for q in question_starts:
        if t.startswith(q + " ") or t == q:
            return True

    # Check for question words occurring anywhere in the text (e.g. "yeh abhi bhi kyun hai", "idu innu yake ide")
    inner_words = set(re.findall(r'[\w\u0900-\u097F\u0C80-\u0CFF]+', t))
    inner_question_words = {
        "why", "what", "where", "when", "how",
        "kyun", "kyu", "kya", "kaise",
        "क्यों", "क्या", "कैसे",
        "yake", "eke", "enu", "hege",
        "ಯಾಕೆ", "ಏಕೆ", "ಏನು", "ಹೇಗೆ"
    }
    if inner_words & inner_question_words:
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

        # Check pending choice state (ambiguity follow-up)
        from agent.pending_choice import (
            get_pending_choice, clear_pending_choice, set_pending_choice, resolve_candidate_choice
        )
        pending_ch = get_pending_choice(now=now)
        if pending_ch:
            chosen_task = resolve_candidate_choice(db, user_text, pending_ch.candidate_task_ids, language)
            if chosen_task:
                resp_lang = language if language != "en" else (pending_ch.language or "en")
                clear_pending_choice()
                if pending_ch.action == "cancel":
                    if chosen_task.status == TaskStatus.CANCELLED.value:
                        from agent.replies import format_already_cancelled
                        reply_text = format_already_cancelled(chosen_task.title, resp_lang)
                        changes = []
                    elif chosen_task.status == TaskStatus.DONE.value:
                        from agent.replies import format_already_done
                        reply_text = format_already_done(chosen_task.title, resp_lang)
                        changes = []
                    else:
                        chosen_task.status = TaskStatus.CANCELLED.value
                        db.commit()
                        from scheduler import remove_task_job
                        remove_task_job(chosen_task.id)
                        log_event("task_cancelled", f"Cancelled: {chosen_task.title}", task_id=chosen_task.id)
                        from agent.replies import format_cancelled
                        reply_text = format_cancelled(chosen_task.title, resp_lang)
                        changes = [{"type": "cancelled", "title": chosen_task.title}]
                elif pending_ch.action == "done":
                    chosen_task.status = TaskStatus.DONE.value
                    db.commit()
                    from scheduler import remove_task_job
                    remove_task_job(chosen_task.id)
                    log_event("task_done", f"Done: {chosen_task.title}", task_id=chosen_task.id)
                    from agent.replies import format_done
                    reply_text = format_done(chosen_task.title, resp_lang)
                    changes = [{"type": "done", "title": chosen_task.title}]
                else:
                    reply_text = "Updated."
                    changes = []

                agent_utt = Utterance(role="assistant", text=reply_text, language=resp_lang)
                db.add(agent_utt)
                db.commit()
                log_event("agent_reply", reply_text)
                return {"reply_text": reply_text, "task_changes": changes, "language": resp_lang}
            else:
                # ANY other utterance clears the pending choice state and is processed normally
                clear_pending_choice()

        # Check pending single-task confirmation state
        from agent.pending_action import get_pending_action, clear_pending_action, set_pending_action, PendingAction
        pending_act = get_pending_action(now=now)
        pending_plan = get_pending_plan()

        # Deterministic precedence between replan preview and single-task confirmation:
        # The newest question wins!
        if pending_act and pending_plan:
            plan_created = getattr(pending_plan, "created_at", None) or pending_act.created_at
            if plan_created >= pending_act.created_at:
                pending_act = None
            else:
                pending_plan = None

        YES_WORDS = {
            "yes", "yeah", "yep", "ok", "okay", "do it", "go ahead",
            "haan", "ha", "हाँ", "हां", "कर दो", "ठीक है",
            "houdu", "sari", "maadi", "agide", "aaytu", "aayithu", "ಆಯಿತು", "ಹೌದು", "ಸರಿ"
        }
        NO_WORDS = {
            "no", "dont", "don't", "nahi", "nahin", "नहीं", "ना", "ಬೇಡ", "ಇಲ್ಲ"
        }
        text_clean = user_text.strip(" !.,?:;\"'").lower()
        is_yes = (text_clean in YES_WORDS) or any(text_clean == y or text_clean.startswith(y + " ") for y in YES_WORDS)
        is_no = (text_clean in NO_WORDS) or any(text_clean == y or text_clean.startswith(y + " ") for y in NO_WORDS)

        if pending_act:
            resp_lang = language if language != "en" else (pending_act.language or "en")
            if pending_act.action == "move_to_tomorrow":
                if is_yes:
                    from timeutil import to_ist_naive, format_time_spoken
                    from scheduler import schedule_task_reminder
                    new_task = Task(
                        title=pending_act.title,
                        due_at=to_ist_naive(pending_act.target_dt),
                        status=TaskStatus.SCHEDULED.value,
                        language=resp_lang,
                        is_fixed=True,
                    )
                    db.add(new_task)
                    db.commit()
                    db.refresh(new_task)
                    schedule_task_reminder(new_task.id, pending_act.target_dt)
                    clear_pending_action()

                    time_str = format_time_spoken(pending_act.target_dt, resp_lang)
                    if resp_lang == "hi":
                        reply_text = f"ठीक है, {pending_act.title} का रिमाइंडर कल {time_str} सेट कर दिया गया है।"
                    elif resp_lang == "kn":
                        reply_text = f"ಸರಿ, {pending_act.title} ರಿಮೈಂಡರ್ ಅನ್ನು ನಾಳೆ {time_str} ಹೊಂದಿಸಲಾಗಿದೆ."
                    else:
                        reply_text = f"Got it, reminder set: {pending_act.title} for tomorrow at {time_str}."

                    agent_utt = Utterance(role="assistant", text=reply_text, language=resp_lang)
                    db.add(agent_utt)
                    db.commit()
                    log_event("agent_reply", reply_text)
                    return {
                        "reply_text": reply_text,
                        "task_changes": [{"type": "created", "task_id": new_task.id, "title": new_task.title, "due_at": pending_act.target_dt.isoformat()}],
                        "language": resp_lang
                    }
                elif is_no:
                    clear_pending_action()
                    if resp_lang == "hi":
                        reply_text = "ठीक है, मैं इसे शेड्यूल नहीं करूँगा।"
                    elif resp_lang == "kn":
                        reply_text = "ಸರಿ, ನಾನು ಅದನ್ನು ನಿಗದಿಪಡಿಸುವುದಿಲ್ಲ."
                    else:
                        reply_text = "Okay, I won't schedule it."

                    agent_utt = Utterance(role="assistant", text=reply_text, language=resp_lang)
                    db.add(agent_utt)
                    db.commit()
                    log_event("agent_reply", reply_text)
                    return {"reply_text": reply_text, "task_changes": [], "language": resp_lang}
                else:
                    clear_pending_action()

            elif is_yes:
                # Re-check task in DB
                task = db.query(Task).filter_by(id=pending_act.task_id).first()
                if not task or task.status not in (TaskStatus.SCHEDULED.value, TaskStatus.SNOOZED.value, TaskStatus.DUE.value):
                    clear_pending_action()
                    from agent.replies import format_already_done
                    reply_text = format_already_done(pending_act.title, resp_lang)
                    agent_utt = Utterance(role="assistant", text=reply_text, language=resp_lang)
                    db.add(agent_utt)
                    db.commit()
                    log_event("agent_reply", reply_text)
                    return {"reply_text": reply_text, "task_changes": [], "language": resp_lang}
                else:
                    task.status = TaskStatus.CANCELLED.value
                    db.commit()
                    from scheduler import remove_task_job
                    remove_task_job(task.id)
                    log_event("task_cancelled", f"Cancelled: {task.title}", task_id=task.id)
                    clear_pending_action()
                    from agent.replies import format_cancelled
                    reply_text = format_cancelled(task.title, resp_lang)

                agent_utt = Utterance(role="assistant", text=reply_text, language=resp_lang)
                db.add(agent_utt)
                db.commit()
                log_event("agent_reply", reply_text)
                return {"reply_text": reply_text, "task_changes": [{"type": "cancelled", "title": pending_act.title}], "language": resp_lang}

            elif is_no:
                clear_pending_action()
                from agent.replies import format_cancel_aborted_leave
                reply_text = format_cancel_aborted_leave(pending_act.title, resp_lang)
                agent_utt = Utterance(role="assistant", text=reply_text, language=resp_lang)
                db.add(agent_utt)
                db.commit()
                log_event("agent_reply", reply_text)
                return {"reply_text": reply_text, "task_changes": [], "language": resp_lang}

            else:
                # ANY other utterance clears the pending state and is processed normally
                clear_pending_action()

        # Check pending replan confirmation (yes / no)
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

        # If neither pending_act nor pending_plan exists:
        # A bare acknowledgment ("okay", "ठीक है", "ಆಯಿತು") gets a plain "Okay." in the user's language.
        # A bare "yes" gets "Yes to what? I don't have a pending question."
        # Both guarantee nothing in the schedule is changed.
        if not pending_act and not pending_plan:
            ACK_WORDS = {
                "ok", "okay", "theek hai", "thik hai", "chalega", "sahi hai",
                "achha", "acha", "sari", "agide", "aaytu", "aayithu",
                "ठीक है", "अच्छा", "ಆಯಿತು", "ಸರಿ"
            }
            if text_clean in ACK_WORDS:
                if language == "hi":
                    reply_text = "ठीक है।"
                elif language == "kn":
                    reply_text = "ಸರಿ."
                else:
                    reply_text = "Okay."
                agent_utt = Utterance(role="assistant", text=reply_text, language=language)
                db.add(agent_utt)
                db.commit()
                log_event("agent_reply", reply_text)
                return {"reply_text": reply_text, "task_changes": [], "language": language}
            elif is_yes:
                from agent.replies import format_yes_to_what_no_pending
                reply_text = format_yes_to_what_no_pending(language)
                agent_utt = Utterance(role="assistant", text=reply_text, language=language)
                db.add(agent_utt)
                db.commit()
                log_event("agent_reply", reply_text)
                return {"reply_text": reply_text, "task_changes": [], "language": language}

        # FIX D: Deterministic ambiguity check before LLM acts or replan
        import re
        from agent.matcher import find_task_by_title
        from agent.replies import format_ambiguous

        AMBIGUITY_ACTION_TRIGGERS = [
            # cancel
            "cancel", "remove", "delete", "drop", "scrap", "get rid of",
            "hata do", "hatao", "hata de", "hata", "radd karo", "radd",
            "हटा दो", "हटाओ", "हटा देना", "हटा", "रद्द करो", "रद्द", "कैंसिल",
            "raddu madi", "raddu", "tegeduhaku", "tegedu", "ರದ್ದು ಮಾಡು", "ರದ್ದು ಮಾಡಿ", "ರದ್ದು", "ತೆಗೆದುಹಾಕು", "ತೆಗೆ",
            # done / ho gaya
            "mark done", "done", "finished", "complete", "completed", "finish",
            "ho gaya", "ho gayi", "khatam", "pura ho gaya", "kar diya", "ho chuka",
            "हो गया", "हो गई", "पूरा हो गया", "खत्म", "कर दिया",
            "mugiyithu", "aayithu", "aagide", "mugi", "ಮುಗಿಯಿತು", "ಆಯಿತು", "ಮುಗಿದಿದೆ", "ಪೂರ್ಣವಾಯಿತು",
            # snooze
            "snooze karo", "snooze", "स्नूज़ करो", "स्नूज़", "ಸ್ನೂಜ್ ಮಾಡಿ", "ಸ್ನೂಜ್",
            # move / update
            "reschedule", "postpone", "update", "move", "shift", "push",
            "badal do", "badlo", "aage badhao", "aage badha do",
            "बदल दो", "बदलो", "आगे बढ़ाओ", "आगे बढ़ा दो", "टालो", "शिफ्ट",
            "badalisu", "munde haku", "talli haaki", "mundoodu",
            "ಬದಲಾಯಿಸು", "ಮುಂದೂಡು", "ಮುಂದೆ ಹಾಕು", "ತಳ್ಳಿ ಹಾಕು"
        ]
        AMBIGUITY_ACTION_TRIGGERS.sort(key=len, reverse=True)

        PARTICLES_TO_CLEAN = {
            "the", "my", "please", "ko", "ka", "ki", "bhi", "karo", "kar do", "dijiye",
            "kar", "दो", "करो", "कर", "दीजिए", "को", "का", "की", "भी",
            "madi", "madu", "haku", "annu", "vannu",
            "ಅನ್ನು", "ವನ್ನು", "ಗೆ", "ಕ್ಕೆ", "ಮಾಡೀ", "ಮಾಡು", "ಮಾಡಿ"
        }

        text_lower = user_text.lower().strip()
        found_action = None
        for a in AMBIGUITY_ACTION_TRIGGERS:
            if a in text_lower:
                found_action = a
                break

        if found_action:
            parts = text_lower.split(found_action, 1)

            def _clean_side(s: str) -> str:
                s = re.sub(r'\b(?:to|at|by)\s+\d+.*', '', s).strip()
                s = re.sub(r'\b\d+\s*(?:am|pm|baje|ghante|ಗಂಟೆಗೆ).*', '', s).strip()
                words = s.split()
                clean_words = [w for w in words if w not in PARTICLES_TO_CLEAN]
                return " ".join(clean_words).strip()

            before = _clean_side(parts[0])
            after = _clean_side(parts[1])
            target = after or before

            if target:
                active_tasks = db.query(Task).filter(
                    Task.status.in_([TaskStatus.SCHEDULED.value, TaskStatus.SNOOZED.value, TaskStatus.DUE.value])
                ).all()
                status, matched_task, candidates = find_task_by_title(db, target, active_tasks=active_tasks, cutoff=0.6, margin=0.1)
                if status == "ambiguous":
                    act_type = "cancel"
                    for act_word in AMBIGUITY_ACTION_TRIGGERS:
                        if act_word in text_lower:
                            if any(act_word.startswith(c) or act_word == c for c in ["cancel", "remove", "delete", "drop", "scrap", "hata", "radd", "हटा", "रद्द", "कैंसिल", "raddu", "tegedu", "ರದ್ದು", "ತೆಗೆ"]):
                                act_type = "cancel"
                            elif any(act_word.startswith(d) or act_word == d for d in ["mark done", "done", "finished", "complete", "finish", "ho gaya", "khatam", "pura", "kar diya", "हो गया", "पूरा", "खत्म", "mugiyithu", "aayithu", "aagide", "ಮುಗಿಯಿತು", "ಆಯಿತು", "ಮುಗಿದಿದೆ"]):
                                act_type = "done"
                            elif "snooze" in act_word or "स्नूज़" in act_word or "ಸ್ನೂಜ್" in act_word:
                                act_type = "snooze"
                            else:
                                act_type = "move"
                            break

                    cand_tasks = [t for t in active_tasks if t.title in candidates]
                    cand_ids = [t.id for t in cand_tasks]
                    from agent.pending_choice import set_pending_choice, PendingChoice
                    ref_now = ensure_ist(now) if now is not None else now_ist()
                    set_pending_choice(PendingChoice(
                        action=act_type,
                        candidate_task_ids=cand_ids,
                        language=language,
                        created_at=ref_now,
                    ))

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
                change = await _execute_tool(db, tc, now, language, user_text=user_text)
                if change:
                    if change.get("type") == "batch_created":
                        task_changes.extend(change.get("items", []))
                    else:
                        task_changes.append(change)

            # Generate natural spoken confirmation
            reply_text = _generate_confirmation(task_changes, language, now=now)
        else:
            # Check if user asked to cancel/remove and tool wasn't invoked
            if has_destructive_command(user_text):
                change = _handle_cancel_task(db, {}, user_text=user_text, language=language)
                if change:
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


async def _execute_tool(db, tool_call: dict, now: datetime, language: str, user_text: str = "") -> Optional[dict]:
    """Execute a single tool call and return the result."""
    name = tool_call["name"]
    args = tool_call["arguments"]

    if name == "add_tasks":
        tasks_list = args.get("tasks") or []
        items = []
        last_resolved_dt = None  # anchor for "on the way back"-style vague phrases
        for t_args in tasks_list:
            c = _handle_add_task(db, t_args, now, language, anchor_dt=last_resolved_dt, user_text=user_text)
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
        return _handle_add_task(db, args, now, language, user_text=user_text)
    elif name == "update_task":
        return _handle_update_task(db, args, now)
    elif name == "cancel_task":
        return _handle_cancel_task(db, args, user_text=user_text, language=language, now=now)
    elif name == "ask_clarification":
        return {"type": "clarification", "question": args.get("question", "")}

    logger.warning(f"Unknown tool: {name}")
    return None


def _get_task_clause(user_text: str, title: str, time_phrase: str = "") -> str:
    """
    Restrict context-recovery to the clause containing the task title.
    Splits on commas, conjunctions (and, aur, और, ಮತ್ತು), and sentence punctuation.
    """
    if not user_text:
        return ""

    import re
    clauses = re.split(r'[,;.!?\n]|(?:\s+(?:and|aur|और|ಮತ್ತು)\s+)', user_text, flags=re.IGNORECASE)
    clauses = [c.strip() for c in clauses if c.strip()]
    if len(clauses) <= 1:
        return user_text

    t_lower = title.lower().strip()
    # 1. Exact match of full title in clause
    for c in clauses:
        if t_lower in c.lower():
            return c

    # 2. Match significant tokens of title (length >= 3)
    title_words = [w for w in re.split(r'\s+', t_lower) if len(w) >= 3 and w not in {'task', 'reminder'}]
    if title_words:
        for c in clauses:
            c_lower = c.lower()
            if any(w in c_lower for w in title_words):
                return c

    # 3. Match time_phrase if present in a unique clause
    if time_phrase:
        tp_lower = time_phrase.lower().strip()
        matching_tp = [c for c in clauses if tp_lower in c.lower()]
        if len(matching_tp) == 1:
            return matching_tp[0]

    return ""


def _handle_add_task(db, args: dict, now: datetime, language: str, anchor_dt: Optional[datetime] = None, user_text: str = "") -> dict:
    """Create a new task from add_task or add_tasks tool call."""
    title = args.get("title", "Untitled").strip()
    time_phrase = args.get("time_phrase", "in 1 hour")
    recurrence = args.get("recurrence")
    if recurrence in ("none", "null", "", None):
        recurrence = None

    # Context enrichment from user_text scoped to this task's clause
    if user_text:
        scoped_clause = _get_task_clause(user_text, title, time_phrase)
        if scoped_clause:
            u_lower = scoped_clause.lower()
            tp_lower = time_phrase.lower()
            prefix = []
            for ind in ["tomorrow", "kal", "naale", "कल", "ನಾಳೆ"]:
                if ind in u_lower and ind not in tp_lower:
                    prefix.append(ind)
                    break
            for ind in ["sanje", "shaam", "evening", "pm", "ಸಂಜೆ", "ಶಾಮ"]:
                if ind in u_lower and ind not in tp_lower:
                    prefix.append(ind)
                    break
            for ind in ["subah", "morning", "beligge", "am", "ಬೆಳಿಗ್ಗೆ", "सुबह"]:
                if ind in u_lower and ind not in tp_lower:
                    prefix.append(ind)
                    break
            for ind in ["today", "aaj", "आज", "indu", "ಇಂದು"]:
                if ind in u_lower and ind not in tp_lower:
                    prefix.append(ind)
                    break
            if prefix:
                time_phrase = f"{' '.join(prefix)} {time_phrase}"

    # Resolve time (pass anchor_dt for chaining vague phrases after a prior task)
    resolved = resolve_time(time_phrase, now=now, anchor_dt=anchor_dt)

    # Check if time was explicitly marked for today but has already passed
    is_explicit_today = any(w in time_phrase.lower() for w in ["today", "aaj", "आज", "indu", "ಇಂದು"])
    if not is_explicit_today and user_text:
        scoped = _get_task_clause(user_text, title, time_phrase)
        if scoped:
            is_explicit_today = any(w in scoped.lower() for w in ["today", "aaj", "आज", "indu", "ಇಂದು"])

    if is_explicit_today and resolved.dt <= now:
        from datetime import timedelta
        return {
            "type": "past_time_confirmation",
            "title": title,
            "language": language,
            "past_dt": resolved.dt,
            "tomorrow_dt": resolved.dt + timedelta(days=1),
        }

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


def _handle_cancel_task(db, args: dict, user_text: str = "", language: str = "en", now: Optional[datetime] = None) -> dict:
    """
    Cancel a task with safety checks:
    - Rule 1: No command word AND is a question (e.g. "why is it still there?", "यह अभी भी क्यों है?") -> question_help.
    - Rule 2: Command word AND question phrasing together (e.g. "can you remove the gym?") -> ask "Should I cancel <title>?" (destructive_confirm_prompt) and set pending confirmation.
    - Rule 3: No command word AND NOT a question (e.g. "forget the gym") -> ask "Do you want me to cancel <title>?" (destructive_want_confirm) and set pending confirmation.
    - Rule 4: Plain command -> execute directly.
    - Ambiguous: ask which one (candidates).
    - Not-found: only offer "did you mean" when score passes cutoff (otherwise closest is None).
    """
    from agent.matcher import find_task_by_title
    from agent.pending_action import set_pending_action, PendingAction
    from timeutil import ensure_ist, now_ist
    import re

    has_cmd = has_destructive_command(user_text) if user_text else False
    is_q = _is_question(user_text) if user_text else False

    # Rule 1: If it is a question and has NO command word, never act or prompt; return question help
    if user_text and not has_cmd and is_q:
        return {"type": "question_help"}

    task_id = args.get("task_id")
    target_title = (args.get("title") or "").strip()

    active_tasks = db.query(Task).filter(
        Task.status.in_([TaskStatus.SCHEDULED.value, TaskStatus.SNOOZED.value, TaskStatus.DUE.value])
    ).all()

    # Extract target title from user_text if not provided in args
    if not target_title and user_text:
        text_lower = user_text.lower()
        found_stem = None
        for stem in DESTRUCTIVE_STEMS:
            if stem in text_lower:
                found_stem = stem
                break
        if found_stem:
            after = text_lower.split(found_stem, 1)[1]
            before = text_lower.split(found_stem, 1)[0]
            for p in ["the", "my", "ko", "annu", "bhi", "please", "karo", "kar do", "madi", "madu", "ಮಾಡೀ", "ಮಾಡು"]:
                after = re.sub(rf'\b{p}\b', '', after).strip()
                before = re.sub(rf'\b{p}\b', '', before).strip()
            target_title = after or before
        else:
            # Check for phrases like "forget the gym" or "clear gym"
            cleaned = re.sub(r'^(?:can\s+you\s+|could\s+you\s+|please\s+)?(?:forget|clear)\s+(?:about\s+)?(?:the\s+|my\s+)?', '', text_lower).strip()
            if cleaned:
                target_title = cleaned

    task = None
    if target_title:
        status, task, candidates = find_task_by_title(db, target_title, active_tasks=active_tasks, cutoff=0.6, margin=0.1)
        if status == "ambiguous":
            cand_tasks = [t for t in active_tasks if t.title in candidates]
            cand_ids = [t.id for t in cand_tasks]
            from agent.pending_choice import set_pending_choice, PendingChoice
            ref_now = ensure_ist(now) if now is not None else now_ist()
            set_pending_choice(PendingChoice(
                action="cancel",
                candidate_task_ids=cand_ids,
                language=language,
                created_at=ref_now,
            ))
            return {
                "type": "cancel_ambiguous",
                "target": target_title,
                "candidates": candidates,
            }
        elif status == "not_found":
            # Fix for (b): When command word is explicit and title matcher finds nothing,
            # use task_id from LLM tool call if it points to an active task, ask "Should I cancel <title>?" and set pending state.
            fallback_task = None
            if has_cmd and task_id:
                try:
                    fallback_task = db.query(Task).filter(
                        Task.id == int(task_id),
                        Task.status.in_([TaskStatus.SCHEDULED.value, TaskStatus.SNOOZED.value, TaskStatus.DUE.value])
                    ).first()
                except (ValueError, TypeError):
                    fallback_task = None
            if fallback_task:
                ref_now = ensure_ist(now) if now is not None else now_ist()
                set_pending_action(PendingAction(
                    action="cancel",
                    task_id=fallback_task.id,
                    title=fallback_task.title,
                    language=language,
                    created_at=ref_now,
                ))
                return {
                    "type": "destructive_confirm_prompt",
                    "title": fallback_task.title,
                }
            return {
                "type": "cancel_not_found",
                "target": target_title,
                "closest": None,
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
                "closest": None,
            }
    else:
        return {
            "type": "cancel_not_found",
            "target": "",
            "closest": None,
        }

    # Task is found! Check confirmation conditions:
    ref_now = ensure_ist(now) if now is not None else now_ist()

    # Rule 2: Command word AND question phrasing -> ask "Should I cancel <title>?"
    if user_text and is_q:
        set_pending_action(PendingAction(
            action="cancel",
            task_id=task.id,
            title=task.title,
            language=language,
            created_at=ref_now,
        ))
        return {
            "type": "destructive_confirm_prompt",
            "task_id": task.id,
            "title": task.title,
            "language": language,
        }

    # Rule 3: NOT a question and NO command word (e.g. "forget the gym") -> ask "Do you want me to cancel <title>?"
    if user_text and not has_cmd:
        set_pending_action(PendingAction(
            action="cancel",
            task_id=task.id,
            title=task.title,
            language=language,
            created_at=ref_now,
        ))
        return {
            "type": "destructive_want_confirm",
            "task_id": task.id,
            "title": task.title,
            "language": language,
        }

    # Rule 4: Plain command -> execute cancellation!
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
        format_fallback, format_ambiguous, format_cancel_confirm_prompt,
        format_cancel_want_confirm, format_question_help
    )
    if not task_changes:
        return format_fallback(language)

    # Check for past-time confirmation ("That time has passed. Should I move it to tomorrow?")
    past_confirms = [c for c in task_changes if c.get("type") == "past_time_confirmation"]
    if past_confirms:
        from agent.pending_action import set_pending_action, PendingAction
        from agent.replies import format_past_time_confirm
        pc = past_confirms[0]
        set_pending_action(PendingAction(
            action="move_to_tomorrow",
            task_id=0,
            title=pc["title"],
            language=language,
            created_at=now if now is not None else now_ist(),
            target_dt=pc["tomorrow_dt"],
        ))
        return format_past_time_confirm(language)

    # Check for confirmation prompt ("Should I cancel <title>?")
    confirm_prompts = [c for c in task_changes if c.get("type") == "destructive_confirm_prompt"]
    if confirm_prompts:
        return format_cancel_confirm_prompt(confirm_prompts[0].get("title", "this task"), language)

    # Check for want confirmation ("Do you want me to cancel <title>?")
    want_prompts = [c for c in task_changes if c.get("type") == "destructive_want_confirm"]
    if want_prompts:
        return format_cancel_want_confirm(want_prompts[0].get("title", "this task"), language)

    # Check for question help
    if any(c.get("type") == "question_help" for c in task_changes):
        return format_question_help(language)

    if any(c.get("type") == "not_command_blocked" for c in task_changes):
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
