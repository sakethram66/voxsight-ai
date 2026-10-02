import { stripWake } from "./speech.js";

export const VOICE_LANGUAGES = [
  { code: "en-IN", label: "English", native: "English" },
  { code: "te-IN", label: "Telugu", native: "తెలుగు" },
  { code: "hi-IN", label: "Hindi", native: "हिन्दी" },
];

const languageFor = (code) => VOICE_LANGUAGES.find((language) => language.code === code);

export function languageLabel(code) {
  return languageFor(code)?.label || "selected language";
}

export function shouldAutoSpeak(settings) {
  return Boolean(settings.autoSpeak ?? settings.tts ?? false);
}

export function recognitionUnavailableMessage(code) {
  const language = languageFor(code);
  if (language?.code === "te-IN") return "Telugu voice recognition is not available in this browser.";
  if (language?.code === "hi-IN") return "Hindi voice recognition is not available in this browser.";
  return "Speech recognition is unavailable in this browser. You can still type.";
}

export function recognitionErrorMessage(error, code) {
  const reason = typeof error === "string" ? error : error?.error || error?.name || "unknown";
  if (reason === "aborted") return "";
  if (reason === "no-speech") return "No speech detected. Try again.";
  if (["not-allowed", "service-not-allowed", "NotAllowedError"].includes(reason)) return "Microphone permission is required.";
  if (["audio-capture", "NotFoundError"].includes(reason)) return "No microphone was found.";
  if (["network", "NetworkError"].includes(reason)) return "Speech recognition lost its network connection. Reconnecting...";
  if (["language-not-supported", "invalid-language", "language-unavailable"].includes(reason)) {
    return `This browser does not support speech recognition for ${languageLabel(code)}.`;
  }
  return "Speech recognition failed. Check your microphone and try again.";
}

export function microphoneErrorMessage(error) {
  if (error?.name === "NotAllowedError" || error?.name === "PermissionDeniedError") return "Microphone permission is required.";
  if (error?.name === "NotFoundError" || error?.name === "DevicesNotFoundError") return "No microphone was found.";
  if (error?.name === "Insecure") return "Microphone access requires HTTPS or localhost.";
  return "Microphone is unavailable. Check browser permissions and try again.";
}

export function chooseSpeechVoice(voices, language, preferredURI = "") {
  const target = language.toLowerCase();
  if (preferredURI) {
    const preferred = voices.find((voice) => voice.voiceURI === preferredURI);
    if (preferred && preferred.lang?.toLowerCase().startsWith(target.slice(0, 2))) return preferred;
  }
  const exact = voices.find((voice) => voice.lang?.toLowerCase() === target);
  return exact || voices.find((voice) => voice.lang?.toLowerCase().startsWith(target.slice(0, 2))) || null;
}

export function getSpeechRecognition(scope = globalThis) {
  return scope.SpeechRecognition || scope.webkitSpeechRecognition || null;
}

export function mergeSpeechSegments(previousText, nextText) {
  const previous = previousText.trim();
  const next = nextText.trim();
  if (!previous) return next;
  if (!next) return previous;
  const left = previous.toLocaleLowerCase();
  const right = next.toLocaleLowerCase();
  if (right.startsWith(left)) return next;
  if (left.endsWith(right)) return previous;
  const maxOverlap = Math.min(previous.length, next.length);
  for (let overlap = maxOverlap; overlap > 0; overlap--) {
    if (left.slice(-overlap) === right.slice(0, overlap)) {
      return `${previous}${next.slice(overlap)}`.trim();
    }
  }
  return `${previous} ${next}`;
}

function transcriptForLanguage(result, language) {
  const alternatives = Array.from({ length: result.length || 1 }, (_, index) => result[index]);
  const script = language === "te-IN" ? /[\u0C00-\u0C7F]/
    : language === "hi-IN" ? /[\u0900-\u097F]/ : null;
  return (script && alternatives.find((alternative) => script.test(alternative.transcript)))
    ?.transcript || alternatives[0].transcript;
}

