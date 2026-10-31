"""
Localized reply templates for Indic multilingual voice assistant (English, Hindi, Kannada).
Hindi/Hinglish uses Devanagari script for accurate Edge TTS pronunciation.
Kannada uses Kannada script.
"""
from datetime import datetime
from typing import Optional

REPLIES = {
    "en": {
        "created_single": "Got it, reminder set: {title} for {time}.",
        "created_multiple": "Got it, {count} reminders set.",
        "needs_confirmation_guess": "I wasn't sure when, so I set {title} for {time}. Tell me if you want a different time.",
        "updated": "Moved {title} to {time}.",
        "snoozed": "Snoozed {title} for {minutes} minutes.",
        "snoozed_until": "Snoozed {title} for {minutes} minutes, until {until}.",
        "done": "Great, {title} marked as done! ✓",
        "done_recurring": "Great, {title} marked as done! Next reminder is {next_when}.",
        "cancelled": "Cancelled {title}.",
        "cancel_closest": "Could not find that task. Did you mean '{closest}'?",
        "cancel_not_found": "Could not find that task to cancel.",
        "ambiguous_which": "Which one did you mean: {candidates}?",
        "question_help": "I can set, move, snooze or cancel reminders. What would you like to do?",
        "fallback_not_caught": "I didn't catch a task or time in that. Try something like 'dentist at 5 pm tomorrow'.",
        "needs_confirmation": "I've set {title} for {time}. Please confirm if that works.",
        "fallback": "I didn't catch a task or time in that. Try something like 'dentist at 5 pm tomorrow'.",
        "reminder_prompt": "{title} — it's {time}. Done, snooze, or move to tomorrow?",
    },
    "hi": {
        "created_single": "ठीक है, {title} का रिमाइंडर {time} सेट कर दिया गया है।",
        "created_multiple": "ठीक है, {count} रिमाइंडर सेट कर दिए गए हैं।",
        "needs_confirmation_guess": "मुझे समय पता नहीं था, इसलिए {title} को {time} पर सेट किया। अगर दूसरा समय चाहिए तो बताइए।",
        "updated": "{title} को {time} शिफ्ट कर दिया गया है।",
        "snoozed": "{title} को {minutes} मिनट के लिए स्नूज़ कर दिया गया है।",
        "snoozed_until": "{title} को {minutes} मिनट के लिए स्नूज़ कर दिया गया है, {until} तक।",
        "done": "बहुत बढ़िया, {title} पूरा हो गया! ✓",
        "done_recurring": "बहुत बढ़िया, {title} पूरा हो गया! अगला रिमाइंडर {next_when} है।",
        "cancelled": "{title} रद्द कर दिया गया है।",
        "cancel_closest": "वह कार्य नहीं मिला। क्या आपका मतलब '{closest}' था?",
        "cancel_not_found": "रद्द करने के लिए वह कार्य नहीं मिला।",
        "ambiguous_which": "आपका कौन सा मतलब था: {candidates}?",
        "question_help": "मैं रिमाइंडर सेट, आगे बढ़ा, स्नूज़ या रद्द कर सकता हूँ। आप क्या करना चाहते हैं?",
        "fallback_not_caught": "मुझे इसमें कोई कार्य या समय नहीं मिला। जैसे कहें: 'कल शाम 5 बजे डेंटिस्ट'।",
        "needs_confirmation": "मैंने {title} {time} पर सेट किया है। कृपया पुष्टि करें कि क्या यह समय सही है।",
        "fallback": "मुझे इसमें कोई कार्य या समय नहीं मिला। जैसे कहें: 'कल शाम 5 बजे डेंटिस्ट'।",
        "reminder_prompt": "{title} — {time} बज गए हैं। क्या यह पूरा हो गया, स्नूज़ करना है, या कल के लिए टालें?",
    },
    "kn": {
        "created_single": "ಸರಿ, {title} ರಿಮೈಂಡರ್ ಅನ್ನು {time} ಹೊಂದಿಸಲಾಗಿದೆ.",
        "created_multiple": "ಸರಿ, {count} ರಿಮೈಂಡರ್‌ಗಳನ್ನು ಹೊಂದಿಸಲಾಗಿದೆ.",
        "needs_confirmation_guess": "ಸಮಯ ಗೊತ್ತಿಲ್ಲದ ಕಾರಣ {title} ಅನ್ನು {time} ಕ್ಕೆ ಹೊಂದಿಸಿದ್ದೇನೆ. ಬೇರೆ ಸಮಯ ಬೇಕಾದರೆ ತಿಳಿಸಿ.",
        "updated": "{title} ಅನ್ನು {time} ಬದಲಾಯಿಸಲಾಗಿದೆ.",
        "snoozed": "{title} ಅನ್ನು {minutes} ನಿಮಿಷಗಳ ಕಾಲ ಸ್ನೂಜ್ ಮಾಡಲಾಗಿದೆ.",
        "snoozed_until": "{title} ಅನ್ನು {minutes} ನಿಮಿಷಗಳ ಕಾಲ {until} ವರೆಗೆ ಸ್ನೂಜ್ ಮಾಡಲಾಗಿದೆ.",
        "done": "ಉತ್ತಮ, {title} ಮುಕ್ತಾಯಗೊಂಡಿದೆ ಎಂದು ಗುರುತಿಸಲಾಗಿದೆ! ✓",
        "done_recurring": "ಉತ್ತಮ, {title} ಮುಕ್ತಾಯಗೊಂಡಿದೆ! ಮುಂದಿನ ರಿಮೈಂಡರ್ {next_when}.",
        "cancelled": "{title} ರದ್ದುಗೊಳಿಸಲಾಗಿದೆ.",
        "cancel_closest": "ಆ ಕಾರ್ಯ ಕಂಡುಬಂದಿಲ್ಲ. ನೀವು '{closest}' ಅನ್ನು ಉಲ್ಲೇಖಿಸಿದ್ದೀರಾ?",
        "cancel_not_found": "ರದ್ದುಗೊಳಿಸಲು ಆ ಕಾರ್ಯ ಕಂಡುಬಂದಿಲ್ಲ.",
        "ambiguous_which": "ನಿಮ್ಮ ಉದ್ದೇಶ ಯಾವುದು: {candidates}?",
        "question_help": "ನಾನು ರಿಮೈಂಡರ್‌ಗಳನ್ನು ಹೊಂದಿಸಬಹುದು, ಮುಂದೂಡಬಹುದು, ಸ್ನೂಜ್ ಮಾಡಬಹುದು ಅಥವಾ ರದ್ದುಗೊಳಿಸಬಹುದು. ನೀವು ಏನು ಮಾಡಲು ಬಯಸುತ್ತೀರಿ?",
        "fallback_not_caught": "ಅದರಲ್ಲಿ ನನಗೆ ಯಾವುದೇ ಕಾರ್ಯ ಅಥವಾ ಸಮಯ ಕಂಡುಬಂದಿಲ್ಲ. ಉದಾಹರಣೆಗೆ 'ನಾಳೆ ಸಂಜೆ 5 ಗಂಟೆಗೆ ದಂತವೈದ್ಯರ ಭೇಟಿ' ಎಂದು ಹೇಳಿ ನೋಡಿ.",
        "needs_confirmation": "ನಾನು {title} ಅನ್ನು {time} ಕ್ಕೆ ಹೊಂದಿಸಿದ್ದೇನೆ. ಇದು ಸರಿಹೊಂದುತ್ತದೆಯೇ ಎಂದು ದೃಢೀಕರಿಸಿ.",
        "fallback": "ಅದರಲ್ಲಿ ನನಗೆ ಯಾವುದೇ ಕಾರ್ಯ ಅಥವಾ ಸಮಯ ಕಂಡುಬಂದಿಲ್ಲ. ಉದಾಹರಣೆಗೆ 'ನಾಳೆ ಸಂಜೆ 5 ಗಂಟೆಗೆ ದಂತವೈದ್ಯರ ಭೇಟಿ' ಎಂದು ಹೇಳಿ ನೋಡಿ.",
        "reminder_prompt": "{title} — ಸಮಯ {time} ಆಗಿದೆ. ಮುಗಿದಿದೆಯೇ, ಸ್ನೂಜ್ ಮಾಡಬೇಕೇ ಅಥವಾ ನಾಳೆಗೆ ಮುಂದೂಡಬೇಕೇ?",
    },
}


