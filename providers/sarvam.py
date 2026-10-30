"""
Sarvam AI provider (optional). Saaras v3 STT + Bulbul v3 TTS.
OFF by default; enabled by SARVAM_ENABLED=true.
Hard usage budget counter prevents exceeding free credits.
"""
import logging
from typing import Optional
import httpx
from providers.base import STTProvider, TTSProvider, STTResult, TTSResult
from providers.usage import usage
from config import settings

logger = logging.getLogger(__name__)

SARVAM_STT_URL = "https://api.sarvam.ai/speech-to-text-translate"
SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"

# Sarvam language codes
SARVAM_LANG_MAP = {
    "en": "en-IN", "hi": "hi-IN", "kn": "kn-IN",
}
SARVAM_TTS_LANG_MAP = {
    "en": "en-IN", "hi": "hi-IN", "kn": "kn-IN",
}


class SarvamSTT(STTProvider):
    async def transcribe(
        self, audio_bytes: bytes, mime_type: str = "audio/webm",
        language_hint: Optional[str] = None
    ) -> STTResult:
        if not settings.sarvam_enabled:
            raise RuntimeError("Sarvam not enabled")
        if not usage.check_limit("sarvam"):
            raise RuntimeError("Sarvam budget exhausted")

        lang = SARVAM_LANG_MAP.get(language_hint or "en", "en-IN")

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                SARVAM_STT_URL,
                headers={
                    "api-subscription-key": settings.sarvam_api_key,
                },
                files={"file": ("audio.webm", audio_bytes, mime_type)},
                data={"language_code": lang, "model": "saaras:v3"},
            )
            response.raise_for_status()
            data = response.json()

        usage.increment("sarvam")
        return STTResult(
            text=data.get("transcript", ""),
            language=language_hint or "en"
        )


class SarvamTTS(TTSProvider):
    async def synthesize(self, text: str, language: str = "en") -> TTSResult:
        if not settings.sarvam_enabled:
            raise RuntimeError("Sarvam not enabled")
        if not usage.check_limit("sarvam"):
            raise RuntimeError("Sarvam budget exhausted")

        lang = SARVAM_TTS_LANG_MAP.get(language, "en-IN")

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                SARVAM_TTS_URL,
                headers={
                    "api-subscription-key": settings.sarvam_api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "inputs": [text],
                    "target_language_code": lang,
                    "model": "bulbul:v3",
                },
            )
            response.raise_for_status()
            data = response.json()

        usage.increment("sarvam")

        import base64
        audio_b64 = data.get("audios", [None])[0]
        if audio_b64:
            audio_bytes = base64.b64decode(audio_b64)
            return TTSResult(audio_bytes=audio_bytes, mime_type="audio/wav")

        return TTSResult(use_browser_tts=True)