export class SpeechRecognitionController {
  constructor({ createRecognition, getLanguage, onState, onTranscript, onInterim, onError,
    schedule = setTimeout, cancel = clearTimeout, now = () => Date.now(), silenceMs = 2600 }) {
    this.createRecognition = createRecognition;
    this.getLanguage = getLanguage;
    this.onState = onState;
    this.onTranscript = onTranscript;
    this.onInterim = onInterim;
    this.onError = onError;
    this.schedule = schedule;
    this.cancel = cancel;
    this.now = now;
    this.silenceMs = silenceMs;
    this.recognition = null;
    this.restartTimer = null;
    this.silenceTimer = null;
    this.enabled = false;
    this.continuous = false;
    this.processing = false;
    this.speaking = false;
    this.userStopped = true;
    this.pausedForSpeech = false;
    this.finishOnEnd = false;
    this.audioMonitoring = false;
    this.draftFinal = "";
    this.draftInterim = "";
    this.speechRevision = 0;
    this.lastVoiceAt = null;
    this.sessionStartedAt = 0;
    this.restartTimes = [];
    this.generation = 0;
    this.pageVisible = true;
  }

  get listening() { return Boolean(this.recognition); }

  start({ continuous = false } = {}) {
    if (!this.createRecognition) {
      this.enabled = false;
      this.userStopped = true;
      this._state("error");
      this.onError?.(recognitionUnavailableMessage(this.getLanguage()));
      return false;
    }
    if (this.userStopped) {
      this.draftFinal = "";
      this.draftInterim = "";
      this.speechRevision = 0;
      this.lastVoiceAt = null;
      this.sessionStartedAt = 0;
      this.restartTimes = [];
      this.finishOnEnd = false;
      this._emitTranscript();
    }
    this.enabled = true;
    this.userStopped = false;
    this.continuous = continuous;
    this.pausedForSpeech = false;
    if (this.recognition) {
      this._state(this.speaking ? "speaking" : "listening");
      return true;
    }
    if (this.processing) return true;
    this._open();
    return this.enabled;
  }

  stop({ commit = false, keepContinuous = false } = {}) {
    this._clearTimers();
    this.userStopped = !keepContinuous;
    this.enabled = keepContinuous;
    this.continuous = keepContinuous;
    this.processing = false;
    this.pausedForSpeech = false;
    this.finishOnEnd = false;
    const recognition = this.recognition;
    if (commit) {
      this.finishOnEnd = true;
      if (recognition) {
        this._state("processing");
        try { recognition.stop(); } catch { this.recognition = null; this._submitDraft(); }
      } else {
        this._submitDraft();
      }
      return;
    }
    this.generation++;
    this.recognition = null;
    this.draftFinal = "";
    this.draftInterim = "";
    this.speechRevision = 0;
    this.lastVoiceAt = null;
    this.onInterim?.("");
    this._state("paused");
    try { recognition?.abort(); } catch { /* recognizer may already be stopped */ }
  }

  responseFinished() {
    this.processing = false;
    if (this.enabled && this.continuous && !this.speaking) this._open();
    else if (!this.speaking) this._state(this.enabled ? "ready" : "paused");
  }

  pauseListening() {
    this.pausedForSpeech = true;
    this._clearRestartTimer();
    const recognition = this.recognition;
    if (recognition) {
      this.generation++;
      this.recognition = null;
      try { recognition.abort(); } catch { /* recognition may already have ended */ }
    }
    this._state("speaking");
  }

  resumeListening() {
    this.pausedForSpeech = false;
    if (this.enabled && this.continuous && !this.processing) this._open();
    else if (!this.processing) this._state(this.enabled ? "ready" : "paused");
  }

  setSpeaking(speaking) {
    this.speaking = speaking;
    if (speaking) this.pauseListening();
    else this.resumeListening();
  }