def get_template(category: str, language: str = "en") -> str:
    lang_dict = REPLIES.get(language, REPLIES["en"])
    return lang_dict.get(category, REPLIES["en"][category])


def _is_unparseable_guess(change: dict) -> bool:
    """Return True only for fallback guesses where the phrase couldn't be parsed at all.
    This excludes vague-phrase hits (e.g. 'before lunch') and AM/PM guesses ('6' -> 18:00).
    """
    note = change.get("resolution_note") or ""
    return note.startswith("Could not parse")


def format_created(changes: list, language: str = "en", now: Optional[datetime] = None) -> str:
    """Format single or batch task creation/update confirmation."""
    from timeutil import format_when
    created = [c for c in changes if c.get("type") == "created"]
    updated = [c for c in changes if c.get("type") in ("updated", "updated_duplicate")]

    if not created and not updated:
        return get_template("fallback_not_caught", language)

    # All items
    item_strings = []
    for c in created:
        when_str = format_when(c.get("due_at"), now=now, language=language) if c.get("due_at") else "now"
        if language == "hi":
            item_strings.append(f"{c['title']} {when_str}")
        elif language == "kn":
            item_strings.append(f"{c['title']} {when_str}")
        else:
            item_strings.append(f"{c['title']} for {when_str}")

    for c in updated:
        when_str = format_when(c.get("due_at"), now=now, language=language) if c.get("due_at") else "now"
        if language == "hi":
            item_strings.append(f"{c['title']} {when_str}")
        elif language == "kn":
            item_strings.append(f"{c['title']} {when_str}")
        else:
            item_strings.append(f"{c['title']} to {when_str}")

    count = len(created) + len(updated)
    if count == 1 and created:
        c = created[0]
        when_str = format_when(c.get("due_at"), now=now, language=language) if c.get("due_at") else "now"
        # Use "guess" template if time was inferred (needs_confirmation due to vague/unparseable phrase)
        if c.get("needs_confirmation"):
            tmpl = get_template("needs_confirmation_guess", language)
        else:
            tmpl = get_template("created_single", language)
        return tmpl.format(title=c["title"], time=when_str)
    elif count == 1 and updated:
        c = updated[0]
        when_str = format_when(c.get("due_at"), now=now, language=language) if c.get("due_at") else "now"
        tmpl = get_template("updated", language)
        return tmpl.format(title=c["title"], time=when_str)
    elif len(created) == 0 and len(updated) > 1:
        if language == "hi":
            return f"{count} रिमाइंडर अपडेट कर दिए गए हैं।"
        elif language == "kn":
            return f"{count} ರಿಮೈಂಡರ್‌ಗಳನ್ನು ಬದಲಾಯಿಸಲಾಗಿದೆ."
        return f"Moved {count} reminders."

    tmpl = get_template("created_multiple", language)
    base = tmpl.format(count=count)

    # Append a short spoken note for any unparseable-phrase guesses in the batch
    all_items = created + updated
    guess_items = [c for c in all_items if _is_unparseable_guess(c)]
    if guess_items:
        guess_notes = []
        for c in guess_items:
            when_str = format_when(c.get("due_at"), now=now, language=language) if c.get("due_at") else "now"
            if language == "hi":
                guess_notes.append(f"{c['title']} का समय मुझे पता नहीं था, {when_str} लगाया।")
            elif language == "kn":
                guess_notes.append(f"{c['title']} ಸಮಯ ಗೊತ್ತಿಲ್ಲದ ಕಾರಣ {when_str} ಹೊಂದಿಸಿದ್ದೇನೆ।")
            else:
                guess_notes.append(f"{c['title']} was a guess — I set it for {when_str}.")
        if language == "hi":
            base = base + " " + " ".join(guess_notes) + " अगर दूसरा समय चाहिए तो बताइए।"
        elif language == "kn":
            base = base + " " + " ".join(guess_notes) + " ಬೇರೆ ಸಮಯ ಬೇಕಾದರೆ ತಿಳಿಸಿ."
        else:
            base = base + " " + " ".join(guess_notes) + " Tell me if you want a different time."

    return base


