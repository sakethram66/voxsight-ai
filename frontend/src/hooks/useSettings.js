import { useEffect, useState } from "react";

const DEFAULTS = { tts: true, voiceURI: "", rate: 1.05, lang: (typeof navigator !== "undefined" && navigator.language) || "en-US", handsFree: false, autoFrames: true, aiProvider: "" };

export function useSettings() {
  const [s, set] = useState(() => {
    try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem("vox-settings") || "{}") }; } catch { return DEFAULTS; }
  });
  useEffect(() => { try { localStorage.setItem("vox-settings", JSON.stringify(s)); } catch { /* storage unavailable */ } }, [s]);
  return [s, set];
}
