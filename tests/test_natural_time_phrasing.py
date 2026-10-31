"""
Tests for Stage 4 (Fix C): Natural Hindi and Kannada time phrasing.
- 09:00, 12:30, 18:00, 19:30, 23:00 in Hindi (hi) and Kannada (kn).
- Refined Hindi phrasing:
  - 1:30 -> "डेढ़ बजे", 2:30 -> "ढाई बजे", other :30 stay "साढ़े <H> बजे".
  - :15 -> "सवा <H> बजे".
  - :45 -> "पौने <H+1> बजे" (with 12:45 -> "पौने एक बजे").
  - other minutes -> "<H> बजकर <M> मिनट".
  - reminder prompt: hour 1 uses singular "बज गया है", others use "बज गए हैं".
- Kannada:
  - "ಇಂದು/ನಾಳೆ <ಬೆಳಿಗ್ಗೆ|ಮಧ್ಯಾಹ್ನ|ಸಂಜೆ|ರಾತ್ರಿ> <H> ಗಂಟೆಗೆ", dropping :00.
- Never prints "AM" or "PM" in hi or kn spoken text.
- English phrasing remains unchanged.
- Templates integration: created, moved, snoozed, reminder prompt.
"""
import pytest
from datetime import datetime
from timeutil import IST, format_when, format_time_spoken, format_time_for_reminder
from agent.replies import (
    format_created, format_rescheduled, format_snoozed,
    format_reminder_prompt
)

FROZEN_NOW = datetime(2026, 10, 31, 8, 0, 0, tzinfo=IST)  # Saturday 8:00 AM IST


def test_time_of_day_spoken_phrases():
    """Verify expected spoken strings for 09:00, 12:30, 18:00, 19:30, 23:00 in hi and kn."""
    times = [
        (datetime(2026, 10, 31, 9, 0, 0, tzinfo=IST), "सुबह 9 बजे", "ಬೆಳಿಗ್ಗೆ 9 ಗಂಟೆಗೆ"),
        (datetime(2026, 10, 31, 12, 30, 0, tzinfo=IST), "दोपहर साढ़े 12 बजे", "ಮಧ್ಯಾಹ್ನ 12:30 ಗಂಟೆಗೆ"),
        (datetime(2026, 10, 31, 18, 0, 0, tzinfo=IST), "शाम 6 बजे", "ಸಂಜೆ 6 ಗಂಟೆಗೆ"),
        (datetime(2026, 10, 31, 19, 30, 0, tzinfo=IST), "शाम साढ़े 7 बजे", "ಸಂಜೆ 7:30 ಗಂಟೆಗೆ"),
        (datetime(2026, 10, 31, 23, 0, 0, tzinfo=IST), "रात 11 बजे", "ರಾತ್ರಿ 11 ಗಂಟೆಗೆ"),
    ]

    for dt, expected_hi, expected_kn in times:
        assert format_time_spoken(dt, language="hi") == expected_hi
        assert format_time_spoken(dt, language="kn") == expected_kn


def test_refined_hindi_time_cases():
    """Verify refined Hindi phrasing: 1:30 (डेढ़), 2:30 (ढाई), :15 (सवा), :45 (पौने), and other minutes."""
    # 1:30 and 2:30
    dt_130 = datetime(2026, 10, 31, 13, 30, 0, tzinfo=IST)
    dt_230 = datetime(2026, 10, 31, 14, 30, 0, tzinfo=IST)
    assert format_time_spoken(dt_130, language="hi") == "दोपहर डेढ़ बजे"
    assert format_time_spoken(dt_230, language="hi") == "दोपहर ढाई बजे"

    # :15 (सवा)
    dt_915 = datetime(2026, 10, 31, 9, 15, 0, tzinfo=IST)
    dt_115 = datetime(2026, 10, 31, 13, 15, 0, tzinfo=IST)
    assert format_time_spoken(dt_915, language="hi") == "सुबह सवा 9 बजे"
    assert format_time_spoken(dt_115, language="hi") == "दोपहर सवा 1 बजे"

    # :45 (पौने <H+1>, 12:45 -> पौने एक)
    dt_1245 = datetime(2026, 10, 31, 12, 45, 0, tzinfo=IST)
    dt_845 = datetime(2026, 10, 31, 8, 45, 0, tzinfo=IST)
    assert format_time_spoken(dt_1245, language="hi") == "दोपहर पौने एक बजे"
    assert format_time_spoken(dt_845, language="hi") == "सुबह पौने 9 बजे"

    # other minutes: <H> बजकर <M> मिनट
    dt_910 = datetime(2026, 10, 31, 9, 10, 0, tzinfo=IST)
    dt_605 = datetime(2026, 10, 31, 18, 5, 0, tzinfo=IST)
    assert format_time_spoken(dt_910, language="hi") == "सुबह 9 बजकर 10 मिनट"
    assert format_time_spoken(dt_605, language="hi") == "शाम 6 बजकर 5 मिनट"


