const LANGS = ["en-US", "en-GB", "en-IN", "hi-IN", "es-ES", "fr-FR", "de-DE", "pt-BR", "ja-JP"];

export default function SettingsPanel({ open, onClose, s, set, voice, provider = "auto" }) {
  if (!open) return null;
  const up = (k) => (e) => set({ ...s, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.type === "range" ? +e.target.value : e.target.value });
  const langs = LANGS.includes(s.lang) ? LANGS : [s.lang, ...LANGS];
  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" role="dialog" aria-label="Settings" onClick={(e) => e.stopPropagation()}>
        <h3>Settings</h3>
        <label className="fld">AI provider<select value={s.aiProvider || provider} onChange={up("aiProvider")}>
          <option value="auto">Auto (Gemini first)</option>
          <option value="gemini">Gemini</option>
          <option value="groq">Groq</option>
          <option value="openrouter">OpenRouter</option>
        </select></label>
        <label className="opt"><input type="checkbox" checked={s.tts} onChange={up("tts")} /> Speak replies aloud</label>
        <label className="opt"><input type="checkbox" checked={s.handsFree} onChange={up("handsFree")} /> Hands-free conversation (always listening; talk over the AI to interrupt)</label>
        <p className="dim small">Hands-free works best with headphones — speakers can make the AI hear itself.</p>
        <label className="opt"><input type="checkbox" checked={s.autoFrames} onChange={up("autoFrames")} /> Attach a fresh camera / screen frame to each question</label>
        <label className="fld">Speech language<select value={s.lang} onChange={up("lang")}>{langs.map((l) => <option key={l}>{l}</option>)}</select></label>
        <label className="fld">Voice<select value={s.voiceURI} onChange={up("voiceURI")}><option value="">Automatic</option>
          {voice.voices.map((v) => <option key={v.voiceURI} value={v.voiceURI}>{v.name} ({v.lang})</option>)}</select></label>
        <label className="fld">Speaking speed {s.rate.toFixed(2)}×<input type="range" min="0.8" max="1.5" step="0.05" value={s.rate} onChange={up("rate")} /></label>
        <p className="dim small">Speech recognition uses your browser's service (Chrome sends audio to Google). Nothing is recorded by VoxSight.</p>
        <div className="btns"><button onClick={onClose}>Done</button></div>
      </div>
    </div>
  );
}
