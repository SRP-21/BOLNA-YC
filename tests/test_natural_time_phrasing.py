"""
Tests for Stage 4 (Fix C): Natural Hindi and Kannada time phrasing.
- 09:00, 12:30, 18:00, 19:30, 23:00 in Hindi (hi) and Kannada (kn).
- "आज/कल <सुबह|दोपहर|शाम|रात> <H> बजे", dropping :00, "साढ़े <H>" at :30.
- "ಇಂದು/ನಾಳೆ <ಬೆಳಿಗ್ಗೆ|ಮಧ್ಯಾಹ್ನ|ಸಂಜೆ|ರಾತ್ರಿ> <H> ಗಂಟೆಗೆ", dropping :00.
- Never prints "AM" or "PM" in hi or kn spoken text.
- English phrasing remains unchanged.
- Templates integration: created, moved, snoozed, reminder prompt.
"""
import pytest
from datetime import datetime, timezone
from timeutil import IST, format_when, format_time_spoken, format_time_for_reminder
from agent.replies import (
    format_created, format_rescheduled, format_snoozed,
    format_reminder_prompt, format_done
)

FROZEN_NOW = datetime(2026, 10, 31, 8, 0, 0, tzinfo=IST)  # Saturday 8:00 AM IST
TOMORROW_DATE = datetime(2026, 11, 1).date()
TODAY_DATE = datetime(2026, 10, 31).date()


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
        for minute in (0, 15, 30, 45):
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


def test_template_integrations():
    """Verify templates (created, updated, snoozed, reminder prompt) use natural Indic time."""
    dt_9am = datetime(2026, 11, 1, 9, 0, 0, tzinfo=IST)
    dt_6pm = datetime(2026, 10, 31, 18, 0, 0, tzinfo=IST)

    # 1. Created single
    hi_created = format_created([{"type": "created", "title": "Doctor", "due_at": dt_9am.isoformat()}], language="hi", now=FROZEN_NOW)
    assert "Doctor का रिमाइंडर कल सुबह 9 बजे सेट कर दिया गया है।" in hi_created

    kn_created = format_created([{"type": "created", "title": "Doctor", "due_at": dt_9am.isoformat()}], language="kn", now=FROZEN_NOW)
    assert "Doctor ರಿಮೈಂಡರ್ ಅನ್ನು ನಾಳೆ ಬೆಳಿಗ್ಗೆ 9 ಗಂಟೆಗೆ ಹೊಂದಿಸಲಾಗಿದೆ." in kn_created

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
    assert "Gym को 10 मिनट के लिए स्नूज़ कर दिया गया है, आज शाम 6:10 बजे तक।" == hi_snooze

    until_kn = format_when(dt_until, now=FROZEN_NOW, language="kn")
    kn_snooze = format_snoozed("Gym", 10, language="kn", until=until_kn)
    assert "Gym ಅನ್ನು 10 ನಿಮಿಷಗಳ ಕಾಲ ಇಂದು ಸಂಜೆ 6:10 ಗಂಟೆಯವರೆಗೆ ಸ್ನೂಜ್ ಮಾಡಲಾಗಿದೆ." == kn_snooze
