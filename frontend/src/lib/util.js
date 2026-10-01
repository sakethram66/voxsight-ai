let n = 0;
export const uid = () => ++n;
export const newSessionId = () => crypto.randomUUID();
export function ago(ts) {
  const s = Math.max(1, Math.round(Date.now() / 1000 - ts));
  return s < 60 ? "just now" : s < 3600 ? `${Math.round(s / 60)}m ago` : s < 86400 ? `${Math.round(s / 3600)}h ago` : `${Math.round(s / 86400)}d ago`;
}
