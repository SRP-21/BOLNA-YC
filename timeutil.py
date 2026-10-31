"""
Timezone utilities and conventions.

CONVENTION:
- Task.due_at is stored in SQLite as NAIVE IST (Asia/Kolkata) wall-clock time.
- Task.created_at, Task.updated_at, Event.ts, and Utterance.ts are stored as UTC.
- Use now_ist() for the current time in IST (timezone-aware).
- Use to_ist_naive(dt) when writing due_at to the database.
- Use ensure_ist(dt) when reading due_at from the database or preparing it for scheduler/comparison.
"""
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo
from config import settings

IST = ZoneInfo(settings.default_timezone)


def now_ist() -> datetime:
    """Return the current time in IST (timezone-aware)."""
    return datetime.now(IST)


def to_ist_naive(dt: Optional[datetime]) -> Optional[datetime]:
    """
    Convert any datetime (aware UTC, aware IST, or naive IST) to naive IST wall-clock time.
    If naive, assumes it is already IST wall-clock time and returns it naive.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    # If timezone-aware, convert to IST then remove tzinfo
    return dt.astimezone(IST).replace(tzinfo=None)


def ensure_ist(dt: Optional[datetime]) -> Optional[datetime]:
    """
    Ensure a datetime is timezone-aware in IST.
    If naive, attaches the IST timezone.
    If aware, converts to IST timezone.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=IST)
    return dt.astimezone(IST)


HI_WEEKDAYS = {
    "Monday": "सोमवार", "Tuesday": "मंगलवार", "Wednesday": "बुधवार",
    "Thursday": "गुरुवार", "Friday": "शुक्रवार", "Saturday": "शनिवार", "Sunday": "रविवार"
}
KN_WEEKDAYS = {
    "Monday": "ಸೋಮವಾರ", "Tuesday": "ಮಂಗಳವಾರ", "Wednesday": "ಬುಧವಾರ",
    "Thursday": "ಗುರುವಾರ", "Friday": "ಶುಕ್ರವಾರ", "Saturday": "ಶನಿವಾರ", "Sunday": "ಭಾನುವಾರ"
}
HI_MONTHS = {
    "January": "जनवरी", "February": "फ़रवरी", "March": "मार्च", "April": "अप्रैल",
    "May": "मई", "June": "जून", "July": "जुलाई", "August": "अगस्त",
    "September": "सितंबर", "October": "अक्टूबर", "November": "नवंबर", "December": "दिसंबर"
}
KN_MONTHS = {
    "January": "ಜನವರಿ", "February": "ಫೆಬ್ರವರಿ", "March": "ಮಾರ್ಚ್", "April": "ಏಪ್ರಿಲ್",
    "May": "ಮೇ", "June": "ಜೂನ್", "July": "ಜುಲೈ", "August": "ಆಗಸ್ಟ್",
    "September": "ಸೆಪ್ಟೆಂಬರ್", "October": "ಅಕ್ಟೋಬರ್", "November": "ನವೆಂಬರ್", "December": "ಡಿಸೆಂಬರ್"
}


def get_period_of_day(hour: int, language: str = "hi") -> str:
    """
    Return localized period of day.
    04:00 - 11:59: सुबह (hi) / ಬೆಳಿಗ್ಗೆ (kn)
    12:00 - 15:59: दोपहर (hi) / ಮಧ್ಯಾಹ್ನ (kn)
    16:00 - 20:59: शाम (hi) / ಸಂಜೆ (kn)
    21:00 - 03:59: रात (hi) / ರಾತ್ರಿ (kn)
    # TODO: Review 16:00 cutoff between afternoon and evening for Indic speech
    """
    if 4 <= hour < 12:
        return "सुबह" if language == "hi" else "ಬೆಳಿಗ್ಗೆ"
    elif 12 <= hour < 16:
        return "दोपहर" if language == "hi" else "ಮಧ್ಯಾಹ್ನ"
    elif 16 <= hour < 21:
        return "शाम" if language == "hi" else "ಸಂಜೆ"
    else:
        return "रात" if language == "hi" else "ರಾತ್ರಿ"


