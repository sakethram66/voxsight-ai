import { ago } from "../lib/util.js";
import Icon from "./Icon.jsx";

export default function Sidebar({ open, onClose, sessions, sid, onNew, onPick, onDelete, health }) {
  return (
    <>
      {open && <div className="scrim" onClick={onClose} />}
      <aside className={`sidebar ${open ? "open" : ""}`}>
        <div className="brand"><h1>Vox<span>Sight</span> AI</h1></div>
        <button className="newchat" onClick={() => { onNew(); onClose(); }}><Icon name="plus" size={16} /> New session</button>
        <nav aria-label="Conversation history">
          {sessions.length === 0 && <p className="dim">No saved conversations yet.</p>}
          {sessions.map((s) => (
            <div key={s.id} className={`sess ${s.id === sid ? "on" : ""}`}>
              <button onClick={() => { onPick(s.id); onClose(); }}><span>{s.title}</span><small>{ago(s.updated)}</small></button>
              <button className="del" aria-label={`Delete ${s.title}`} onClick={() => onDelete(s.id)}><Icon name="trash" size={15} /></button>
            </div>
          ))}
        </nav>
        <div className="sidefoot">
          <small className="dim">Agent tools</small>
          <div className="toolchips">{(health?.tools || []).map((t) => <span key={t}>{t}</span>)}{health && !health.email_enabled && <span className="off" title="Set SMTP_* in backend/.env to enable">send_email (off)</span>}</div>
          <small className="dim">Stored: text history only. Images and files stay in memory.</small>
        </div>
      </aside>
    </>
  );
}
