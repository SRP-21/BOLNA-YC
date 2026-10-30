"""
Event logging and SSE broadcasting.
Every state change writes to the events table; SSE clients get live updates.
"""
import asyncio
import json
from datetime import datetime, timezone
from typing import Optional
from db import SessionLocal, Event

# In-memory subscribers for SSE
_subscribers: list[asyncio.Queue] = []
_loop: Optional[asyncio.AbstractEventLoop] = None


def set_loop(loop: asyncio.AbstractEventLoop):
    """Set the running event loop for thread-safe event scheduling."""
    global _loop
    _loop = loop


def _enqueue(q: asyncio.Queue, item: dict):
    """Helper to safely put item into queue, dropping if full."""
    try:
        q.put_nowait(item)
    except asyncio.QueueFull:
        pass  # Drop if subscriber is too slow


def log_event(event_type: str, message: str, task_id: Optional[int] = None):
    """Write an event to the DB and broadcast to all SSE subscribers."""
    db = SessionLocal()
    try:
        event = Event(
            ts=datetime.now(timezone.utc),
            type=event_type,
            message=message,
            task_id=task_id
        )
        db.add(event)
        db.commit()
        db.refresh(event)

        # Broadcast to SSE subscribers
        data = {
            "id": event.id,
            "ts": event.ts.isoformat(),
            "type": event.type,
            "message": event.message,
            "task_id": event.task_id,
        }
        subscribers_copy = list(_subscribers)
        if _loop is not None and _loop.is_running():
            for q in subscribers_copy:
                _loop.call_soon_threadsafe(_enqueue, q, data)
        else:
            for q in subscribers_copy:
                _enqueue(q, data)
    finally:
        db.close()


def subscribe() -> asyncio.Queue:
    q = asyncio.Queue(maxsize=100)
    _subscribers.append(q)
    return q


def unsubscribe(q: asyncio.Queue):
    if q in _subscribers:
        _subscribers.remove(q)


async def event_generator(q: asyncio.Queue):
    """Async generator for SSE stream."""
    try:
        while True:
            data = await q.get()
            yield json.dumps(data)
    except asyncio.CancelledError:
        unsubscribe(q)
        raise

