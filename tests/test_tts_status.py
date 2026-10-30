"""
Tests for Phase 1: edge-tts provider, fallback behavior, failure streak logging,
and tts_provider_used field in API responses.
All tests run offline with external calls mocked.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from providers.base import TTSResult
from providers.edge_tts_provider import EdgeTTSProvider
from providers.registry import registry
from main import app
from db import init_db, SessionLocal, Task, TaskStatus
from datetime import datetime
from timeutil import now_ist

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_db():
    init_db()
    db = SessionLocal()
    db.query(Task).delete()
    db.commit()
    db.close()


@pytest.mark.asyncio
async def test_edge_tts_mocked_raise_gives_browser_fallback(caplog):
    """With the edge provider mocked to raise, response has tts_fallback=True and tts_provider_used='browser'."""
    provider = EdgeTTSProvider()
    
    with patch("edge_tts.Communicate.save", side_effect=Exception("403 Forbidden")):
        with caplog.at_level("WARNING"):
            result = await provider.synthesize("Hello world", "en")
            assert result.use_browser_tts is True
            assert result.provider == "browser"
            assert "Edge TTS failed" in caplog.text

            # Test failure streak: second failure should NOT log again
            caplog.clear()
            result2 = await provider.synthesize("Hello again", "en")
            assert result2.use_browser_tts is True
            assert result2.provider == "browser"
            assert "Edge TTS failed" not in caplog.text


@pytest.mark.asyncio
async def test_edge_tts_mocked_success_gives_edge_provider():
    """With the edge provider mocked to succeed, response has tts_fallback=False and tts_provider_used='edge'."""
    provider = EdgeTTSProvider()
    
    with patch("edge_tts.Communicate.save", new_callable=AsyncMock) as mock_save, \
         patch("builtins.open", MagicMock()) as mock_open:
        mock_file = MagicMock()
        mock_file.read.return_value = b"fake-audio-bytes"
        mock_open.return_value.__enter__.return_value = mock_file
        
        result = await provider.synthesize("Hello world", "en")
        assert result.use_browser_tts is False
        assert result.provider == "edge"
        assert result.audio_bytes == b"fake-audio-bytes"


def test_text_turn_endpoint_tts_provider_used_browser():
    """Test /api/text/turn response when TTS fails soft to browser."""
    with patch.object(registry, "synthesize", new_callable=AsyncMock) as mock_synth, \
         patch("agent.planner.process_turn", new_callable=AsyncMock) as mock_turn:
        
        mock_turn.return_value = {
            "reply_text": "Task noted.",
            "task_changes": [],
            "language": "en"
        }
        mock_synth.return_value = TTSResult(use_browser_tts=True, provider="browser")
        
        resp = client.post("/api/text/turn", data={"text": "test task"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["tts_fallback"] is True
        assert data["tts_provider_used"] == "browser"


def test_text_turn_endpoint_tts_provider_used_edge():
    """Test /api/text/turn response when TTS succeeds with edge."""
    with patch.object(registry, "synthesize", new_callable=AsyncMock) as mock_synth, \
         patch("agent.planner.process_turn", new_callable=AsyncMock) as mock_turn:
        
        mock_turn.return_value = {
            "reply_text": "Task noted.",
            "task_changes": [],
            "language": "en"
        }
        mock_synth.return_value = TTSResult(
            audio_bytes=b"edge-audio",
            mime_type="audio/mpeg",
            use_browser_tts=False,
            provider="edge"
        )
        
        resp = client.post("/api/text/turn", data={"text": "test task"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["tts_fallback"] is False
        assert data["tts_provider_used"] == "edge"
        assert "audio_base64" in data


def test_reminder_reply_endpoint_tts_provider_used():
    """Test /api/reminders/{id}/reply response includes tts_provider_used."""
    db = SessionLocal()
    task = Task(title="Test Task", due_at=now_ist().replace(tzinfo=None), status=TaskStatus.DUE.value)
    db.add(task)
    db.commit()
    task_id = task.id
    db.close()

    with patch.object(registry, "synthesize", new_callable=AsyncMock) as mock_synth:
        mock_synth.return_value = TTSResult(use_browser_tts=True, provider="browser")
        
        resp = client.post(f"/api/reminders/{task_id}/reply", data={"text": "done"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["outcome"] == "done"
        assert data["tts_fallback"] is True
        assert data["tts_provider_used"] == "browser"
