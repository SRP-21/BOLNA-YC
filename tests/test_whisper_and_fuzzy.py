"""
Tests for Phase 6: Names and Whisper accuracy.
1. "cancel Mohan Aswar" cancels the task (exact and phonetic 'mona search' fuzzy match).
2. Transcription prompt contains active task titles so Whisper is primed for proper nouns.
"""
import io
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, patch, MagicMock
from starlette.testclient import TestClient

from main import app
from db import init_db, SessionLocal, Task, TaskStatus
from agent.resolver import IST
from agent.planner import process_turn, _handle_cancel_task
from providers.base import STTResult
from providers.groq_stt import GroqSTT

FROZEN_NOW = datetime(2026, 10, 31, 10, 0, 0, tzinfo=IST)


@pytest.fixture(autouse=True)
def clean_db():
    init_db()
    db = SessionLocal()
    db.query(Task).delete()
    db.commit()
    db.close()


@pytest.mark.asyncio
async def test_cancel_mohan_aswar_cancels_task():
    """'cancel Mohan Aswar' finds and cancels the task in the database."""
    db = SessionLocal()
    t = Task(
        title="Mohan Aswar",
        due_at=datetime(2026, 10, 31, 15, 0, 0),
        status=TaskStatus.SCHEDULED.value,
        language="en",
    )
    db.add(t)
    db.commit()
    task_id = t.id
    db.close()

    # Process turn with cancel utterance (using regex fallback or mock LLM)
    res = await process_turn("cancel Mohan Aswar", language="en", now=FROZEN_NOW)
    assert "Cancelled Mohan Aswar." in res["reply_text"]

    db = SessionLocal()
    updated = db.query(Task).filter_by(id=task_id).first()
    assert updated.status == TaskStatus.CANCELLED.value
    db.close()


def test_fuzzy_cancel_phonetic_mona_search():
    """Phonetic distortion 'mona search' matches and cancels 'Mohan Aswar' via difflib."""
    db = SessionLocal()
    t = Task(
        title="Mohan Aswar",
        due_at=datetime(2026, 10, 31, 16, 0, 0),
        status=TaskStatus.SCHEDULED.value,
        language="en",
    )
    db.add(t)
    db.commit()
    task_id = t.id

    result = _handle_cancel_task(db, {"title": "mona search"})
    assert result["type"] == "cancelled"
    assert result["title"] == "Mohan Aswar"

    updated = db.query(Task).filter_by(id=task_id).first()
    assert updated.status == TaskStatus.CANCELLED.value
    db.close()


def test_voice_turn_transcription_prompt_contains_active_tasks():
    """In routes/voice.py, transcription prompt hint contains active task titles."""
    client = TestClient(app)

    db = SessionLocal()
    t1 = Task(
        title="Mohan Aswar",
        due_at=datetime(2026, 10, 31, 14, 0, 0),
        status=TaskStatus.SCHEDULED.value,
    )
    t2 = Task(
        title="Dentist Checkup",
        due_at=datetime(2026, 10, 31, 17, 0, 0),
        status=TaskStatus.SCHEDULED.value,
    )
    # Cancelled task should NOT be in the prompt hint
    t3 = Task(
        title="Old Task",
        due_at=datetime(2026, 10, 31, 12, 0, 0),
        status=TaskStatus.CANCELLED.value,
    )
    db.add_all([t1, t2, t3])
    db.commit()
    db.close()

    dummy_stt = STTResult(text="cancel Mohan Aswar", language="en")
    with patch("routes.voice.registry.transcribe", new_callable=AsyncMock) as mock_stt, \
         patch("routes.voice.registry.synthesize", new_callable=AsyncMock) as mock_tts:
        mock_stt.return_value = dummy_stt
        mock_tts.return_value = MagicMock(use_browser_tts=True, provider="browser", audio_bytes=None)

        resp = client.post(
            "/api/voice/turn",
            files={"audio": ("sample.wav", b"dummy_audio_bytes", "audio/wav")},
        )
        assert resp.status_code == 200
        assert mock_stt.called

        # Verify prompt hint was passed and contains active task titles
        call_kwargs = mock_stt.call_args.kwargs
        prompt_passed = call_kwargs.get("prompt")
        assert prompt_passed is not None
        assert "Mohan Aswar" in prompt_passed
        assert "Dentist Checkup" in prompt_passed
        assert "Old Task" not in prompt_passed


def test_voice_turn_transcription_prompt_none_when_no_active_tasks():
    """When no active tasks exist, transcription prompt is None."""
    client = TestClient(app)

    dummy_stt = STTResult(text="hello", language="en")
    with patch("routes.voice.registry.transcribe", new_callable=AsyncMock) as mock_stt, \
         patch("routes.voice.registry.synthesize", new_callable=AsyncMock) as mock_tts:
        mock_stt.return_value = dummy_stt
        mock_tts.return_value = MagicMock(use_browser_tts=True, provider="browser", audio_bytes=None)

        resp = client.post(
            "/api/voice/turn",
            files={"audio": ("sample.wav", b"dummy_audio_bytes", "audio/wav")},
        )
        assert resp.status_code == 200
        call_kwargs = mock_stt.call_args.kwargs
        assert call_kwargs.get("prompt") is None


@pytest.mark.asyncio
async def test_groq_stt_passes_prompt_to_api():
    """GroqSTT.transcribe forwards the prompt parameter to the OpenAI/Groq API client."""
    provider = GroqSTT()
    mock_create = AsyncMock()
    mock_create.return_value = MagicMock(text="test transcript", language="english")

    with patch.object(provider.client.audio.transcriptions, "create", mock_create), \
         patch("providers.groq_stt.usage.check_limit", return_value=True), \
         patch("providers.groq_stt.usage.increment"):
        res = await provider.transcribe(
            b"audio_bytes",
            mime_type="audio/webm",
            language_hint="en",
            prompt="Reminders: Mohan Aswar, Standup",
        )
        assert res.text == "test transcript"
        assert mock_create.called
        create_kwargs = mock_create.call_args.kwargs
        assert create_kwargs.get("prompt") == "Reminders: Mohan Aswar, Standup"
