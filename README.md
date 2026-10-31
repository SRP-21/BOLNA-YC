# Bolna Planner 🎙️
> **"A planner you talk to, that talks back"**  
> Built for the **Bolna x Y Combinator "Path to YC" Voice AI Buildathon**.

---

## 🎯 What It Is
A voice-first daily planner built for people who don't want to type — gig & field workers, shopkeepers, busy professionals, and anyone with their hands full.
1. **Speak your day**: Speak in **English, Hindi, Kannada, or Hinglish** (e.g., *"standup at 10, send the invoice before lunch, gym around 6, groceries on the way back"*).
2. **AI Task Engine**: Groq Whisper STT + Groq LLM tool calling extracts tasks, resolves ambiguous/vague times against Asia/Kolkata timezone, and speaks a one-sentence confirmation.
3. **"My Day Changed" Voice Replanning**: Tell the planner your reality shifted (*"meeting ran long, push everything by 45 minutes"*, *"only free after 5"*, *"swap the invoice and groceries"*, *"sab kuch 45 minute aage kar do"*). The deterministic engine shifts tasks, respects fixed vs. flexible times, avoids quiet hours (22:00–07:00), detects conflicts, and lets you review or **Undo** with one tap or word.
4. **Adaptive Nudges & Learned Preferences**: Categorizes tasks (health, work, errands, family, other) and learns your habits. If you consistently snooze a category 3+ times, the planner offers to automatically schedule future reminders with your preferred offset, while handling ignored reminders with escalating 2-minute and 5-minute nudges.
5. **Evening Recap & Morning Carry-Over**: Say *"end my day"* or *"recap"* (or review at 20:30 IST) to get a strictly verified daily review, completion ring, 7-day trend chart, and 1-click morning carry-over for missed tasks.
6. **Live Dashboard & Spoken Reminder Loop**: Real-time SSE updates, live WebAudio visualizer, and a full voice conversation loop when reminders fire (*"Done"*, *"10 minutes later"*, *"Kal subah"*).

---

## 🛡️ 100% Free Tier Architecture
Zero paid usage anywhere. Built with strict free-tier hygiene:
- **LLM Planner**: Groq `openai/gpt-oss-120b` (Primary, tool calling) &rarr; Fallback `openai/gpt-oss-20b` &rarr; Fast classifier `openai/gpt-oss-20b` (configured in `config.py`).
- **Speech-to-Text**: Groq `whisper-large-v3-turbo` with `verbose_json` for automatic language detection (English, Hindi, Kannada, etc.).
- **Text-to-Speech**: High-quality Indian multilingual voices via `edge-tts` (`en-IN-NeerjaNeural`, `hi-IN-SwaraNeural`, `kn-IN-SapnaNeural`), with fail-soft automatic fallback to browser `speechSynthesis`.
- **Backend**: FastAPI + SQLite (SQLAlchemy 2.0 with WAL mode) + APScheduler (DB-backed persistent jobs surviving process restarts).
- **Frontend**: Single static page with Tailwind CSS CDN + vanilla JS, WebAudio visualizer, and silence detection.
- **Strict Separation of Concerns**: LLMs parse intent and format phrasing. **Scheduling math, time resolution, quiet hours, gap enforcement, conflict detection, and statistics are 100% deterministic, unit-tested Python code.**

### 🕒 Timezone Convention
- **Task `due_at`**: Stored in SQLite as **naive IST** (`Asia/Kolkata`) wall-clock time.
- **Audit Timestamps (`created_at`, `updated_at`, `Event.ts`, `Utterance.ts`)**: Stored in **UTC**.
- Helper functions in `timeutil.py` (`now_ist()`, `to_ist_naive()`, `ensure_ist()`) enforce consistent handling across the resolver, routes, and scheduler.

---

## 🚀 How to Run & Test It

