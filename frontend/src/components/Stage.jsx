export default function Stage({ capture, autoFrames }) {
  return (
    <section className="stage">
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
