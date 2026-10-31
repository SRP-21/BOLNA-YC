"""
Tests for Stage 5 (Fix D): Deterministic ambiguity checks before LLM acts.
- Covers actions: cancel, move, snooze, update, and 'done'/'ho gaya'.
- Multilingual testing: English, Hindi (native Devanagari script), Kannada (native script).
- Ensures nothing in the database changes until the user answers the which-one question.
"""
import pytest
from datetime import datetime
from unittest.mock import patch, AsyncMock

from db import init_db, SessionLocal, Task, TaskStatus
from agent.planner import process_turn
from timeutil import IST

FROZEN_NOW = datetime(2026, 10, 31, 10, 0, 0, tzinfo=IST)


@pytest.fixture(autouse=True)
def clean_db():
    init_db()
    db = SessionLocal()
    db.query(Task).delete()
    db.commit()
    db.close()
    yield
    db = SessionLocal()
    db.query(Task).delete()
    db.commit()
    db.close()


def _setup_ambiguous_tasks():
    db = SessionLocal()
    t1 = Task(title="Gym", due_at=datetime(2026, 10, 31, 17, 0, 0), status=TaskStatus.SCHEDULED.value)
    t2 = Task(title="Gym class", due_at=datetime(2026, 10, 31, 18, 0, 0), status=TaskStatus.SCHEDULED.value)
    db.add_all([t1, t2])
    db.commit()
    id1, id2 = t1.id, t2.id
    db.close()
    return id1, id2


@pytest.mark.asyncio
async def test_ambiguity_cancel_all_languages():
    """Cancel action triggers deterministic ambiguity question in en, hi, kn without touching DB."""
    # 1. English
    id1, id2 = _setup_ambiguous_tasks()
    res_en = await process_turn("cancel gym", language="en", now=FROZEN_NOW)
    assert "Which one did you mean: Gym or Gym class?" in res_en["reply_text"]
    assert res_en["task_changes"] == [{"type": "ambiguous", "candidates": ["Gym", "Gym class"]}]

    db = SessionLocal()
    assert db.query(Task).filter(Task.status == TaskStatus.SCHEDULED.value).count() == 2
    db.close()

    # 2. Hindi (native script)
    res_hi = await process_turn("जिम कैंसिल कर दो", language="hi", now=FROZEN_NOW)
    assert "आपका कौन सा मतलब था: Gym या Gym class?" in res_hi["reply_text"]
    assert res_hi["task_changes"] == [{"type": "ambiguous", "candidates": ["Gym", "Gym class"]}]

    res_hi_hatao = await process_turn("जिम हटाओ", language="hi", now=FROZEN_NOW)
    assert "आपका कौन सा मतलब था: Gym या Gym class?" in res_hi_hatao["reply_text"]

    db = SessionLocal()
    assert db.query(Task).filter(Task.status == TaskStatus.SCHEDULED.value).count() == 2
    db.close()

    # 3. Kannada (native script)
    res_kn = await process_turn("ಜಿಮ್ ರದ್ದು ಮಾಡಿ", language="kn", now=FROZEN_NOW)
    assert "ನಿಮ್ಮ ಉದ್ದೇಶ ಯಾವುದು: Gym ಅಥವಾ Gym class?" in res_kn["reply_text"]
    assert res_kn["task_changes"] == [{"type": "ambiguous", "candidates": ["Gym", "Gym class"]}]

    db = SessionLocal()
    assert db.query(Task).filter(Task.status == TaskStatus.SCHEDULED.value).count() == 2
    db.close()


