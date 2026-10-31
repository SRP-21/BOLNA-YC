"""
API routes for evening recap, carry-over, and honest demo data.
GET /api/recap — today's recap summary & 7-day completion trend
POST /api/recap/carryover — move missed tasks to tomorrow morning
POST /api/dev/generate-demo-data — generate 1 week of synthetic history (behind config flag)
POST /api/dev/clear-demo-data — clear synthetic data
"""
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import SessionLocal
from agent.recap import build_evening_recap, apply_carryover_to_tomorrow
from agent.demo_data import generate_demo_data, clear_demo_data
from timeutil import now_ist
from config import settings

router = APIRouter()


class CarryOverRequest(BaseModel):
    pass


class DemoDataRequest(BaseModel):
    force_enable: bool = False


@router.get("/api/recap")
async def get_recap(language: str = "en"):
    """Get today's evening recap, missed tasks, and 7-day trend."""
    db = SessionLocal()
    try:
        now = now_ist()
        recap = build_evening_recap(db, now=now, language=language)
        return recap
    finally:
        db.close()


@router.post("/api/recap/carryover")
async def carryover_missed_tasks():
    """Carry over all today's missed tasks to tomorrow morning (09:00 IST)."""
    db = SessionLocal()
    try:
        now = now_ist()
        result = apply_carryover_to_tomorrow(db, now=now)
        return result
    finally:
        db.close()


@router.post("/api/dev/generate-demo-data")
async def generate_synthetic_data(req: Optional[DemoDataRequest] = None):
    """Generate 1 week of realistic synthetic history (gated behind ENABLE_DEMO_DATA)."""
    force = req.force_enable if req else False
    db = SessionLocal()
    try:
        now = now_ist()
        return generate_demo_data(db, now=now, enabled=force)
    finally:
        db.close()


@router.post("/api/dev/clear-demo-data")
async def clear_synthetic_data():
    """Clear all synthetic tasks and preferences."""
    db = SessionLocal()
    try:
        return clear_demo_data(db)
    finally:
        db.close()
