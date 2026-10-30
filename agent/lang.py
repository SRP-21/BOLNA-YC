"""
Language detector for Indic multilingual planner (English, Hindi/Hinglish, Kannada).
Pure standard library, zero external dependencies.
"""
import re
from typing import Optional

# Devanagari block: \u0900 - \u097F
DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")

# Kannada block: \u0C80 - \u0CFF
KANNADA_RE = re.compile(r"[\u0C80-\u0CFF]")

# Common Hinglish/Hindi markers in Latin script
HINGLISH_MARKERS = [
    r"\bkal\b",
    r"\bsubah\b",
    r"\bshaam\b",
    r"\braat\b",
    r"\bbaje\b",
    r"\bhai\b",
    r"\bhain\b",
    r"\bkaro\b",
    r"\bkarein\b",
    r"\bkarna\b",
    r"\bkarenge\b",
    r"\bho\s*gaya\b",
    r"\bhogaya\b",
    r"\bkar\s*liya\b",
    r"\bkarliya\b",
    r"\bnahi\b",
    r"\baaj\b",
    r"\bdopahar\b",
    r"\bkhatam\b",
    r"\bchahiye\b",
    r"\bjaldi\b",
    r"\bbaad\b",
    r"\bthodi\s*der\b",
    r"\bkya\b",
    r"\bkarte\b",
    r"\bmera\b",
    r"\bmeri\b",
    r"\bmujhe\b",
]
HINGLISH_RE = re.compile("|".join(HINGLISH_MARKERS), re.IGNORECASE)

# Kannada Latin markers
KANNADA_LATIN_MARKERS = [
    r"\baaytu\b",
    r"\bmadide\b",
    r"\bnaale\b",
    r"\bbeligge\b",
    r"\bsanje\b",
    r"\braatri\b",
]
KANNADA_LATIN_RE = re.compile("|".join(KANNADA_LATIN_MARKERS), re.IGNORECASE)


def detect_language(text: Optional[str], fallback: str = "en") -> str:
    """
    Detect language code ('en', 'hi', or 'kn') from text.
    - Kannada characters or Kannada Latin markers -> 'kn'
    - Devanagari characters -> 'hi'
    - Latin text with Hinglish markers -> 'hi' (treated as Hinglish, spoken with Hindi TTS)
    - Otherwise -> fallback (default 'en')
    """
    if not text or not text.strip():
        return fallback

    text_clean = text.strip()

    # 1. Check for Kannada script or Kannada markers
    if KANNADA_RE.search(text_clean) or KANNADA_LATIN_RE.search(text_clean):
        return "kn"

    # 2. Check for Devanagari script
    if DEVANAGARI_RE.search(text_clean):
        return "hi"

    # 3. Check for Hinglish markers in Latin text
    if HINGLISH_RE.search(text_clean):
        return "hi"

    return fallback
