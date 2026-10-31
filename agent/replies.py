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
        "cancel_confirm_prompt": "Should I cancel {title}?",
        "cancel_want_confirm": "Do you want me to cancel {title}?",
        "cancel_aborted_leave": "Okay, I'll leave {title}.",
        "yes_to_what_no_pending": "Yes to what? I don't have a pending question.",
        "ambiguous_which": "Which one did you mean: {candidates}?",
        "already_done": "{title} is already marked as done.",
        "past_time_confirm": "That time has passed. Should I move it to tomorrow?",
        "question_help": "I can set, move, snooze or cancel reminders. What would you like to do?",
        "fallback_not_caught": "I didn't catch a task or time in that. Try something like 'dentist at 5 pm tomorrow'.",
        "needs_confirmation": "I've set {title} for {time}. Please confirm if that works.",
        "fallback": "I didn't catch a task or time in that. Try something like 'dentist at 5 pm tomorrow'.",
        "reminder_prompt": "{title} — it's {time}. Done, snooze, or move to tomorrow?",
    },
    "hi": {
        "created_single": "ठीक है, {title} का रिमाइंडर {time} सेट कर दिया गया है।",
        "created_multiple": "ठीक है, {count} रिमाइंडर सेट कर दिए गए हैं।",
        "needs_confirmation_guess": "मुझे समय पता नहीं था, इसलिए {title} को {time} सेट किया। अगर दूसरा समय चाहिए तो बताइए।",
        "updated": "{title} को {time} शिफ्ट कर दिया गया है।",
        "snoozed": "{title} को {minutes} मिनट के लिए स्नूज़ कर दिया गया है।",
        "snoozed_until": "{title} को {minutes} मिनट के लिए स्नूज़ कर दिया गया है, {until} तक।",
        "done": "बहुत बढ़िया, {title} पूरा हो गया! ✓",
        "done_recurring": "बहुत बढ़िया, {title} पूरा हो गया! अगला रिमाइंडर {next_when} है।",
        "cancelled": "{title} रद्द कर दिया गया है।",
        "cancel_closest": "वह कार्य नहीं मिला। क्या आपका मतलब '{closest}' था?",
        "cancel_not_found": "रद्द करने के लिए वह कार्य नहीं मिला।",
        "cancel_confirm_prompt": "क्या मैं {title} को रद्द कर दूँ?",
        "cancel_want_confirm": "क्या आप चाहते हैं कि मैं {title} को रद्द कर दूँ?",
        "cancel_aborted_leave": "ठीक है, मैं {title} को वैसे ही रहने दूंगा।",
        "yes_to_what_no_pending": "किसके लिए हाँ? मेरे पास कोई लंबित सवाल नहीं है।",
        "ambiguous_which": "आपका कौन सा मतलब था: {candidates}?",
        "already_done": "{title} पहले ही पूरा हो चुका है।",
        "past_time_confirm": "वह समय बीत चुका है। क्या मैं इसे कल के लिए रख दूं?",
        "question_help": "मैं रिमाइंडर सेट, आगे बढ़ा, स्नूज़ या रद्द कर सकता हूँ। आप क्या करना चाहते हैं?",
        "fallback_not_caught": "मुझे इसमें कोई कार्य या समय नहीं मिला। जैसे कहें: 'कल शाम 5 बजे डेंटिस्ट'।",
        "needs_confirmation": "मैंने {title} {time} सेट किया है। कृपया पुष्टि करें कि क्या यह समय सही है।",
        "fallback": "मुझे इसमें कोई कार्य या समय नहीं मिला। जैसे कहें: 'कल शाम 5 बजे डेंटिस्ट'।",
        "reminder_prompt": "{title} — {time}। क्या यह पूरा हो गया, स्नूज़ करना है, या कल के लिए टालें?",
    },
    "kn": {
        "created_single": "ಸರಿ, {title} ರಿಮೈಂಡರ್ ಅನ್ನು {time} ಹೊಂದಿಸಲಾಗಿದೆ.",
        "created_multiple": "ಸರಿ, {count} ರಿಮೈಂಡರ್‌ಗಳನ್ನು ಹೊಂದಿಸಲಾಗಿದೆ.",
        "needs_confirmation_guess": "ಸಮಯ ಗೊತ್ತಿಲ್ಲದ ಕಾರಣ {title} ಅನ್ನು {time} ಹೊಂದಿಸಿದ್ದೇನೆ. ಬೇರೆ ಸಮಯ ಬೇಕಾದರೆ ತಿಳಿಸಿ.",
        "updated": "{title} ಅನ್ನು {time} ಬದಲಾಯಿಸಲಾಗಿದೆ.",
        "snoozed": "{title} ಅನ್ನು {minutes} ನಿಮಿಷಗಳ ಕಾಲ ಸ್ನೂಜ್ ಮಾಡಲಾಗಿದೆ.",
        "snoozed_until": "{title} ಅನ್ನು {minutes} ನಿಮಿಷಗಳ ಕಾಲ {until} ಸ್ನೂಜ್ ಮಾಡಲಾಗಿದೆ.",
        "done": "ಉತ್ತಮ, {title} ಮುಕ್ತಾಯಗೊಂಡಿದೆ ಎಂದು ಗುರುತಿಸಲಾಗಿದೆ! ✓",
        "done_recurring": "ಉತ್ತಮ, {title} ಮುಕ್ತಾಯಗೊಂಡಿದೆ! ಮುಂದಿನ ರಿಮೈಂಡರ್ {next_when}.",
        "cancelled": "{title} ರದ್ದುಗೊಳಿಸಲಾಗಿದೆ.",
        "cancel_closest": "ಆ ಕಾರ್ಯ ಕಂಡುಬಂದಿಲ್ಲ. ನೀವು '{closest}' ಅನ್ನು ಉಲ್ಲೇಖಿಸಿದ್ದೀರಾ?",
        "cancel_not_found": "ರದ್ದುಗೊಳಿಸಲು ಆ ಕಾರ್ಯ ಕಂಡುಬಂದಿಲ್ಲ.",
        "cancel_confirm_prompt": "ನಾನು {title} ಅನ್ನು ರದ್ದುಗೊಳಿಸಬೇಕೇ?",
        "cancel_want_confirm": "ನಾನು {title} ಅನ್ನು ರದ್ದುಗೊಳಿಸಬೇಕೆಂದು ನೀವು ಬಯಸುತ್ತೀರಾ?",
        "cancel_aborted_leave": "ಸರಿ, ನಾನು {title} ಅನ್ನು ಹಾಗೆಯೇ ಬಿಡುತ್ತೇನೆ.",
        "yes_to_what_no_pending": "ಯಾವುದಕ್ಕೆ ಹೌದು? ನನ್ನ ಬಳಿ ಯಾವುದೇ ಬಾಕಿ ಉಳಿದ ಪ್ರಶ್ನೆ ಇಲ್ಲ.",
        "ambiguous_which": "ನಿಮ್ಮ ಉದ್ದೇಶ ಯಾವುದು: {candidates}?",
        "already_done": "{title} ಈಗಾಗಲೇ ಮುಕ್ತಾಯಗೊಂಡಿದೆ.",
        "past_time_confirm": "ಆ ಸಮಯ ಈಗಾಗಲೇ ಮುಗಿದಿದೆ. ನಾನು ಅದನ್ನು ನಾಳೆಗೆ ಬದಲಾಯಿಸಬೇಕೆ?",
        "question_help": "ನಾನು ರಿಮೈಂಡರ್‌ಗಳನ್ನು ಹೊಂದಿಸಬಹುದು, ಮುಂದೂಡಬಹುದು, ಸ್ನೂಜ್ ಮಾಡಬಹುದು ಅಥವಾ ರದ್ದುಗೊಳಿಸಬಹುದು. ನೀವು ಏನು ಮಾಡಲು ಬಯಸುತ್ತೀರಿ?",
        "fallback_not_caught": "ಅದರಲ್ಲಿ ನನಗೆ ಯಾವುದೇ ಕಾರ್ಯ ಅಥವಾ ಸಮಯ ಕಂಡುಬಂದಿಲ್ಲ. ಉದಾಹರಣೆಗೆ 'ನಾಳೆ ಸಂಜೆ 5 ಗಂಟೆಗೆ ದಂತವೈದ್ಯರ ಭೇಟಿ' ಎಂದು ಹೇಳಿ ನೋಡಿ.",
        "needs_confirmation": "ನಾನು {title} ಅನ್ನು {time} ಹೊಂದಿಸಿದ್ದೇನೆ. ಇದು ಸರಿಹೊಂದುತ್ತದೆಯೇ ಎಂದು ದೃಢೀಕರಿಸಿ.",
        "fallback": "ಅದರಲ್ಲಿ ನನಗೆ ಯಾವುದೇ ಕಾರ್ಯ ಅಥವಾ ಸಮಯ ಕಂಡುಬಂದಿಲ್ಲ. ಉದಾಹರಣೆಗೆ 'ನಾಳೆ ಸಂಜೆ 5 ಗಂಟೆಗೆ ದಂತವೈದ್ಯರ ಭೇಟಿ' ಎಂದು ಹೇಳಿ ನೋಡಿ.",
        "reminder_prompt": "{title} — ಸಮಯ {time} ಆಗಿದೆ. ಮುಗಿದಿದೆಯೇ, ಸ್ನೂಜ್ ಮಾಡಬೇಕೇ ಅಥವಾ ನಾಳೆಗೆ ಮುಂದೂಡಬೇಕೇ?",
    },
}


