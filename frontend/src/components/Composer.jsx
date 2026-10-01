import { useRef } from "react";
import Icon from "./Icon.jsx";
import Waveform from "./Waveform.jsx";

const VOICE_LABELS = {
  ready: "Click and hold to speak",
  listening: "Listening…",
  reconnecting: "Reconnecting…",
  processing: "Thinking…",
  speaking: "VoxSight is responding…",
  paused: "Paused",
  error: "Voice unavailable",
};

export default function Composer({ text, setText, files, setFiles, addFiles, onSend, onStop, busy, connected, capture,
  voice, continuousListening, setContinuousListening, language, setLanguage, onStopVoice }) {
  const pick = useRef(null);
  const pointerActive = useRef(false);
  const uploading = files.some((f) => f.status === "uploading");
  const beginPushToTalk = (event) => {
    if (continuousListening || !voice.supported) return;
    pointerActive.current = true;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    void voice.start({ continuous: false });
  };
  const finishPushToTalk = () => {
    if (!pointerActive.current) return;
    pointerActive.current = false;
    voice.stop({ commit: true, keepContinuous: continuousListening });
  };
  const keyboardPushToTalk = (event) => {
    if (event.detail !== 0 || continuousListening) return;
    if (voice.listening) voice.stop({ commit: true });
    else void voice.start({ continuous: false });
  };
  const voiceMode = ["listening", "reconnecting"].includes(voice.state) ? "listening"
    : voice.state === "speaking" ? "speaking"
      : ["processing", "reconnecting"].includes(voice.state) ? "busy" : "idle";
  const voiceStatus = !voice.supported ? voice.unsupportedMessage
    : voice.state === "error" ? (voice.error || "Voice unavailable") : VOICE_LABELS[voice.state] || "Ready";
  return (
    <footer className="composer">
      {files.length > 0 && (
        <ul className="pending">
          {files.map((f) => (
            <li key={f.key} className={f.status}>
              {f.url ? <img src={f.url} alt="" /> : <Icon name="file" size={16} />}
              <span>{f.name}{f.status === "uploading" ? " · uploading…" : f.status === "error" ? ` · ${f.error}` : ""}</span>
              <button aria-label={`Remove ${f.name}`} onClick={() => setFiles((p) => p.filter((x) => x.key !== f.key))}><Icon name="x" size={14} /></button>
            </li>
          ))}
        </ul>
      )}
      <div className={`voice-controls ${voice.state === "listening" ? "voice-controls-listening" : ""}`}>
        <button className={`voice-mic ${voice.state}`} type="button" disabled={continuousListening || !voice.supported}
          onPointerDown={beginPushToTalk} onPointerUp={finishPushToTalk} onPointerCancel={() => voice.stop()}
          onClick={keyboardPushToTalk} aria-label={voice.listening ? "Release to send voice message" : "Start voice conversation"}
          title={voice.supported ? "Press and hold to speak" : "Speech recognition is unavailable in this browser"}>
          <Icon name="mic" size={20} />
        </button>
        <div className="voice-feedback" aria-live="polite">
          <div className="voice-feedback-top"><b>{voiceStatus}</b><span>{language === "te-IN" ? "తెలుగు" : language === "hi-IN" ? "हिन्दी" : "English"}</span></div>
          <Waveform mode={voiceMode} analyser={voice.analyser} />
          <span className={`voice-transcript ${voice.interim ? "live" : ""}`}>
            {voice.interim || (voice.supported ? (continuousListening ? "Continuous Listening" : "Your transcript will appear here") : "You can still type or attach media.")}
          </span>
        </div>
        <label className="voice-language">Language
          <select aria-label="Voice language" value={language} onChange={(event) => setLanguage(event.target.value)}>
            <option value="en-IN">English</option>
            <option value="te-IN">తెలుగు</option>
            <option value="hi-IN">हिन्दी</option>
          </select>
        </label>
        <label className="continuous-toggle"><input type="checkbox" aria-label="Continuous Listening" checked={continuousListening}
          onChange={(event) => setContinuousListening(event.target.checked)} /> <span>Continuous Listening</span></label>
        <button className={`voice-stop ${voice.speaking || busy ? "response-active" : ""}`} type="button" onClick={onStopVoice}
          aria-label="Stop voice conversation" title={voice.speaking || busy ? "Stop Response and resume listening" : "Stop voice conversation"}>
          <Icon name="stop" size={16} /><span>{voice.speaking || busy ? "Stop Response" : "Stop"}</span>
        </button>
      </div>
      <div className="row">
        <input ref={pick} type="file" hidden multiple accept="image/*,.pdf,.docx,.txt,.md,.log,.csv,.json,.py,.js,.ts,.java,.c,.cpp,.html,.css,.yaml,.yml,.xml,.sql,.sh"
               onChange={(e) => { addFiles([...e.target.files]); e.target.value = ""; }} />
        <button className="icon" onClick={() => pick.current.click()} title="Attach image, screenshot, PDF or text file (you can also paste a screenshot)" aria-label="Attach file"><Icon name="clip" /></button>
        <button className={`icon ${capture.camera ? "active" : ""}`} onClick={capture.toggleCamera} title={capture.camera ? "Stop camera" : "Start camera"} aria-pressed={!!capture.camera}><Icon name="camera" /></button>
        <button className={`icon ${capture.screen ? "active" : ""}`} onClick={capture.toggleScreen} title={capture.screen ? "Stop sharing" : "Share screen"} aria-pressed={!!capture.screen}><Icon name="screen" /></button>
        <input className="text" value={text} onChange={(e) => setText(e.target.value)} placeholder="Ask about what you've shown…"
               onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && onSend()} aria-label="Message" />
        {busy ? <button className="send stop" onClick={onStop} aria-label="Stop"><Icon name="stop" /></button>
          : <button className="send" onClick={() => onSend()} disabled={!connected || uploading || (!text.trim() && !files.some((f) => f.status === "ready"))} aria-label="Send"><Icon name="send" /></button>}
      </div>
    </footer>
  );
}