def format_time_hindi(dt: datetime) -> str:
    """
    Hindi time of day:
    - Drops minutes when :00 ('सुबह 9 बजे', 'शाम 6 बजे')
    - 1:30 -> 'डेढ़ बजे', 2:30 -> 'ढाई बजे'
    - Other :30 stay 'साढ़े <H> बजे' ('दोपहर साढ़े 12 बजे', 'शाम साढ़े 7 बजे')
    - :15 -> 'सवा <H> बजे' ('सुबह सवा 9 बजे')
    - :45 -> 'पौने <H+1> बजे' (12:45 -> 'पौने एक बजे')
    - Any other minutes -> '<H> बजकर <M> मिनट'
    - Never outputs AM or PM.
    """
    period = get_period_of_day(dt.hour, language="hi")
    h = dt.hour % 12
    if h == 0:
        h = 12
    m = dt.minute

    if m == 0:
        return f"{period} {h} बजे"
    elif m == 30:
        if h == 1:
            return f"{period} डेढ़ बजे"
        elif h == 2:
            return f"{period} ढाई बजे"
        else:
            return f"{period} साढ़े {h} बजे"
    elif m == 15:
        return f"{period} सवा {h} बजे"
    elif m == 45:
        next_h = 1 if h == 12 else (h + 1)
        next_h_str = "एक" if next_h == 1 else str(next_h)
        return f"{period} पौने {next_h_str} बजे"
    else:
        return f"{period} {h} बजकर {m} मिनट"


def format_time_kannada(dt: datetime) -> str:
    """
    Kannada time of day:
    - Drops :00 ('ಬೆಳಿಗ್ಗೆ 9 ಗಂಟೆಗೆ', 'ಸಂಜೆ 6 ಗಂಟೆಗೆ')
    - Formats minutes without AM or PM ('ಮಧ್ಯಾಹ್ನ 12:30 ಗಂಟೆಗೆ', 'ಸಂಜೆ 7:30 ಗಂಟೆಗೆ')
    - Never outputs AM or PM.
    """
    period = get_period_of_day(dt.hour, language="kn")
    h = dt.hour % 12
    if h == 0:
        h = 12
    m = dt.minute
    if m == 0:
        return f"{period} {h} ಗಂಟೆಗೆ"
    else:
        return f"{period} {h}:{m:02d} ಗಂಟೆಗೆ"


def format_time_spoken(dt: Optional[datetime], language: str = "en") -> str:
    """
    Format time of day for speech without AM/PM for Hindi and Kannada.
    English keeps AM/PM.
    """
    if dt is None:
        return "now"
    dt_ist = ensure_ist(dt)
    if language == "hi":
        return format_time_hindi(dt_ist)
    elif language == "kn":
        return format_time_kannada(dt_ist)
    else:
        return dt_ist.strftime('%I:%M %p').lstrip('0')


