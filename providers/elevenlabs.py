"""
ElevenLabs TTS provider (optional, behind TTS_PROVIDER=elevenlabs).
High-fidelity neural voices.
Fails soft to Edge TTS or Browser TTS if key is missing or quota is exceeded.
"""
import logging
import os
import hashlib
import httpx
from typing import Optional
from providers.base import TTSProvider, TTSResult
from providers.usage import usage
from config import settings

logger = logging.getLogger(__name__)

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "tts_cache")


class ElevenLabsTTS(TTSProvider):
    def __init__(self):
        os.makedirs(CACHE_DIR, exist_ok=True)
        self.api_key = settings.elevenlabs_api_key
        # Default to 'Rachel' (21m00Tcm4TlvDq8ikWAM) or 'Sarah' (EXAVITQu4vr4xnSDxMaL)
        self.voice_id = settings.elevenlabs_voice_id or "21m00Tcm4TlvDq8ikWAM"

    def _cache_key(self, text: str, language: str) -> str:
        h = hashlib.md5(f"eleven:{self.voice_id}:{language}:{text}".encode()).hexdigest()
        return os.path.join(CACHE_DIR, f"{h}.mp3")

    async def synthesize(self, text: str, language: str = "en") -> TTSResult:
        if not self.api_key:
            logger.warning("ElevenLabs API key missing, failing soft")
            raise RuntimeError("ElevenLabs API key not configured")

        cache_path = self._cache_key(text, language)
        if os.path.exists(cache_path):
            with open(cache_path, "rb") as f:
                return TTSResult(audio_bytes=f.read(), mime_type="audio/mpeg")

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}"
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": self.api_key,
        }
        payload = {
            "text": text,
            "model_id": "eleven_multilingual_v2",  # Supports English, Hindi, etc.
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
            }
        }

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                audio_bytes = resp.content

            with open(cache_path, "wb") as f:
                f.write(audio_bytes)

            usage.increment("elevenlabs_tts")
            return TTSResult(audio_bytes=audio_bytes, mime_type="audio/mpeg")

        except Exception as e:
            logger.warning(f"ElevenLabs TTS error ({e}), falling back")
            raise

