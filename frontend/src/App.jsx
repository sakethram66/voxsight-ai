import { useCallback, useEffect, useRef, useState } from "react";
import Composer from "./components/Composer.jsx";
import ConfirmModal from "./components/ConfirmModal.jsx";
import Icon from "./components/Icon.jsx";
import Messages from "./components/Messages.jsx";
import SettingsPanel from "./components/SettingsPanel.jsx";
import Sidebar from "./components/Sidebar.jsx";
import Stage from "./components/Stage.jsx";
import StatusStrip, { LABELS } from "./components/StatusStrip.jsx";
import { useAgent } from "./hooks/useAgent.js";
import { useCapture } from "./hooks/useCapture.js";
import { useSettings } from "./hooks/useSettings.js";
import { useVoice } from "./hooks/useVoice.js";
import { uid } from "./lib/util.js";

export default function App() {
  const [settings, setSettings] = useSettings();
  const [toasts, setToasts] = useState([]);
  const [text, setText] = useState("");
  const [files, setFiles] = useState([]);
  const [drawer, setDrawer] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [health, setHealth] = useState(null);
  const voiceRef = useRef(null);

  const notify = useCallback((message) => {
    const id = uid();
    setToasts((t) => [...t.slice(-2), { id, message }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 7000);
  }, []);

  const agent = useAgent({
    onDelta: (d) => voiceRef.current?.feed(d),
    onDone: () => { voiceRef.current?.endReply(); voiceRef.current?.responseFinished(); },
    onError: (m, fromServer) => { if (fromServer) { voiceRef.current?.endReply(); voiceRef.current?.responseFinished(); } notify(m); },
    onConfirm: () => voiceRef.current?.speakNow("This action needs your confirmation."),
  });
  const capture = useCapture(notify);

  const submit = async (spoken) => {
    const fromVoice = typeof spoken === "string";
    const resumeVoice = () => { if (fromVoice) voiceRef.current?.responseFinished(); };
    const t = (typeof spoken === "string" ? spoken : text).trim();
    const ready = files.filter((f) => f.status === "ready");
    if (files.some((f) => f.status === "uploading")) { notify("Still uploading attachments…"); resumeVoice(); return; }
    if (!t && !ready.length) { resumeVoice(); return; }
    if (agent.busy) { agent.cancel(); voiceRef.current?.cancelSpeech(); } // a new question replaces the current one
    let frames = [];
    if (settings.autoFrames) {
      try { frames = await capture.grabFrames(); } catch (e) { notify(`Couldn't capture a frame: ${e.message}`); }
    }
    voiceRef.current?.beginReply();
    if (agent.send({ text: t, files: ready, frames, provider: settings.aiProvider || undefined })) {
      setText(""); setFiles((f) => f.filter((x) => x.status !== "ready"));
    } else resumeVoice();
  };

  const voice = useVoice({ settings, onFinal: (t) => submit(t), onError: notify, onBargeIn: () => agent.cancel() });
  voiceRef.current = voice;
  const previousContinuous = useRef(settings.continuousListening);
  useEffect(() => {
    if (settings.continuousListening) {
      voiceRef.current?.start({ continuous: true }).then((started) => {
        if (!started) {
          previousContinuous.current = false;
          setSettings((current) => ({ ...current, continuousListening: false }));
        }
      });
    }
    else if (previousContinuous.current) voiceRef.current?.stop();
    previousContinuous.current = settings.continuousListening;
  }, [settings.continuousListening]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (settings.continuousListening && ["error", "paused"].includes(voice.state)) {
      previousContinuous.current = false;
      setSettings((current) => ({ ...current, continuousListening: false }));
    }
  }, [settings.continuousListening, voice.state]);

  const addFiles = async (list) => {
    for (const file of list) {
      const key = uid(), name = file.name || "pasted-image.png", isImg = file.type.startsWith("image/");
      setFiles((f) => [...f, { key, name, kind: isImg ? "image" : "doc", url: isImg ? URL.createObjectURL(file) : null, status: "uploading" }]);
      try {
        const fd = new FormData();
        fd.append("file", file, name);
        const r = await fetch(`/api/sessions/${agent.sid}/attachments`, { method: "POST", body: fd });
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `Upload failed (${r.status})`);
        const j = await r.json();
        setFiles((f) => f.map((x) => (x.key === key ? { ...x, ...j, status: "ready" } : x)));
      } catch (e) {
        const msg = e instanceof TypeError ? "Couldn't reach the server." : e.message;
        setFiles((f) => f.map((x) => (x.key === key ? { ...x, status: "error", error: msg } : x)));
        notify(`${name}: ${msg}`);
      }
    }
  };

  useEffect(() => { fetch("/api/health").then((r) => r.json()).then(setHealth).catch(() => setHealth({ ok: false, error: "Can't reach the VoxSight backend on port 8000.", tools: [] })); }, []);
  useEffect(() => { setFiles([]); }, [agent.sid]);
  useEffect(() => {
    const onPaste = (e) => { const imgs = [...(e.clipboardData?.files || [])].filter((f) => f.type.startsWith("image/")); if (imgs.length) { e.preventDefault(); addFiles(imgs); } };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  });
  const phase = agent.busy ? agent.state.name : voice.state === "processing" ? "thinking" : voice.state;
  const pill = phase === "analyzing" && agent.state.detail ? `${agent.state.detail}…` : phase === "using_tool" && agent.state.tool ? `Using ${agent.state.tool}…` : LABELS[phase] || phase;
  const pillBusy = agent.busy || ["listening", "reconnecting", "speaking"].includes(voice.state);

  const stopAll = () => {
    setSettings((current) => ({ ...current, continuousListening: false }));
    voice.stop(); voice.cancelSpeech(); agent.cancel();
  };
  const stopVoice = () => {
    if (settings.continuousListening && settings.resumeAfterInterruption && (agent.busy || voice.speaking)) {
      agent.cancel();
      voice.cancelSpeech();
      voice.responseFinished();
      return;
    }
    stopAll();
  };

  return (
    <div className="shell">
      <Sidebar open={drawer} onClose={() => setDrawer(false)} sessions={agent.sessions} sid={agent.sid} health={health}
               onNew={agent.newSession} onPick={agent.switchTo} onDelete={agent.remove} />
      <div className="main">
        <header>
          <button className="icon menu" onClick={() => setDrawer(true)} aria-label="Open sessions"><Icon name="menu" /></button>
          <div className="title"><h1>Vox<span>Sight</span> AI</h1><p>HEAR IT. SEE IT. UNDERSTAND IT. ACT ON IT.</p></div>
          <div className={`pill ${pillBusy ? "busy" : ""}`} role="status"><i />{pill}</div>
          <button className="icon" onClick={() => setShowSettings(true)} aria-label="Settings"><Icon name="sliders" /></button>
        </header>
        <StatusStrip phase={phase} />
        {health && !health.ok && <div className="banner" role="alert">Setup needed: {health.error}</div>}
        <Stage capture={capture} autoFrames={settings.autoFrames} />
        <Messages messages={agent.messages} />
        <Composer text={text} setText={setText} files={files} setFiles={setFiles} addFiles={addFiles} onSend={submit}
            onStop={stopAll} busy={agent.busy} connected={agent.connected} capture={capture} voice={voice}
            continuousListening={settings.continuousListening}
            setContinuousListening={(value) => setSettings((current) => ({ ...current, continuousListening: value }))}
            language={settings.lang} setLanguage={(value) => setSettings((current) => ({ ...current, lang: value }))}
            onStopVoice={stopVoice} />
      </div>
      <ConfirmModal req={agent.confirm} onAnswer={agent.answer} />
      <SettingsPanel open={showSettings} onClose={() => setShowSettings(false)} s={settings} set={setSettings} voice={voice} provider={health?.provider || "auto"} />
      <div className="toasts" aria-live="assertive">{toasts.map((t) => <div key={t.id} className="toast" onClick={() => setToasts((x) => x.filter((y) => y.id !== t.id))}>{t.message}</div>)}</div>
    </div>
  );
}
