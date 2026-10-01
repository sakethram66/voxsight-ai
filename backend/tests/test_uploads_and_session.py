import dataclasses
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.providers.base import MediaPart, Message
from app.session import Session, compact
from app.store import Store
from app.uploads import UploadError, classify, frame_to_attachment
from .helpers import docx_bytes, png_bytes

S = Settings(max_image_mb=1, max_text_mb=1)


def test_classify_kinds():
    assert classify("a.png", png_bytes(), S).kind == "image"
    assert classify("a.pdf", b"%PDF-1.4 x", S).kind == "pdf"
    assert classify("err.log", b"Traceback...", S).kind == "text"
    assert "VoxSight" in classify("p.docx", docx_bytes(), S).text


@pytest.mark.parametrize("name,data,status", [
    ("x.exe", b"MZ\x90\x00", 415), ("empty.txt", b"", 400), ("bin.txt", b"\xff\xfe\x00\x81", 415),
    ("big.png", png_bytes() + b"0" * (2 * 1024 * 1024), 413), ("bad.docx", b"PK\x03\x04junk", 422)],
    ids=["exe", "empty-text", "binary-text", "oversized-image", "invalid-docx"])
def test_classify_rejects(name, data, status):
    with pytest.raises(UploadError) as e:
        classify(name, data, S)
    assert e.value.status == status


def test_png_named_txt_is_still_an_image_and_fake_png_is_not():
    assert classify("shot.txt", png_bytes(), S).kind == "image"
    with pytest.raises(UploadError):
        classify("fake.png", b"not really a png", S)


def test_frame_validation():
    import base64
    ok = {"tag": "camera", "mime": "image/jpeg", "data": base64.b64encode(png_bytes()).decode()}
    assert frame_to_attachment(ok, S).tag == "camera"
    for bad in ({**ok, "tag": "evil"}, {**ok, "data": "!!!"}, {**ok, "data": base64.b64encode(b"hello").decode()}, "str"):
        with pytest.raises(UploadError):
            frame_to_attachment(bad, S)


def test_compaction_keeps_latest_live_frame_and_caps_uploads():
    def m(tag, n): return Message("user", f"t{n}", media=[MediaPart("image/png", b"x", name=f"{tag}{n}", tag=tag)])
    msgs = [m("camera", 1), m("screen", 2), m("camera", 3)] + [m("upload", i) for i in range(10, 20)]
    out = compact(msgs, max_uploads=8)
    kept = [p.name for x in out for p in x.media]
    assert "camera1" not in kept and "camera3" in kept and "screen2" in kept
    assert sum(n.startswith("upload") for n in kept) == 8 and "omitted" in out[0].text
    assert msgs[0].media  # originals untouched


def test_store_rehydrates_text_history(tmp_path):
    st = Store(str(tmp_path / "t.db"))
    s = Session("abcdefgh", st)
    s.commit([], [{"role": "user", "text": "why?", "meta": {"attachments": [{"name": "e.png", "kind": "image"}]}},
                  {"role": "ai", "text": "because"}, {"role": "tool", "text": "calculator", "meta": {}}])
    h = Session("abcdefgh", st).history
    assert [x.role for x in h] == ["user", "model"] and "e.png" in h[0].text
    assert st.sessions()[0]["title"] == "why?"
    st.delete("abcdefgh"); assert st.messages("abcdefgh") == []


def test_upload_endpoint(tmp_path):
    app = create_app(S, agent=object(), store=Store(":memory:"))  # agent unused here
    c = TestClient(app)
    r = c.post("/api/sessions/session-1234/attachments", files={"file": ("shot.png", png_bytes(), "image/png")})
    assert r.status_code == 200 and r.json()["kind"] == "image"
    assert c.post("/api/sessions/session-1234/attachments", files={"file": ("a.exe", b"MZ", "x/y")}).status_code == 415
    assert c.post("/api/sessions/bad/attachments", files={"file": ("a.txt", b"hi", "text/plain")}).status_code == 400