  changeLanguage() {
    const shouldRestart = Boolean(this.recognition) && this.enabled && !this.processing && !this.speaking;
    const previous = this.recognition;
    this.generation++;
    this.recognition = null;
    this.draftFinal = "";
    this.draftInterim = "";
    this.speechRevision = 0;
    this.lastVoiceAt = null;
    this._clearSilenceTimer();
    this._emitTranscript();
    try { previous.abort(); } catch { /* recognizer may already be stopped */ }
    if (shouldRestart) {
      this._state("reconnecting");
      this._scheduleRestart(0);
    }
  }

  setPageVisible(visible) {
    if (this.pageVisible === visible) return;
    this.pageVisible = visible;
    if (!visible) {
      this._clearRestartTimer();
      const recognition = this.recognition;
      if (recognition) {
        this.generation++;
        this.recognition = null;
        try { recognition.abort(); } catch { /* recognition may already be stopped */ }
      }
      if (this.enabled && !this.processing) this._state("paused");
      return;
    }
    if (this.enabled && this.continuous && !this.processing && !this.speaking && !this.pausedForSpeech) {
      this.restartTimes = [];
      this._state("reconnecting");
      this._scheduleRestart(0);
    }
  }

  noteAudioLevel(level, timestamp = this.now()) {
    this.audioMonitoring = true;
    if (!this.enabled || !this.continuous || this.processing || this.pausedForSpeech) return;
    if (level >= 0.022) {
      this.lastVoiceAt = timestamp;
      this._clearSilenceTimer();
      return;
    }
    if (this.draftFinal.trim() && this.lastVoiceAt !== null && timestamp - this.lastVoiceAt >= this.silenceMs) {
      this._submitDraft(true);
    }
    this._armSilenceFallback();
  }

  setAudioMonitoring(available) {
    this.audioMonitoring = Boolean(available);
  }

  _state(value) { this.onState?.(value); }

  _emitTranscript() {
    this.onInterim?.(mergeSpeechSegments(this.draftFinal, this.draftInterim));
  }

  _clearRestartTimer() {
    if (this.restartTimer !== null) this.cancel(this.restartTimer);
    this.restartTimer = null;
  }

  _clearSilenceTimer() {
    if (this.silenceTimer !== null) this.cancel(this.silenceTimer);
    this.silenceTimer = null;
  }

  _clearTimers() {
    this._clearRestartTimer();
    this._clearSilenceTimer();
  }

  _armSilenceFallback() {
    this._clearSilenceTimer();
    if (!this.continuous || this.audioMonitoring || !this.draftFinal.trim()) return;
    const speechRevision = this.speechRevision;
    this.silenceTimer = this.schedule(() => {
      this.silenceTimer = null;
      if (speechRevision === this.speechRevision && this.enabled && this.continuous && !this.processing) this._submitDraft(true);
    }, this.silenceMs);
  }

  _submitDraft(stopRecognition = false) {
    if (this.processing) return;
    this._clearRestartTimer();
    const transcript = stripWake(this.draftFinal.trim());
    this.draftFinal = "";
    this.draftInterim = "";
    this.lastVoiceAt = null;
    this._clearSilenceTimer();
    this._emitTranscript();
    if (!transcript) {
      if (this.enabled && this.continuous && !this.pausedForSpeech) this._open();
      else this._state(this.enabled ? "ready" : "paused");
      return;
    }
    this.processing = true;
    this._state("processing");
    const recognition = stopRecognition ? this.recognition : null;
    if (recognition) {
      this.finishOnEnd = true;
      try { recognition.stop(); } catch { this.recognition = null; this.finishOnEnd = false; }
    }
    this.onTranscript?.(transcript);
  }

