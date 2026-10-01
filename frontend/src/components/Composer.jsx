import { useRef } from "react";
import Icon from "./Icon.jsx";

export default function Composer({ text, setText, files, setFiles, addFiles, onSend, onStop, busy, connected, capture }) {
  const pick = useRef(null);
  const uploading = files.some((f) => f.status === "uploading");
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
