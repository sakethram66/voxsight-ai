import Icon from "./Icon.jsx";
import Waveform from "./Waveform.jsx";

export default function Stage({ voice, mode, onMic, capture, autoFrames }) {
  const hint = voice.interim || (voice.listening ? "Listening… go ahead" : "Tap the mic, or type below. Try: “VoxSight, look at this and tell me what's wrong.”");
  const label = voice.listening ? "Stop listening" : voice.speaking ? "Interrupt and talk" : "Start talking";
  return (
    <section className="stage">
      <div className="voicebar">
        <button className={`orb ${mode}`} onClick={onMic} aria-label={label} title={label} disabled={!voice.supported}>
          <Icon name={voice.listening ? "stop" : "mic"} size={26} />
        </button>
        <div className="wavebox">
          <Waveform mode={mode} analyser={voice.analyser} />
          <p className={`transcript ${voice.interim ? "live" : ""}`} aria-live="polite">{voice.supported ? hint : "Voice input isn't supported in this browser — use Chrome, Edge or Safari. Typing works everywhere."}</p>
        </div>
      </div>
      {(capture.camera || capture.screen) && (
        <div className="tiles">
          {capture.camera && (
            <figure className="tile"><video ref={capture.camRef} autoPlay muted playsInline />
              <figcaption><b className="live"><i />CAMERA LIVE</b><button onClick={() => capture.stop("camera")}>Stop camera</button></figcaption></figure>
          )}
          {capture.screen && (
            <figure className="tile"><video ref={capture.scrRef} autoPlay muted playsInline />
              <figcaption><b className="live"><i />SHARING SCREEN</b><button onClick={() => capture.stop("screen")}>Stop sharing</button></figcaption></figure>
          )}
          <p className="tilehint">{autoFrames ? "A fresh frame is attached to each question you ask." : "Live frames are off in Settings, so they won't be sent."}</p>
        </div>
      )}
    </section>
  );
}
