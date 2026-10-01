import { useCallback, useEffect, useRef, useState } from "react";
import { SentenceChunker, stripWake } from "../lib/speech.js";

const SR = typeof window !== "undefined" ? window.SpeechRecognition || window.webkitSpeechRecognition : null;
const TTS = typeof window !== "undefined" && "speechSynthesis" in window;

function micMessage(e) {
  if (!navigator.mediaDevices) return "Microphone access needs HTTPS or localhost.";
  if (e.name === "NotAllowedError") return "Microphone permission denied. Click the lock icon in the address bar, allow the microphone, then try again.";
  if (e.name === "NotFoundError") return "No microphone found.";
  return `Microphone error: ${e.message}`;
}

/** Browser STT (Web Speech API) + TTS (speechSynthesis) with sentence-level streaming playback and barge-in. */
export function useVoice({ settings, onFinal, onError, onBargeIn }) {
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const [speaking, setSpeaking] = useState(false);
  const [analyser, setAnalyser] = useState(null);
  const [voices, setVoices] = useState([]);
  const cb = useRef({});
  cb.current = { settings, onFinal, onError, onBargeIn };
  const rec = useRef(null), want = useRef(false), mic = useRef(null), ctx = useRef(null);
  const pending = useRef(0), gen = useRef(0), chunker = useRef(new SentenceChunker());
  const barged = useRef(false);

  useEffect(() => {
    if (!TTS) return;
    const load = () => setVoices(speechSynthesis.getVoices());
    load();
    speechSynthesis.addEventListener("voiceschanged", load);
    return () => speechSynthesis.removeEventListener("voiceschanged", load);
  }, []);

  // ---------- TTS ----------
  const say = useCallback((text) => {
    const s = cb.current.settings;
    if (!TTS || !s.tts || !text) return;
    const u = new SpeechSynthesisUtterance(text);
    const vs = speechSynthesis.getVoices(), base = (s.lang || "en").slice(0, 2);
    const v = vs.find((x) => x.voiceURI === s.voiceURI) || vs.find((x) => x.lang === s.lang) || vs.find((x) => x.lang.startsWith(base));
    if (v) { u.voice = v; u.lang = v.lang; } else u.lang = s.lang;
    u.rate = s.rate;
    const g = gen.current;
    pending.current++;
    setSpeaking(true);
    const fin = () => {
      if (g !== gen.current) return; // cancelled utterance
      pending.current = Math.max(0, pending.current - 1);
      if (pending.current === 0) setSpeaking(false);
    };
    u.onend = fin; u.onerror = fin;
    speechSynthesis.speak(u);
  }, []);

  const cancelSpeech = useCallback(() => {
    gen.current++; pending.current = 0;
    chunker.current.reset();
    if (TTS) speechSynthesis.cancel();
    setSpeaking(false);
  }, []);

  const beginReply = useCallback(() => { chunker.current.reset(); }, []);
  const feed = useCallback((d) => chunker.current.push(d).forEach(say), [say]);
  const endReply = useCallback(() => chunker.current.flush().forEach(say), [say]);
  const speakNow = useCallback((t) => { cancelSpeech(); say(t); }, [cancelSpeech, say]);

  // ---------- microphone level (for the waveform) ----------
  const ensureMic = async () => {
    if (mic.current) return;
    if (!navigator.mediaDevices?.getUserMedia) throw Object.assign(new Error("no mediaDevices"), { name: "Insecure" });
    mic.current = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    const AC = window.AudioContext || window.webkitAudioContext;
    ctx.current = new AC();
    const node = ctx.current.createAnalyser();
    node.fftSize = 256;
    ctx.current.createMediaStreamSource(mic.current).connect(node);
    setAnalyser(node);
  };
  const releaseMic = () => {
    mic.current?.getTracks().forEach((t) => t.stop());
    ctx.current?.close().catch(() => {});
    mic.current = ctx.current = null;
    setAnalyser(null);
  };

  // ---------- STT ----------
  const start = useCallback(async ({ keepSpeech = false } = {}) => {
    if (!SR) { cb.current.onError("Speech recognition isn't supported in this browser. Use Chrome, Edge or Safari, or type instead."); return; }
    if (rec.current) return;
    if (!keepSpeech) cancelSpeech(); // tapping the mic interrupts the assistant
    want.current = true;
    try { await ensureMic(); } catch (e) { want.current = false; cb.current.onError(micMessage(e)); return; }
    if (!want.current || rec.current) return;
    const r = new SR();
    r.lang = cb.current.settings.lang; r.interimResults = true; r.continuous = false; r.maxAlternatives = 1;
    let finalText = "";
    barged.current = false;
    r.onstart = () => setListening(true);
    r.onresult = (e) => {
      let live = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i];
        if (res.isFinal) finalText += res[0].transcript; else live += res[0].transcript;
      }
      const heard = (finalText + live).trim();
      setInterim(heard);
      // Barge-in (hands-free): the user talks over the assistant -> stop speaking and generating.
      if (cb.current.settings.handsFree && pending.current > 0 && !barged.current && heard.split(/\s+/).length >= 2) {
        barged.current = true;
        cancelSpeech();
        cb.current.onBargeIn?.();
      }
    };
    r.onerror = (e) => {
      if (e.error === "no-speech" || e.error === "aborted") return;
      if (e.error === "not-allowed" || e.error === "service-not-allowed") { want.current = false; cb.current.onError("Microphone permission denied for speech recognition."); }
      else if (e.error === "audio-capture") { want.current = false; cb.current.onError("No microphone found."); }
      else if (e.error === "network") cb.current.onError("Speech recognition needs a network connection (Chrome sends audio to Google's speech service).");
      else cb.current.onError(`Speech recognition error: ${e.error}`);
    };
    r.onend = () => {
      rec.current = null;
      setListening(false); setInterim("");
      const text = stripWake(finalText.trim());
      if (text) cb.current.onFinal(text);
      if (want.current && cb.current.settings.handsFree) setTimeout(() => start({ keepSpeech: true }), 250);
      else { want.current = false; releaseMic(); }
    };
    rec.current = r;
    try { r.start(); } catch { rec.current = null; }
  }, [cancelSpeech]); // eslint-disable-line react-hooks/exhaustive-deps

  const stop = useCallback(() => {
    want.current = false;
    rec.current?.abort();
    releaseMic();
    setListening(false); setInterim("");
  }, []);

  useEffect(() => () => { want.current = false; rec.current?.abort(); releaseMic(); if (TTS) speechSynthesis.cancel(); }, []);

  return { supported: !!SR, ttsSupported: TTS, listening, interim, speaking, analyser, voices,
           start, stop, beginReply, feed, endReply, cancelSpeech, speakNow };
}
