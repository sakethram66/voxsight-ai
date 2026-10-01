import { useEffect, useState } from "react";

const DEFAULTS = { autoSpeak: true, voiceURI: "", rate: 1.05, volume: 1, lang: "en-IN", continuousListening: false, resumeAfterInterruption: true, autoFrames: true, aiProvider: "" };

export function normalizeSettings(stored = {}) {
  const { tts, handsFree, ...currentSettings } = stored;
  const language = stored.lang === "te-IN" || stored.lang?.startsWith("te") ? "te-IN"
    : stored.lang === "hi-IN" || stored.lang?.startsWith("hi") ? "hi-IN" : "en-IN";
  return {
    ...DEFAULTS,
    ...currentSettings,
    autoSpeak: stored.autoSpeak ?? tts ?? DEFAULTS.autoSpeak,
    continuousListening: stored.continuousListening ?? handsFree ?? DEFAULTS.continuousListening,
    lang: language,
  };
}

function savedSettings() {
  try {
    const stored = JSON.parse(localStorage.getItem("vox-settings") || "{}");
    return normalizeSettings(stored);
  } catch {
    return DEFAULTS;
  }
}

export function useSettings() {
  const [s, set] = useState(savedSettings);
  useEffect(() => { try { localStorage.setItem("vox-settings", JSON.stringify(s)); } catch { /* storage unavailable */ } }, [s]);
  return [s, set];
}