@pytest.mark.asyncio
async def test_ambiguity_done_ho_gaya_all_languages():
    """'done' / 'ho gaya' triggers deterministic ambiguity question in en, hi, kn without touching DB."""
    id1, id2 = _setup_ambiguous_tasks()

    # 1. English: "gym done"
    res_en = await process_turn("gym done", language="en", now=FROZEN_NOW)
    assert "Which one did you mean: Gym or Gym class?" in res_en["reply_text"]

    db = SessionLocal()
    assert db.query(Task).filter(Task.status == TaskStatus.SCHEDULED.value).count() == 2
    db.close()

    # 2. Hindi: "जिम हो गया"
    res_hi = await process_turn("जिम हो गया", language="hi", now=FROZEN_NOW)
    assert "आपका कौन सा मतलब था: Gym या Gym class?" in res_hi["reply_text"]

    db = SessionLocal()
    assert db.query(Task).filter(Task.status == TaskStatus.SCHEDULED.value).count() == 2
    db.close()

    # 3. Kannada: "ಜಿಮ್ ಮುಗಿಯಿತು"
    res_kn = await process_turn("ಜಿಮ್ ಮುಗಿಯಿತು", language="kn", now=FROZEN_NOW)
    assert "ನಿಮ್ಮ ಉದ್ದೇಶ ಯಾವುದು: Gym ಅಥವಾ Gym class?" in res_kn["reply_text"]

    db = SessionLocal()
    assert db.query(Task).filter(Task.status == TaskStatus.SCHEDULED.value).count() == 2
    db.close()


@pytest.mark.asyncio
async def test_ambiguity_snooze_all_languages():
    """'snooze' triggers deterministic ambiguity question in en, hi, kn without touching DB."""
    id1, id2 = _setup_ambiguous_tasks()

    # 1. English
    res_en = await process_turn("snooze gym", language="en", now=FROZEN_NOW)
    assert "Which one did you mean: Gym or Gym class?" in res_en["reply_text"]

    # 2. Hindi (native script)
    res_hi = await process_turn("जिम स्नूज़ करो", language="hi", now=FROZEN_NOW)
    assert "आपका कौन सा मतलब था: Gym या Gym class?" in res_hi["reply_text"]

    # 3. Kannada (native script)
    res_kn = await process_turn("ಜಿಮ್ ಸ್ನೂಜ್ ಮಾಡಿ", language="kn", now=FROZEN_NOW)
    assert "ನಿಮ್ಮ ಉದ್ದೇಶ ಯಾವುದು: Gym ಅಥವಾ Gym class?" in res_kn["reply_text"]

    db = SessionLocal()
    assert db.query(Task).filter(Task.status == TaskStatus.SCHEDULED.value).count() == 2
    db.close()


@pytest.mark.asyncio
async def test_ambiguity_move_update_all_languages():
    """'move' / 'update' triggers deterministic ambiguity question in en, hi, kn without touching DB."""
    id1, id2 = _setup_ambiguous_tasks()

    # 1. English
    res_en = await process_turn("move gym to 8 pm", language="en", now=FROZEN_NOW)
    assert "Which one did you mean: Gym or Gym class?" in res_en["reply_text"]

    # 2. Hindi (native script)
    res_hi = await process_turn("जिम आगे बढ़ाओ", language="hi", now=FROZEN_NOW)
    assert "आपका कौन सा मतलब था: Gym या Gym class?" in res_hi["reply_text"]

    # 3. Kannada (native script)
    res_kn = await process_turn("ಜಿಮ್ ಮುಂದೂಡು", language="kn", now=FROZEN_NOW)
    assert "ನಿಮ್ಮ ಉದ್ದೇಶ ಯಾವುದು: Gym ಅಥವಾ Gym class?" in res_kn["reply_text"]

    # Verify no times were altered
    db = SessionLocal()
    t1 = db.query(Task).filter_by(id=id1).first()
    t2 = db.query(Task).filter_by(id=id2).first()
    assert t1.status == TaskStatus.SCHEDULED.value
    assert t1.due_at == datetime(2026, 10, 31, 17, 0, 0)
    assert t2.status == TaskStatus.SCHEDULED.value
    assert t2.due_at == datetime(2026, 10, 31, 18, 0, 0)
    db.close()
