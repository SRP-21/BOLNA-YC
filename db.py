"""
Database models and engine setup.
SQLite via SQLAlchemy with WAL mode, normal synchronous, and 20s busy timeout for rock-solid concurrency.

TIMEZONE CONVENTION:
- Task.due_at is stored in SQLite as NAIVE IST (Asia/Kolkata) wall-clock time.
- Task.created_at, Task.updated_at, Event.ts, and Utterance.ts are stored as UTC.
- Use timeutil.now_ist(), timeutil.to_ist_naive(dt), and timeutil.ensure_ist(dt) for conversions.
"""
from sqlalchemy import (
    create_engine, Column, Integer, String, DateTime, Boolean, Text, event
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from datetime import datetime, timezone
import enum

DATABASE_URL = "sqlite:///./planner.db"

# connect_args timeout=20 ensures waiting gracefully on concurrency
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 20}
)


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Enable WAL mode, NORMAL synchronous, and 20s busy timeout on SQLite connection."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=20000")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class TaskStatus(str, enum.Enum):
    SCHEDULED = "scheduled"
    DUE = "due"
    DONE = "done"
    SNOOZED = "snoozed"
    MISSED = "missed"
    CANCELLED = "cancelled"


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, default=1)
    title = Column(String, nullable=False)
    due_at = Column(DateTime, nullable=False)
    recurrence = Column(String, nullable=True)
    status = Column(String, default=TaskStatus.SCHEDULED.value)
    needs_confirmation = Column(Boolean, default=False)
    source_phrase = Column(Text, nullable=True)
    resolution_note = Column(Text, nullable=True)
    snooze_count = Column(Integer, default=0)
    language = Column(String, default="en")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


class Utterance(Base):
    __tablename__ = "utterances"

    id = Column(Integer, primary_key=True, autoincrement=True)
    role = Column(String, nullable=False)
    text = Column(Text, nullable=False)
    language = Column(String, default="en")
    ts = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ts = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    type = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    task_id = Column(Integer, nullable=True)


class UsageCounter(Base):
    """Track daily API usage to stay within free-tier limits."""
    __tablename__ = "usage_counters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(String, nullable=False)
    provider = Column(String, nullable=False)
    request_count = Column(Integer, default=0)
    token_count = Column(Integer, default=0)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