_variant_counter = 0


def next_variant_index(modulo: int = 3) -> int:
    """Return deterministic variant index rotating across calls."""
    global _variant_counter
    idx = _variant_counter % modulo
    _variant_counter += 1
    return idx


def reset_variant_counter():
    """Reset rotating variant counter (primarily for test repeatability)."""
    global _variant_counter
    _variant_counter = 0


CREATED_SINGLE_VARIANTS = {
    "en": [
        "Okay, {title} {time_phrase}.",
        "Done. {title}, {time}.",
        "Got it, {title} {time_phrase}.",
    ],
    "hi": [
        "ठीक है, {title} का रिमाइंडर {time} सेट कर दिया गया है।",
        "हो गया, {title} {time} सेट कर दिया गया है।",
        "समझ गया, {title} {time} सेट हो गया।",
    ],
    "kn": [
        "ಸರಿ, {title} ರಿಮೈಂಡರ್ ಅನ್ನು {time} ಹೊಂದಿಸಲಾಗಿದೆ.",
        "ಆಯಿತು, {title} {time} ಹೊಂದಿಸಲಾಗಿದೆ.",
        "ಖಚಿತ, {title} {time} ಹೊಂದಿಸಲಾಗಿದೆ.",
    ],
}

NEEDS_CONF_GUESS_VARIANTS = {
    "en": [
        "I set {title} for {time}. Tell me if you want a different time.",
        "{title} set for {time}. Let me know if that works.",
        "Got it, {title} set for {time}. Tell me if you want another time.",
    ],
    "hi": [
        "{title} को {time} सेट किया है। अगर दूसरा समय चाहिए तो बताइए।",
        "{title} {time} सेट किया है। दूसरा समय चाहिए तो बताएँ।",
        "{title} को {time} सेट किया है। कोई और समय चाहिए तो बताइए।",
    ],
    "kn": [
        "{title} ಅನ್ನು {time} ಹೊಂದಿಸಿದ್ದೇನೆ. ಬೇರೆ ಸಮಯ ಬೇಕಾದರೆ ತಿಳಿಸಿ.",
        "{title} ಅನ್ನು {time} ನಿಗದಿಪಡಿಸಲಾಗಿದೆ. ಬೇರೆ ಸಮಯ ಬೇಕಾದರೆ ಹೇಳಿ.",
        "{title} {time} ಹೊಂದಿಸಲಾಗಿದೆ. ಬೇರೆ ಸಮಯ ಬೇಕಿದ್ದರೆ ತಿಳಿಸಿ.",
    ],
}

