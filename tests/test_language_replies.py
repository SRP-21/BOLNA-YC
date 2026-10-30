"""
Tests for Phase 2: language detection, localized reply templates (en, hi, kn),
voice/text turn language detection, and reminder reply language propagation.
All tests run offline.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from agent.lang import detect_language
from agent.replies import (
    format_created,
    format_snoozed,
    format_done,
    format_cancelled,
    format_reminder_prompt,
)
from providers.base import TTSResult
from providers.registry import registry
from main import app
from db import init_db, SessionLocal, Task, TaskStatus
from timeutil import now_ist

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_db():
    init_db()
    db = SessionLocal()
    db.query(Task).delete()
    db.commit()
    db.close()


def test_language_detection():
    # Hinglish Latin
    assert detect_language("kal subah 9 baje doctor ka appointment hai") == "hi"
    assert detect_language("shaam ko 6 baje gym jana hai") == "hi"
    assert detect_language("10 min baad remind karna") == "hi"
    assert detect_language("ho gaya") == "hi"
    assert detect_language("aaj dopahar ko call karna") == "hi"

    # Devanagari
    assert detect_language("डॉक्टर अपॉइंटमेंट") == "hi"
    assert detect_language("दोपहर 1 बजे") == "hi"

    # Kannada Script
    assert detect_language("ನಿಮ್ಮ ರಿಮೈಂಡರ್ ಸಿದ್ಧವಾಗಿದೆ") == "kn"
    assert detect_language("ನಾಳೆ ಬೆಳಿಗ್ಗೆ 9 ಗಂಟೆಗೆ") == "kn"

    # English
    assert detect_language("standup at 10, send invoice before lunch") == "en"
    assert detect_language("gym at 6, no make that 7 pm") == "en"
    assert detect_language("snooze 10 minutes") == "en"
    assert detect_language("done") == "en"


def test_localized_reply_formatting():
    # Single created
    hi_created = format_created([{"type": "created", "title": "Doctor", "due_at": "2026-10-31T09:00:00"}], "hi")
    assert "Doctor" in hi_created
    assert "सेट कर दिया गया है" in hi_created

    kn_created = format_created([{"type": "created", "title": "Doctor", "due_at": "2026-10-31T09:00:00"}], "kn")
    assert "Doctor" in kn_created
    assert "ಹೊಂದಿಸಲಾಗಿದೆ" in kn_created

    en_created = format_created([{"type": "created", "title": "Doctor", "due_at": "2026-10-31T09:00:00"}], "en")
    assert "Got it, reminder set: Doctor" in en_created

    # Done
    assert "पूरा हो गया" in format_done("Gym", "hi")
    assert "ಮುಕ್ತಾಯಗೊಂಡಿದೆ" in format_done("Gym", "kn")
    assert "marked as done" in format_done("Gym", "en")

    # Snoozed
    assert "मिनट के लिए स्नूज़" in format_snoozed("Gym", 10, "hi")
    assert "ನಿಮಿಷಗಳ ಕಾಲ ಸ್ನೂಜ್" in format_snoozed("Gym", 10, "kn")
    assert "Snoozed Gym for 10 minutes" in format_snoozed("Gym", 10, "en")


def test_text_turn_hinglish_detection_and_hindi_reply():
    """'kal subah 9 baje doctor ka appointment hai' -> language 'hi' and Hindi reply."""
    with patch.object(registry, "synthesize", new_callable=AsyncMock) as mock_synth, \
         patch.object(registry.llm, "chat", new_callable=AsyncMock) as mock_llm:
        
        mock_llm.return_value = {
            "content": "",
            "tool_calls": [
                {
                    "name": "add_task",
                    "arguments": {
                        "title": "Doctor appointment",
                        "time_phrase": "9 am",
                    }
                }
            ]
        }
        mock_synth.return_value = TTSResult(use_browser_tts=True, provider="browser")

        resp = client.post("/api/text/turn", data={"text": "kal subah 9 baje doctor ka appointment hai"})
        assert resp.status_code == 200
        data = resp.json()

        assert data["language"] == "hi"
        assert "Doctor appointment" in data["reply_text"]
        # Spoken confirmation is in Devanagari Hindi
        assert "सेट कर दिया गया है" in data["reply_text"]
        # Verify TTS was called with language="hi"
        assert mock_synth.call_args[0][1] == "hi"


def test_reminder_reply_response_includes_language():
    """Verify that /api/reminders/{id}/reply response includes 'language' field."""
    db = SessionLocal()
    task = Task(title="Doctor appointment", due_at=now_ist().replace(tzinfo=None),
                status=TaskStatus.DUE.value, language="hi")
    db.add(task)
    db.commit()
    task_id = task.id
    db.close()

    with patch.object(registry, "synthesize", new_callable=AsyncMock) as mock_synth:
        mock_synth.return_value = TTSResult(use_browser_tts=True, provider="browser")

        resp = client.post(f"/api/reminders/{task_id}/reply", data={"text": "ho gaya"})
        assert resp.status_code == 200
        data = resp.json()

        assert "language" in data
        assert data["language"] == "hi"
        assert data["outcome"] == "done"
        assert "पूरा हो गया" in data["reply_text"]
        assert mock_synth.call_args[0][1] == "hi"


def test_reminder_fired_prompt_uses_task_stored_language():
    """Verify fire-now produces localized prompt based on task.language."""
    db = SessionLocal()
    t_hi = Task(title="Dawai", due_at=now_ist().replace(tzinfo=None),
                status=TaskStatus.SCHEDULED.value, language="hi")
    t_kn = Task(title="Oota", due_at=now_ist().replace(tzinfo=None),
                status=TaskStatus.SCHEDULED.value, language="kn")
    t_en = Task(title="Standup", due_at=now_ist().replace(tzinfo=None),
                status=TaskStatus.SCHEDULED.value, language="en")
    db.add_all([t_hi, t_kn, t_en])
    db.commit()
    hi_id, kn_id, en_id = t_hi.id, t_kn.id, t_en.id
    db.close()

    with patch("routes.tasks.log_event") as mock_log:
        client.post(f"/api/tasks/{hi_id}/fire-now")
        assert mock_log.call_args[0][0] == "reminder_fired"
        assert "बज गए हैं" in mock_log.call_args[0][1]

        client.post(f"/api/tasks/{kn_id}/fire-now")
        assert "ಸಮಯ" in mock_log.call_args[0][1]

        client.post(f"/api/tasks/{en_id}/fire-now")
        assert "Done, snooze, or move to tomorrow?" in mock_log.call_args[0][1]
