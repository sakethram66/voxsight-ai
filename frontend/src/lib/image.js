const b64 = (blob) => new Promise((res, rej) => {
  const r = new FileReader();
  r.onload = () => res(String(r.result).split(",")[1]);
  r.onerror = () => rej(new Error("Could not read frame"));
  r.readAsDataURL(blob);
});

/** Grab one downscaled JPEG frame from a <video>. Snapshots (not continuous video) keep latency and cost low. */
export async function frameFromVideo(video, maxDim = 1280, quality = 0.8) {
  const w = video.videoWidth, h = video.videoHeight;
  if (!w || !h) throw new Error("video isn't ready yet");
  const k = Math.min(1, maxDim / Math.max(w, h));
  const c = document.createElement("canvas");
  c.width = Math.round(w * k); c.height = Math.round(h * k);
  c.getContext("2d").drawImage(video, 0, 0, c.width, c.height);
  const blob = await new Promise((r) => c.toBlob(r, "image/jpeg", quality));
  if (!blob) throw new Error("frame capture failed");
  return { mime: "image/jpeg", data: await b64(blob), url: URL.createObjectURL(blob) };
}