CREATED_MULTIPLE_VARIANTS = {
    "en": [
        "Okay, {count} reminders set.",
        "Done, {count} reminders set.",
        "Got it, {count} reminders set.",
    ],
    "hi": [
        "ठीक है, {count} रिमाइंडर सेट कर दिए गए हैं।",
        "हो गया, {count} रिमाइंडर सेट हो गए।",
        "समझ गया, {count} रिमाइंडर सेट कर दिए।",
    ],
    "kn": [
        "ಸರಿ, {count} ರಿಮೈಂಡರ್‌ಗಳನ್ನು ಹೊಂದಿಸಲಾಗಿದೆ.",
        "ಆಯಿತು, {count} ರಿಮೈಂಡರ್‌ಗಳನ್ನು ಹೊಂದಿಸಲಾಗಿದೆ.",
        "ಖಚಿತ, {count} ರಿಮೈಂಡರ್‌ಗಳನ್ನು ಹೊಂದಿಸಲಾಗಿದೆ.",
    ],
}

UPDATED_VARIANTS = {
    "en": [
        "Moved {title} to {time}.",
        "Okay, moved {title} to {time}.",
        "Done. {title} moved to {time}.",
    ],
    "hi": [
        "{title} को {time} शिफ्ट कर दिया गया है।",
        "ठीक है, {title} को {time} शिफ्ट कर दिया।",
        "हो गया, {title} को {time} कर दिया।",
    ],
    "kn": [
        "{title} ಅನ್ನು {time} ಬದಲಾಯಿಸಲಾಗಿದೆ.",
        "ಸರಿ, {title} ಅನ್ನು {time} ಬದಲಾಯಿಸಲಾಗಿದೆ.",
        "ಆಯಿತು, {title} ಅನ್ನು {time} ಮಾಡಲಾಗಿದೆ.",
    ],
}


