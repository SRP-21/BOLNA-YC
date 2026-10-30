"""
Provider registry and fallback chain.
Instantiates the right provider based on config and handles fallbacks.
Shows "rate limited, using fallback" rather than failing silently.
"""
import logging
from typing import Optional
from providers.base import STTProvider, TTSProvider, LLMProvider
from providers.groq_stt import GroqSTT
from providers.groq_llm import GroqLLM
from providers.edge_tts_provider import EdgeTTSProvider, BrowserTTSProvider
from providers.sarvam import SarvamSTT, SarvamTTS
from providers.elevenlabs import ElevenLabsTTS
from config import settings

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """
    Central registry. Holds active providers and handles fallbacks.
    The frontend checks /api/health to show active providers.
    """
    def __init__(self):
        # LLM
        self.llm = GroqLLM()

        # STT chain: Sarvam (if enabled) -> Groq Whisper
        self._stt_primary: STTProvider = GroqSTT()
        self._stt_fallback: Optional[STTProvider] = None
        if settings.sarvam_enabled and settings.sarvam_api_key:
            self._stt_primary = SarvamSTT()
            self._stt_fallback = GroqSTT()

        # TTS chain: ElevenLabs (if configured) -> Sarvam (if enabled) -> Edge TTS -> Browser TTS
        if settings.tts_provider == "elevenlabs" and settings.elevenlabs_api_key:
            self._tts_primary: TTSProvider = ElevenLabsTTS()
            self._tts_fallback: TTSProvider = EdgeTTSProvider()
        elif settings.sarvam_enabled and settings.sarvam_api_key:
            self._tts_primary: TTSProvider = SarvamTTS()
            self._tts_fallback: TTSProvider = EdgeTTSProvider()
        elif settings.tts_provider == "edge":
            self._tts_primary = EdgeTTSProvider()
            self._tts_fallback = BrowserTTSProvider()
        else:
            self._tts_primary = BrowserTTSProvider()
            self._tts_fallback = BrowserTTSProvider()

        self._active_stt = "sarvam" if isinstance(self._stt_primary, SarvamSTT) else "groq_whisper"
        self._active_tts = (
            "elevenlabs" if isinstance(self._tts_primary, ElevenLabsTTS)
            else "sarvam" if isinstance(self._tts_primary, SarvamTTS)
            else "edge_tts" if isinstance(self._tts_primary, EdgeTTSProvider)
            else "browser"
        )
        self._fallback_info: Optional[str] = None

    @property
    def active_stt(self) -> str:
        return self._active_stt

    @property
    def active_tts(self) -> str:
        return self._active_tts

    @property
    def fallback_info(self) -> Optional[str]:
        return self._fallback_info

    async def transcribe(self, audio_bytes: bytes, mime_type: str = "audio/webm",
                         language_hint: Optional[str] = None):
        """STT with fallback chain."""
        try:
            result = await self._stt_primary.transcribe(audio_bytes, mime_type, language_hint)
            self._fallback_info = None
            return result
        except Exception as e:
            logger.warning(f"Primary STT failed: {e}")
            if self._stt_fallback:
                self._fallback_info = f"STT: using fallback ({e})"
                self._active_stt = "groq_whisper (fallback)"
                return await self._stt_fallback.transcribe(audio_bytes, mime_type, language_hint)
            raise

    async def synthesize(self, text: str, language: str = "en"):
        """TTS with fallback chain."""
        try:
            result = await self._tts_primary.synthesize(text, language)
            return result
        except Exception as e:
            logger.warning(f"Primary TTS failed ({e}), attempting fallback")
            if self._tts_fallback:
                try:
                    self._fallback_info = f"TTS: using fallback ({e})"
                    return await self._tts_fallback.synthesize(text, language)
                except Exception as e2:
                    logger.warning(f"Fallback TTS failed ({e2}), falling to browser")
            from providers.base import TTSResult
            return TTSResult(use_browser_tts=True, provider="browser")

    def health_status(self) -> dict:
        from providers.usage import usage
        return {
            "stt": self._active_stt,
            "tts": self._active_tts,
            "llm": self.llm.active_model,
            "llm_fallback_reason": self.llm.fallback_reason,
            "fallback_info": self._fallback_info,
            "usage_today": usage.get_all_today(),
        }


# Singleton
registry = ProviderRegistry()
