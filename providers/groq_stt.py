"""
Groq Whisper STT provider.
Uses OpenAI-compatible API at https://api.groq.com/openai/v1/audio/transcriptions.
verbose_json response gives us detected language.
"""
import io
import logging
from typing import Optional
from openai import AsyncOpenAI
from providers.base import STTProvider, STTResult
from providers.usage import usage
from config import settings

logger = logging.getLogger(__name__)

# Whisper language code -> our language code mapping
WHISPER_LANG_MAP = {
    "english": "en", "hindi": "hi", "kannada": "kn",
    "en": "en", "hi": "hi", "kn": "kn",
}


class GroqSTT(STTProvider):
    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.groq_api_key,
            base_url=settings.groq_base_url,
        )
        self.model = settings.stt_model

    async def transcribe(
        self, audio_bytes: bytes, mime_type: str = "audio/webm",
        language_hint: Optional[str] = None
    ) -> STTResult:
        if not usage.check_limit("groq_stt"):
            raise RuntimeError("Daily STT request limit reached")

        # Map mime type to file extension for the API
        ext_map = {
            "audio/webm": "webm", "audio/wav": "wav", "audio/mp3": "mp3",
            "audio/mpeg": "mp3", "audio/ogg": "ogg", "audio/m4a": "m4a",
            "audio/mp4": "mp4", "audio/flac": "flac",
        }
        ext = ext_map.get(mime_type, "webm")
        filename = f"audio.{ext}"

        kwargs = {
            "model": self.model,
            "file": (filename, io.BytesIO(audio_bytes), mime_type),
            "response_format": "verbose_json",
        }
        # Language hint improves accuracy for known languages
        if language_hint and language_hint in ("en", "hi", "kn"):
            kwargs["language"] = language_hint

        try:
            response = await self.client.audio.transcriptions.create(**kwargs)
            usage.increment("groq_stt")

            # Extract detected language from verbose_json response
            detected = getattr(response, "language", "english")
            lang_code = WHISPER_LANG_MAP.get(detected, "en")
            text = response.text.strip()

            logger.info(f"STT result: lang={lang_code}, text={text[:80]}...")
            return STTResult(text=text, language=lang_code)

        except Exception as e:
            logger.error(f"Groq STT error: {e}")
            raise