def test_format_when_tomorrow_phrases():
    """Verify format_when for tomorrow across all 5 key times."""
    times = [
        (datetime(2026, 11, 1, 9, 0, 0, tzinfo=IST), "कल सुबह 9 बजे", "ನಾಳೆ ಬೆಳಿಗ್ಗೆ 9 ಗಂಟೆಗೆ"),
        (datetime(2026, 11, 1, 12, 30, 0, tzinfo=IST), "कल दोपहर साढ़े 12 बजे", "ನಾಳೆ ಮಧ್ಯಾಹ್ನ 12:30 ಗಂಟೆಗೆ"),
        (datetime(2026, 11, 1, 18, 0, 0, tzinfo=IST), "कल शाम 6 बजे", "ನಾಳೆ ಸಂಜೆ 6 ಗಂಟೆಗೆ"),
        (datetime(2026, 11, 1, 19, 30, 0, tzinfo=IST), "कल शाम साढ़े 7 बजे", "ನಾಳೆ ಸಂಜೆ 7:30 ಗಂಟೆಗೆ"),
        (datetime(2026, 11, 1, 23, 0, 0, tzinfo=IST), "कल रात 11 बजे", "ನಾಳೆ ರಾತ್ರಿ 11 ಗಂಟೆಗೆ"),
    ]

    for dt, expected_hi, expected_kn in times:
        assert format_when(dt, now=FROZEN_NOW, language="hi") == expected_hi
        assert format_when(dt, now=FROZEN_NOW, language="kn") == expected_kn


def test_format_when_today_phrases():
    """Verify format_when for today across all 5 key times."""
    times = [
        (datetime(2026, 10, 31, 9, 0, 0, tzinfo=IST), "आज सुबह 9 बजे", "ಇಂದು ಬೆಳಿಗ್ಗೆ 9 ಗಂಟೆಗೆ"),
        (datetime(2026, 10, 31, 12, 30, 0, tzinfo=IST), "आज दोपहर साढ़े 12 बजे", "ಇಂದು ಮಧ್ಯಾಹ್ನ 12:30 ಗಂಟೆಗೆ"),
        (datetime(2026, 10, 31, 18, 0, 0, tzinfo=IST), "आज शाम 6 बजे", "ಇಂದು ಸಂಜೆ 6 ಗಂಟೆಗೆ"),
        (datetime(2026, 10, 31, 19, 30, 0, tzinfo=IST), "आज शाम साढ़े 7 बजे", "ಇಂದು ಸಂಜೆ 7:30 ಗಂಟೆಗೆ"),
        (datetime(2026, 10, 31, 23, 0, 0, tzinfo=IST), "आज रात 11 बजे", "ಇಂದು ರಾತ್ರಿ 11 ಗಂಟೆಗೆ"),
    ]

    for dt, expected_hi, expected_kn in times:
        assert format_when(dt, now=FROZEN_NOW, language="hi") == expected_hi
        assert format_when(dt, now=FROZEN_NOW, language="kn") == expected_kn


