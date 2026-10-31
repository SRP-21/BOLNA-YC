"""
API routes for behavior statistics and learned preferences.
GET /api/stats/categories — statistics per category & hour
GET /api/preferences — active preferences and pending preference offers
POST /api/preferences/{category}/accept — accept learned preference
POST /api/preferences/{category}/decline — decline learned preference (14-day cooldown)
DELETE /api/preferences/{category} — reset / remove learned preference
"""
from typing import Optional
from fastapi import APIRouter, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from db import SessionLocal, LearnedPreference
from agent.stats import (
    compute_category_stats, evaluate_learned_preferences,
    apply_learned_preference, decline_learned_preference,
    reset_learned_preference
)
from timeutil import now_ist

router = APIRouter()


class PreferenceAcceptRequest(BaseModel):
    offset_minutes: int
    evidence_count: int = 3
    is_synthetic: bool = False


@router.get("/api/stats/categories")
async def get_category_stats(category: Optional[str] = None):
    """Return deterministic statistics per category and hour."""
    db = SessionLocal()
    try:
        categories = [category] if category else ["health", "work", "errands", "family", "other"]
        results = {}
        for cat in categories:
            results[cat] = compute_category_stats(db, category=cat)
        results["overall"] = compute_category_stats(db, category=None)
        return results
    finally:
        db.close()


@router.get("/api/preferences")
async def get_preferences():
    """List active learned preferences and any eligible pending offers."""
    db = SessionLocal()
    try:
        prefs = db.query(LearnedPreference).all()
        now = now_ist()
        offers = evaluate_learned_preferences(db, now=now)
        return {
            "active_preferences": [{
                "id": p.id,
                "category": p.category,
                "offset_minutes": p.offset_minutes,
                "evidence_count": p.evidence_count,
                "is_active": p.is_active,
                "is_synthetic": p.is_synthetic,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            } for p in prefs if p.is_active],
            "offers": offers,
        }
    finally:
        db.close()


@router.post("/api/preferences/{category}/accept")
async def accept_preference(category: str, req: PreferenceAcceptRequest):
    """Accept and activate a learned preference."""
    db = SessionLocal()
    try:
        pref = apply_learned_preference(
            db,
            category=category,
            offset_minutes=req.offset_minutes,
            evidence_count=req.evidence_count,
            is_synthetic=req.is_synthetic,
        )
        return {
            "ok": True,
            "category": pref.category,
            "offset_minutes": pref.offset_minutes,
            "message": f"Applied {pref.offset_minutes}m offset for future {pref.category} reminders.",
        }
    finally:
        db.close()


@router.post("/api/preferences/{category}/decline")
async def decline_preference(category: str):
    """Decline a learned preference offer (14-day cooldown)."""
    db = SessionLocal()
    try:
        decline_learned_preference(db, category=category)
        return {
            "ok": True,
            "category": category,
            "message": f"Declined. Will not suggest {category} changes for 14 days.",
        }
    finally:
        db.close()


@router.delete("/api/preferences/{category}")
async def reset_preference(category: str):
    """Reset a learned preference back to default."""
    db = SessionLocal()
    try:
        reset_learned_preference(db, category=category)
        return {
            "ok": True,
            "category": category,
            "message": f"Reset {category} preference.",
        }
    finally:
        db.close()
