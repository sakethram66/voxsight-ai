import test from "node:test";
import assert from "node:assert/strict";
import {
  SpeechRecognitionController,
  VOICE_LANGUAGES,
  chooseSpeechVoice,
  getSpeechRecognition,
  mergeSpeechSegments,
  microphoneErrorMessage,
  recognitionErrorMessage,
  recognitionUnavailableMessage,
  shouldAutoSpeak,
} from "./voice.js";
import { normalizeSettings } from "../hooks/useSettings.js";

class FakeRecognition {
  constructor() {
    this.startCalls = 0;
    this.stopCalls = 0;
    this.abortCalls = 0;
  }
  start() { this.startCalls++; this.onstart?.(); }
  stop() { this.stopCalls++; this.onend?.(); }
  abort() {
    this.abortCalls++;
    this.onerror?.({ error: "aborted" });
    this.onend?.();
  }
  result(text, isFinal = true) {
    const item = { isFinal, 0: { transcript: text } };
    this.onresult?.({ resultIndex: 0, results: [item] });
  }
}

function harness(language = "en-IN") {
  const recognitions = [];
  const states = [];
  const interim = [];
  const transcripts = [];
  const errors = [];
  const timers = [];
  const controller = new SpeechRecognitionController({
    createRecognition: () => {
      const recognition = new FakeRecognition();
      recognitions.push(recognition);
      return recognition;
    },
    getLanguage: () => language,
    onState: (state) => states.push(state),
    onTranscript: (text) => transcripts.push(text),
    onInterim: (text) => interim.push(text),
    onError: (error) => errors.push(error),
    schedule: (callback, delay) => {
      const timer = { callback, delay, cancelled: false };
      timers.push(timer);
      return timer;
    },
    cancel: (timer) => { timer.cancelled = true; },
  });
  return { controller, recognitions, states, interim, transcripts, errors, timers, setLanguage: (value) => { language = value; } };
}

test("recognition receives actual English, Telugu, and Hindi BCP-47 language codes", () => {
  assert.deepEqual(VOICE_LANGUAGES.map((language) => language.code), ["en-IN", "te-IN", "hi-IN"]);
  for (const code of ["en-IN", "te-IN", "hi-IN"]) {
    const { controller, recognitions } = harness(code);
    controller.start();
    assert.equal(recognitions[0].lang, code);
    assert.equal(recognitions[0].interimResults, true);
    assert.equal(recognitions[0].continuous, true);
  }
});

test("push-to-talk submits only final recognition text on release", () => {
  const { controller, recognitions, states, interim, transcripts } = harness();
  controller.start();
  recognitions[0].result("Hey VoxSight, what is here?");
  assert.equal(interim.at(-1), "Hey VoxSight, what is here?");
  controller.stop({ commit: true });
  assert.deepEqual(transcripts, ["what is here?"]);
  assert.equal(states.at(-1), "processing");
});

test("continuous listening restarts after end, waits during processing, then resumes after response", () => {
  const { controller, recognitions, timers, transcripts } = harness();
  controller.start({ continuous: true });
  recognitions[0].onend();
  assert.equal(timers[0].delay, 250);
  timers[0].callback();
  assert.equal(recognitions.length, 2);
  recognitions[1].result("next question");
  recognitions[1].onend();
  assert.deepEqual(transcripts, []);
  assert.equal(recognitions.length, 2);
  controller.noteAudioLevel(0, controller.lastVoiceAt + 1000);
  assert.deepEqual(transcripts, []);
  controller.noteAudioLevel(0, controller.lastVoiceAt + 2700);
  assert.deepEqual(transcripts, ["next question"]);
  controller.responseFinished();
  assert.equal(recognitions.length, 3);
});

test("enabling continuous mode during processing waits for the response to finish", () => {
  const { controller, recognitions, transcripts } = harness();
  controller.start();
  recognitions[0].result("question");
  controller.stop({ commit: true });
  assert.deepEqual(transcripts, ["question"]);
  controller.start({ continuous: true });
  assert.equal(recognitions.length, 1);
  controller.responseFinished();
  assert.equal(recognitions.length, 2);
  assert.equal(recognitions[1].lang, "en-IN");
});

test("continuous mode can be enabled during an active push-to-talk recognizer", () => {
  const { controller, recognitions, timers } = harness();
  controller.start();
  assert.equal(controller.start({ continuous: true }), true);
  assert.equal(controller.continuous, true);
  recognitions[0].onend();
  assert.equal(timers.length, 1);
  assert.equal(timers[0].delay, 250);
});

