const LANGS = [{ code: "en-IN", label: "English" }, { code: "te-IN", label: "తెలుగు" }, { code: "hi-IN", label: "हिन्दी" }];

export default function SettingsPanel({ open, onClose, s, set, voice, provider = "auto" }) {
  if (!open) return null;
  const up = (k) => (e) => set({ ...s, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.type === "range" ? +e.target.value : e.target.value });
  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" role="dialog" aria-label="Settings" onClick={(e) => e.stopPropagation()}>
        <h3>Settings</h3>
        <h4 className="settings-section">Voice</h4>
        <label className="fld">Language<select value={s.lang} onChange={up("lang")}>
          {LANGS.map((language) => <option key={language.code} value={language.code}>{language.label} · {language.code}</option>)}
        </select></label>
        <label className="opt"><input type="checkbox" checked={s.continuousListening} onChange={up("continuousListening")} /> Conversation Mode</label>
        <label className="opt"><input type="checkbox" checked={s.autoSpeak} onChange={up("autoSpeak")} /> Auto Speak Response</label>
        <label className="fld">Voice<select value={s.voiceURI} onChange={up("voiceURI")}><option value="">Automatic</option>
          {voice.voices.map((v) => <option key={v.voiceURI} value={v.voiceURI}>{v.name} ({v.lang})</option>)}</select></label>
        <details className="voice-advanced"><summary>Advanced voice settings</summary>
          <p className="dim small">Continuous Listening is active while Conversation Mode is on.</p>
          <label className="opt"><input type="checkbox" checked={s.resumeAfterInterruption} onChange={up("resumeAfterInterruption")} /> Resume listening after Stop Response</label>
          <label className="fld">Speech speed {s.rate.toFixed(2)}×<input type="range" min="0.8" max="1.5" step="0.05" value={s.rate} onChange={up("rate")} /></label>
          <label className="fld">Speech volume {Math.round(s.volume * 100)}%<input type="range" min="0" max="1" step="0.05" value={s.volume} onChange={up("volume")} /></label>
        </details>
        <h4 className="settings-section">Visual input</h4>
        <label className="opt"><input type="checkbox" checked={s.autoFrames} onChange={up("autoFrames")} /> Attach a fresh camera / screen frame to each question</label>
        <h4 className="settings-section">Provider</h4>
        <label className="fld">AI provider<select value={s.aiProvider || provider} onChange={up("aiProvider")}>
          <option value="auto">Auto (Gemini first)</option>
          <option value="gemini">Gemini</option>
          <option value="groq">Groq</option>
          <option value="openrouter">OpenRouter</option>
        </select></label>
        <p className="dim small">Speech recognition uses your browser's service (Chrome sends audio to Google). Nothing is recorded by VoxSight.</p>
        <div className="btns"><button onClick={onClose}>Done</button></div>
      </div>
    </div>
  );
}
