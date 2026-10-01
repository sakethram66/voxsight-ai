const STEPS = [["listening", "Listening"], ["analyzing", "Analyzing"], ["thinking", "Thinking"], ["using_tool", "Using tool"], ["generating", "Generating"], ["speaking", "Speaking"]];

export const LABELS = { idle: "Ready", ready: "Ready", paused: "Paused", error: "Voice unavailable", reconnecting: "Reconnecting…", connecting: "Connecting…", listening: "Listening…", analyzing: "Analyzing…", processing: "Thinking…", thinking: "Thinking…",
  using_tool: "Using tool…", generating: "Generating…", speaking: "Speaking…", awaiting_confirmation: "Waiting for your confirmation" };

export default function StatusStrip({ phase }) {
  const active = phase === "awaiting_confirmation" ? "using_tool" : phase;
  return (
    <ol className="strip" aria-label="Agent pipeline status">
      {STEPS.map(([k, label]) => <li key={k} className={k === active ? "on" : ""} aria-current={k === active}><i />{label}</li>)}
    </ol>
  );
}
