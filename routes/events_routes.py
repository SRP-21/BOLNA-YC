"""
SSE events stream and health route.
"""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse
from events import subscribe, unsubscribe, event_generator
from providers.registry import registry
from db import SessionLocal, Event

router = APIRouter()


@router.get("/api/events/stream")
async def events_stream(request: Request):
    """SSE stream for live dashboard updates."""
    q = subscribe()

    async def generate():
        try:
            async for data in event_generator(q):
                if await request.is_disconnected():
                    break
                yield {"data": data}
        finally:
            unsubscribe(q)

    return EventSourceResponse(generate())


@router.get("/api/events")
async def list_events(limit: int = 50):
    """Get recent events for initial dashboard load."""
    db = SessionLocal()
    try:
        events = db.query(Event).order_by(Event.ts.desc()).limit(limit).all()
        return [{
            "id": e.id,
            "ts": e.ts.isoformat() if e.ts else None,
            "type": e.type,
            "message": e.message,
            "task_id": e.task_id,
        } for e in reversed(events)]
    finally:
        db.close()


@router.get("/api/health")
async def health():
    """Health check with active providers and usage counters."""
    status = registry.health_status()
    return JSONResponse(content={
        "status": "ok",
        "providers": status,
    })

