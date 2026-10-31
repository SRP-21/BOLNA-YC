<div align="center">

# 🎙️ BOLNA PLANNER
### *The Autonomous, Voice-Native Daily Operating System*
**A voice-first planner you talk to, that talks back.**  
Built for the **Bolna x Y Combinator "Path to YC" Voice AI Buildathon**.

[![Test Suite](https://img.shields.io/badge/Test%20Suite-168%2F168%20Passing-brightgreen?style=for-the-badge&logo=pytest)](file:///tests)
[![Architecture](https://img.shields.io/badge/Stack-100%25%20Free--Tier%20%2F%20Open--Weights-blue?style=for-the-badge)](file:///config.py)
[![Latency](https://img.shields.io/badge/Latency-Sub--Second%20Voice%20Turnaround-orange?style=for-the-badge)](file:///static/vad.js)
[![Indic Languages](https://img.shields.io/badge/Languages-English%20%7C%20Hindi%20%7C%20Kannada-purple?style=for-the-badge)](file:///agent/resolver.py)
[![Persistence](https://img.shields.io/badge/Database-SQLite%20WAL%20%2B%20APScheduler-darkgreen?style=for-the-badge)](file:///db.py)

---

### [Executive Vision](#-executive-summary) • [System Architecture](#-system-architecture) • [Core Breakthroughs](#-core-breakthroughs) • [Live Demo Script](#-3-minute-executive-demo-script) • [Quickstart](#-60-second-quickstart) • [API & Configuration](#-api-specification--configuration)

---

</div>

## 📌 Executive Summary

Modern productivity software is broken for people on the move. Legacy calendar and to-do apps demand intense visual focus, tedious typing, and manual micro-management. When a meeting runs 45 minutes over, real-world professionals—gig operators, field engineers, surgeons, founders, and deskless workers—don't have the luxury to open a calendar app and manually drag 6 subsequent appointments.

Traditional voice assistants (Siri, Alexa) fail just as badly: they are rigid single-turn command routers that choke on vernacular code-switching, lack temporal intuition, interrogate users with annoying confirmation prompts, and cannot orchestrate cascading schedule changes.

**Bolna Planner** is an autonomous, voice-native daily planner that bridges this gap. You speak your day naturally in **English, Hindi, Kannada, or Hinglish**, and the system:
1. **Captures and organizes your commitments instantly** using sub-second speech processing and intelligent temporal reasoning.
2. **Dynamically reshapes your schedule when reality changes** (*"meeting ran long, push everything by 45 minutes"*), applying deterministic constraints and offering instant atomic Undo.
3. **Learns your subconscious behavioral patterns**, proactively offering automated scheduling optimizations when you consistently snooze specific task categories.
4. **Maintains a fluid, hands-free smart-speaker conversational loop** powered by client-side Web Audio adaptive voice activity detection (VAD), acoustic barge-in echo cancellation, and neural Indic voices.

All of this is delivered on an enterprise-grade **100% free-tier, open-weights architecture** backed by **168 automated integration tests**.

---

## 🏗️ System Architecture

Bolna Planner combines real-time client-side DSP with high-throughput cloud inferencing and a deterministic local state machine. The LLM is strictly isolated to natural language understanding and tool dispatch; **all scheduling calculations, conflict checks, quiet hours, and rollbacks are 100% deterministic Python code.**

```mermaid
flowchart TD
    subgraph Client ["Client Layer (Web Audio DSP & Reactive SPA)"]
        User(["🎤 User Speech"]) --> Mic[Web Audio API]
        Mic --> VAD["Adaptive Running-Floor VAD<br/>(50ms frames, RMS noise floor)"]
        VAD --> BargeIn{"Barge-In Guard<br/>(2x threshold, 400ms sustained)"}
        BargeIn -->|Audio Payload| HTTP["Async REST & SSE Stream"]
        AudioOut["Audio Player<br/>(Edge TTS & Fail-soft Browser Voice)"] <== Playback == HTTP
    end

    subgraph Gateway ["FastAPI Ingestion & Orchestration Gateway"]
        HTTP --> Endpoints["/api/voice/turn<br/>/api/text/turn<br/>/api/tts"]
        Endpoints --> LangDetect["Vernacular Script & Code-Switching Classifier"]
    end

    subgraph Intelligence ["Inference & Temporal Reasoning Engine"]
        Endpoints --> Whisper["Groq Whisper Large v3 Turbo<br/>(Sub-300ms STT with Auto-Language)"]
        Whisper --> TextNorm["Temporal Pre-Processor<br/>(Whisper dot normalization, Bare-Hour logic)"]
        TextNorm --> Resolver["Clause-Scoped Temporal Resolver<br/>(Asia/Kolkata naive wall-clock mapping)"]
        Resolver --> LLM["Groq Llama-3 / GPT-OSS Engine<br/>(Multi-Task Tool-Calling Dispatch)"]
    end

    subgraph Core ["Deterministic Scheduler & State Engine"]
        LLM --> ReplanEngine["Deterministic Replanning Engine<br/>(15m gap enforcement, quiet hours 22:00-07:00)"]
        ReplanEngine --> DB[(SQLite WAL Mode<br/>Full ACID Transactionality)]
        DB --> APScheduler["Persistent APScheduler<br/>(Job recovery surviving restarts)"]
        APScheduler --> Nudges["Escalating Nudges (+2m, +5m)<br/>& Adaptive Preference Learner"]
    end

    subgraph Speech ["Voice Synthesis Pipeline"]
        ReplanEngine --> VoiceGen["Edge TTS Engine<br/>(en-IN, hi-IN, kn-IN Neural Voices)"]
        VoiceGen --> TTSCache["Disk Audio Cache (SHA-256)"]
        TTSCache --> AudioOut
    end

    DB -. Real-Time Updates .-> Dashboard["Live SSE Activity Stream & 7-Day Analytics"]
```

---

## ⚡ Core Breakthroughs

### 1. Smart-Speaker Conversational Turn-Taking (Web Audio DSP)
Traditional web apps require push-to-talk buttons and cut off prematurely. Bolna Planner incorporates a dedicated audio DSP pipeline in `static/vad.js`:
- **Dynamic Ambient Noise Floor Tracking**: Continuously computes the running minimum RMS over a 2-second sliding window (capped at `0.04`), adapting to noisy street, vehicle, or cafeteria environments without swallowing initial syllables.
- **Acoustic Barge-In Suppression**: Enables natural interruption of the assistant. During audio playback, the speech detection threshold automatically doubles ($2.0\times$) and requires $\ge 400\text{ ms}$ of sustained speech before interrupting, preventing echo feedback loops.
- **Post-Playback Cooldown**: Imposes a calibrated $300\text{ ms}$ silence window after speech synthesis terminates to reject acoustic room reverberation.
- **Hands-Free Conversation Mode**: Uses an `expects_reply` protocol. When the planner asks a confirmation question (*"That time has passed. Should I move it to tomorrow?"*), the microphone re-arms automatically without user intervention.
- **Natural Stop Detection**: Supports cultural conversational terminators (*"stop"*, *"that's all"*, *"bas"*, *"बस"*, *"ಸಾಕು"*), while preserving compound intent (*"gym at 6, that's all"* creates the task and concludes the session).

### 2. Deep Vernacular Indic Intelligence (English, Hindi, Kannada)
Designed ground-up for the linguistic reality of India and emerging markets:
- **Zero-Friction Code-Switching**: Handles English, Hindi (Devanagari and Hinglish), and Kannada (Kannada script and Kanglish) seamlessly without requiring the user to toggle language settings.
- **Clause-Scoped Temporal Disambiguation**: In compound sentences (e.g., *"standup at 10, kal subah doctor at 9, gym around 6"*), the temporal context of *"kal subah"* (tomorrow morning) is strictly scoped to the doctor appointment, leaving standup and gym on today's schedule.
- **Cultural Temporal Windows**: Native mapping of idiomatic timeframes:
  - *Subah / Beligge* $\rightarrow$ 09:00 AM
  - *Dopahar / Madhyahna* $\rightarrow$ 02:30 PM
  - *Lunch se pehle* $\rightarrow$ 12:30 PM
  - *Shaam / Sanje* $\rightarrow$ 06:00 PM
  - *Raat / Raatri* $\rightarrow$ 09:00 PM
- **Whisper Punctuation Normalization**: Sanitizes automated transcription artifacts (`5 p.m.` $\rightarrow$ `5 pm`, `6 o'clock` $\rightarrow$ `6`, `half past 5` $\rightarrow$ `5:30`) to eliminate erroneous disambiguation queries.
- **Concise, Human Voice Responses**: Replaces robotic monologues with concise, rotating confirmations (e.g., *"Added: Standup for today at 10:00 AM."*, *"Got it, reminder set: Gym at 6:00 PM."*).

### 3. Deterministic "My Day Changed" Replanning Engine
When circumstances change, an executive or field worker needs instant schedule adaptation:
- **Natural Shifting**: Commands like *"meeting ran long, push everything by 45 minutes"* or *"sab kuch 30 minute aage kar do"* immediately recalculate all active tasks.
- **Constraint-Preserving Optimization**: Automatically enforces minimum 15-minute buffers, preserves hard boundaries, respects quiet hours (**22:00–07:00 IST**), and intelligently rolls late-night overflow into **09:00 AM tomorrow**.
- **Atomic Rollback & Instant Undo**: Every schedule mutation generates an in-memory transactional snapshot. Say *"undo"* or tap **Undo**, and the entire previous schedule is restored instantaneously.

### 4. Self-Learning Habit Engine & Escalating Nudges
- **Automatic Task Categorization**: Classifies every item into `work`, `health`, `errands`, `family`, or `other`.
- **Habit Discovery**: When a user snoozes reminders within a category $\ge 3$ times (e.g., snoozing morning workouts by 20 minutes), the planner detects the pattern and asks:
  > *"You usually snooze Gym by 20 minutes. Should I schedule future health tasks 20 minutes later?"*
- Accepting persists a learned rule; declining triggers a 14-day respectful cooldown.
- **2-Tier Escalation Guard**: Ignored reminders trigger gentle re-notifications at **+2 minutes** and **+5 minutes** before marking as missed, ensuring critical alerts are never lost.

### 5. Evening Closure & Next-Day Velocity
- **Automated Evening Recap**: At 20:30 IST (or via *"recap"* / *"end my day"*), the assistant delivers an auditable daily breakdown.
- **Velocity Metrics**: Visualized via an SVG completion ring and a 7-day trend chart.
- **1-Click Morning Rollover**: Missed items can be transferred to tomorrow morning at 09:00 AM with a single click or voice confirmation (*"carry over"*).

---

## 💎 100% Free-Tier & Open-Weights Stack

Bolna Planner delivers state-of-the-art voice performance with zero ongoing API licensing costs:

| Component | Technology | Rationale & Specifications |
|---|---|---|
| **Speech-to-Text** | Groq `whisper-large-v3-turbo` | Ultra-low latency (<300ms), native Indic language detection, verbose JSON. |
| **Primary LLM** | Groq `openai/gpt-oss-120b` | State-of-the-art open-weights reasoning for multi-task extraction and tool dispatch. |
| **Fallback LLM** | Groq `openai/gpt-oss-20b` | High-speed fallback providing sub-second recovery if primary limits are approached. |
| **Voice Synthesis** | Microsoft `edge-tts` Neural | High-fidelity Indian neural voices (`en-IN-NeerjaNeural`, `hi-IN-SwaraNeural`, `kn-IN-SapnaNeural`). |
| **TTS Fail-Soft** | Web Speech API | Client-side zero-latency fallback ensuring voice output is never interrupted. |
| **Database & Queue**| SQLite WAL + APScheduler | Zero-maintenance relational store with ACID transactions and durable background jobs. |
| **Client Frontend** | Vanilla HTML5 / Tailwind / Web Audio | Zero build step, instant load time, cross-platform mobile and desktop compatibility. |

---

## 🎬 3-Minute Executive Demo Script

Use this proven script to showcase Bolna Planner to investors, judges, or enterprise partners:

| Timestamp | Action / Input | Spoken Dialogue / Highlight |
|---|---|---|
| **0:00 - 0:30** | Click **"Start my day"** | *"Judges, daily planners fail because reality changes the minute your day begins. Bolna Planner is an autonomous voice operating system that listens, adapts, and manages your day with zero typing—built 100% on open-weights and free-tier infrastructure."* |
| **0:30 - 1:15** | Tap Mic & Add Multi-Tasks | Say aloud:<br>_**"Standup at 10, send invoice before lunch, gym around 6, and groceries on the way back."**_<br>👉 **Highlight**: Notice the sub-second response. 4 tasks are created instantly. Point out automatic category tagging (`work`, `health`, `errands`), and note that *"before lunch"* cleanly resolved to 12:30 PM with confirmation reasoning. |
| **1:15 - 1:55** | "My Day Changed" & Instant Undo | Say in English or Hinglish:<br>_**"Meeting ran long, push everything by 45 minutes."**_<br>👉 **Highlight**: The Replan Preview slides in, displaying exact before/after deltas. The assistant speaks a natural one-sentence summary. Click **Accept** to commit, then tap or say **"Undo"** to instantly restore the original schedule from the snapshot. |
| **1:55 - 2:30** | Spoken Reminder Loop & Adaptive Habits | Click **"Fire now"** on *"Gym"*. The assistant speaks:<br>_**"Gym — it's 6:00 PM. Done, snooze, or move to tomorrow?"**_<br>Respond: _**"Snooze 20 minutes."**_<br>👉 **Highlight**: Explain the Habit Learning Engine. When a user repeatedly snoozes a category, the assistant proactively offers to adjust future schedules automatically. |
| **2:30 - 3:00** | Evening Recap & Carry-Over | Click **Recap** (or say _"end my day"_).<br>👉 **Highlight**: The assistant summarizes completion metrics. Point out the SVG completion ring, 7-day velocity chart, and 1-click **Carry to Tomorrow 9 AM** for missed tasks. Conclude with: *168 passing automated tests, enterprise-grade architecture, zero paid APIs.* |

---

## 🚀 60-Second Quickstart

### Prerequisites
- Python 3.10+ (Windows, macOS, or Linux)
- A free Groq Cloud API Key from [console.groq.com](https://console.groq.com)

### 1. Clone & Set Up Environment
```bash
git clone https://github.com/SRP-21/BOLNA-YC.git
cd BOLNA-YC

# Create virtual environment
python -m venv venv

# Windows:
.\venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### 2. Configure Environment Variables
Create a `.env` file in the project root:
```ini
GROQ_API_KEY=gsk_your_groq_api_key_here
```
*(See `.env.example` for all configurable parameters).*

### 3. Launch Server & Open Dashboard
```bash
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```
Navigate to: **`http://localhost:8000`** in your browser.  
Click **"Start my day"** to prime the Web Audio context, and start speaking!

---

## 🧪 Comprehensive Verification Suite

Bolna Planner features rigorous automated test coverage across temporal resolvers, voice activity detection, replan constraint solving, multilingual phonetics, and database persistence.

To execute the full test suite:
```bash
pytest tests -v
```
```text
============================== 168 passed in 17.82s ==============================
```
- **Hermetic Temporal Testing**: Gated behind `ENABLE_TEST_CLOCK=true` to eliminate flaky time-dependent assertions.
- **Database Isolation**: Tests run against isolated in-memory or temporary SQLite databases, never mutating production state.

---

## 📡 API Specification & Configuration

### Key Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/voice/turn` | Ingests WebM/WAV voice audio, returns transcribed text, task mutations, and `expects_reply` state. |
| `POST` | `/api/text/turn` | Full text fallback endpoint for silent environments or automated pipelines. |
| `GET/POST`| `/api/tts` | High-performance audio streaming endpoint backed by Edge TTS with SHA-256 caching. |
| `GET` | `/api/events` | Server-Sent Events (SSE) live bus pushing real-time task creations, nudges, and state changes. |
| `GET` | `/api/tasks` | Lists active, completed, snoozed, and missed tasks for the current day. |
| `POST` | `/api/replan/confirm` | Atomically commits a pending schedule transformation. |
| `POST` | `/api/replan/undo` | Rolls back the schedule to the pre-replan snapshot. |
| `GET` | `/api/recap` | Computes today's completion rates, 7-day velocity, and missed task list. |

### Enterprise Configuration Reference

Key settings configurable via environment variables in `.env`:

| Parameter | Default | Purpose |
|---|---|---|
| `GROQ_API_KEY` | *(Required)* | Groq API authentication key |
| `LLM_PLANNER_MODEL` | `openai/gpt-oss-120b` | Primary tool-calling reasoning model |
| `LLM_PLANNER_FALLBACK`| `openai/gpt-oss-20b` | High-speed failover model |
| `STT_MODEL` | `whisper-large-v3-turbo`| Audio transcription model |
| `TTS_PROVIDER` | `edge` | Primary voice engine (`edge`, `elevenlabs`, or `browser`) |
| `DEFAULT_TIMEZONE` | `Asia/Kolkata` | Base operating timezone |
| `QUIET_HOURS_START` | `22` | Quiet hours onset (10:00 PM IST) |
| `QUIET_HOURS_END` | `7` | Quiet hours conclusion (07:00 AM IST) |
| `REPLAN_MIN_GAP_MINUTES`| `15` | Minimum spacing enforced between replanned items |
| `PREFERENCE_SNOOZE_THRESHOLD`| `3` | Snoozes required to trigger automated preference offer |
| `NUDGE_DELAY_1_SECONDS` | `120` | First escalation delay for unacknowledged reminders (2 min) |
| `NUDGE_DELAY_2_SECONDS` | `300` | Second escalation delay for unacknowledged reminders (5 min) |
| `ENABLE_DEMO_DATA` | `False` | Gating flag for synthetic demo data generation |
| `ENABLE_TEST_CLOCK` | `False` | Hermetic clock override gate for deterministic testing |

---

## 👥 Authors & Acknowledgments

Developed by **SRP-21** for the **Bolna x Y Combinator "Path to YC" Voice AI Buildathon**.  
Special thanks to the **Bolna AI** and **Groq** teams for pioneering ultra-low-latency voice developer infrastructure.