def test_never_prints_am_pm_in_hi_or_kn():
    """Exhaustively verify that AM/PM never appears in any hi or kn time phrase across all 24 hours."""
    for hour in range(24):
        for minute in (0, 5, 10, 15, 30, 45, 55):
            dt = datetime(2026, 11, 1, hour, minute, 0, tzinfo=IST)
            for lang in ("hi", "kn"):
                spoken = format_time_spoken(dt, language=lang)
                when = format_when(dt, now=FROZEN_NOW, language=lang)
                reminder = format_time_for_reminder(dt, language=lang)

                assert "AM" not in spoken, f"Found AM in spoken {lang}: {spoken}"
                assert "PM" not in spoken, f"Found PM in spoken {lang}: {spoken}"
                assert "AM" not in when, f"Found AM in when {lang}: {when}"
                assert "PM" not in when, f"Found PM in when {lang}: {when}"
                assert "AM" not in reminder, f"Found AM in reminder {lang}: {reminder}"
                assert "PM" not in reminder, f"Found PM in reminder {lang}: {reminder}"


def test_english_time_unchanged():
    """Verify English retains original format with AM/PM."""
    dt_morning = datetime(2026, 11, 1, 9, 0, 0, tzinfo=IST)
    dt_evening = datetime(2026, 10, 31, 18, 0, 0, tzinfo=IST)

    assert format_when(dt_morning, now=FROZEN_NOW, language="en") == "tomorrow at 9:00 AM"
    assert format_when(dt_evening, now=FROZEN_NOW, language="en") == "today at 6:00 PM"


def test_reminder_prompt_grammar_singular_plural():
    """Verify hour 1 uses singular 'बज गया है' and other hours use 'बज गए हैं'."""
    dt_1pm = datetime(2026, 10, 31, 13, 0, 0, tzinfo=IST)
    dt_130pm = datetime(2026, 10, 31, 13, 30, 0, tzinfo=IST)
    dt_230pm = datetime(2026, 10, 31, 14, 30, 0, tzinfo=IST)
    dt_6pm = datetime(2026, 10, 31, 18, 0, 0, tzinfo=IST)
    dt_1230pm = datetime(2026, 10, 31, 12, 30, 0, tzinfo=IST)

    # Hour 1 singular
    prompt_1pm = format_reminder_prompt("Lunch", dt_1pm, language="hi")
    assert prompt_1pm == "Lunch — दोपहर 1 बज गया है। क्या यह पूरा हो गया, स्नूज़ करना है, या कल के लिए टालें?"

    prompt_130pm = format_reminder_prompt("Lunch", dt_130pm, language="hi")
    assert prompt_130pm == "Lunch — दोपहर डेढ़ बज गया है। क्या यह पूरा हो गया, स्नूज़ करना है, या कल के लिए टालें?"

    dt_1315 = datetime(2026, 10, 31, 13, 15, 0, tzinfo=IST)
    prompt_1315 = format_reminder_prompt("Doctor", dt_1315, language="hi")
    assert prompt_1315 == "Doctor — दोपहर सवा 1 बज गया है। क्या यह पूरा हो गया, स्नूज़ करना है, या कल के लिए टालें?"

    dt_1245 = datetime(2026, 10, 31, 12, 45, 0, tzinfo=IST)
    prompt_1245 = format_reminder_prompt("Lunch", dt_1245, language="hi")
    assert prompt_1245 == "Lunch — दोपहर पौने एक बज गया है। क्या यह पूरा हो गया, स्नूज़ करना है, या कल के लिए टालें?"

    # Odd-minute prompts joining "बजकर <M> मिनट" with "हो गए हैं"
    dt_910am = datetime(2026, 10, 31, 9, 10, 0, tzinfo=IST)
    prompt_910am = format_reminder_prompt("Standup", dt_910am, language="hi")
    assert prompt_910am == "Standup — सुबह 9 बजकर 10 मिनट हो गए हैं। क्या यह पूरा हो गया, स्नूज़ करना है, या कल के लिए टालें?"

    dt_605pm = datetime(2026, 10, 31, 18, 5, 0, tzinfo=IST)
    prompt_605pm = format_reminder_prompt("Gym", dt_605pm, language="hi")
    assert prompt_605pm == "Gym — शाम 6 बजकर 5 मिनट हो गए हैं। क्या यह पूरा हो गया, स्नूज़ करना है, या कल के लिए टालें?"

    # Other hours plural
    prompt_230pm = format_reminder_prompt("Meeting", dt_230pm, language="hi")
    assert prompt_230pm == "Meeting — दोपहर ढाई बज गए हैं। क्या यह पूरा हो गया, स्नूज़ करना है, या कल के लिए टालें?"

    prompt_6pm = format_reminder_prompt("Gym", dt_6pm, language="hi")
    assert prompt_6pm == "Gym — शाम 6 बज गए हैं। क्या यह पूरा हो गया, स्नूज़ करना है, या कल के लिए टालें?"

    prompt_1230pm = format_reminder_prompt("Doctor", dt_1230pm, language="hi")
    assert prompt_1230pm == "Doctor — दोपहर साढ़े 12 बज गए हैं। क्या यह पूरा हो गया, स्नूज़ करना है, या कल के लिए टालें?"


