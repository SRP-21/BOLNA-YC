# Bolna Planner 🎙️
> **"A planner you talk to, that talks back"**  
> Built for the **Bolna x Y Combinator "Path to YC" Voice AI Buildathon**.

---

## 🎯 What It Is
A voice-first daily planner built for people who don't want to type — gig & field workers, shopkeepers, busy professionals, and anyone with their hands full.
1. **Speak your day**: Speak in **English, Hindi, Kannada, or Hinglish** (e.g., *"standup at 10, send the invoice before lunch, gym around 6, groceries on the way back"*).
2. **AI Task Engine**: Groq Whisper STT + Groq LLM tool calling extracts tasks, resolves ambiguous/vague times against Asia/Kolkata timezone, and speaks a one-sentence confirmation.
3. **Live Dashboard**: Tasks and live activity events update in real time via Server-Sent Events (SSE).
4. **Spoken Reminders**: When a reminder is due, the app **speaks aloud** to you (*"Hey, it's 12:30, time to send the invoice. Done, snooze, or move to tomorrow?"*).
5. **Spoken Reply Loop**: Automatically listens for your response (*"Done"*, *"10 minutes later"*, *"Kal subah"*), interprets the outcome via rules + LLM, and updates the task and schedule in real time.

---

## 🛡️ 100% Free Tier Architecture
Zero paid usage anywhere. Built with strict free-tier hygiene:
- **LLM Planner**: Groq `openai/gpt-oss-120b` (Primary, tool calling) &rarr; Fallback `llama-3.3-70b-versatile` &rarr; Classifier `llama-3.1-8b-instant`.
- **Speech-to-Text**: Groq `whisper-large-v3-turbo` with `verbose_json` for automatic language detection (English, Hindi, Kannada, etc.).
- **Text-to-Speech**: High-quality Indian multilingual voices via `edge-tts` (`en-IN-NeerjaNeural`, `hi-IN-SwaraNeural`, `kn-IN-SapnaNeural`), with fail-soft automatic fallback to browser `speechSynthesis`.
- **Backend**: FastAPI + SQLite (SQLAlchemy) + APScheduler (DB-backed persistent jobs surviving restarts).
- **Frontend**: Single static page with Tailwind CSS CDN + vanilla JS, WebAudio visualizer, and silence detection.

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

### Test A: Run the Automated Test Suite (22 Unit & Integration Tests)
Run pytest to verify all deterministic time-resolution, recurrence, deduplication, outcome parsing, and fallback logic:
```bash
python -m pytest tests -v
```
*(All 22 tests pass in < 5 seconds!)*

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
   - The agent creates 4 tasks on the dashboard.
   - Vague phrase *"before lunch"* is flagged with a **Needs confirmation** badge (`12:30 PM`, hover to see reasoning).
   - The agent speaks aloud a single-sentence confirmation.
   - The live activity feed records all database transactions.

### Test D: Test with Voice (The Hero Experience)
1. Tap the big central microphone button.
2. Speak in **English, Hindi, or Hinglish**:
   - *English*: *"Dentist appointment at 5 pm and team sync every Monday at 10 am"*
   - *Hindi / Hinglish*: *"Dopahar 1 baje client call hai, aur shaam 6 baje gym jana hai"*
   - *Kannada-English*: *"Beligge 9 am meeting ide, sanje 6 pm groceries"*
3. Pause for 1.8 seconds — the built-in silence detection will auto-stop recording.
4. Watch the agent think, create the tasks, and speak back in the matching language!

### Test E: Test Spoken Reminders & Voice Reply Loop ("Fire now")
To demonstrate what happens when a reminder is due without waiting hours:
1. Find any task in the list on the right.
2. Click the **"Fire now"** button next to it.
3. **Observe**:
   - The reminder modal pops up.
   - The browser **speaks aloud**: *"Standup meeting — it's 10:00 AM, time for standup meeting. Done, snooze, or move to tomorrow?"*
   - The mic automatically activates to listen for your reply!
   - Say: *"Done"* (or *"Ho gaya"* / *"Snooze 10 minutes"* / *"Kal karte hain"* / *"Cancel"*).
   - The agent interprets your reply, confirms via voice, updates the task status, and reschedules or marks it complete.

---

## 🎬 3-Minute Live Stage Demo Script for Judges

| Time | Action | What to Say / Highlight |
|---|---|---|
| **0:00 - 0:30** | Click **"Start my day"** | *"Judges, voice assistants usually make you type or give canned answers. Bolna Planner is a voice-first daily planner that you talk to, and that talks back — built completely on free tiers."* |
| **0:30 - 1:15** | Tap Mic & Brain-Dump | Tap the mic and say:<br>_**"Standup at 10, send the invoice before lunch, gym around 6, and groceries on the way back."**_<br>Highlight: 4 tasks appear live via SSE. Point out the yellow badge on *"before lunch"* explaining it resolved to 12:30 PM with confirmation reasoning. |
| **1:15 - 1:45** | Multilingual & Corrections | Type or speak in Hinglish:<br>_**"Gym at 6, no make that 7 pm instead."**_<br>Highlight: It doesn't duplicate the task — it updates existing task #3 to 7:00 PM. |
| **1:45 - 2:30** | Trigger Reminder ("Fire now") | Click **"Fire now"** on *"Send invoice"*. The computer speaks:<br>_**"Send invoice — it's 12:30 PM. Done, snooze, or move to tomorrow?"**_<br>User speaks: _**"Ho gaya"**_ (or _"Done"_).<br>App speaks: _"Great, Send invoice marked as done!"_ and chips update green. |
| **2:30 - 3:00** | Architecture & Wrap | Show Provider Badges at the top (Groq Whisper, gpt-oss-120b, Edge TTS) and live event log. Emphasize: *No hardcoding, real DB persistence, real APScheduler jobs, zero paid APIs.* |

---

## ⚙️ Free Deployment (Public HTTPS for Mic Access)

Microphone access in mobile browsers requires **HTTPS**:
1. **Local Tunneling (instant for live demos)**:
   ```bash
   npx cloudflared tunnel --url http://127.0.0.1:8000
   # OR
   ngrok http 8000
   ```
2. **Free Cloud Host (Render / Railway / Fly.io)**:
   - Connect repository to Render.com (Web Service, free tier).
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - Environment Variable: `GROQ_API_KEY=gsk_...`

---

## 🔧 Troubleshooting

- **Microphone permission blocked**: Click the lock icon in your browser address bar &rarr; Site settings &rarr; Microphone &rarr; Allow.
- **Audio didn't speak**: Browsers block audio before user interaction. Click the **"Start my day"** button at the top of the page.
- **Groq Rate Limits (429)**: The system automatically falls back to `llama-3.3-70b-versatile` and logs the fallback state in the header status indicator.
- **Edge TTS fallback**: If Microsoft Edge TTS is temporarily unreachable, the frontend automatically falls back to the browser's native `speechSynthesis`.

