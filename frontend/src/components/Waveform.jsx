import { useEffect, useRef } from "react";

const COLORS = { listening: "#39e5ff", speaking: "#b388ff", busy: "#ffd166", idle: "#2b3a5c" };

/** Real mic levels while listening; animated envelopes while speaking/processing (TTS audio can't be tapped). */
export default function Waveform({ mode, analyser }) {
  const ref = useRef(null);
  useEffect(() => {
    const c = ref.current, g = c.getContext("2d");
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const data = analyser ? new Uint8Array(analyser.frequencyBinCount) : null;
    let raf, t = 0;
    const draw = () => {
      const dpr = devicePixelRatio || 1, w = c.clientWidth, h = c.clientHeight;
      if (c.width !== Math.round(w * dpr)) { c.width = Math.round(w * dpr); c.height = Math.round(h * dpr); }
      g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);
      const bars = Math.max(24, Math.floor(w / 8)), step = w / bars;
      if (mode === "listening" && analyser) analyser.getByteFrequencyData(data);
      g.fillStyle = COLORS[mode] || COLORS.idle;
      for (let i = 0; i < bars; i++) {
        let v = 0.05;
        if (mode === "listening" && data) v = Math.max(0.05, data[Math.floor((i / bars) * data.length * 0.7)] / 255);
        else if (mode === "speaking") v = reduce ? 0.3 : 0.2 + 0.6 * Math.abs(Math.sin(t * 3 + i * 0.5) * Math.sin(t * 1.7 + i * 0.21));
        else if (mode === "busy") v = reduce ? 0.2 : 0.12 + 0.25 * (0.5 + 0.5 * Math.sin(t * 4 - i * 0.4));
        const bh = Math.max(3, v * h);
        g.beginPath(); g.roundRect(i * step + 1, (h - bh) / 2, Math.max(2, step - 3), bh, 2); g.fill();
      }
      t += 0.016;
      raf = requestAnimationFrame(draw);
    };
    draw();
    return () => cancelAnimationFrame(raf);
  }, [mode, analyser]);
  return <canvas ref={ref} className="wave" aria-hidden="true" />;
}
