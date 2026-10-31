"""
Deterministic coarse task categorization with keyword rules and cached classifier fallback.
Categories: health, work, errands, family, other.
"""
import re
from typing import Optional

_category_cache: dict[str, str] = {}

CATEGORY_KEYWORDS = {
    "health": [
        "gym", "workout", "doctor", "dentist", "medicine", "pill", "tablet",
        "walk", "running", "jog", "exercise", "clinic", "hospital", "yoga",
        "dawai", "kasrat", "arogya", "physio", "blood test", "checkup"
    ],
    "work": [
        "standup", "meeting", "invoice", "email", "pr", "presentation",
        "report", "sync", "review", "client", "code", "bug", "office",
        "deploy", "demo", "call with", "interview", "kaam", "office ka"
    ],
    "errands": [
        "groceries", "grocery", "milk", "laundry", "dry clean", "bank",
        "buy", "store", "pickup", "drop off", "sabzi", "dukan", "petrol",
        "post office", "courier", "package", "kirana", "supermarket"
    ],
    "family": [
        "mom", "dad", "sister", "brother", "son", "daughter", "wife",
        "husband", "kids", "child", "dinner with", "mummy", "papa", "bhai",
        "amma", "appa", "family", "parents"
    ],
}


def categorize_by_rules(title: str) -> Optional[str]:
    """Match task title against keyword rules."""
    t = title.lower().strip()
    words = set(re.findall(r"\b\w+\b", t))

    for category, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if " " in kw:
                if kw in t:
                    return category
            else:
                if kw in words:
                    return category
    return None


async def categorize_task(title: str) -> str:
    """
    Categorize a task title:
    1. Keyword heuristics first (0ms, 0 tokens)
    2. In-memory cache
    3. Small LLM classifier fallback, cached by normalized title
    """
    clean_title = title.strip()
    norm = clean_title.lower()

    # 1. Rule-based
    cat = categorize_by_rules(norm)
    if cat:
        _category_cache[norm] = cat
        return cat

    # 2. Cache
    if norm in _category_cache:
        return _category_cache[norm]

    # 3. Small LLM classifier fallback
    try:
        from providers.registry import registry
        from config import settings
        prompt = (
            f"Classify this task title into exactly one of: health, work, errands, family, other.\n"
            f"Task: {clean_title}\n"
            f"Return ONLY the category name in lowercase."
        )
        res = await registry.llm.chat(
            messages=[{"role": "user", "content": prompt}],
            model_override=settings.llm_classifier_model,
        )
        category = (res.get("content") or "").strip().lower()
        if category in ("health", "work", "errands", "family", "other"):
            _category_cache[norm] = category
            return category
    except Exception:
        pass

    _category_cache[norm] = "other"
    return "other"
