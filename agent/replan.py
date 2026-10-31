"""
Replan intent parser and interaction handler.
Extracts structured intent from user utterances (rule-based fast paths + LLM fallback),
handles yes/no/undo confirmation rules without calling LLMs, and coordinates preview and commit.
"""
import re
import logging
from typing import Optional, Tuple
from datetime import datetime, timedelta

from agent.replan_engine import (
    ReplanIntent, ReplanPlan, compute_replan,
    apply_replan_commit, apply_replan_undo
)
from agent.resolver import resolve_time
from timeutil import now_ist, ensure_ist, IST

logger = logging.getLogger(__name__)

# Single pending replan session (for voice/UI preview flow)
_current_pending_plan: Optional[ReplanPlan] = None


def get_pending_plan() -> Optional[ReplanPlan]:
    global _current_pending_plan
    return _current_pending_plan


def set_pending_plan(plan: Optional[ReplanPlan]):
    global _current_pending_plan
    _current_pending_plan = plan


def parse_confirmation_rule(text: str) -> Optional[str]:
    """
    Handle yes/no/undo with deterministic rules before touching the LLM.
    Returns: 'yes' | 'no' | 'undo' | None
    """
    t = text.lower().strip()
    t = re.sub(r"[!?.,;:\'\"()\-]", "", t).strip()

    undo_words = {
        "undo", "undo that", "undo it", "wapas kar do", "wapas", "revert",
        "hinde tegeduko", "pichla kar do", "cancel that last change"
    }
    if t in undo_words:
        return "undo"

    yes_words = {
        "yes", "yeah", "yep", "sure", "okay", "ok", "do it", "go ahead",
        "ha", "haan", "theek hai", "chalega", "sahi hai",
        "houdu", "sari", "maadi", "agide",
        "हाँ", "हां", "कर दो", "ठीक है", "हೌದು", "ಹೌದು", "ಸರಿ"
    }
    if any(t == y or t.startswith(y + " ") for y in yes_words):
        return "yes"

    no_words = {
        "no", "nope", "dont", "don't", "cancel that", "stop", "leave it",
        "nahi", "na", "mat karo", "rehne do", "chhod do",
        "beda", "bedave beda",
        "नहीं", "ना", "मत करो", "रहने दो", "छोड़ दो", "ಬೇಡ", "ಇಲ್ಲ"
    }
    if any(t == n or t.startswith(n + " ") for n in no_words):
        return "no"

    return None


REPLAN_KEYWORDS = [
    "push", "delay", "postpone", "replan", "reschedule", "free after",
    "swap", "skip the", "clear the", "sab kuch", "aage kar do",
    "aage badha", "shift all", "shift everything", "move gym to tomorrow",
    "move ", "सब कुछ", "आगे कर", "आगे बढ़ा", "ಮುಂದೆ ಹಾಕು", "ಮುಂದೆ ತಳ್ಳಿ", "ಎಲ್ಲವನ್ನೂ", "ಎಲ್ಲವನ್ನು", "ಎಲ್ಲಾ", "ellavannu"
]


def has_replan_cue(text: str) -> bool:
    """Check if utterance contains replanning signals."""
    t = text.lower()
    # Don't treat simple cancel / delete as replan
    if any(t.startswith(w + " ") or t == w for w in ["cancel", "delete", "remove", "hata do", "radd karo"]):
        return False
    return any(cue in t for cue in REPLAN_KEYWORDS)


