import { useCallback, useEffect, useRef, useState } from "react";
import { newSessionId, uid } from "../lib/util.js";

const rowToMsg = (r) =>
  r.role === "user" ? { id: uid(), role: "user", text: r.text, images: [], chips: (r.meta.attachments || []).map((a) => ({ name: a.name, kind: a.kind })) }
  : r.role === "ai" ? { id: uid(), role: "ai", text: r.text }
  : r.role === "tool" ? { id: uid(), role: "tool", name: r.text, args: r.meta.args, result: r.meta.result } : null;

/** WebSocket agent connection + session list. Callbacks are kept in a ref so they never go stale. */
export function useAgent(callbacks) {
  const [sid, setSid] = useState(() => localStorage.getItem("vox-sid") || newSessionId());
  const [messages, setMessages] = useState([]);
  const [state, setState] = useState({ name: "connecting", detail: "", tool: "" });
  const [confirm, setConfirm] = useState(null);
  const [sessions, setSessions] = useState([]);
  const ws = useRef(null), cb = useRef(callbacks);
  cb.current = callbacks;

  const refresh = useCallback(() => fetch("/api/sessions").then((r) => r.json()).then(setSessions).catch(() => {}), []);
  const endStream = () => setMessages((p) => p.map((m) => (m.streaming ? { ...m, streaming: false } : m)));

  useEffect(() => {
    localStorage.setItem("vox-sid", sid);
    let closed = false, retry, sock;
    setMessages([]); setConfirm(null);
    fetch(`/api/sessions/${sid}`).then((r) => r.json()).then((rows) => !closed && setMessages(rows.map(rowToMsg).filter(Boolean))).catch(() => {});
    refresh();

    const handle = (e) => {
      const ev = JSON.parse(e.data);
      if (ev.type === "status") setState({ name: ev.state, detail: ev.detail || "", tool: ev.tool || "" });
      else if (ev.type === "delta") {
        setMessages((p) => {
          const last = p[p.length - 1];
          return last?.role === "ai" && last.streaming ? [...p.slice(0, -1), { ...last, text: last.text + ev.text }]
            : [...p, { id: uid(), role: "ai", text: ev.text, streaming: true }];
        });
        cb.current.onDelta?.(ev.text);
      } else if (ev.type === "tool") { endStream(); setMessages((p) => [...p, { id: uid(), role: "tool", name: ev.name, args: ev.args, result: ev.result }]); }
      else if (ev.type === "confirmation_request") { setConfirm(ev); cb.current.onConfirm?.(ev); }
      else if (ev.type === "done") { endStream(); cb.current.onDone?.(); refresh(); }
      else if (ev.type === "error") { endStream(); setConfirm(null); setMessages((p) => [...p, { id: uid(), role: "error", text: ev.message }]); cb.current.onError?.(ev.message, true); }
    };
    const connect = () => {
      sock = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/${sid}`);
      ws.current = sock;
      sock.onopen = () => setState({ name: "idle", detail: "", tool: "" });
      sock.onclose = () => { if (!closed) { setState({ name: "connecting", detail: "", tool: "" }); retry = setTimeout(connect, 1500); } };
      sock.onmessage = handle;
    };
    connect();
    return () => { closed = true; clearTimeout(retry); sock?.close(); };
  }, [sid, refresh]);

  const send = useCallback(({ text, files, frames, provider, language }) => {
    const s = ws.current;
    if (!s || s.readyState !== 1) { cb.current.onError?.("Not connected to the VoxSight server. Retrying…"); return false; }
    const images = [...files.filter((f) => f.kind === "image").map((f) => ({ url: f.url, name: f.name })),
                    ...frames.map((f) => ({ url: f.url, name: f.tag === "camera" ? "Camera frame" : "Screen frame" }))];
    setMessages((p) => [...p, { id: uid(), role: "user", text, images, chips: files.filter((f) => f.kind !== "image").map((f) => ({ name: f.name, kind: f.kind })) }]);
    s.send(JSON.stringify({ type: "user_message", text, attachment_ids: files.map((f) => f.id), frames: frames.map(({ tag, mime, data }) => ({ tag, mime, data })), provider, language }));
    return true;
  }, []);

  const runTool = useCallback(({ name, args, provider }) => {
    const socket = ws.current;
    if (!socket || socket.readyState !== 1) {
      cb.current.onError?.("Not connected to the VoxSight server. Retrying…");
      return false;
    }
    const summary = Object.values(args).filter(Boolean).join(" ");
    setMessages((current) => [...current, { id: uid(), role: "user", text: `Run ${name}${summary ? `: ${summary}` : ""}` }]);
    setState({ name: "thinking", detail: "", tool: name });
    socket.send(JSON.stringify({ type: "tool_action", name, args, provider }));
    return true;
  }, []);

  const cancel = useCallback(() => { if (ws.current?.readyState === 1) ws.current.send(JSON.stringify({ type: "cancel" })); }, []);
  const answer = useCallback((approved) => {
    setConfirm((c) => { if (c && ws.current?.readyState === 1) ws.current.send(JSON.stringify({ type: "confirm", id: c.id, approved })); return null; });
  }, []);
  const remove = useCallback((id) => {
    fetch(`/api/sessions/${id}`, { method: "DELETE" }).then(() => { refresh(); if (id === sid) setSid(newSessionId()); }).catch(() => cb.current.onError?.("Couldn't delete that session."));
  }, [sid, refresh]);

  const busy = !["idle", "connecting"].includes(state.name);
  return { sid, messages, state, confirm, sessions, busy, connected: state.name !== "connecting",
           send, runTool, cancel, answer, remove, newSession: () => setSid(newSessionId()), switchTo: setSid };
}
