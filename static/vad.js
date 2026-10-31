/**
 * Voice Activity Detector (VAD) with adaptive noise floor tracking.
 * - Noise floor is tracked as the running minimum of smoothed RMS over the last ~2 seconds,
 *   capped at an absolute maximum (0.04), initialized from the quietest frame.
 * - Speech onset at frame 0 or in the first 400 ms is immediately detected.
 * - Speech threshold = max(noiseFloor * multiplier, minSpeechThreshold).
 * - End of speech = ~1.1 s silence after at least 300 ms speech.
 * - Times out after 6 s if no speech occurs; hard cap at 20 s.
 */
class AdaptiveVAD {
  constructor(config = {}) {
    this.frameDurationMs = config.frame_duration_ms || 50;
    this.historyWindowMs = config.history_window_ms || 2000;
    this.maxNoiseFloor = config.max_noise_floor || 0.04;
    this.minSpeechThreshold = config.min_speech_threshold || 0.015;
    this.multiplier = config.multiplier || 3.0;
    this.minSpeechMs = config.min_speech_ms || 300;
    this.endSilenceMs = config.end_silence_ms || 1100;
    this.noSpeechTimeoutMs = config.no_speech_timeout_ms || 6000;
    this.hardCapMs = config.hard_cap_ms || 20000;
    this.smoothingAlpha = config.smoothing_alpha || 0.3;

    this.maxHistoryFrames = Math.max(1, Math.round(this.historyWindowMs / this.frameDurationMs));
    this.reset();
  }

  static async loadConfig(url = '/static/vad_config.json') {
    try {
      const resp = await fetch(url);
      if (resp.ok) {
        return await resp.json();
      }
    } catch (e) {
      console.warn('Could not load VAD config from server, using defaults', e);
    }
    return {};
  }

  reset() {
    this.totalMs = 0;
    this.smoothedRms = null;
    this.history = [];
    this.noiseFloor = null;
    this.speechThreshold = null;
    this.speechAccumulatedMs = 0;
    this.currentSilenceMs = 0;
    this.speechDetected = false;
    this.state = 'listening';
    this.isFinal = false;
    this.finalReason = null;
  }

  processFrame(rms, frameDurationMs = null) {
    const dt = frameDurationMs || this.frameDurationMs;
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

    this.totalMs += dt;

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

    // 1. Exponential moving average smoothing of RMS
    if (this.smoothedRms === null) {
      this.smoothedRms = rms;
    } else {
      this.smoothedRms = this.smoothingAlpha * rms + (1.0 - this.smoothingAlpha) * this.smoothedRms;
    }

    // 2. History buffer of smoothed RMS over the last ~2 seconds
    this.history.push(this.smoothedRms);
    if (this.history.length > this.maxHistoryFrames) {
      this.history.shift();
    }

    // 3. Noise floor: running minimum over the history window, capped at maxNoiseFloor (0.04)
    let minSmoothed = this.history[0];
    for (let i = 1; i < this.history.length; i++) {
      if (this.history[i] < minSmoothed) {
        minSmoothed = this.history[i];
      }
    }
    this.noiseFloor = Math.min(minSmoothed, this.maxNoiseFloor);

    // 4. Speech threshold
    this.speechThreshold = Math.max(this.noiseFloor * this.multiplier, this.minSpeechThreshold);

    // 5. Speech detection
    const isSpeechFrame = rms >= this.speechThreshold;

    if (isSpeechFrame) {
      this.speechAccumulatedMs += dt;
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

    // Speech was detected (>= 300ms), now in silence
    this.currentSilenceMs += dt;
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
