"""
Usage tracking for free-tier hygiene.
Tracks requests and tokens per provider per day, with limit checks.
"""
from datetime import datetime, timezone
from db import SessionLocal, UsageCounter
from config import settings
import logging

logger = logging.getLogger(__name__)


class UsageTracker:
    """Thread-safe usage counter backed by SQLite."""

    def _today(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _get_or_create(self, db, provider: str) -> UsageCounter:
        today = self._today()
        counter = db.query(UsageCounter).filter_by(
            date=today, provider=provider
        ).first()
        if not counter:
            counter = UsageCounter(date=today, provider=provider)
            db.add(counter)
            db.commit()
            db.refresh(counter)
        return counter

    def increment(self, provider: str, requests: int = 1, tokens: int = 0):
        db = SessionLocal()
        try:
            counter = self._get_or_create(db, provider)
            counter.request_count += requests
            counter.token_count += tokens
            db.commit()
        finally:
            db.close()

    def check_limit(self, provider: str) -> bool:
        """Returns True if we're still within limits."""
        db = SessionLocal()
        try:
            counter = self._get_or_create(db, provider)
            if provider == "groq_llm":
                return counter.token_count < settings.daily_token_limit
            elif provider == "groq_stt":
                return counter.request_count < settings.daily_stt_requests
            elif provider in ("edge_tts", "browser_tts"):
                return counter.request_count < settings.daily_tts_requests
            elif provider == "sarvam":
                return counter.request_count < settings.sarvam_budget_credits
            return True
        finally:
            db.close()

    def get_all_today(self) -> dict:
        """Get all usage counters for today, for /api/health."""
        db = SessionLocal()
        try:
            today = self._today()
            counters = db.query(UsageCounter).filter_by(date=today).all()
            return {
                c.provider: {"requests": c.request_count, "tokens": c.token_count}
                for c in counters
            }
        finally:
            db.close()


usage = UsageTracker()

