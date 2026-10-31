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

# Common Hinglish/Hindi markers in Latin script (compound phrases first)
HINGLISH_MARKERS = [
    r"\bkal\s+subah\b",
    r"\bshaam\s+ko\b",
    r"\braat\s+ko\b",
    r"\bho\s*gaya\b",
    r"\bhogaya\b",
    r"\bkar\s*liya\b",
    r"\bkarliya\b",
    r"\bthodi\s*der\b",
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
    r"\bnahi\b",
    r"\baaj\b",
    r"\bdopahar\b",
    r"\bkhatam\b",
    r"\bchahiye\b",
    r"\bjaldi\b",
    r"\bbaad\b",
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
    - Kannada script -> 'kn'
    - Devanagari script -> 'hi'
    - Latin text with Kannada markers -> 'kn'
    - Latin text with Hinglish markers:
      One Hinglish marker word in an otherwise English sentence stays English.
      Requires at least 2 markers, or markers making up at least 25% of words, for Hinglish.
    - Otherwise -> fallback (default 'en')
    """
    if not text or not text.strip():
        return fallback

    text_clean = text.strip()

    # 1. Native script detection always wins
    if KANNADA_RE.search(text_clean):
        return "kn"
    if DEVANAGARI_RE.search(text_clean):
        return "hi"

    words = re.findall(r"\b\w+\b", text_clean)
    num_words = len(words)

    # 2. Kannada Latin markers
    k_matches = KANNADA_LATIN_RE.findall(text_clean)
    num_k = len(k_matches)
    if num_k >= 2 or (num_words <= 2 and num_k >= 1):
        return "kn"

    # 3. Hinglish markers in Latin text
    # One marker in an otherwise English sentence stays English.
    # At least 2 markers, or markers making up >= 25% of words (for short 1-2 word utterances) -> 'hi'
    h_matches = HINGLISH_RE.findall(text_clean)
    num_h = len(h_matches)
    if num_h >= 2 or (num_words <= 2 and num_h >= 1):
        return "hi"

    return fallback