test("unexpected onend restarts finitely with bounded backoff", () => {
  const { controller, recognitions, timers, errors, states } = harness();
  controller.start({ continuous: true });
  for (let attempt = 0; attempt < 9; attempt++) {
    recognitions.at(-1).onerror({ error: "no-speech" });
    recognitions.at(-1).onend();
    if (attempt < 8) timers.at(-1).callback();
  }
  assert.deepEqual(timers.map((timer) => timer.delay), [250, 500, 1000, 2000, 4000, 8000, 8000, 8000]);
  assert.deepEqual(errors, ["Speech recognition keeps disconnecting. Tap the microphone to try again."]);
  assert.equal(states.at(-1), "error");
  assert.equal(controller.enabled, false);
});

test("background tab pauses continuous recognition and resumes without spending retries", () => {
  const { controller, recognitions, timers, states } = harness("hi-IN");
  controller.start({ continuous: true });

  controller.setPageVisible(false);
  assert.equal(recognitions[0].abortCalls, 1);
  assert.equal(controller.enabled, true);
  assert.equal(controller.userStopped, false);
  assert.equal(timers.length, 0);
  assert.equal(states.at(-1), "paused");

  controller.setPageVisible(true);
  assert.equal(timers.at(-1).delay, 0);
  timers.at(-1).callback();
  assert.equal(recognitions.length, 2);
  assert.equal(recognitions[1].lang, "hi-IN");
});

test("natural pauses keep one draft and interim text alone is never submitted", () => {
  const { controller, recognitions, interim, transcripts } = harness();
  controller.start({ continuous: true });
  recognitions[0].result("Look at the screen", true);
  controller.noteAudioLevel(0, controller.lastVoiceAt + 1200);
  assert.deepEqual(transcripts, []);
  recognitions[0].result("what is wrong here", true);
  assert.match(interim.at(-1), /Look at the screen what is wrong here/);
  controller.noteAudioLevel(0, controller.lastVoiceAt + 1800);
  assert.deepEqual(transcripts, []);
  controller.noteAudioLevel(0, controller.lastVoiceAt + 2700);
  assert.deepEqual(transcripts, ["Look at the screen what is wrong here"]);

  const second = harness();
  second.controller.start({ continuous: true });
  second.recognitions[0].result("unfinished thought", false);
  second.controller.noteAudioLevel(0, second.controller.lastVoiceAt + 4000);
  assert.deepEqual(second.transcripts, []);
});

test("interim transcript survives unexpected recognition restart and merges without duplication", () => {
  const { controller, recognitions, timers, interim, transcripts } = harness();
  controller.start({ continuous: true });
  recognitions[0].result("Look at this screen", false);
  recognitions[0].onend();
  assert.equal(interim.at(-1), "Look at this screen");
  timers[0].callback();
  recognitions[1].result("Look at this screen and tell me what is wrong", true);
  assert.equal(interim.at(-1), "Look at this screen and tell me what is wrong");
  controller.noteAudioLevel(0, controller.lastVoiceAt + 2700);
  assert.deepEqual(transcripts, ["Look at this screen and tell me what is wrong"]);
});

test("network error reports reconnecting and restarts recognition", () => {
  const { controller, recognitions, timers, errors, states } = harness();
  controller.start({ continuous: true });
  recognitions[0].onerror({ error: "network" });
  recognitions[0].onend();
  assert.equal(errors[0], "Speech recognition lost its network connection. Reconnecting...");
  assert.equal(states.at(-1), "reconnecting");
  timers[0].callback();
  assert.equal(recognitions.length, 2);
});

test("explicit stop aborts and never restarts or submits an utterance", () => {
  const { controller, recognitions, transcripts, timers, states } = harness();
  controller.start({ continuous: true });
  controller.stop();
  assert.equal(recognitions[0].abortCalls, 1);
  assert.deepEqual(transcripts, []);
  assert.equal(timers.length, 0);
  assert.equal(states.at(-1), "paused");
  assert.equal(controller.enabled, false);
});

test("push-to-talk release stops recognition and commits the final result", () => {
  const { controller, recognitions, transcripts } = harness("te-IN");
  controller.start();
  recognitions[0].result("ఇది ఏమిటి?");
  controller.stop({ commit: true });
  assert.equal(recognitions[0].stopCalls, 1);
  assert.deepEqual(transcripts, ["ఇది ఏమిటి?"]);
});

test("changing language during continuous mode restarts with the new recognition language", () => {
  const { controller, recognitions, timers, setLanguage } = harness("en-IN");
  controller.start({ continuous: true });
  setLanguage("hi-IN");
  controller.changeLanguage();
  assert.equal(recognitions[0].abortCalls, 1);
  timers.at(-1).callback();
  assert.equal(recognitions.at(-1).lang, "hi-IN");
});