def _format_time_phrase(when_str: str, language: str) -> str:
    """Helper to attach 'at' or 'for' cleanly to time expressions in English."""
    if language != "en":
        return when_str
    if when_str.startswith(("today at", "tomorrow at", "yesterday at")):
        return f"for {when_str}"
    return f"at {when_str}"


def get_template(category: str, language: str = "en") -> str:
    lang_dict = REPLIES.get(language, REPLIES["en"])
    return lang_dict.get(category, REPLIES["en"][category])


def _is_unparseable_guess(change: dict, language: str = "en") -> bool:
    """Return True only for fallback guesses where the phrase couldn't be parsed at all."""
    note = change.get("resolution_note") or ""
    return note.startswith("Could not parse")


def format_created(changes: list, language: str = "en", now: Optional[datetime] = None) -> str:
    """Format single or batch task creation/update confirmation with rotating short variants."""
    from timeutil import format_when
    created = [c for c in changes if c.get("type") == "created"]
    updated = [c for c in changes if c.get("type") in ("updated", "updated_duplicate")]

    if not created and not updated:
        return get_template("fallback_not_caught", language)

    count = len(created) + len(updated)
    if count == 1 and created:
        c = created[0]
        when_str = format_when(c.get("due_at"), now=now, language=language) if c.get("due_at") else "now"
        if c.get("needs_confirmation"):
            tmpl_list = NEEDS_CONF_GUESS_VARIANTS.get(language, NEEDS_CONF_GUESS_VARIANTS["en"])
            v_idx = next_variant_index(len(tmpl_list))
            return tmpl_list[v_idx].format(title=c["title"], time=when_str)
        else:
            tmpl_list = CREATED_SINGLE_VARIANTS.get(language, CREATED_SINGLE_VARIANTS["en"])
            v_idx = next_variant_index(len(tmpl_list))
            time_phrase = _format_time_phrase(when_str, language)
            return tmpl_list[v_idx].format(title=c["title"], time=when_str, time_phrase=time_phrase)

    elif count == 1 and updated:
        c = updated[0]
        when_str = format_when(c.get("due_at"), now=now, language=language) if c.get("due_at") else "now"
        tmpl_list = UPDATED_VARIANTS.get(language, UPDATED_VARIANTS["en"])
        v_idx = next_variant_index(len(tmpl_list))
        return tmpl_list[v_idx].format(title=c["title"], time=when_str)

    elif len(created) == 0 and len(updated) > 1:
        if language == "hi":
            return f"{count} रिमाइंडर अपडेट कर दिए गए हैं।"
        elif language == "kn":
            return f"{count} ರಿಮೈಂಡರ್‌ಗಳನ್ನು ಬದಲಾಯಿಸಲಾಗಿದೆ."
        return f"Moved {count} reminders."

    tmpl_list = CREATED_MULTIPLE_VARIANTS.get(language, CREATED_MULTIPLE_VARIANTS["en"])
    v_idx = next_variant_index(len(tmpl_list))
    base = tmpl_list[v_idx].format(count=count)

    # Append a short spoken note only if an unparseable phrase was present
    all_items = created + updated
    guess_items = [c for c in all_items if _is_unparseable_guess(c, language)]
    if guess_items:
        guess_notes = []
        for c in guess_items:
            when_str = format_when(c.get("due_at"), now=now, language=language) if c.get("due_at") else "now"
            if language == "hi":
                guess_notes.append(f"{c['title']} का समय मुझे पता नहीं था, {when_str} लगाया।")
            elif language == "kn":
                guess_notes.append(f"{c['title']} ಸಮಯ ಗೊತ್ತಿಲ್ಲದ ಕಾರಣ {when_str} ಹೊಂದಿಸಿದ್ದೇನೆ.")
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
        until_disp = until
        if language == "kn" and until.endswith("ಗಂಟೆಗೆ"):
            # TODO: Review Kannada until phrasing (ಗಂಟೆಗೆ ವರೆಗೆ vs ಗಂಟೆಯವರೆಗೆ)
            until_disp = until[:-6] + "ಗಂಟೆಯವರೆಗೆ"
        tmpl = get_template("snoozed_until", language)
        return tmpl.format(title=title, minutes=minutes, until=until_disp)
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