def test_template_integrations():
    """Verify templates (created, updated, snoozed, reminder prompt) use natural Indic time."""
    dt_9am = datetime(2026, 11, 1, 9, 0, 0, tzinfo=IST)
    dt_6pm = datetime(2026, 10, 31, 18, 0, 0, tzinfo=IST)

    # 1. Created single
    hi_created = format_created([{"type": "created", "title": "Doctor", "due_at": dt_9am.isoformat()}], language="hi", now=FROZEN_NOW)
    assert "Doctor" in hi_created and "कल सुबह 9 बजे" in hi_created

    kn_created = format_created([{"type": "created", "title": "Doctor", "due_at": dt_9am.isoformat()}], language="kn", now=FROZEN_NOW)
    assert "Doctor" in kn_created and "ನಾಳೆ ಬೆಳಿಗ್ಗೆ 9 ಗಂಟೆಗೆ" in kn_created

    # 2. Updated
    hi_updated = format_rescheduled("Gym", format_when(dt_6pm, now=FROZEN_NOW, language="hi"), language="hi")
    assert "Gym को आज शाम 6 बजे शिफ्ट कर दिया गया है।" in hi_updated

    kn_updated = format_rescheduled("Gym", format_when(dt_6pm, now=FROZEN_NOW, language="kn"), language="kn")
    assert "Gym ಅನ್ನು ಇಂದು ಸಂಜೆ 6 ಗಂಟೆಗೆ ಬದಲಾಯಿಸಲಾಗಿದೆ." in kn_updated

    # 3. Reminder prompts
    hi_prompt = format_reminder_prompt("Gym", dt_6pm, language="hi")
    assert "Gym — शाम 6 बज गए हैं। क्या यह पूरा हो गया, स्नूज़ करना है, या कल के लिए टालें?" == hi_prompt

    kn_prompt = format_reminder_prompt("Gym", dt_6pm, language="kn")
    assert "Gym — ಸಮಯ ಸಂಜೆ 6 ಗಂಟೆ ಆಗಿದೆ. ಮುಗಿದಿದೆಯೇ, ಸ್ನೂಜ್ ಮಾಡಬೇಕೇ ಅಥವಾ ನಾಳೆಗೆ ಮುಂದೂಡಬೇಕೇ?" == kn_prompt

    # 4. Snoozed until
    dt_until = datetime(2026, 10, 31, 18, 10, 0, tzinfo=IST)
    until_hi = format_when(dt_until, now=FROZEN_NOW, language="hi")
    hi_snooze = format_snoozed("Gym", 10, language="hi", until=until_hi)
    assert "Gym को 10 मिनट के लिए स्नूज़ कर दिया गया है, आज शाम 6 बजकर 10 मिनट तक।" == hi_snooze

    until_kn = format_when(dt_until, now=FROZEN_NOW, language="kn")
    kn_snooze = format_snoozed("Gym", 10, language="kn", until=until_kn)
    assert "Gym ಅನ್ನು 10 ನಿಮಿಷಗಳ ಕಾಲ ಇಂದು ಸಂಜೆ 6:10 ಗಂಟೆಯವರೆಗೆ ಸ್ನೂಜ್ ಮಾಡಲಾಗಿದೆ." == kn_snooze
