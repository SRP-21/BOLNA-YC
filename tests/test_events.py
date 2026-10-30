"""
Tests for events and thread-safe SSE broadcast.
"""
import asyncio
import threading
import pytest
from events import subscribe, unsubscribe, log_event, set_loop


@pytest.mark.asyncio
async def test_threadsafe_log_event():
    """Verify log_event called from a plain thread delivers event to an async subscriber within 1s."""
    loop = asyncio.get_running_loop()
    set_loop(loop)

    q = subscribe()
    try:
        def background_writer():
            log_event("thread_test", "hello from thread", task_id=999)

        thread = threading.Thread(target=background_writer)
        thread.start()

        item = await asyncio.wait_for(q.get(), timeout=1.0)
        thread.join(timeout=1.0)

        assert item["type"] == "thread_test"
        assert item["message"] == "hello from thread"
        assert item["task_id"] == 999
    finally:
        unsubscribe(q)
        set_loop(None)
