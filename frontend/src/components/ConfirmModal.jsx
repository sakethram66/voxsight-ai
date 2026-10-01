import { useEffect, useRef } from "react";

export default function ConfirmModal({ req, onAnswer }) {
  const cancel = useRef(null);
  useEffect(() => { if (req) cancel.current?.focus(); }, [req]);
  if (!req) return null;
  return (
    <div className="overlay" role="alertdialog" aria-modal="true" aria-labelledby="cf-t" onKeyDown={(e) => e.key === "Escape" && onAnswer(false)}>
      <div className="modal">
        <h3 id="cf-t">Action requires confirmation</h3>
        <p className="dim">VoxSight wants to run <code>{req.tool}</code>. Nothing happens unless you confirm.</p>
        <pre>{req.summary}</pre>
        <div className="btns">
          <button ref={cancel} className="ghost" onClick={() => onAnswer(false)}>Cancel</button>
          <button onClick={() => onAnswer(true)}>Confirm</button>
        </div>
      </div>
    </div>
  );
}