def format_time_for_reminder(dt_or_str, language: str = "en") -> str:
    """
    Format time specifically for reminder prompts:
    - hi: hour 1 uses singular 'बज गया है', others use 'बज गए हैं'
    - kn: 'ಸಮಯ {time} ಆಗಿದೆ' -> time is 'ಬೆಳಿಗ್ಗೆ 9 ಗಂಟೆ', 'ಸಂಜೆ 6 ಗಂಟೆ'
    - en: 'it's {time}' -> time is '6:00 PM'
    """
    dt = None
    if isinstance(dt_or_str, datetime):
        dt = ensure_ist(dt_or_str)
    elif isinstance(dt_or_str, str):
        for fmt in ('%I:%M %p', '%H:%M', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S'):
            try:
                dt = datetime.strptime(dt_or_str.strip(), fmt)
                break
            except ValueError:
                pass
    if dt is None:
        return str(dt_or_str)

    if language == "hi":
        period = get_period_of_day(dt.hour, language="hi")
        h = dt.hour % 12
        if h == 0:
            h = 12
        m = dt.minute

        # Determine phrase and whether it refers to hour 1 (singular)
        is_singular = (h == 1 and m != 45) or (h == 12 and m == 45)

        verb = "बज गया है" if is_singular else "बज गए हैं"
        if m == 0:
            time_part = f"{period} {h}"
        elif m == 30:
            if h == 1:
                time_part = f"{period} डेढ़"
            elif h == 2:
                time_part = f"{period} ढाई"
            else:
                time_part = f"{period} साढ़े {h}"
        elif m == 15:
            time_part = f"{period} सवा {h}"
        elif m == 45:
            next_h = 1 if h == 12 else (h + 1)
            next_h_str = "एक" if next_h == 1 else str(next_h)
            time_part = f"{period} पौने {next_h_str}"
        else:
            time_part = f"{period} {h} बजकर {m} मिनट"

        return f"{time_part} {verb}"

    elif language == "kn":
        period = get_period_of_day(dt.hour, language="kn")
        h = dt.hour % 12
        if h == 0:
            h = 12
        m = dt.minute
        if m == 0:
            return f"{period} {h} ಗಂಟೆ"
        else:
            return f"{period} {h}:{m:02d} ಗಂಟೆ"
    else:
        return dt.strftime('%I:%M %p').lstrip('0')


def format_when(dt: Optional[datetime], now: Optional[datetime] = None, language: str = "en") -> str:
    """
    Format a datetime relative to `now`:
    - 'today at 7:00 PM' / 'आज शाम 7 बजे' / 'ಇಂದು ಸಂಜೆ 7 ಗಂಟೆಗೆ'
    - 'tomorrow at 9:00 AM' / 'कल सुबह 9 बजे' / 'ನಾಳೆ ಬೆಳಿಗ್ಗೆ 9 ಗಂಟೆಗೆ'
    - 'Monday at 10:00 AM' / 'सोमवार सुबह 10 बजे' / 'ಸೋಮವಾರ ಬೆಳಿಗ್ಗೆ 10 ಗಂಟೆಗೆ'
    - Full date for >= 7 days or past dates (e.g. 'Nov 12 at 7:00 PM' / '12 नवंबर शाम 7 बजे' / '12 ನವೆಂಬರ್ ಸಂಜೆ 7 ಗಂಟೆಗೆ')
    """
    if dt is None:
        return "now"

    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    if isinstance(now, str):
        now = datetime.fromisoformat(now)

    dt_ist = ensure_ist(dt)
    now_ist_dt = ensure_ist(now) if now is not None else now_ist()

    days_diff = (dt_ist.date() - now_ist_dt.date()).days

    if language == "hi":
        time_hi = format_time_hindi(dt_ist)
        if days_diff == 0:
            return f"आज {time_hi}"
        elif days_diff == 1:
            return f"कल {time_hi}"
        elif 1 < days_diff < 7:
            weekday_en = dt_ist.strftime("%A")
            weekday_hi = HI_WEEKDAYS.get(weekday_en, weekday_en)
            return f"{weekday_hi} {time_hi}"
        else:
            month_name = dt_ist.strftime('%B')
            month_hi = HI_MONTHS.get(month_name, dt_ist.strftime('%B'))
            return f"{dt_ist.day} {month_hi} {time_hi}"

    elif language == "kn":
        time_kn = format_time_kannada(dt_ist)
        if days_diff == 0:
            return f"ಇಂದು {time_kn}"
        elif days_diff == 1:
            return f"ನಾಳೆ {time_kn}"
        elif 1 < days_diff < 7:
            weekday_en = dt_ist.strftime("%A")
            weekday_kn = KN_WEEKDAYS.get(weekday_en, weekday_en)
            return f"{weekday_kn} {time_kn}"
        else:
            month_name = dt_ist.strftime('%B')
            month_kn = KN_MONTHS.get(month_name, dt_ist.strftime('%B'))
            return f"{dt_ist.day} {month_kn} {time_kn}"

    else:
        time_en = dt_ist.strftime('%I:%M %p').lstrip('0')
        if days_diff == 0:
            return f"today at {time_en}"
        elif days_diff == 1:
            return f"tomorrow at {time_en}"
        elif 1 < days_diff < 7:
            weekday_en = dt_ist.strftime("%A")
            return f"{weekday_en} at {time_en}"
        else:
            return f"{dt_ist.strftime('%b %d')} at {time_en}"
