/**
 * Voice Activity Detector (VAD) with adaptive noise floor calibration.
 * Measures ambient noise floor during first ~400 ms, then detects speech
 * when RMS exceeds max(noiseFloor * 3, minThreshold).
 * 
 * State transitions:
 * - calibrating (first 400ms)
 * - listening (waiting for speech)
 * - hearing (speech >= threshold)
 * - speech_end (1.1s silence after >= 300ms speech)
 * - timeout_no_speech (no speech within 6s)
 * - hard_cap (total recording reached 20s)
 */
class AdaptiveVAD {
  constructor(options = {}) {
    this.calibrationMs = options.calibrationMs || 400;
    this.multiplier = options.multiplier || 3.0;
    this.minThreshold = options.minThreshold !== undefined ? options.minThreshold : 0.015;
    this.minSpeechMs = options.minSpeechMs || 300;
    this.endSilenceMs = options.endSilenceMs || 1100;
    this.noSpeechTimeoutMs = options.noSpeechTimeoutMs || 6000;
    this.hardCapMs = options.hardCapMs || 20000;

    this.reset();
  }

  reset() {
    this.totalMs = 0;
    this.calibrationSamples = [];
    this.noiseFloor = null;
    this.speechThreshold = null;
    this.speechAccumulatedMs = 0;
    this.currentSilenceMs = 0;
    this.speechDetected = false;
    this.state = 'calibrating';
    this.isFinal = false;
    this.finalReason = null;
  }

  processFrame(rms, frameDurationMs = 50) {
    if (this.isFinal) {
      return {
        state: this.state,
        isFinal: true,
        reason: this.finalReason,
        rms,
        noiseFloor: this.noiseFloor,
        threshold: this.speechThreshold,
      };
    }

    this.totalMs += frameDurationMs;

    // Hard cap (20s)
    if (this.totalMs >= this.hardCapMs) {
      this.isFinal = true;
      this.finalReason = 'hard_cap';
      this.state = 'hard_cap';
      return {
        state: this.state,
        isFinal: true,
        reason: this.finalReason,
        rms,
        noiseFloor: this.noiseFloor,
        threshold: this.speechThreshold,
      };
    }

    // 1. Calibration phase (first ~400 ms)
    if (this.totalMs <= this.calibrationMs) {
      this.calibrationSamples.push(rms);
      this.state = 'calibrating';
      return {
        state: 'calibrating',
        isFinal: false,
        rms,
        noiseFloor: null,
        threshold: null,
      };
    }

    // End of calibration: compute noise floor & threshold on first frame past calibration
    if (this.speechThreshold === null) {
      const sum = this.calibrationSamples.reduce((a, b) => a + b, 0);
      this.noiseFloor = this.calibrationSamples.length > 0 ? (sum / this.calibrationSamples.length) : 0;
      this.speechThreshold = Math.max(this.noiseFloor * this.multiplier, this.minThreshold);
    }

    const isSpeechFrame = rms >= this.speechThreshold;

    if (isSpeechFrame) {
      this.speechAccumulatedMs += frameDurationMs;
      this.currentSilenceMs = 0;
      if (this.speechAccumulatedMs >= this.minSpeechMs) {
        this.speechDetected = true;
      }
      this.state = 'hearing';
      return {
        state: 'hearing',
        isFinal: false,
        rms,
        noiseFloor: this.noiseFloor,
        threshold: this.speechThreshold,
      };
    }

    // Below speech threshold
    if (!this.speechDetected) {
      // No speech detected yet
      if (this.totalMs >= this.noSpeechTimeoutMs) {
        this.isFinal = true;
        this.finalReason = 'no_speech';
        this.state = 'timeout_no_speech';
        return {
          state: this.state,
          isFinal: true,
          reason: this.finalReason,
          rms,
          noiseFloor: this.noiseFloor,
          threshold: this.speechThreshold,
        };
      }
      this.state = 'listening';
      return {
        state: 'listening',
        isFinal: false,
        rms,
        noiseFloor: this.noiseFloor,
        threshold: this.speechThreshold,
      };
    }

    // User previously spoke for at least 300 ms, now silent
    this.currentSilenceMs += frameDurationMs;
    if (this.currentSilenceMs >= this.endSilenceMs) {
      this.isFinal = true;
      this.finalReason = 'speech_end';
      this.state = 'speech_end';
      return {
        state: this.state,
        isFinal: true,
        reason: this.finalReason,
        rms,
        noiseFloor: this.noiseFloor,
        threshold: this.speechThreshold,
      };
    }

    // Brief pause during speech (less than endSilenceMs)
    this.state = 'hearing';
    return {
      state: 'hearing',
      isFinal: false,
      rms,
      noiseFloor: this.noiseFloor,
      threshold: this.speechThreshold,
    };
  }
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { AdaptiveVAD };
}