def format_snoozed(title: str, minutes: int, language: str = "en", until: Optional[str] = None) -> str:
    if until:
        tmpl = get_template("snoozed_until", language)
        return tmpl.format(title=title, minutes=minutes, until=until)
    tmpl = get_template("snoozed", language)
    return tmpl.format(title=title, minutes=minutes)


def format_done(title: str, language: str = "en", next_when: Optional[str] = None) -> str:
    if next_when:
        tmpl = get_template("done_recurring", language)
        return tmpl.format(title=title, next_when=next_when)
    tmpl = get_template("done", language)
    return tmpl.format(title=title)


def format_cancelled(title: str, language: str = "en") -> str:
    tmpl = get_template("cancelled", language)
    return tmpl.format(title=title)


def format_cancel_not_found(closest: Optional[str] = None, language: str = "en") -> str:
    if closest:
        tmpl = get_template("cancel_closest", language)
        return tmpl.format(closest=closest)
    return get_template("cancel_not_found", language)


def format_ambiguous(candidates: list, language: str = "en") -> str:
    tmpl = get_template("ambiguous_which", language)
    if language == "hi":
        cand_str = " या ".join(candidates)
    elif language == "kn":
        cand_str = " ಅಥವಾ ".join(candidates)
    else:
        cand_str = " or ".join(candidates)
    return tmpl.format(candidates=cand_str)


def format_rescheduled(title: str, time_str: str, language: str = "en") -> str:
    tmpl = get_template("updated", language)
    return tmpl.format(title=title, time=time_str)


def format_reminder_prompt(title: str, time_str: str, language: str = "en") -> str:
    tmpl = get_template("reminder_prompt", language)
    return tmpl.format(title=title, time=time_str)


def format_question_help(language: str = "en") -> str:
    return get_template("question_help", language)


def format_fallback(language: str = "en") -> str:
    return get_template("fallback_not_caught", language)
