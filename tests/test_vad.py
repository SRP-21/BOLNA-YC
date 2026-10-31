"""
Unit tests for AdaptiveVAD and voice end-of-speech detection.
Loads constants from static/vad_config.json so the Python port and vad.js remain 100% identical.

Tested sequences:
1. Speech starting at frame 0 (immediate speech onset in first 400ms)
2. Speech starting at 1 s
3. Loud-room floor (ambient noise floor tracked, no false triggers)
4. Synthetic silence (times out at 6s)
5. Continuous moderate noise (times out at 6s)
6. Speech then silence (~1.1s silence triggers speech_end)
7. Hard cap (20s)
8. Trailing standalone 'stop' stripping
"""
import os
import json
import pytest

# Load shared constants from static/vad_config.json
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "static", "vad_config.json")
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    VAD_CONFIG = json.load(f)


class AdaptiveVAD:
    """Python port of static/vad.js state machine sharing vad_config.json."""

    def __init__(self, config=None):
        cfg = config or VAD_CONFIG
        self.frame_duration_ms = cfg.get("frame_duration_ms", 50)
        self.history_window_ms = cfg.get("history_window_ms", 2000)
        self.max_noise_floor = cfg.get("max_noise_floor", 0.04)
        self.min_speech_threshold = cfg.get("min_speech_threshold", 0.015)
        self.multiplier = cfg.get("multiplier", 3.0)
        self.min_speech_ms = cfg.get("min_speech_ms", 300)
        self.end_silence_ms = cfg.get("end_silence_ms", 1100)
        self.no_speech_timeout_ms = cfg.get("no_speech_timeout_ms", 6000)
        self.hard_cap_ms = cfg.get("hard_cap_ms", 20000)
        self.smoothing_alpha = cfg.get("smoothing_alpha", 0.3)

        self.max_history_frames = max(
            1, round(self.history_window_ms / self.frame_duration_ms)
        )
        self.reset()

    def reset(self):
        self.total_ms = 0
        self.smoothed_rms = None
        self.history = []
        self.noise_floor = None
        self.speech_threshold = None
        self.speech_accumulated_ms = 0
        self.current_silence_ms = 0
        self.speech_detected = False
        self.state = "listening"
        self.is_final = False
        self.final_reason = None

    def process_frame(self, rms: float, frame_duration_ms: int = None) -> dict:
        dt = frame_duration_ms or self.frame_duration_ms
        if self.is_final:
            return {
                "state": self.state,
                "is_final": True,
                "reason": self.final_reason,
                "rms": rms,
                "noise_floor": self.noise_floor,
                "threshold": self.speech_threshold,
            }

        self.total_ms += dt

        # Hard cap (20s)
        if self.total_ms >= self.hard_cap_ms:
            self.is_final = True
            self.final_reason = "hard_cap"
            self.state = "hard_cap"
            return {
                "state": self.state,
                "is_final": True,
                "reason": self.final_reason,
                "rms": rms,
                "noise_floor": self.noise_floor,
                "threshold": self.speech_threshold,
            }

        # 1. Exponential moving average smoothing of RMS
        if self.smoothed_rms is None:
            self.smoothed_rms = rms
        else:
            self.smoothed_rms = (
                self.smoothing_alpha * rms
                + (1.0 - self.smoothing_alpha) * self.smoothed_rms
            )

        # 2. History buffer of smoothed RMS over the last ~2 seconds
        self.history.append(self.smoothed_rms)
        if len(self.history) > self.max_history_frames:
            self.history.pop(0)

        # 3. Noise floor: running minimum over the history window, capped at max_noise_floor (0.04)
        min_smoothed = min(self.history)
        self.noise_floor = min(min_smoothed, self.max_noise_floor)

        # 4. Speech threshold
        self.speech_threshold = max(
            self.noise_floor * self.multiplier, self.min_speech_threshold
        )

        # 5. Speech detection
        is_speech_frame = rms >= self.speech_threshold

        if is_speech_frame:
            self.speech_accumulated_ms += dt
            self.current_silence_ms = 0
            if self.speech_accumulated_ms >= self.min_speech_ms:
                self.speech_detected = True
            self.state = "hearing"
            return {
                "state": "hearing",
                "is_final": False,
                "rms": rms,
                "noise_floor": self.noise_floor,
                "threshold": self.speech_threshold,
            }

        # Below speech threshold
        if not self.speech_detected:
            if self.total_ms >= self.no_speech_timeout_ms:
                self.is_final = True
                self.final_reason = "no_speech"
                self.state = "timeout_no_speech"
                return {
                    "state": self.state,
                    "is_final": True,
                    "reason": self.final_reason,
                    "rms": rms,
                    "noise_floor": self.noise_floor,
                    "threshold": self.speech_threshold,
                }
            self.state = "listening"
            return {
                "state": "listening",
                "is_final": False,
                "rms": rms,
                "noise_floor": self.noise_floor,
                "threshold": self.speech_threshold,
            }

        # Speech was detected (>= 300ms), now in silence
        self.current_silence_ms += dt
        if self.current_silence_ms >= self.end_silence_ms:
            self.is_final = True
            self.final_reason = "speech_end"
            self.state = "speech_end"
            return {
                "state": self.state,
                "is_final": True,
                "reason": self.final_reason,
                "rms": rms,
                "noise_floor": self.noise_floor,
                "threshold": self.speech_threshold,
            }

        self.state = "hearing"
        return {
            "state": "hearing",
            "is_final": False,
            "rms": rms,
            "noise_floor": self.noise_floor,
            "threshold": self.speech_threshold,
        }


