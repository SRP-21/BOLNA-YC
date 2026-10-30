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

logger = logging.getLogger(__name__)
router = APIRouter()


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

        # STT
        try:
            stt_result = await registry.transcribe(audio_bytes, mime_type, language_hint)
        except Exception as e:
            logger.error(f"STT failed: {e}")
            return JSONResponse(status_code=500, content={
                "error": "Speech recognition failed",
                "detail": str(e),
                "fallback": "text",
            })

        user_text = stt_result.text
        detected_language = stt_result.language

        if not user_text.strip():
            return JSONResponse(content={
                "transcript": "",
                "reply_text": "I didn't catch that. Could you say it again?",
                "tts_fallback": True,
                "task_changes": [],
                "language": detected_language,
            })

        # Agent
        result = await process_turn(user_text, detected_language)

        # TTS
        tts_result = await registry.synthesize(
            result["reply_text"], detected_language
        )

        response = {
            "transcript": user_text,
            "reply_text": result["reply_text"],
            "task_changes": result["task_changes"],
            "language": detected_language,
            "tts_fallback": tts_result.use_browser_tts,
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
    language: Optional[str] = Form("en"),
):
    """
    Text input fallback — goes through the exact same pipeline.
    Same agent, same resolver, same everything.
    """
    try:
        result = await process_turn(text, language or "en")

        # TTS for the reply
        tts_result = await registry.synthesize(
            result["reply_text"], result.get("language", "en")
        )

        response = {
            "transcript": text,
            "reply_text": result["reply_text"],
            "task_changes": result["task_changes"],
            "language": result.get("language", "en"),
            "tts_fallback": tts_result.use_browser_tts,
            "input_mode": "text",
        }

        if not tts_result.use_browser_tts and tts_result.audio_bytes:
            response["audio_base64"] = base64.b64encode(tts_result.audio_bytes).decode()
            response["audio_mime"] = tts_result.mime_type

        return JSONResponse(content=response)

    except Exception as e:
        logger.exception(f"Text turn error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