test("speech errors map to useful messages and expected failures do not loop", () => {
  assert.equal(recognitionErrorMessage("no-speech", "en-IN"), "No speech detected. Try again.");
  assert.equal(recognitionErrorMessage("network", "en-IN"), "Speech recognition lost its network connection. Reconnecting...");
  assert.equal(recognitionErrorMessage("not-allowed", "en-IN"), "Microphone permission is required.");
  assert.equal(recognitionErrorMessage("service-not-allowed", "en-IN"), "Microphone permission is required.");
  assert.equal(recognitionErrorMessage("bad-grammar", "en-IN"), "Speech recognition failed. Check your microphone and try again.");
  assert.equal(recognitionErrorMessage("language-not-supported", "te-IN"), "This browser does not support speech recognition for Telugu.");
  assert.equal(recognitionErrorMessage("language-not-supported", "hi-IN"), "This browser does not support speech recognition for Hindi.");
  assert.equal(recognitionErrorMessage("aborted", "en-IN"), "");

  const { controller, recognitions, errors, timers } = harness();
  controller.start({ continuous: true });
  recognitions[0].onerror({ error: "not-allowed" });
  recognitions[0].onend();
  assert.equal(controller.enabled, false);
  assert.equal(timers.length, 0);
  assert.equal(errors[0], "Microphone permission is required.");
});

test("unsupported selected language stops continuous recognition with an error state", () => {
  const { controller, recognitions, states, errors } = harness("te-IN");
  controller.start({ continuous: true });
  recognitions[0].onerror({ error: "language-not-supported" });
  recognitions[0].onend();
  assert.equal(controller.enabled, false);
  assert.equal(states.at(-1), "error");
  assert.equal(errors.at(-1), "This browser does not support speech recognition for Telugu.");
});

test("unsupported recognition remains explicit and microphone failures are friendly", () => {
  const messages = [];
  const controller = new SpeechRecognitionController({
    createRecognition: null, getLanguage: () => "te-IN", onState: () => {}, onTranscript: () => {},
    onInterim: () => {}, onError: (message) => messages.push(message),
  });
  assert.equal(controller.start(), false);
  assert.equal(messages[0], recognitionUnavailableMessage("te-IN"));
  assert.equal(microphoneErrorMessage({ name: "NotAllowedError" }), "Microphone permission is required.");
  assert.equal(microphoneErrorMessage({ name: "NotFoundError" }), "No microphone was found.");
});

test("speech voice selection prefers requested language and tolerates missing voices", () => {
  const voices = [
    { voiceURI: "hi", lang: "hi-IN" },
    { voiceURI: "en", lang: "en-IN" },
  ];
  assert.equal(chooseSpeechVoice(voices, "hi-IN").voiceURI, "hi");
  assert.equal(chooseSpeechVoice(voices, "hi-IN", "hi").voiceURI, "hi");
  assert.equal(chooseSpeechVoice(voices, "te-IN"), null);
  assert.equal(getSpeechRecognition({ webkitSpeechRecognition: FakeRecognition }), FakeRecognition);
  assert.equal(getSpeechRecognition({}), null);
});

test("auto-speak respects the persisted setting and migrates the prior tts setting", () => {
  assert.equal(shouldAutoSpeak({ autoSpeak: true }), true);
  assert.equal(shouldAutoSpeak({ autoSpeak: false }), false);
  assert.equal(shouldAutoSpeak({ tts: false }), false);
  assert.equal(normalizeSettings({ tts: false }).autoSpeak, false);
  assert.equal(normalizeSettings({ handsFree: true }).continuousListening, true);
  assert.equal(normalizeSettings({ volume: 0.45, resumeAfterInterruption: false }).volume, 0.45);
  assert.equal(normalizeSettings({ volume: 0.45, resumeAfterInterruption: false }).resumeAfterInterruption, false);
  assert.equal(normalizeSettings({ lang: "te-IN" }).lang, "te-IN");
  assert.equal(normalizeSettings({ lang: "hi-IN" }).lang, "hi-IN");
  assert.equal(normalizeSettings({ lang: "en-US" }).lang, "en-IN");
});

test("speech segment overlap is merged without duplicating words", () => {
  assert.equal(mergeSpeechSegments("Look at this", "Look at this screen"), "Look at this screen");
  assert.equal(mergeSpeechSegments("Look at this", "this screen"), "Look at this screen");
});

test("TTS pauses recognition and continuous mode resumes it after speech", () => {
  const { controller, recognitions, states } = harness();
  controller.start({ continuous: true });
  controller.setSpeaking(true);
  assert.equal(recognitions[0].abortCalls, 1);
  assert.equal(states.at(-1), "speaking");
  controller.responseFinished();
  assert.equal(recognitions.length, 1);
  controller.setSpeaking(false);
  assert.equal(recognitions.length, 2);
  assert.equal(states.at(-1), "listening");
});