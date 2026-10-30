"""
Central configuration for the voice planner.
All time-resolution defaults, provider settings, and app constants live here.
"""
from pydantic_settings import BaseSettings
from pydantic import Field, ConfigDict
from typing import Optional
import os
from dotenv import load_dotenv

load_dotenv()


class TimeWindows:
    """
    Default time windows for vague phrases.
    All times in 24h format, Asia/Kolkata.
    """
    EARLY_MORNING = (5, 0)
    MORNING = (9, 0)
    BEFORE_LUNCH = (12, 30)
    LUNCH = (13, 0)
    AFTERNOON = (14, 30)
    EVENING = (18, 0)
    NIGHT = (21, 0)
    LATE_NIGHT = (23, 0)

    PHRASE_MAP = {
        "early morning": EARLY_MORNING,
        "morning": MORNING,
        "before lunch": BEFORE_LUNCH,
        "lunch": LUNCH,
        "lunchtime": LUNCH,
        "afternoon": AFTERNOON,
        "evening": EVENING,
        "night": NIGHT,
        "late night": LATE_NIGHT,
        "end of day": (17, 30),
        "eod": (17, 30),
        "subah": MORNING,
        "subah jaldi": EARLY_MORNING,
        "dopahar": AFTERNOON,
        "dopahar ka khana": LUNCH,
        "lunch se pehle": BEFORE_LUNCH,
        "shaam": EVENING,
        "shaam ko": EVENING,
        "raat": NIGHT,
        "raat ko": NIGHT,
        "beligge": MORNING,
        "madhyahna": AFTERNOON,
        "sanje": EVENING,
        "raatri": NIGHT,
        "tonight": NIGHT,
        "today evening": EVENING,
        "aaj shaam": EVENING,
        "kal subah": MORNING,
        "tomorrow morning": MORNING,
        "tomorrow evening": EVENING,
    }

    DEFAULT_SNOOZE_MINUTES = 10


class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Groq
    groq_api_key: str = Field(default="")
    groq_base_url: str = "https://api.groq.com/openai/v1"

    # LLM models (active Groq models)
    llm_planner_model: str = "openai/gpt-oss-120b"
    llm_planner_fallback: str = "openai/gpt-oss-20b"
    llm_classifier_model: str = "openai/gpt-oss-20b"

    # STT
    stt_model: str = "whisper-large-v3-turbo"

    # TTS ("edge", "elevenlabs", or "browser")
    tts_provider: str = "edge"

    # ElevenLabs (optional high quality voice)
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"  # Rachel (or user's preferred voice)

    # Sarvam (optional)
    sarvam_enabled: bool = False
    sarvam_api_key: str = ""
    sarvam_budget_credits: int = 100

    # App
    default_timezone: str = "Asia/Kolkata"
    default_language: str = "en"
    reminder_retry_delay_seconds: int = 60
    reminder_stagger_seconds: int = 10
    overdue_policy: str = "fire_now"

    # Usage limits
    daily_token_limit: int = 100000
    daily_stt_requests: int = 200
    daily_tts_requests: int = 300


settings = Settings()
time_windows = TimeWindows()
