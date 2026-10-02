import { useState } from "react";
import { ago } from "../lib/util.js";
import Icon from "./Icon.jsx";

const TOOL_FIELDS = {
  calculator: [{ name: "expression", label: "Expression", required: true }],
  web_search: [{ name: "query", label: "Search query", required: true }],
  save_note: [
    { name: "title", label: "Title", required: true },
    { name: "content", label: "Note", required: true, multiline: true },
  ],
  send_email: [
    { name: "to", label: "Recipient", required: true, type: "email" },
    { name: "subject", label: "Subject", required: true },
    { name: "body", label: "Message", required: true, multiline: true },
  ],
};

export default function Sidebar({ open, onClose, sessions, sid, onNew, onPick, onDelete, health,
  onRunTool, busy, connected }) {
  const [activeTool, setActiveTool] = useState("");
  const [values, setValues] = useState({});
  const startTool = (name) => {
    if (busy || !connected) return;
    if (!TOOL_FIELDS[name]) {
      onRunTool(name, {});
      onClose();
      return;
    }
    setActiveTool(name);
    setValues(Object.fromEntries(TOOL_FIELDS[name].map((field) => [field.name, ""])));
  };
  const submitTool = (event) => {
    event.preventDefault();
    if (onRunTool(activeTool, values)) {
      setActiveTool("");
      onClose();
    }
  };

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
          <div className="toolchips">{(health?.tools || []).map((tool) => <button key={tool} className="toolchip" type="button"
            onClick={() => startTool(tool)} disabled={busy || !connected} aria-label={`Run ${tool}`} title={`Run ${tool}`}>
            {tool}
          </button>)}{health && !health.email_enabled && <button className="toolchip off" type="button" disabled
            title="Set SMTP_* in backend/.env to enable">send_email (off)</button>}</div>
          <small className="dim">Stored: text history only. Images and files stay in memory.</small>
        </div>
      </aside>
      {activeTool && <div className="overlay" onClick={() => setActiveTool("")}>
        <form className="modal" role="dialog" aria-modal="true" aria-label={`Run ${activeTool}`} onSubmit={submitTool}
          onClick={(event) => event.stopPropagation()}>
          <h3>Run {activeTool}</h3>
          {TOOL_FIELDS[activeTool].map((field) => {
            const props = { required: field.required, type: field.type || "text", value: values[field.name], autoFocus: field === TOOL_FIELDS[activeTool][0],
              onChange: (event) => setValues((current) => ({ ...current, [field.name]: event.target.value })) };
            return <label className="fld" key={field.name}>{field.label}
              {field.multiline ? <textarea {...props} rows={5} /> : <input {...props} />}
            </label>;
          })}
          <div className="btns"><button type="button" className="ghost" onClick={() => setActiveTool("")}>Cancel</button>
            <button type="submit" disabled={busy || !connected}>Run tool</button></div>
        </form>
      </div>}
    </>
  );
}
