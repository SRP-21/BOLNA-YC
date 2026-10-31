"""
Voice and text turn routes.
POST /api/voice/turn — audio -> STT -> agent -> TTS
POST /api/text/turn — text -> agent -> TTS
"""
import base64
import logging
from fastapi import APIRouter, UploadFile, File, Form
from fastapi.responses import JSONResponse
from typing import Optional
from agent.planner import process_turn
from providers.registry import registry
from db import SessionLocal, Task, TaskStatus
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


def is_hint_echo(transcript: str, hint: Optional[str]) -> bool:
    """Return True if transcript equals or is mostly the prompt hint text (hallucinated echo)."""
    if not hint or not transcript:
        return False
    t_norm = transcript.strip().lower().rstrip(".!?")
    h_norm = hint.strip().lower().rstrip(".!?")
    if not t_norm:
        return False
    if t_norm == h_norm:
        return True
    h_noprefix = h_norm.replace("reminders:", "").strip()
    if t_norm == h_noprefix:
        return True
    import difflib
    if difflib.SequenceMatcher(None, t_norm, h_norm).ratio() > 0.7:
        return True
    if difflib.SequenceMatcher(None, t_norm, h_noprefix).ratio() > 0.7:
        return True
    return False


@router.post("/api/voice/turn")
async def voice_turn(
    audio: UploadFile = File(...),
    language_hint: Optional[str] = Form(None),
):
    """
    Full voice loop: audio -> STT -> agent -> TTS.
    Returns transcript, reply text, audio (base64) or tts-fallback flag, and task changes.
    """
    try:
        audio_bytes = await audio.read()
        mime_type = audio.content_type or "audio/webm"

        # STT (prime Whisper with active task titles, capped to ~200 tokens, most recent first)
        prompt_hint = None
        db = SessionLocal()
        try:
            active = db.query(Task).filter(
                Task.status.in_([TaskStatus.SCHEDULED.value, TaskStatus.SNOOZED.value, TaskStatus.DUE.value])
            ).order_by(Task.id.desc()).all()
            titles = [t.title for t in active if t.title]
            if titles:
                selected_titles = []
                cur_tokens = 0
                for t in titles:
                    t_tok = max(1, len(t.split()))
                    if cur_tokens + t_tok > 200:
                        break
                    selected_titles.append(t)
                    cur_tokens += t_tok
                if selected_titles:
                    prompt_hint = f"Reminders: {', '.join(selected_titles)}"
        finally:
            db.close()

        try:
            stt_result = await registry.transcribe(
                audio_bytes, mime_type, language_hint, prompt=prompt_hint
            )
        except Exception as e:
            logger.error(f"STT failed: {e}")
            return JSONResponse(status_code=500, content={
                "error": "Speech recognition failed",
                "detail": str(e),
                "fallback": "text",
            })

        user_text = stt_result.text
        detected_language = stt_result.language

        # Treat empty or hint-echoed transcripts as unclear
        if not user_text.strip() or is_hint_echo(user_text, prompt_hint):
            return JSONResponse(content={
                "transcript": "",
                "reply_text": "I didn't catch that. Could you say it again?",
                "tts_fallback": True,
                "tts_provider_used": "browser",
                "task_changes": [],
                "language": detected_language,
            })

        # Agent
        eff_lang = detected_language or "en"
        result = await process_turn(user_text, eff_lang)
        final_lang = result.get("language") or eff_lang

        # TTS
        tts_result = await registry.synthesize(
            result["reply_text"], final_lang
        )

        response = {
            "transcript": user_text,
            "reply_text": result["reply_text"],
            "task_changes": result["task_changes"],
            "language": final_lang,
            "tts_fallback": tts_result.use_browser_tts,
            "tts_provider_used": tts_result.provider,
        }

        if not tts_result.use_browser_tts and tts_result.audio_bytes:
            response["audio_base64"] = base64.b64encode(tts_result.audio_bytes).decode()
            response["audio_mime"] = tts_result.mime_type

        return JSONResponse(content=response)

    except Exception as e:
        logger.exception(f"Voice turn error: {e}")
        return JSONResponse(status_code=500, content={
            "error": str(e),
            "fallback": "text",
        })


@router.post("/api/text/turn")
async def text_turn(
    text: str = Form(...),
    language: Optional[str] = Form(None),
    now: Optional[str] = Form(None),
):
    """
    Text input fallback — goes through the exact same pipeline.
    Same agent, same resolver, same everything.
    """
    try:
        from agent.lang import detect_language
        eff_lang = language if (language and language != "en") else detect_language(text, fallback="en")
        turn_now = None
        if now and getattr(settings, "enable_test_clock", False):
            from datetime import datetime
            from timeutil import ensure_ist
            try:
                turn_now = ensure_ist(datetime.fromisoformat(now))
            except Exception:
                turn_now = None
        result = await process_turn(text, eff_lang, now=turn_now)
        final_lang = result.get("language") or eff_lang

        # TTS for the reply
        tts_result = await registry.synthesize(
            result["reply_text"], final_lang
        )

        response = {
            "transcript": text,
            "reply_text": result["reply_text"],
            "task_changes": result["task_changes"],
            "language": final_lang,
            "tts_fallback": tts_result.use_browser_tts,
            "tts_provider_used": tts_result.provider,
            "input_mode": "text",
        }

        if not tts_result.use_browser_tts and tts_result.audio_bytes:
            response["audio_base64"] = base64.b64encode(tts_result.audio_bytes).decode()
            response["audio_mime"] = tts_result.mime_type

        return JSONResponse(content=response)

    except Exception as e:
        logger.exception(f"Text turn error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

