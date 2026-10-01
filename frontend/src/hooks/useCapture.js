import { useCallback, useEffect, useRef, useState } from "react";
import { frameFromVideo } from "../lib/image.js";

const camErr = (e) => !navigator.mediaDevices ? "Camera needs HTTPS or localhost."
  : e.name === "NotAllowedError" ? "Camera permission denied. Allow it via the lock icon in the address bar, then try again."
  : e.name === "NotFoundError" ? "No camera found on this device."
  : e.name === "NotReadableError" ? "The camera is being used by another app."
  : `Camera error: ${e.message}`;
const scrErr = (e) => !navigator.mediaDevices?.getDisplayMedia ? "Screen sharing isn't supported in this browser (try desktop Chrome, Edge or Firefox)."
  : e.name === "NotAllowedError" ? "Screen sharing was cancelled or blocked."
  : `Screen sharing error: ${e.message}`;

/** Camera + screen share. Frames are grabbed as snapshots when a question is asked. */
export function useCapture(notify) {
  const [camera, setCamera] = useState(null);
  const [screen, setScreen] = useState(null);
  const camRef = useRef(null), scrRef = useRef(null), streams = useRef({});

  const stop = useCallback((k) => {
    streams.current[k]?.getTracks().forEach((t) => t.stop());
    delete streams.current[k];
    (k === "camera" ? setCamera : setScreen)(null);
  }, []);

  const startCamera = useCallback(async () => {
    if (streams.current.camera) return;
    try {
      const s = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 } } });
      streams.current.camera = s; setCamera(s);
    } catch (e) { notify(camErr(e)); }
  }, [notify]);

  const startScreen = useCallback(async () => {
    if (streams.current.screen) return;
    try {
      const s = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 5 }, audio: false });
      s.getVideoTracks()[0].addEventListener("ended", () => stop("screen")); // stopped via the browser's own bar
      streams.current.screen = s; setScreen(s);
    } catch (e) { notify(scrErr(e)); }
  }, [notify, stop]);

  useEffect(() => { if (camRef.current) camRef.current.srcObject = camera; }, [camera]);
  useEffect(() => { if (scrRef.current) scrRef.current.srcObject = screen; }, [screen]);
  useEffect(() => () => { ["camera", "screen"].forEach(stop); }, [stop]);

  const grabFrames = useCallback(async () => {
    const out = [];
    for (const [tag, ref, max, q] of [["camera", camRef, 1280, 0.8], ["screen", scrRef, 1920, 0.85]]) {
      const v = ref.current;
      if (!streams.current[tag] || !v) continue;
      if (v.readyState < 2) await new Promise((r) => setTimeout(r, 400));
      out.push({ tag, ...(await frameFromVideo(v, max, q)) });
    }
    return out;
  }, []);

  return { camera, screen, camRef, scrRef, startCamera, startScreen, stop, grabFrames,
           toggleCamera: () => (streams.current.camera ? stop("camera") : startCamera()),
           toggleScreen: () => (streams.current.screen ? stop("screen") : startScreen()) };
}
