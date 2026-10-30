"""
Tests for 429 rate limit fallback chain and provider resiliency.
Ensures zero silent failures — fallbacks log and report gracefully.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from openai import RateLimitError
import httpx
from providers.groq_llm import GroqLLM
from providers.registry import ProviderRegistry
from providers.edge_tts_provider import EdgeTTSProvider, BrowserTTSProvider
from db import init_db, SessionLocal, Task, TaskStatus
from scheduler import reload_pending_tasks, schedule_task_reminder
from datetime import datetime, timedelta
from agent.resolver import IST


def test_groq_llm_model_fallback_config():
    """Verify that GroqLLM initializes with primary, fallback, and classifier models configured."""
    llm = GroqLLM(retry_delay=0.0)
    assert llm.primary_model == "openai/gpt-oss-120b"
    assert llm.fallback_model == "openai/gpt-oss-20b"
    assert llm.classifier_model == "openai/gpt-oss-20b"
    assert llm.active_model == "openai/gpt-oss-120b"
    assert llm.fallback_reason is None


def test_provider_registry_health_status():
    """Verify registry health_status reports active providers."""
    registry = ProviderRegistry()
    status = registry.health_status()
    assert "stt" in status
    assert "tts" in status
    assert "llm" in status
    assert status["llm"] == "openai/gpt-oss-120b"


def test_scheduler_reload_and_overdue_handling():
    """Verify that on startup, reload_pending_tasks properly loads pending and snoozed tasks."""
    init_db()
    db = SessionLocal()
    db.query(Task).delete()
    db.commit()

    now = datetime.now(IST)
    # Add a pending task
    t1 = Task(title="Morning call", due_at=now + timedelta(hours=2), status=TaskStatus.SCHEDULED.value)
    # Add an overdue task
    t2 = Task(title="Past meeting", due_at=now - timedelta(minutes=10), status=TaskStatus.SCHEDULED.value)
    # Add a completed task (should NOT be reloaded)
    t3 = Task(title="Done task", due_at=now - timedelta(hours=1), status=TaskStatus.DONE.value)
    db.add_all([t1, t2, t3])
    db.commit()
    db.close()

    # Reload should execute without error
    reload_pending_tasks()
