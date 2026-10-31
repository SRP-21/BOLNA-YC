"""
Unit tests for AdaptiveVAD and voice end-of-speech detection.
Ports the vad.js state machine to Python to test all required synthetic audio sequences:
1. Silence
2. Continuous noise
3. Speech
4. Speech then silence
5. Pure noise that is louder than expected
6. Trailing standalone 'stop' stripping
"""
import pytest
import re


class AdaptiveVAD:
    """Python port of static/vad.js state machine."""

    def __init__(
        self,
        calibration_ms: int = 400,
        multiplier: float = 3.0,
        min_threshold: float = 0.015,
        min_speech_ms: int = 300,
        end_silence_ms: int = 1100,
        no_speech_timeout_ms: int = 6000,
        hard_cap_ms: int = 20000,
    ):
        self.calibration_ms = calibration_ms
        self.multiplier = multiplier
        self.min_threshold = min_threshold
        self.min_speech_ms = min_speech_ms
        self.end_silence_ms = end_silence_ms
        self.no_speech_timeout_ms = no_speech_timeout_ms
        self.hard_cap_ms = hard_cap_ms
        self.reset()

    def reset(self):
        self.total_ms = 0
        self.calibration_samples = []
        self.noise_floor = None
        self.speech_threshold = None
        self.speech_accumulated_ms = 0
        self.current_silence_ms = 0
        self.speech_detected = False
        self.state = "calibrating"
        self.is_final = False
        self.final_reason = None

    def process_frame(self, rms: float, frame_duration_ms: int = 50) -> dict:
        if self.is_final:
            return {
                "state": self.state,
                "is_final": True,
                "reason": self.final_reason,
                "rms": rms,
                "noise_floor": self.noise_floor,
                "threshold": self.speech_threshold,
            }

        self.total_ms += frame_duration_ms

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

        # Calibration phase (first ~400 ms)
        if self.total_ms <= self.calibration_ms:
            self.calibration_samples.append(rms)
            self.state = "calibrating"
            return {
                "state": "calibrating",
                "is_final": False,
                "rms": rms,
                "noise_floor": None,
                "threshold": None,
            }

        # End of calibration: compute noise floor & threshold
        if self.speech_threshold is None:
            self.noise_floor = (
                sum(self.calibration_samples) / len(self.calibration_samples)
                if self.calibration_samples
                else 0.0
            )
            self.speech_threshold = max(
                self.noise_floor * self.multiplier, self.min_threshold
            )

        is_speech_frame = rms >= self.speech_threshold

        if is_speech_frame:
            self.speech_accumulated_ms += frame_duration_ms
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

        # User previously spoke for at least 300 ms, now silent
        self.current_silence_ms += frame_duration_ms
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


def test_vad_synthetic_silence():
    """Silence sequence: low ambient floor, no speech, times out at 6s."""
    vad = AdaptiveVAD()
    # 130 frames @ 50ms = 6500ms of near silence (rms ~0.002)
    final_res = None
    for _ in range(130):
        res = vad.process_frame(0.002, frame_duration_ms=50)
        if res["is_final"]:
            final_res = res
            break

    assert final_res is not None
    assert final_res["is_final"] is True
    assert final_res["reason"] == "no_speech"
    assert final_res["state"] == "timeout_no_speech"
    assert vad.total_ms == 6000


def test_vad_synthetic_continuous_noise():
    """Continuous noise sequence: moderate background hum (rms ~0.02) does not trigger speech and times out."""
    vad = AdaptiveVAD()
    final_res = None
    for _ in range(130):
        res = vad.process_frame(0.02, frame_duration_ms=50)
        if res["is_final"]:
            final_res = res
            break

    assert final_res is not None
    assert final_res["reason"] == "no_speech"
    assert vad.total_ms == 6000
    # Threshold should be max(0.02 * 3, 0.015) = 0.06
    assert vad.speech_threshold == pytest.approx(0.06)


def test_vad_synthetic_pure_noise_louder_than_expected():
    """Pure noise louder than expected (e.g. loud AC/fan at rms 0.05).
    Threshold adapts to floor * 3 = 0.15, avoiding false triggers and timing out at 6s."""
    vad = AdaptiveVAD()
    final_res = None
    # Noise fluctuates around 0.05 - 0.06
    for i in range(130):
        rms = 0.05 + (0.01 if i % 2 == 0 else -0.01)
        res = vad.process_frame(rms, frame_duration_ms=50)
        if res["is_final"]:
            final_res = res
            break

    assert final_res is not None
    assert final_res["reason"] == "no_speech"
    assert vad.noise_floor >= 0.045
    assert vad.speech_threshold >= 0.135


def test_vad_synthetic_speech_then_silence():
    """Speech then silence:
    - 400 ms calibration (quiet room rms ~0.005)
    - 600 ms speech (rms ~0.15) -> accumulated speech > 300ms
    - 1100 ms silence (rms ~0.005) -> triggers speech_end."""
    vad = AdaptiveVAD()

    # 1. 400ms calibration (8 frames @ 50ms)
    for _ in range(8):
        res = vad.process_frame(0.005, 50)
        assert res["state"] == "calibrating"

    # 2. 600ms speech (12 frames @ 50ms)
    for _ in range(12):
        res = vad.process_frame(0.15, 50)
        assert res["state"] == "hearing"

    assert vad.speech_detected is True
    assert vad.speech_accumulated_ms == 600

    # 3. Silence: 22 frames = 1100ms
    final_res = None
    for _ in range(25):
        res = vad.process_frame(0.005, 50)
        if res["is_final"]:
            final_res = res
            break

    assert final_res is not None
    assert final_res["reason"] == "speech_end"
    assert final_res["state"] == "speech_end"
    # Total time: 400ms calib + 600ms speech + 1100ms silence = 2100ms
    assert vad.total_ms == 2100


def test_vad_synthetic_speech_hard_cap():
    """Continuous speech reaching hard cap at 20 seconds."""
    vad = AdaptiveVAD()
    # 8 frames calib
    for _ in range(8):
        vad.process_frame(0.005, 50)

    final_res = None
    # Speech continues until 20s
    for _ in range(450):
        res = vad.process_frame(0.15, 50)
        if res["is_final"]:
            final_res = res
            break

    assert final_res is not None
    assert final_res["reason"] == "hard_cap"
    assert final_res["state"] == "hard_cap"
    assert vad.total_ms >= 20000


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

