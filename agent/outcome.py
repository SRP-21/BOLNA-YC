"""
Outcome interpreter for reminder replies.
First tries cheap regex rules, then falls back to the small LLM model.

WHY rules first:
- "done", "ho gaya", "cancel" are unambiguous — no need to burn tokens
- The LLM is only called when the regex doesn't match
- This saves ~80% of classifier calls in practice
"""
import re
import logging
from typing import Optional
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ReminderOutcome(BaseModel):
    outcome: str  # done | snooze | reschedule | cancel | no_response
    minutes: Optional[int] = None  # For snooze
    new_time_phrase: Optional[str] = None  # For reschedule


# --- Rule-based matching (covers ~80% of cases) ---
# Patterns grouped by outcome, supporting English + Hindi + Hinglish + Kannada

DONE_PATTERNS = [
    r"\b(done|finished|complete[d]?|ho\s*gaya|ho\s*gya|hogaya|hogya|kar\s*liya|karliya|khatam|aaytu|madide|ok done)\b",
    r"^(yes|haan|ha|ok|okay|yep|yup|acha)$",
]

SNOOZE_PATTERNS = [
    # "snooze 10 minutes", "10 min baad", "thodi der baad", "snooze"
    r"snooze\s*(\d+)?\s*(min(?:utes?)?|mins?)?",
    r"(\d+)\s*min(?:utes?)?\s*(?:baad|later|mein|me)",
    r"(\d+)\s*ghante?\s*(?:baad|later|mein|me)",
    r"\b(thodi\s*der\s*baad|baad\s*mein|later|remind\s*later)\b",
]

CANCEL_PATTERNS = [
    r"\b(cancel|skip|nahi|nahi\s*chahiye|nako|hat[a]?o|chhod|beda|remove|delete)\b",
]

RESCHEDULE_PATTERNS = [
    # "kal karte hain", "tomorrow", "move to evening"
    r"\b(kal|tomorrow|naale)\b",
    r"\b(move\s*to|shift\s*to|change\s*to)\s+(.+)",
    r"\b(kal\s*karte?\s*hai[n]?|kal\s*kar[a-z]*)\b",
]


def parse_outcome_rules(text: str) -> Optional[ReminderOutcome]:
    """Try to parse the reply using regex rules. Returns None if no match."""
    text_lower = text.lower().strip()

    # Done
    for pattern in DONE_PATTERNS:
        if re.search(pattern, text_lower):
            return ReminderOutcome(outcome="done")

    # Cancel
    for pattern in CANCEL_PATTERNS:
        if re.search(pattern, text_lower):
            return ReminderOutcome(outcome="cancel")

    # Snooze with duration
    for pattern in SNOOZE_PATTERNS:
        m = re.search(pattern, text_lower)
        if m:
            groups = m.groups()
            minutes = None
            for g in groups:
                if g and g.isdigit():
                    minutes = int(g)
                    break
            # "ghante" means hours
            if "ghante" in text_lower or "hour" in text_lower:
                minutes = (minutes or 1) * 60
            return ReminderOutcome(
                outcome="snooze",
                minutes=minutes or 10  # Default snooze: 10 minutes
            )

    # Reschedule
    for pattern in RESCHEDULE_PATTERNS:
        m = re.search(pattern, text_lower)
        if m:
            # Try to extract the new time phrase
            new_time = None
            if m.lastindex and m.lastindex >= 2:
                new_time = m.group(m.lastindex).strip()
            elif "kal" in text_lower or "tomorrow" in text_lower or "naale" in text_lower:
                new_time = "tomorrow morning"
            return ReminderOutcome(
                outcome="reschedule",
                new_time_phrase=new_time
            )

    return None  # No rule matched -> use LLM


async def parse_outcome_llm(text: str, task_title: str) -> ReminderOutcome:
    """
    Use the cheap classifier model when rules don't match.
    Prompt is tiny to minimize token usage.
    """
    from providers.registry import registry

    messages = [
        {
            "role": "system",
            "content": (
                "You classify reminder replies. The user was reminded about a task and replied. "
                "Respond with EXACTLY one JSON object: "
                '{"outcome": "done|snooze|reschedule|cancel|no_response", "minutes": null_or_number, "new_time_phrase": null_or_string}\n'
                "Rules: 'done'=task completed. 'snooze'=remind later (extract minutes, default 10). "
                "'reschedule'=move to new time (extract phrase). 'cancel'=remove task. "
                "'no_response'=unclear/empty."
            )
        },
        {
            "role": "user",
            "content": f'Task: "{task_title}"\nReply: "{text}"\nClassify:'
        }
    ]

    try:
        response = await registry.llm.classify(messages)
        content = response.get("content", "").strip()
        # Extract JSON from response
        import json
        # Try to find JSON in the response
        json_match = re.search(r'\{[^}]+\}', content)
        if json_match:
            data = json.loads(json_match.group())
            return ReminderOutcome(**data)
    except Exception as e:
        logger.error(f"LLM outcome parsing failed: {e}")

    return ReminderOutcome(outcome="no_response")


async def parse_outcome(text: str, task_title: str = "") -> ReminderOutcome:
    """
    Main entry point: try rules first, then LLM.
    """
    if not text or not text.strip():
        return ReminderOutcome(outcome="no_response")

    # Try rules first (free, fast)
    result = parse_outcome_rules(text)
    if result:
        logger.info(f"Outcome parsed by rules: {result.outcome}")
        return result

    # Fall back to LLM (costs tokens)
    logger.info(f"Rules didn't match '{text}', using LLM classifier")
    return await parse_outcome_llm(text, task_title)

