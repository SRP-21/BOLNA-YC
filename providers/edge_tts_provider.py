"""
Edge-TTS provider for high-quality Hindi/Kannada voices.
Unofficial Microsoft Edge TTS — may break, so fails soft to browser TTS.
Includes audio caching for repeated phrases.
"""
import asyncio
import hashlib
import logging
import os
from typing import Optional
from providers.base import TTSProvider, TTSResult
from providers.usage import usage

logger = logging.getLogger(__name__)

# Best voices per language
VOICE_MAP = {
    "en": "en-IN-NeerjaNeural",       # Indian English female
    "hi": "hi-IN-SwaraNeural",         # Hindi female
    "kn": "kn-IN-SapnaNeural",         # Kannada female
}

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "tts_cache")


class EdgeTTSProvider(TTSProvider):
    def __init__(self):
        os.makedirs(CACHE_DIR, exist_ok=True)

    def _cache_key(self, text: str, language: str) -> str:
        """Hash text+language for cache lookup."""
        h = hashlib.md5(f"{language}:{text}".encode()).hexdigest()
        return os.path.join(CACHE_DIR, f"{h}.mp3")

    async def synthesize(self, text: str, language: str = "en") -> TTSResult:
        if not usage.check_limit("edge_tts"):
            logger.warning("Edge TTS limit reached, falling back to browser")
            return TTSResult(use_browser_tts=True)

        # Check cache first
        cache_path = self._cache_key(text, language)
        if os.path.exists(cache_path):
            with open(cache_path, "rb") as f:
                return TTSResult(audio_bytes=f.read(), mime_type="audio/mpeg")

        voice = VOICE_MAP.get(language, VOICE_MAP["en"])

        try:
            import edge_tts
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(cache_path)

            with open(cache_path, "rb") as f:
                audio_bytes = f.read()

            usage.increment("edge_tts")
            return TTSResult(audio_bytes=audio_bytes, mime_type="audio/mpeg")

        except Exception as e:
            # Fail soft: edge-tts is unofficial, may break anytime
            logger.warning(f"Edge TTS failed ({e}), falling back to browser TTS")
            # Clean up partial file
            if os.path.exists(cache_path):
                os.remove(cache_path)
            return TTSResult(use_browser_tts=True)


class BrowserTTSProvider(TTSProvider):
    """Signals the frontend to use speechSynthesis. No server-side work."""
    async def synthesize(self, text: str, language: str = "en") -> TTSResult:
        return TTSResult(use_browser_tts=True)

