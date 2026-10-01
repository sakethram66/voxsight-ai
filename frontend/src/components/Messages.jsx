import { useEffect, useRef } from "react";

function inline(text) {
  return text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g).map((p, i) =>
    p.length > 2 && p.startsWith("`") && p.endsWith("`") ? <code key={i}>{p.slice(1, -1)}</code>
    : p.length > 4 && p.startsWith("**") && p.endsWith("**") ? <strong key={i}>{p.slice(2, -2)}</strong> : p);
}
function Markdown({ text }) {
  return text.split("```").map((seg, i) => i % 2
    ? <pre key={i}><code>{seg.replace(/^[\w+-]*\n/, "")}</code></pre>
    : <div key={i} className="md">{seg.split("\n").map((l, j) => (l.trim() ? <p key={j}>{inline(l)}</p> : null))}</div>);
}
const short = (v, n = 220) => { const s = typeof v === "string" ? v : JSON.stringify(v); return s.length > n ? s.slice(0, n) + "…" : s; };

function ToolCard({ m }) {
  const r = m.result || {};
  return (
    <div className="msg tool">
      <div><b>{m.name}</b> <code>{short(m.args, 120)}</code></div>
      {r.error ? <div className="bad">{r.error}</div>
        : m.name === "web_search" && r.sources ? <div>{r.sources.map((s) => <a key={s.url} href={s.url} target="_blank" rel="noreferrer noopener">{s.title}</a>)}</div>
        : r.saved ? <div className="good">Saved to {r.path}</div>
        : r.sent ? <div className="good">Email sent to {r.to}</div>
        : <code>{short(r)}</code>}
    </div>
  );
}

export default function Messages({ messages }) {
  const end = useRef(null);
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);
  return (
    <main className="messages" aria-live="polite">
      {messages.length === 0 && (
        <div className="empty"><h2>HEAR IT. SEE IT.<br />UNDERSTAND IT. ACT ON IT.</h2>
          <p>Talk to VoxSight while showing it a screenshot, PDF, your camera or your screen. Follow-up questions keep the same context.</p></div>
      )}
      {messages.map((m) => m.role === "tool" ? <ToolCard key={m.id} m={m} /> : (
        <div key={m.id} className={`msg ${m.role}`}>
          {m.images?.length > 0 && <div className="thumbs">{m.images.map((im, i) => <img key={i} src={im.url} alt={im.name} title={im.name} />)}</div>}
          {m.chips?.length > 0 && <div className="chips">{m.chips.map((c, i) => <span key={i} className="chip">{c.name}</span>)}</div>}
          {m.role === "ai" ? <><Markdown text={m.text} />{m.streaming && <b className="cursor" />}</> : m.text}
        </div>
      ))}
      <div ref={end} />
    </main>
  );
}