def extract_replan_intent_rules(text: str, now: datetime) -> Optional[ReplanIntent]:
    """
    Rule-based extraction for common replanning requests.
    Returns ReplanIntent or None if LLM fallback needed.
    """
    t = text.lower().strip()

    # 1. "push everything by N minutes" / "sab kuch N minute aage kar do" / "delay by N mins"
    shift_match = re.search(
        r"(?:push|delay|postpone|shift|move)\s+(?:everything|all(?:\s+tasks)?|the\s+rest)\s+by\s+(\d+)\s*(?:min|mins|minutes)?",
        t
    )
    if not shift_match:
        # Hinglish: "sab kuch 45 minute aage kar do"
        shift_match = re.search(r"sab\s*kuch\s+(\d+)\s*min(?:ute)?.*aage", t)
    if not shift_match:
        # Hindi Devanagari: "सब कुछ 30 मिनट आगे" / "सब 30 मिनट आगे बढ़ा दो"
        shift_match = re.search(r"सब\s*(?:कुछ)?\s*(\d+)\s*मिनट.*(?:आगे|बढ़ा)", t)
    if not shift_match:
        # Kannada: "ಎಲ್ಲವನ್ನೂ 30 ನಿಮಿಷ ಮುಂದೆ" / "ಎಲ್ಲಾ 30 ನಿಮಿಷ ಮುಂದೆ" / "ellavannu 30 minute munde"
        shift_match = re.search(r"(?:ಎಲ್ಲವನ್ನೂ|ಎಲ್ಲವನ್ನು|ಎಲ್ಲಾ|ellavannu)\s*(\d+)\s*(?:ನಿಮಿಷ|min|minute).*(?:ಮುಂದೆ|munde|ಹಾಕು|ತಳ್ಳಿ)", t)

    if shift_match:
        mins = int(shift_match.group(1))
        return ReplanIntent(intent_type="shift_all", minutes=mins)

    # 2. "only free after 5" / "free after 5 pm" / "5 baje ke baad"
    free_after = re.search(r"(?:only\s+)?free\s+after\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", t)
    if not free_after:
        free_after = re.search(r"(\d{1,2})\s*baje\s*ke\s*baad", t)
    if free_after:
        h = int(free_after.group(1))
        m = int(free_after.group(2) or 0)
        ampm = free_after.group(3) if len(free_after.groups()) >= 3 else None
        if ampm == "pm" or (h <= 7 and not ampm):
            h += 12
        elif ampm == "am" and h == 12:
            h = 0
        window_end = datetime(now.year, now.month, now.day, h, m, tzinfo=IST)
        if window_end <= now:
            window_end += timedelta(days=1)
        return ReplanIntent(
            intent_type="block_window",
            window_start=now,
            window_end=window_end,
        )

    # 3. "swap X and Y" / "swap the invoice and groceries"
    swap_match = re.search(r"swap\s+(?:the\s+)?([a-zA-Z\s]+?)\s+(?:and|with)\s+(?:the\s+)?([a-zA-Z\s]+)", t)
    if swap_match:
        t1 = swap_match.group(1).strip()
        t2 = swap_match.group(2).strip()
        return ReplanIntent(
            intent_type="swap_tasks",
            task_identifier=t1,
            task_identifier_2=t2,
        )

    # 4. "skip the rest of the afternoon" / "clear the afternoon"
    if "skip" in t or "clear" in t:
        if "afternoon" in t or "dopahar" in t:
            w_start = datetime(now.year, now.month, now.day, 12, 0, tzinfo=IST)
            w_end = datetime(now.year, now.month, now.day, 17, 0, tzinfo=IST)
            return ReplanIntent(
                intent_type="clear_range",
                window_start=max(now, w_start),
                window_end=w_end,
            )

    # 5. "move gym to tomorrow" / "move invoice to 5 pm"
    move_match = re.search(r"move\s+(?:the\s+)?([a-zA-Z\s]+?)\s+to\s+([a-zA-Z0-9\s:]+)", t)
    if move_match:
        target = move_match.group(1).strip()
        dest = move_match.group(2).strip()
        return ReplanIntent(
            intent_type="move_task",
            task_identifier=target,
            destination_phrase=dest,
        )

    return None


async def extract_replan_intent(text: str, now: datetime) -> Optional[ReplanIntent]:
    """
    Extract replanning intent using fast rules first, then small LLM call if needed.
    NEVER outputs final times — only validated structured intent.
    """
    if not has_replan_cue(text):
        return None

    rule_intent = extract_replan_intent_rules(text, now)
    if rule_intent:
        return rule_intent

    # LLM Structured Intent Fallback
    from providers.registry import registry
    intent_tools = [
        {
            "type": "function",
            "function": {
                "name": "set_replan_intent",
                "description": "Extract user's replanning intent. NEVER calculate final times.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "intent_type": {
                            "type": "string",
                            "enum": ["shift_all", "shift_from", "block_window", "move_task", "swap_tasks", "clear_range"],
                            "description": "The category of schedule change"
                        },
                        "minutes": {
                            "type": "integer",
                            "description": "Minutes to shift/delay (e.g. 45, 60)"
                        },
                        "start_phrase": {
                            "type": "string",
                            "description": "Start time phrase for window (e.g. 'now', '2 pm')"
                        },
                        "end_phrase": {
                            "type": "string",
                            "description": "End time phrase for window (e.g. '5 pm', 'evening')"
                        },
                        "task_identifier": {
                            "type": "string",
                            "description": "Task name or reference"
                        },
                        "task_identifier_2": {
                            "type": "string",
                            "description": "Second task name for swaps"
                        },
                        "destination_phrase": {
                            "type": "string",
                            "description": "Destination time or day phrase (e.g. 'tomorrow', '7 pm')"
                        }
                    },
                    "required": ["intent_type"]
                }
            }
        }
    ]

    messages = [
        {
            "role": "system",
            "content": "You are a daily planner intent extractor. Return set_replan_intent with parameters only. Never compute times."
        },
        {"role": "user", "content": text}
    ]

    try:
        res = await registry.llm.chat(messages, tools=intent_tools)
        if res.get("tool_calls"):
            tc = res["tool_calls"][0]
            args = tc.get("arguments", {})
            itype = args.get("intent_type")
            if itype:
                w_start = resolve_time(args["start_phrase"], now=now).dt if args.get("start_phrase") else None
                w_end = resolve_time(args["end_phrase"], now=now).dt if args.get("end_phrase") else None
                return ReplanIntent(
                    intent_type=itype,
                    minutes=args.get("minutes"),
                    window_start=w_start,
                    window_end=w_end,
                    task_identifier=args.get("task_identifier"),
                    task_identifier_2=args.get("task_identifier_2"),
                    destination_phrase=args.get("destination_phrase"),
                )
    except Exception as e:
        logger.warning(f"LLM replan intent extraction failed: {e}")

    return None