### Step 1: Set your Groq API Key
1. Create a free account at [console.groq.com](https://console.groq.com).
2. Generate a free API key (starts with `gsk_...`).
3. Copy `.env.example` to `.env` and paste your key:
```bash
cp .env.example .env
```
In `.env`:
```ini
GROQ_API_KEY=gsk_your_groq_api_key_here
```

### Step 2: Start the Server
Run the FastAPI server with Uvicorn:
```bash
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

### Step 3: Open in Browser
Open:
```
http://localhost:8000
```

---

## 🧪 How to Test It (Step-by-Step)

### Test A: Run the Automated Test Suite (97 Unit & Integration Tests)
Install development dependencies and run pytest:
```bash
pip install -r requirements-dev.txt
python -m pytest tests -v
```
*(All 97 tests pass with 0 failures!)*

### Test B: Audio Unlock ("Start my day")
1. When opening the browser, notice the banner: **"Audio is locked by browser policy"**.
2. Click **"Start my day"** to prime the WebAudio context and enable system notification permissions.

### Test C: Test with Text Fallback (No Mic Required)
If you don't have a mic or are in a quiet room:
1. In the bottom-left text input box labeled **"Text Fallback"**, enter:
   ```text
   standup at 10, send the invoice before lunch, gym around 6, groceries on the way back
   ```
2. Click **Send**.
3. **Observe**:
   - The agent creates 4 tasks on the dashboard with category tags (`work`, `errands`, `health`).
   - Vague phrase *"before lunch"* is flagged with a **Needs confirmation** badge (`12:30 PM`, hover to see reasoning).
   - The agent speaks aloud a single-sentence confirmation.
   - The live activity feed records all database transactions.

### Test D: Test "My Day Changed" Voice Replanning
1. Speak or type:
   ```text
   my meeting ran long, push everything by 45 minutes
   ```
2. **Observe**:
   - The **Replan Preview Panel** appears, showing each task with its old time and proposed new time.
   - The agent speaks a short summary of the proposal.
   - Click **Accept** (or say *"yes"* / *"theek hai"*) to commit atomically.
   - If you change your mind, click **Undo** (or say *"undo"* / *"wapas pehle jaisa kar do"*) to restore the exact previous schedule from snapshot history!

### Test E: Test Conflicts & Quiet Hours Overflow
1. Speak or type:
   ```text
   swap gym and send invoice
   ```
   Or set a task past 21:30 (e.g., *"dinner at 10 pm"*).
2. **Observe**:
   - The deterministic engine flags overlaps or quiet-hours violations (22:00–07:00 IST).
   - Tasks that exceed the day end (21:30) automatically offer to carry over to **09:00 AM tomorrow** with staggered 15-minute minimum gaps.

### Test F: Test Adaptive Nudges & Learned Preferences
1. Tasks are automatically categorized into: `health`, `work`, `errands`, `family`, `other`.
2. When you snooze reminders in a category 3 or more times (e.g., consistently snoozing morning workouts by 20 minutes):
   - The planner detects the pattern and offers: *"You usually snooze Gym by 20 minutes. Should I schedule future health tasks 20 minutes later?"*
   - Accepting stores a learned preference that automatically offsets future reminders.
   - Declining enters a 14-day quiet cooldown. You can reset preferences anytime from the dashboard.
3. Ignored reminders trigger gentle escalating nudges at +2 minutes and +5 minutes before moving to missed.

### Test G: Test Evening Recap & Carry-Over
1. In the evening (or click the **Recap** button / type *"end my day"*):
   - The circular completion ring displays today's rate.
   - The 7-day trend bar chart visualizes weekly completion performance.
   - Any missed tasks appear in the **Missed Today** list.
   - Click **"Carry to Tomorrow 9 AM"** (or say *"carry over"*): missed tasks are moved to tomorrow morning, resolving conflicts automatically.

### Test H: Honest Synthetic Demo Data (1-Click Review)
To evaluate 7-day history and learned preferences immediately:
1. Under **Today's Summary & Trends**, click **"Generate 1-Wk Demo Data"**.
2. Realistic past week tasks and a sample learned preference are populated.
3. Every synthetic task and preference is marked with `is_synthetic=True` and an amber **⚡ Synthetic Demo Data** badge appears in the UI.
4. Click **"Clear"** to remove all synthetic data without affecting your real reminders.

---

## 🎬 3-Minute Live Stage Demo Script for Judges

| Time | Action | What to Say / Highlight |
|---|---|---|
| **0:00 - 0:30** | Click **"Start my day"** | *"Judges, daily planners fail because plans change the moment your day starts. Bolna Planner is a voice-first planner that adapts when your day changes — built entirely on free-tier infrastructure."* |
| **0:30 - 1:15** | Tap Mic & Add Multi-Tasks | Tap the mic and say:<br>_**"Standup at 10, send invoice before lunch, gym around 6, and groceries on the way back."**_<br>Highlight: 4 tasks appear live via SSE. Point out automatic categorization (`work`, `health`, `errands`) and the yellow badge on *"before lunch"* explaining it resolved to 12:30 PM with confirmation reasoning. |
| **1:15 - 1:55** | "My Day Changed" & Snapshot Undo | Tap the mic and say in Hinglish or English:<br>_**"Meeting ran long, push everything by 45 minutes."**_<br>Highlight: The Replan Preview Panel slides in, showing exact old &rarr; new times. The agent speaks a 1-sentence proposal.<br>Click **Accept** &rarr; tasks shift atomically.<br>Then say or click **Undo** &rarr; schedule immediately restores from the database snapshot. |
| **1:55 - 2:30** | Spoken Reminder Loop & Adaptive Nudges | Click **"Fire now"** on *"Gym"*. The computer speaks aloud:<br>_**"Gym — it's 6:00 PM. Done, snooze, or move to tomorrow?"**_<br>Reply: _**"Snooze 20 minutes."**_<br>Highlight: Explain that after 3 snoozes, the planner proactively offers a learned preference to automatically schedule future workouts at 6:20 PM. Show the Learned Preferences panel. |
| **2:30 - 3:00** | Evening Recap, Trends & Architecture | Click **Recap** (or say _"end my day"_). The agent reads today's verified stats.<br>Point out: SVG completion ring, 7-day completion trend, and 1-click **Carry to Tomorrow 9 AM**.<br>Highlight: *100% free tier (Groq Whisper, gpt-oss-120b, Edge-TTS), persistent APScheduler SQLite jobs, zero paid usage, 97 passing tests.* |

---

## ⚙️ Configuration & Environment Variables

Key settings in `config.py` and `.env`:

| Setting | Default | Description |
|---|---|---|
| `GROQ_API_KEY` | *(Required)* | Free Groq API key for Whisper STT and LLM planner |
| `PRIMARY_MODEL` | `openai/gpt-oss-120b` | High-capability model for multi-task extraction and replanning |
| `FALLBACK_MODEL` | `openai/gpt-oss-20b` | Fast fallback model on 429 rate limits |
| `QUIET_HOURS_START` | `22` | Start of quiet hours (22:00 IST / 10 PM) |
| `QUIET_HOURS_END` | `7` | End of quiet hours (07:00 IST / 7 AM) |
| `DAY_END_HOUR` | `21` | Day end hour (21:30 IST), tasks after this overflow to tomorrow |
| `DAY_END_MINUTE` | `30` | Day end minute (21:30 IST) |
| `REPLAN_MIN_GAP_MINUTES` | `15` | Minimum spacing enforced between replanned tasks |
| `PREFERENCE_SNOOZE_THRESHOLD`| `3` | Snoozes in a category required to trigger a learned preference offer |
| `PREFERENCE_COOLDOWN_DAYS` | `14` | Days to suppress preference offers after user declines |
| `RECAP_HOUR` | `20` | Scheduled evening recap hour (20:30 IST) |
| `RECAP_MINUTE` | `30` | Scheduled evening recap minute (20:30 IST) |
| `ENABLE_DEMO_DATA` | `False` | Gating flag for synthetic demo data generation |
| `NUDGE_DELAY_1_SECONDS` | `120` | First escalation nudge for unacknowledged reminders (2 min) |
| `NUDGE_DELAY_2_SECONDS` | `300` | Second escalation nudge for unacknowledged reminders (5 min) |

---

## 🔧 Troubleshooting

- **Microphone permission blocked**: Click the lock icon in your browser address bar &rarr; Site settings &rarr; Microphone &rarr; Allow.
- **Audio didn't speak**: Browsers block autoplay before user interaction. Click the **"Start my day"** button at the top of the page.
- **Groq Rate Limits (429)**: The system automatically falls back to `openai/gpt-oss-20b` and logs the fallback state in the header status indicator.
- **Edge TTS fallback**: If Microsoft Edge TTS is temporarily unreachable, the frontend automatically falls back to the browser's native `speechSynthesis`.