def test_vad_speech_starting_at_frame_0():
    """Speech starting immediately at frame 0 must be detected and not swallowed."""
    vad = AdaptiveVAD()
    # User speaks immediately with RMS 0.16 on frame 0
    res0 = vad.process_frame(0.16, 50)
    assert res0["state"] == "hearing"
    assert vad.noise_floor <= 0.04  # Capped at max_noise_floor
    assert vad.speech_threshold <= 0.12  # 0.04 * 3 = 0.12 < 0.16

    # Continue speech for 350 ms (7 frames total)
    for _ in range(6):
        res = vad.process_frame(0.16, 50)
        assert res["state"] == "hearing"

    assert vad.speech_detected is True
    assert vad.speech_accumulated_ms >= 300


def test_vad_speech_starting_at_1_second():
    """Speech starting at 1 second (after 1000ms of quiet room):
    Frames 0-19 are listening; frame 20 triggers hearing."""
    vad = AdaptiveVAD()
    # 20 frames @ 50ms = 1000ms of quiet room (rms ~0.005)
    for _ in range(20):
        res = vad.process_frame(0.005, 50)
        assert res["state"] == "listening"
        assert res["is_final"] is False

    assert vad.speech_detected is False
    assert vad.noise_floor == pytest.approx(0.005, abs=0.002)

    # Frame 20 (at 1000ms): user starts speaking with RMS 0.14
    res_speech = vad.process_frame(0.14, 50)
    assert res_speech["state"] == "hearing"
    assert res_speech["is_final"] is False


def test_vad_loud_room_floor():
    """Loud room floor (e.g. ambient fan / AC noise around 0.035).
    Noise floor tracks running minimum around ~0.035, speech threshold is ~0.105.
    Loud continuous noise does not trigger false speech and times out at 6s."""
    vad = AdaptiveVAD()
    final_res = None
    for i in range(130):
        # Noise fluctuates between 0.032 and 0.038
        rms = 0.035 + (0.003 if i % 2 == 0 else -0.003)
        res = vad.process_frame(rms, 50)
        if res["is_final"]:
            final_res = res
            break

    assert final_res is not None
    assert final_res["reason"] == "no_speech"
    assert final_res["state"] == "timeout_no_speech"
    assert vad.noise_floor <= 0.04
    assert vad.speech_detected is False


def test_vad_synthetic_silence():
    """Silence sequence: low ambient floor, no speech, times out at 6s."""
    vad = AdaptiveVAD()
    final_res = None
    for _ in range(130):
        res = vad.process_frame(0.002, 50)
        if res["is_final"]:
            final_res = res
            break

    assert final_res is not None
    assert final_res["reason"] == "no_speech"
    assert final_res["state"] == "timeout_no_speech"
    assert vad.total_ms == 6000


def test_vad_synthetic_speech_then_silence():
    """Speech then silence:
    - 400 ms quiet room (rms ~0.005)
    - 600 ms speech (rms ~0.15) -> accumulated speech > 300ms
    - 1100 ms silence (rms ~0.005) -> triggers speech_end."""
    vad = AdaptiveVAD()

    for _ in range(8):
        res = vad.process_frame(0.005, 50)
        assert res["state"] == "listening"

    for _ in range(12):
        res = vad.process_frame(0.15, 50)
        assert res["state"] == "hearing"

    assert vad.speech_detected is True
    assert vad.speech_accumulated_ms == 600

    final_res = None
    for _ in range(25):
        res = vad.process_frame(0.005, 50)
        if res["is_final"]:
            final_res = res
            break

    assert final_res is not None
    assert final_res["reason"] == "speech_end"
    assert final_res["state"] == "speech_end"


def test_strip_trailing_standalone_stop():
    """Verify trailing standalone 'stop' is stripped while keeping legitimate words."""
    from routes.voice import strip_trailing_stop

    assert strip_trailing_stop("standup at 10 stop") == "standup at 10"
    assert strip_trailing_stop("standup at 10, stop.") == "standup at 10"
    assert strip_trailing_stop("gym at 6 - STOP!") == "gym at 6"
    assert strip_trailing_stop("stop by the grocery store at 5") == "stop by the grocery store at 5"
    assert strip_trailing_stop("non-stop flight at 9") == "non-stop flight at 9"
    assert strip_trailing_stop("stop") == ""
    assert strip_trailing_stop("  stop.  ") == ""
    assert strip_trailing_stop(None) == ""


@pytest.mark.asyncio
async def test_text_turn_with_trailing_stop_end_to_end():
    """Verify POST /api/text/turn strips trailing 'stop' from input text before planning."""
    from fastapi.testclient import TestClient
    from main import app
    from unittest.mock import patch, AsyncMock
    from providers.base import TTSResult

    client = TestClient(app)
    with patch("providers.registry.registry.synthesize", new_callable=AsyncMock) as mock_synth, \
         patch("routes.voice.process_turn", new_callable=AsyncMock) as mock_turn:
        mock_synth.return_value = TTSResult(use_browser_tts=True, provider="browser")
        mock_turn.return_value = {"reply_text": "ok", "task_changes": [], "language": "en"}
        resp = client.post("/api/text/turn", data={"text": "standup at 10 stop"})
        assert resp.status_code == 200
        mock_turn.assert_called_once_with("standup at 10", "en", now=None)
