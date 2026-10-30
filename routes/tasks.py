"""
Task CRUD routes.
GET /api/tasks — list all tasks
PATCH /api/tasks/{id} — update a task
DELETE /api/tasks/{id} — cancel a task
POST /api/tasks/{id}/fire-now — trigger reminder immediately (for demos)
POST /api/reminders/{task_id}/reply — handle reminder reply (voice or text)
"""
import base64
import logging
from fastapi import APIRouter, Form, UploadFile, File
from fastapi.responses import JSONResponse
from typing import Optional
from datetime import datetime
from zoneinfo import ZoneInfo
from db import SessionLocal, Task, TaskStatus
from events import log_event
from agent.outcome import parse_outcome
from agent.resolver import compute_snooze, resolve_time
from timeutil import IST, now_ist, ensure_ist, to_ist_naive
from scheduler import schedule_task_reminder, remove_task_job
from providers.registry import registry
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/tasks")
async def list_tasks():
    """List all tasks, sorted by due time."""
    db = SessionLocal()
    try:
        tasks = db.query(Task).order_by(Task.due_at).all()
        return [{
            "id": t.id,
            "title": t.title,
            "due_at": t.due_at.isoformat() if t.due_at else None,
            "recurrence": t.recurrence,
            "status": t.status,
            "needs_confirmation": t.needs_confirmation,
            "resolution_note": t.resolution_note,
            "source_phrase": t.source_phrase,
            "snooze_count": t.snooze_count,
            "language": t.language,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        } for t in tasks]
    finally:
        db.close()


@router.patch("/api/tasks/{task_id}")
async def update_task(task_id: int, title: Optional[str] = Form(None),
                      due_at: Optional[str] = Form(None),
                      status: Optional[str] = Form(None)):
    """Update a task's title, time, or status."""
    db = SessionLocal()
    try:
        task = db.query(Task).filter_by(id=task_id).first()
        if not task:
            return JSONResponse(status_code=404, content={"error": "Task not found"})

        if title:
            task.title = title
        if due_at:
            parsed_dt = datetime.fromisoformat(due_at)
            task.due_at = to_ist_naive(parsed_dt)
            schedule_task_reminder(task.id, task.due_at)
        if status:
            task.status = status
            if status == TaskStatus.CANCELLED.value:
                remove_task_job(task.id)

        task.needs_confirmation = False  # User confirmed by editing
        db.commit()
        log_event("task_updated", f"Edited: {task.title}", task_id=task.id)
        return {"ok": True, "task_id": task.id}
    finally:
        db.close()


@router.delete("/api/tasks/{task_id}")
async def delete_task(task_id: int):
    """Cancel a task."""
    db = SessionLocal()
    try:
        task = db.query(Task).filter_by(id=task_id).first()
        if not task:
            return JSONResponse(status_code=404, content={"error": "Task not found"})

        task.status = TaskStatus.CANCELLED.value
        db.commit()
        remove_task_job(task.id)
        log_event("task_cancelled", f"Cancelled: {task.title}", task_id=task.id)
        return {"ok": True}
    finally:
        db.close()


@router.post("/api/tasks/{task_id}/fire-now")
async def fire_now(task_id: int):
    """Trigger a reminder immediately. For stage demos."""
    db = SessionLocal()
    try:
        task = db.query(Task).filter_by(id=task_id).first()
        if not task:
            return JSONResponse(status_code=404, content={"error": "Task not found"})

        task.status = TaskStatus.DUE.value
        db.commit()

        due_str = task.due_at.strftime('%I:%M %p') if task.due_at else "now"
        log_event(
            "reminder_fired",
            f"{task.title} — it's {due_str}. Done, snooze, or move to tomorrow?",
            task_id=task.id
        )
        return {"ok": True, "task_id": task.id, "title": task.title}
    finally:
        db.close()


@router.post("/api/reminders/{task_id}/reply")
async def reminder_reply(
    task_id: int,
    text: Optional[str] = Form(None),
    audio: Optional[UploadFile] = File(None),
    language_hint: Optional[str] = Form(None),
):
    """
    Handle a reminder reply (voice or text).
    Parses the outcome and updates the task + schedule accordingly.
    """
    db = SessionLocal()
    try:
        task = db.query(Task).filter_by(id=task_id).first()
        if not task:
            return JSONResponse(status_code=404, content={"error": "Task not found"})

        # Transcribe if audio
        reply_text = text or ""
        if audio and not reply_text:
            audio_bytes = await audio.read()
            mime_type = audio.content_type or "audio/webm"
            stt_result = await registry.transcribe(audio_bytes, mime_type, language_hint)
            reply_text = stt_result.text

        # Parse outcome
        outcome = await parse_outcome(reply_text, task.title)

        # Apply outcome
        reply_message = ""
        if outcome.outcome == "done":
            task.status = TaskStatus.DONE.value
            remove_task_job(task.id)
            reply_message = f"Great, {task.title} marked as done! ✓"
            log_event("task_done", f"Done: {task.title}", task_id=task.id)

            # Handle recurrence
            if task.recurrence:
                from scheduler import _schedule_next_recurrence
                _schedule_next_recurrence(db, task)

        elif outcome.outcome == "snooze":
            minutes = outcome.minutes or 10
            new_due = compute_snooze(now_ist(), minutes)
            task.status = TaskStatus.SNOOZED.value
            task.due_at = to_ist_naive(new_due)
            task.snooze_count += 1
            schedule_task_reminder(task.id, new_due)
            reply_message = f"Snoozed {task.title} for {minutes} minutes."
            log_event("task_snoozed", f"Snoozed: {task.title} +{minutes}min", task_id=task.id)

        elif outcome.outcome == "reschedule":
            if outcome.new_time_phrase:
                resolved = resolve_time(outcome.new_time_phrase)
                task.due_at = to_ist_naive(resolved.dt)
                task.status = TaskStatus.SCHEDULED.value
                schedule_task_reminder(task.id, resolved.dt)
                reply_message = f"Moved {task.title} to {resolved.dt.strftime('%I:%M %p')}."
            else:
                # Default: move to tomorrow same time
                from datetime import timedelta
                new_due = ensure_ist(task.due_at) + timedelta(days=1)
                task.due_at = to_ist_naive(new_due)
                task.status = TaskStatus.SCHEDULED.value
                schedule_task_reminder(task.id, new_due)
                reply_message = f"Moved {task.title} to tomorrow."
            log_event("task_rescheduled", reply_message, task_id=task.id)

        elif outcome.outcome == "cancel":
            task.status = TaskStatus.CANCELLED.value
            remove_task_job(task.id)
            reply_message = f"Cancelled {task.title}."
            log_event("task_cancelled", f"Cancelled: {task.title}", task_id=task.id)

        else:  # no_response
            reply_message = f"I didn't catch that. Is {task.title} done?"

        db.commit()

        # TTS for the reply
        tts_result = await registry.synthesize(reply_message, task.language or "en")
        response = {
            "outcome": outcome.outcome,
            "reply_text": reply_message,
            "task_id": task.id,
            "tts_fallback": tts_result.use_browser_tts,
        }
        if not tts_result.use_browser_tts and tts_result.audio_bytes:
            response["audio_base64"] = base64.b64encode(tts_result.audio_bytes).decode()
            response["audio_mime"] = tts_result.mime_type

        return JSONResponse(content=response)
    finally:
        db.close()