def format_already_done(title: str, language: str = "en") -> str:
    tmpl = get_template("already_done", language)
    return tmpl.format(title=title)


def format_rescheduled(title: str, time_str: str, language: str = "en") -> str:
    tmpl = get_template("updated", language)
    return tmpl.format(title=title, time=time_str)


def format_reminder_prompt(title: str, time_input, language: str = "en") -> str:
    from timeutil import format_time_for_reminder
    time_str = format_time_for_reminder(time_input, language)
    tmpl = get_template("reminder_prompt", language)
    return tmpl.format(title=title, time=time_str)


def format_cancel_confirm_prompt(title: str, language: str = "en") -> str:
    tmpl = get_template("cancel_confirm_prompt", language)
    return tmpl.format(title=title)


def format_cancel_want_confirm(title: str, language: str = "en") -> str:
    tmpl = get_template("cancel_want_confirm", language)
    return tmpl.format(title=title)


def format_cancel_aborted_leave(title: str, language: str = "en") -> str:
    tmpl = get_template("cancel_aborted_leave", language)
    return tmpl.format(title=title)


def format_yes_to_what_no_pending(language: str = "en") -> str:
    return get_template("yes_to_what_no_pending", language)


def format_past_time_confirm(language: str = "en") -> str:
    return get_template("past_time_confirm", language)


def format_question_help(language: str = "en") -> str:
    return get_template("question_help", language)


def format_fallback(language: str = "en") -> str:
    return get_template("fallback_not_caught", language)
