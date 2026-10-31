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

import re

logger = logging.getLogger(__name__)
router = APIRouter()

TRAILING_STOP_RE = re.compile(
    r"[\s,;.-]+(?:that's\s+all|that\s+is\s+all|stop|bas|बस|ಸಾಕು)[\s.!?]*$",
    re.IGNORECASE,
)

STOP_WORDS = {"stop", "that's all", "that is all", "bas", "बस", "ಸಾಕು"}


def is_exact_stop(text: Optional[str]) -> bool:
    """Return True only if text is an EXACT match of a stop word after trimming punctuation and case."""
    if not text:
        return False
    norm = text.strip().lower().strip(" \t\n\r.!?,-;:\"'~`#")
    return norm in STOP_WORDS


def is_stop_command(text: Optional[str]) -> bool:
    """Backwards-compatible alias for is_exact_stop."""
    return is_exact_stop(text)


def has_trailing_stop(text: Optional[str]) -> bool:
    """Return True if text ends with a trailing stop phrase (longer utterance)."""
    if not text:
        return False
    t = text.strip()
    if is_exact_stop(t):
        return False
    return bool(TRAILING_STOP_RE.search(t))


def strip_trailing_stop(text: Optional[str]) -> str:
    """Strip a trailing stop phrase or standalone stop word from text."""
    if not text:
        return ""
    t = text.strip()
    if is_exact_stop(t):
        return ""
    match = TRAILING_STOP_RE.search(t)
    if match:
        return t[:match.start()].strip(" \t\n\r,;.-")
    return t


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

        raw_text = stt_result.text or ""
        detected_language = stt_result.language
        eff_lang = detected_language or "en"

        # 1. Exact stop command: triggers stop immediately with no task
        if is_exact_stop(raw_text):
            stop_reply = "Okay, going idle."
            tts_res = await registry.synthesize(stop_reply, eff_lang)
            resp = {
                "transcript": raw_text,
                "reply_text": stop_reply,
                "task_changes": [],
                "language": eff_lang,
                "tts_fallback": tts_res.use_browser_tts,
                "tts_provider_used": tts_res.provider,
                "expects_reply": False,
                "stopped": True,
            }
            if not tts_res.use_browser_tts and tts_res.audio_bytes:
                resp["audio_base64"] = base64.b64encode(tts_res.audio_bytes).decode()
                resp["audio_mime"] = tts_res.mime_type
            return JSONResponse(content=resp)

        # 2. Check for trailing stop phrase in longer utterance
        had_trailing_stop = has_trailing_stop(raw_text)
        user_text = strip_trailing_stop(raw_text)

        # Treat empty or hint-echoed transcripts as unclear
        if not user_text.strip() or is_hint_echo(user_text, prompt_hint):
            return JSONResponse(content={
                "transcript": "",
                "reply_text": "I didn't catch that. Could you say it again?",
                "tts_fallback": True,
                "tts_provider_used": "browser",
                "task_changes": [],
                "language": detected_language,
                "expects_reply": False,
            })

        # Agent
        result = await process_turn(user_text, eff_lang)
        final_lang = result.get("language") or eff_lang

        # TTS
        tts_result = await registry.synthesize(
            result["reply_text"], final_lang
        )

        from agent.pending_action import get_pending_action
        from agent.pending_choice import get_pending_choice
        has_pending = (
            get_pending_action() is not None
            or get_pending_choice() is not None
            or bool(result.get("replan_preview"))
        )
        expects_reply = False if had_trailing_stop else bool(has_pending)
        stopped = bool(had_trailing_stop)

        response = {
            "transcript": raw_text,
            "reply_text": result["reply_text"],
            "task_changes": result["task_changes"],
            "language": final_lang,
            "tts_fallback": tts_result.use_browser_tts,
            "tts_provider_used": tts_result.provider,
            "expects_reply": expects_reply,
            "stopped": stopped,
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

        # 1. Exact stop command: triggers stop immediately with no task
        if is_exact_stop(text):
            stop_reply = "Okay, going idle."
            tts_res = await registry.synthesize(stop_reply, eff_lang)
            resp = {
                "transcript": text,
                "reply_text": stop_reply,
                "task_changes": [],
                "language": eff_lang,
                "tts_fallback": tts_res.use_browser_tts,
                "tts_provider_used": tts_res.provider,
                "expects_reply": False,
                "stopped": True,
                "input_mode": "text",
            }
            if not tts_res.use_browser_tts and tts_res.audio_bytes:
                resp["audio_base64"] = base64.b64encode(tts_res.audio_bytes).decode()
                resp["audio_mime"] = tts_res.mime_type
            return JSONResponse(content=resp)

        # 2. Check for trailing stop phrase in longer utterance
        had_trailing_stop = has_trailing_stop(text)
        cleaned_text = strip_trailing_stop(text)
        if not cleaned_text.strip():
            return JSONResponse(content={
                "transcript": "",
                "reply_text": "I didn't catch that. Could you say it again?",
                "tts_fallback": True,
                "tts_provider_used": "browser",
                "task_changes": [],
                "language": language or "en",
                "expects_reply": False,
                "input_mode": "text",
            })
        eff_lang = language if (language and language != "en") else detect_language(cleaned_text, fallback="en")
        turn_now = None
        if now and getattr(settings, "enable_test_clock", False):
            from datetime import datetime
            from timeutil import ensure_ist
            try:
                turn_now = ensure_ist(datetime.fromisoformat(now))
            except Exception:
                turn_now = None
        result = await process_turn(cleaned_text, eff_lang, now=turn_now)
        final_lang = result.get("language") or eff_lang

        # TTS for the reply
        tts_result = await registry.synthesize(
            result["reply_text"], final_lang
        )

        from agent.pending_action import get_pending_action
        from agent.pending_choice import get_pending_choice
        has_pending = (
            get_pending_action(now=turn_now) is not None
            or get_pending_choice(now=turn_now) is not None
            or bool(result.get("replan_preview"))
        )
        expects_reply = False if had_trailing_stop else bool(has_pending)
        stopped = bool(had_trailing_stop)

        response = {
            "transcript": text,
            "reply_text": result["reply_text"],
            "task_changes": result["task_changes"],
            "language": final_lang,
            "tts_fallback": tts_result.use_browser_tts,
            "tts_provider_used": tts_result.provider,
            "input_mode": "text",
            "expects_reply": expects_reply,
            "stopped": stopped,
        }

        if not tts_result.use_browser_tts and tts_result.audio_bytes:
            response["audio_base64"] = base64.b64encode(tts_result.audio_bytes).decode()
            response["audio_mime"] = tts_result.mime_type

        return JSONResponse(content=response)

    except Exception as e:
        logger.exception(f"Text turn error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