  _open() {
    if (!this.pageVisible || !this.enabled || this.userStopped || this.recognition || this.processing || this.speaking || this.pausedForSpeech) return;
    const generation = ++this.generation;
    let recognition;
    try {
      recognition = this.createRecognition();
      recognition.lang = this.getLanguage();
      recognition.interimResults = true;
      recognition.continuous = true;
      recognition.maxAlternatives = this.getLanguage() === "en-IN" ? 1 : 3;
      this.recognition = recognition;
    } catch (error) {
      this.enabled = false;
      this.userStopped = true;
      this._state("error");
      this.onError?.(recognitionErrorMessage(error, this.getLanguage()));
      return;
    }

    let failed = false;
    recognition.onstart = () => {
      if (generation === this.generation) {
        this.sessionStartedAt = this.now();
        this._state(this.speaking ? "speaking" : "listening");
        this._emitTranscript();
      }
    };
    recognition.onresult = (event) => {
      if (generation !== this.generation) return;
      let interim = "";
      for (let index = event.resultIndex || 0; index < event.results.length; index++) {
        const result = event.results[index];
        if (result.isFinal) {
          const segment = transcriptForLanguage(result, this.getLanguage());
          this.draftFinal = mergeSpeechSegments(this.draftFinal, this.draftInterim);
          this.draftFinal = mergeSpeechSegments(this.draftFinal, segment);
          this.draftInterim = "";
        } else interim = mergeSpeechSegments(interim, transcriptForLanguage(result, this.getLanguage()));
      }
      if (interim) this.draftInterim = mergeSpeechSegments(this.draftInterim, interim);
      this.speechRevision++;
      this.lastVoiceAt = this.now();
      this._emitTranscript();
      this._armSilenceFallback();
    };
    recognition.onerror = (event) => {
      if (generation !== this.generation || event.error === "aborted") return;
      const fatal = ["not-allowed", "service-not-allowed", "audio-capture", "language-not-supported"].includes(event.error);
      if (fatal) {
        failed = true;
        this.enabled = false;
        this.userStopped = true;
        this._state("error");
        this.onError?.(recognitionErrorMessage(event, this.getLanguage()));
      } else if (event.error === "network") {
        this._state("reconnecting");
        this.onError?.("Speech recognition lost its network connection. Reconnecting...");
      } else if (event.error === "bad-grammar") {
        this._state("reconnecting");
        this.onError?.("Speech recognition had a temporary error. Reconnecting...");
      } else if (event.error === "no-speech" && !this.continuous) {
        this.onError?.(recognitionErrorMessage(event, this.getLanguage()));
      }
    };
    recognition.onend = () => {
      if (generation !== this.generation) return;
      this.recognition = null;
      if (this.sessionStartedAt && this.now() - this.sessionStartedAt >= 10_000) this.restartTimes = [];
      if (this.finishOnEnd) {
        this.finishOnEnd = false;
        if (!this.processing) this._submitDraft();
        return;
      }
      if (failed || this.userStopped || !this.enabled) {
        this._state(failed ? "error" : this.enabled ? "ready" : "paused");
        return;
      }
      if (this.now() - this.sessionStartedAt >= 10_000) this.restartTimes = [];
      this._emitTranscript();
      this._state("reconnecting");
      this._scheduleRestart();
    };
    try {
      recognition.start();
    } catch (error) {
      if (generation !== this.generation) return;
      this.recognition = null;
      this._state("reconnecting");
      this._scheduleRestart();
      this.onError?.(recognitionErrorMessage(error, this.getLanguage()));
    }
  }

  _scheduleRestart(delay = null) {
    if (!this.pageVisible || !this.enabled || this.userStopped || this.processing || this.speaking || this.pausedForSpeech || this.restartTimer !== null) return;
    const now = this.now();
    this.restartTimes = this.restartTimes.filter((started) => now - started < 60_000);
    if (this.restartTimes.length >= 8) {
      this.enabled = false;
      this.userStopped = true;
      this._state("error");
      this.onError?.("Speech recognition keeps disconnecting. Tap the microphone to try again.");
      return;
    }
    const restarts = this.restartTimes.length;
    const backoff = [250, 500, 1000, 2000, 4000, 8000][Math.min(restarts, 5)];
    this.restartTimes.push(now);
    const generation = this.generation;
    this.restartTimer = this.schedule(() => {
      this.restartTimer = null;
      if (generation === this.generation) this._open();
    }, delay ?? backoff);
  }
}