"""
Main FastAPI application.
Voice-first daily planner — "a planner you talk to, that talks back."
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from db import init_db
from scheduler import scheduler, reload_pending_tasks
from routes.voice import router as voice_router
from routes.tasks import router as tasks_router
from routes.events_routes import router as events_router

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    # Startup
    logger.info("🚀 Starting Voice Planner...")
    init_db()
    logger.info("📦 Database initialized")

    scheduler.start()
    logger.info("⏰ Scheduler started")

    reload_pending_tasks()
    logger.info("📋 Pending tasks reloaded")

    yield

    # Shutdown
    scheduler.shutdown(wait=False)
    logger.info("👋 Scheduler stopped. Goodbye!")


app = FastAPI(
    title="Voice Planner",
    description="A planner you talk to, that talks back",
    version="1.0.0",
    lifespan=lifespan,
)

# Routes
app.include_router(voice_router)
app.include_router(tasks_router)
app.include_router(events_router)

# Static files
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root():
    return FileResponse("static/index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

