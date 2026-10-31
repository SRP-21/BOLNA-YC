"""
Provider-agnostic interfaces for STT, TTS, and LLM.
Each adapter implements these; swapping providers is one env var change.
"""
from abc import ABC, abstractmethod
from typing import Optional, Any
from pydantic import BaseModel


class STTResult(BaseModel):
    text: str
    language: str  # ISO 639-1 detected language code


class TTSResult(BaseModel):
    audio_bytes: Optional[bytes] = None
    mime_type: str = "audio/mpeg"
    use_browser_tts: bool = False  # Signal frontend to use speechSynthesis
    provider: str = "browser"


class STTProvider(ABC):
    @abstractmethod
    async def transcribe(
        self, audio_bytes: bytes, mime_type: str = "audio/webm",
        language_hint: Optional[str] = None,
        prompt: Optional[str] = None,
    ) -> STTResult:
        ...


class TTSProvider(ABC):
    @abstractmethod
    async def synthesize(
        self, text: str, language: str = "en"
    ) -> TTSResult:
        ...


class LLMProvider(ABC):
    @abstractmethod
    async def chat(
        self, messages: list[dict], tools: Optional[list[dict]] = None,
        model_override: Optional[str] = None
    ) -> dict:
        """
        Returns the raw API response dict with 'choices'.
        Handles retries on invalid tool args internally.
        """
        ...

