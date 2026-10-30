"""
Localized reply templates for Indic multilingual voice assistant (English, Hindi, Kannada).
Hindi/Hinglish uses Devanagari script for accurate Edge TTS pronunciation.
Kannada uses Kannada script.
"""

REPLIES = {
    "en": {
        "created_single": "Got it, reminder set: {title} at {time}.",
        "created_multiple": "Got it, {count} reminders set: {items}.",
        "updated": "Moved {title} to {time}.",
        "snoozed": "Snoozed {title} for {minutes} minutes.",
        "done": "Great, {title} marked as done! ✓",
        "cancelled": "Cancelled {title}.",
        "needs_confirmation": "I've set {title} for {time}. Please confirm if that works.",
        "fallback": "I'm listening. Tell me what tasks you'd like to schedule!",
        "reminder_prompt": "{title} — it's {time}. Done, snooze, or move to tomorrow?",
    },
    "hi": {
        "created_single": "ठीक है, {title} का रिमाइंडर {time} बजे सेट कर दिया गया है।",
        "created_multiple": "ठीक है, {count} रिमाइंडर सेट कर दिए गए हैं: {items}।",
        "updated": "{title} को {time} पर शिफ्ट कर दिया गया है।",
        "snoozed": "{title} को {minutes} मिनट के लिए स्नूज़ कर दिया गया है।",
        "done": "बहुत बढ़िया, {title} पूरा हो गया! ✓",
        "cancelled": "{title} रद्द कर दिया गया है।",
        "needs_confirmation": "मैंने {title} {time} पर सेट किया है। कृपया पुष्टि करें कि क्या यह समय सही है।",
        "fallback": "मैं सुन रहा हूँ। बताइए आप क्या शेड्यूल करना चाहते हैं!",
        "reminder_prompt": "{title} — {time} बज गए हैं। क्या यह पूरा हो गया, स्नूज़ करना है, या कल के लिए टालें?",
    },
    "kn": {
        "created_single": "ಸರಿ, {title} ರಿಮೈಂಡರ್ ಅನ್ನು {time} ಕ್ಕೆ ಹೊಂದಿಸಲಾಗಿದೆ.",
        "created_multiple": "ಸರಿ, {count} ರಿಮೈಂಡರ್‌ಗಳನ್ನು ಹೊಂದಿಸಲಾಗಿದೆ: {items}.",
        "updated": "{title} ಅನ್ನು {time} ಕ್ಕೆ ಬದಲಾಯಿಸಲಾಗಿದೆ.",
        "snoozed": "{title} ಅನ್ನು {minutes} ನಿಮಿಷಗಳ ಕಾಲ ಸ್ನೂಜ್ ಮಾಡಲಾಗಿದೆ.",
        "done": "ಉತ್ತಮ, {title} ಮುಕ್ತಾಯಗೊಂಡಿದೆ ಎಂದು ಗುರುತಿಸಲಾಗಿದೆ! ✓",
        "cancelled": "{title} ರದ್ದುಗೊಳಿಸಲಾಗಿದೆ.",
        "needs_confirmation": "ನಾನು {title} ಅನ್ನು {time} ಕ್ಕೆ ಹೊಂದಿಸಿದ್ದೇನೆ. ಇದು ಸರಿಹೊಂದುತ್ತದೆಯೇ ಎಂದು ದೃಢೀಕರಿಸಿ.",
        "fallback": "ನಾನು ಕೇಳುತ್ತಿದ್ದೇನೆ. ನೀವು ಯಾವ ಕಾರ್ಯಗಳನ್ನು ನಿಗದಿಪಡಿಸಲು ಬಯಸುತ್ತೀರಿ ಎಂದು ತಿಳಿಸಿ!",
        "reminder_prompt": "{title} — ಸಮಯ {time} ಆಗಿದೆ. ಮುಗಿದಿದೆಯೇ, ಸ್ನೂಜ್ ಮಾಡಬೇಕೇ ಅಥವಾ ನಾಳೆಗೆ ಮುಂದೂಡಬೇಕೇ?",
    },
}


def get_template(category: str, language: str = "en") -> str:
    lang_dict = REPLIES.get(language, REPLIES["en"])
    return lang_dict.get(category, REPLIES["en"][category])


def format_created(changes: list, language: str = "en") -> str:
    """Format single or batch task creation/update confirmation."""
    created = [c for c in changes if c.get("type") == "created"]
    updated = [c for c in changes if c.get("type") in ("updated", "updated_duplicate")]

    if not created and not updated:
        return get_template("fallback", language)

    # All items
    item_strings = []
    for c in created:
        from datetime import datetime as dt
        due_str = dt.fromisoformat(c["due_at"]).strftime("%I:%M %p") if c.get("due_at") else "now"
        item_strings.append(f"{c['title']} at {due_str}")

    for c in updated:
        from datetime import datetime as dt
        due_str = dt.fromisoformat(c["due_at"]).strftime("%I:%M %p") if c.get("due_at") else "now"
        if language == "hi":
            item_strings.append(f"{c['title']} {due_str} पर")
        elif language == "kn":
            item_strings.append(f"{c['title']} {due_str} ಕ್ಕೆ")
        else:
            item_strings.append(f"{c['title']} moved to {due_str}")

    count = len(created) + len(updated)
    if count == 1 and created:
        c = created[0]
        from datetime import datetime as dt
        due_str = dt.fromisoformat(c["due_at"]).strftime("%I:%M %p") if c.get("due_at") else "now"
        tmpl = get_template("created_single", language)
        return tmpl.format(title=c["title"], time=due_str)
    elif count == 1 and updated:
        c = updated[0]
        from datetime import datetime as dt
        due_str = dt.fromisoformat(c["due_at"]).strftime("%I:%M %p") if c.get("due_at") else "now"
        tmpl = get_template("updated", language)
        return tmpl.format(title=c["title"], time=due_str)

    tmpl = get_template("created_multiple", language)
    return tmpl.format(count=count, items=", ".join(item_strings))


def format_snoozed(title: str, minutes: int, language: str = "en") -> str:
    tmpl = get_template("snoozed", language)
    return tmpl.format(title=title, minutes=minutes)


def format_done(title: str, language: str = "en") -> str:
    tmpl = get_template("done", language)
    return tmpl.format(title=title)


def format_cancelled(title: str, language: str = "en") -> str:
    tmpl = get_template("cancelled", language)
    return tmpl.format(title=title)


def format_rescheduled(title: str, time_str: str, language: str = "en") -> str:
    tmpl = get_template("updated", language)
    return tmpl.format(title=title, time=time_str)


def format_reminder_prompt(title: str, time_str: str, language: str = "en") -> str:
    tmpl = get_template("reminder_prompt", language)
    return tmpl.format(title=title, time=time_str)
