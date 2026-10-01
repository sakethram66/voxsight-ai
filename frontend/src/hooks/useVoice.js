import { useCallback, useEffect, useRef, useState } from "react";
import { SentenceChunker } from "../lib/speech.js";
import {
  SpeechRecognitionController,
  chooseSpeechVoice,
  getSpeechRecognition,
  microphoneErrorMessage,
  recognitionUnavailableMessage,
  shouldAutoSpeak,
} from "../lib/voice.js";

const TTS = typeof window !== "undefined" && "speechSynthesis" in window;
const SR = typeof window !== "undefined" ? getSpeechRecognition(window) : null;

/** Browser Web Speech recognition + speech synthesis with a real microphone analyser. */
export function useVoice({ settings, onFinal, onError, onBargeIn }) {
  const [state, setState] = useState("ready");
  const [interim, setInterim] = useState("");
  const [speaking, setSpeaking] = useState(false);
  const [analyser, setAnalyser] = useState(null);
  const [voices, setVoices] = useState([]);
  const [error, setError] = useState("");
  const callbacks = useRef({});
  callbacks.current = { settings, onFinal, onError, onBargeIn };
  const microphone = useRef(null), audioContext = useRef(null), controller = useRef(null);
  const pendingSpeech = useRef(0), speechGeneration = useRef(0), chunker = useRef(new SentenceChunker());
  const bargedIn = useRef(false), starting = useRef(false);
  const startGeneration = useRef(0);

  const releaseMicrophone = () => {
    microphone.current?.getTracks().forEach((track) => track.stop());
    audioContext.current?.close().catch(() => {});
    microphone.current = audioContext.current = null;
    controller.current?.setAudioMonitoring(false);
    setAnalyser(null);
  };

  const ensureMicrophone = async () => {
    if (microphone.current) return;
    if (!navigator.mediaDevices?.getUserMedia) throw Object.assign(new Error("getUserMedia unavailable"), { name: "Insecure" });
    microphone.current = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    try {
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (!AudioContextClass) return;
      audioContext.current = new AudioContextClass();
      if (audioContext.current.state === "suspended") await audioContext.current.resume().catch(() => {});
      const meter = audioContext.current.createAnalyser();
      meter.fftSize = 256;
      audioContext.current.createMediaStreamSource(microphone.current).connect(meter);
      setAnalyser(meter);
    } catch (error) {
      console.debug("Microphone level meter unavailable", error);
      audioContext.current?.close().catch(() => {});
      audioContext.current = null;
      setAnalyser(null);
    }
  };

  const cancelSpeech = useCallback(() => {
    speechGeneration.current++;
    pendingSpeech.current = 0;
    chunker.current.reset();
    if (TTS) window.speechSynthesis.cancel();
    setSpeaking(false);
    controller.current?.setSpeaking(false);
  }, []);

  const say = useCallback((text) => {
    const current = callbacks.current.settings;
    if (!TTS || !shouldAutoSpeak(current) || !text) return;
    const utterance = new SpeechSynthesisUtterance(text);
    const voice = chooseSpeechVoice(window.speechSynthesis.getVoices(), current.lang, current.voiceURI);
    utterance.lang = current.lang;
    if (voice) utterance.voice = voice;
    utterance.rate = current.rate;
    utterance.volume = current.volume ?? 1;
    const generation = speechGeneration.current;
    pendingSpeech.current++;
    setSpeaking(true);
    controller.current?.setSpeaking(true);
    const finish = () => {
      if (generation !== speechGeneration.current) return;
      pendingSpeech.current = Math.max(0, pendingSpeech.current - 1);
      if (pendingSpeech.current === 0) {
        setSpeaking(false);
        controller.current?.setSpeaking(false);
      }
    };
    utterance.onend = finish;
    utterance.onerror = (event) => {
      console.debug("Speech synthesis error", event.error);
      finish();
    };
    try { window.speechSynthesis.speak(utterance); }
    catch (error) {
      console.debug("Speech synthesis unavailable", error);
      finish();
    }
  }, []);

  const beginReply = useCallback(() => { chunker.current.reset(); }, []);
  const feed = useCallback((delta) => chunker.current.push(delta).forEach(say), [say]);
  const endReply = useCallback(() => chunker.current.flush().forEach(say), [say]);
  const speakNow = useCallback((text) => { cancelSpeech(); say(text); }, [cancelSpeech, say]);

  if (!controller.current) {
    controller.current = new SpeechRecognitionController({
      createRecognition: SR ? () => new SR() : null,
      getLanguage: () => callbacks.current.settings.lang,
      onState: (nextState) => {
        setState(nextState);
        if (nextState !== "error") setError("");
        if (nextState === "error" || nextState === "ready" ||
            (nextState === "processing" && !controller.current?.continuous)) releaseMicrophone();
      },
      onTranscript: (transcript) => {
        try {
          const result = callbacks.current.onFinal?.(transcript);
          result?.catch?.((error) => {
            console.debug("Voice submission failed", error);
            callbacks.current.onError?.("Could not send the voice message. Please try again.");
            controller.current?.responseFinished();
          });
        } catch (error) {
          console.debug("Voice submission failed", error);
          callbacks.current.onError?.("Could not send the voice message. Please try again.");
          controller.current?.responseFinished();
        }
      },
      onInterim: (text) => {
        setInterim(text);
        if (pendingSpeech.current > 0 && !bargedIn.current && text.trim().split(/\s+/).length >= 2) {
          bargedIn.current = true;
          cancelSpeech();
          callbacks.current.onBargeIn?.();
        }
      },
      onError: (message) => {
        setError(message);
        callbacks.current.onError?.(message);
      },
    });
  }

  const start = useCallback(async ({ continuous = false } = {}) => {
    if (starting.current) return false;
    setError("");
    if (!SR) return controller.current.start({ continuous });
    if (controller.current.listening) return controller.current.start({ continuous });
    setState("ready");
    if (speaking) {
      cancelSpeech();
      callbacks.current.onBargeIn?.();
    }
    const generation = ++startGeneration.current;
    starting.current = true;
    try {
      await ensureMicrophone();
      if (generation !== startGeneration.current) {
        releaseMicrophone();
        return false;
      }
      bargedIn.current = false;
      return controller.current.start({ continuous });
    } catch (error) {
      console.debug("Microphone setup failed", error);
      callbacks.current.onError?.(microphoneErrorMessage(error));
      setState("error");
      return false;
    } finally {
      if (generation === startGeneration.current) starting.current = false;
    }
  }, [cancelSpeech, speaking]);

  const stop = useCallback(({ commit = false } = {}) => {
    startGeneration.current++;
    starting.current = false;
    controller.current?.stop({ commit });
    if (!commit) releaseMicrophone();
    setInterim("");
  }, []);

  const responseFinished = useCallback(() => controller.current?.responseFinished(), []);
  const changeLanguage = useCallback(() => controller.current?.changeLanguage(), []);

  useEffect(() => {
    if (!TTS) return;
    const loadVoices = () => setVoices(window.speechSynthesis.getVoices());
    loadVoices();
    window.speechSynthesis.addEventListener("voiceschanged", loadVoices);
    return () => window.speechSynthesis.removeEventListener("voiceschanged", loadVoices);
  }, []);

  useEffect(() => {
    if (!analyser || !settings.continuousListening || !["listening", "reconnecting"].includes(state)) return;
    const samples = new Float32Array(analyser.fftSize);
    const monitor = window.setInterval(() => {
      try {
        analyser.getFloatTimeDomainData(samples);
        let energy = 0;
        for (let index = 0; index < samples.length; index++) energy += samples[index] * samples[index];
        controller.current?.noteAudioLevel(Math.sqrt(energy / samples.length));
      } catch (error) {
        console.debug("Microphone activity sampling stopped", error);
        controller.current?.setAudioMonitoring(false);
      }
    }, 100);
    return () => window.clearInterval(monitor);
  }, [analyser, settings.continuousListening, state]);

  useEffect(() => { changeLanguage(); }, [settings.lang, changeLanguage]);

  useEffect(() => () => {
    controller.current?.stop();
    releaseMicrophone();
    if (TTS) window.speechSynthesis.cancel();
  }, []);

  return {
    supported: Boolean(SR), unsupportedMessage: recognitionUnavailableMessage(settings.lang),
    ttsSupported: TTS, state, error, listening: state === "listening",
    interim, speaking, analyser, voices, start, stop, responseFinished, changeLanguage,
    beginReply, feed, endReply, cancelSpeech, speakNow,
  };
}
