"""
Replan API routes:
POST /api/replan/preview — preview schedule changes without committing
POST /api/replan/confirm — commit the previewed replan
POST /api/replan/reject  — discard the previewed replan
POST /api/replan/undo    — restore prior schedule state from snapshot
"""
import logging
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from db import SessionLocal
from agent.replan import (
    extract_replan_intent, get_pending_plan, set_pending_plan,
    compute_replan, apply_replan_commit, apply_replan_undo,
    ReplanIntent
)
from timeutil import now_ist

logger = logging.getLogger(__name__)
router = APIRouter()


class ReplanRequest(BaseModel):
    text: Optional[str] = None
    intent_type: Optional[str] = None
    minutes: Optional[int] = None
    task_identifier: Optional[str] = None
    task_identifier_2: Optional[str] = None
    destination_phrase: Optional[str] = None
    now: Optional[str] = None


@router.post("/api/replan/preview")
async def replan_preview(req: ReplanRequest):
    """Compute and store a preview plan for confirmation."""
    now = datetime.fromisoformat(req.now) if req.now else now_ist()
    db = SessionLocal()
    try:
        intent = None
        if req.intent_type:
            intent = ReplanIntent(
                intent_type=req.intent_type,
                minutes=req.minutes,
                task_identifier=req.task_identifier,
                task_identifier_2=req.task_identifier_2,
                destination_phrase=req.destination_phrase,
            )
        elif req.text:
            intent = await extract_replan_intent(req.text, now)

        if not intent:
            return JSONResponse(status_code=400, content={"error": "Could not parse replan intent"})

        plan = compute_replan(db, intent, now=now)
        set_pending_plan(plan)
        return plan.to_dict()
    finally:
        db.close()


@router.post("/api/replan/confirm")
async def replan_confirm():
    """Commit the active pending plan."""
    plan = get_pending_plan()
    if not plan or not plan.changes:
        return JSONResponse(status_code=400, content={"error": "No pending replan to confirm"})

    db = SessionLocal()
    try:
        snapshot = apply_replan_commit(db, plan, reason=plan.reason)
        set_pending_plan(None)
        return {
            "ok": True,
            "snapshot_id": snapshot.id,
            "tasks_updated": len(plan.changes),
            "summary": plan.summary,
        }
    finally:
        db.close()


@router.post("/api/replan/reject")
async def replan_reject():
    """Discard active pending plan."""
    set_pending_plan(None)
    return {"ok": True, "message": "Replan discarded"}


@router.post("/api/replan/undo")
async def replan_undo(snapshot_id: Optional[int] = None):
    """Restore previous schedule from snapshot."""
    db = SessionLocal()
    try:
        res = apply_replan_undo(db, snapshot_id=snapshot_id)
        if not res.get("ok"):
            return JSONResponse(status_code=400, content=res)
        return res
    finally:
        db.close()
