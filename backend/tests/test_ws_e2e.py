"""End-to-end through the real WebSocket/HTTP layer with a scripted model."""
import base64
import smtplib

from fastapi.testclient import TestClient

from app.agent import Agent
from app.config import Settings
from app.main import create_app
from app.providers.base import TextDelta, ToolCall, ToolCallEvent
from app.providers.testing import ScriptedProvider
from app.store import Store
from app.tools.builtin import default_registry
from .helpers import png_bytes

SID = "sess-e2e-0001"


def make(script, tmp_path, **kw):
    s = Settings(notes_dir=str(tmp_path / "notes"), **kw)
    p = ScriptedProvider(script)
    app = create_app(s, agent=Agent(p, default_registry(p, s)), store=Store(":memory:"))
    return TestClient(app), p, s


def collect(ws):
    evs = []
    while True:
        e = ws.receive_json(); evs.append(e)
        if e["type"] == "status" and e["state"] == "idle" and any(x["type"] in ("done", "error") for x in evs):
            return evs


def media_names(call):
    return [p.name for m in call for p in m.media]


def test_screenshot_then_followup_remembers_it_and_shows_status(tmp_path):
    c, p, _ = make([[TextDelta("It's a ZeroDivisionError.")], [TextDelta("Guard against zero.")]], tmp_path)
    att = c.post(f"/api/sessions/{SID}/attachments", files={"file": ("err.png", png_bytes(), "image/png")}).json()
    with c.websocket_connect(f"/ws/{SID}") as ws:
        ws.send_json({"type": "user_message", "text": "why am I getting this?", "attachment_ids": [att["id"]]})
        ev1 = collect(ws)
        ws.send_json({"type": "user_message", "text": "how do I fix it?"})   # NO new attachment
        ev2 = collect(ws)
    assert any(e.get("state") == "analyzing" and "image" in e["detail"] for e in ev1)
    assert media_names(p.calls[0]) == ["Image: err.png"]
    assert media_names(p.calls[1]) == ["Image: err.png"], "follow-up must still see the screenshot"
    assert "User request" in p.calls[0][0].text and any(e["type"] == "done" for e in ev2)


def test_live_frames_replace_older_frames(tmp_path):
    c, p, _ = make([[TextDelta("a")], [TextDelta("b")]], tmp_path)
    fr = {"tag": "camera", "mime": "image/png", "data": base64.b64encode(png_bytes()).decode()}
    with c.websocket_connect(f"/ws/{SID}") as ws:
        for q in ("what is this?", "and now?"):
            ws.send_json({"type": "user_message", "text": q, "frames": [fr]}); collect(ws)
    assert media_names(p.calls[1]).count("Camera snapshot (live)") == 1


def test_bad_inputs_do_not_crash_socket(tmp_path):
    c, p, _ = make([[TextDelta("still alive")]], tmp_path)
    with c.websocket_connect(f"/ws/{SID}") as ws:
        ws.send_text("not json")
        assert ws.receive_json()["type"] == "error"
        ws.send_json({"type": "user_message", "text": "x", "attachment_ids": ["nope"]})
        assert "no longer available" in ws.receive_json()["message"]
        ws.send_json({"type": "user_message", "text": "hello"})
        assert any(e["type"] == "done" for e in collect(ws))


def note_flow(tmp_path, approve):
    call = ToolCall("save_note", {"title": "Fix", "content": "guard zero"})
    c, p, s = make([[ToolCallEvent(call)], [TextDelta("done")]], tmp_path)
    with c.websocket_connect(f"/ws/{SID}") as ws:
        ws.send_json({"type": "user_message", "text": "remember this"})
        seen = []
        while True:
            e = ws.receive_json(); seen.append(e)
            if e["type"] == "confirmation_request":
                assert not (tmp_path / "notes").exists(), "nothing may run before Confirm"
                ws.send_json({"type": "confirm", "id": e["id"], "approved": approve})
            if e["type"] == "done": break
    return seen, p, tmp_path / "notes"


def test_confirmed_action_really_writes_file(tmp_path):
    seen, p, notes = note_flow(tmp_path, True)
    files = list(notes.glob("*.md"))
    assert len(files) == 1 and "guard zero" in files[0].read_text()
    res = [e for e in seen if e["type"] == "tool"][0]["result"]
    assert res["saved"] and res["path"] == str(files[0])


def test_cancelled_action_does_nothing_and_model_is_told(tmp_path):
    seen, p, notes = note_flow(tmp_path, False)
    assert not notes.exists()
    told = p.calls[1][-1].tool_results[0].response["error"]
    assert "NOT performed" in told


def test_email_action_uses_smtp_only_after_confirm(tmp_path, monkeypatch):
    sent = []
    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def starttls(self): pass
        def login(self, *a): pass
        def send_message(self, m): sent.append(m)
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    call = ToolCall("send_email", {"to": "a@b.co", "subject": "Hi", "body": "Body"})
    c, p, s = make([[ToolCallEvent(call)], [TextDelta("sent")]], tmp_path, smtp_host="h", smtp_from="me@x.io")
    assert "send_email" in c.get("/api/health").json()["tools"]
    with c.websocket_connect(f"/ws/{SID}") as ws:
        ws.send_json({"type": "user_message", "text": "email a@b.co"})
        while True:
            e = ws.receive_json()
            if e["type"] == "confirmation_request":
                assert not sent and "a@b.co" in e["summary"]
                ws.send_json({"type": "confirm", "id": e["id"], "approved": True})
            if e["type"] == "done": break
    assert len(sent) == 1 and sent[0]["To"] == "a@b.co"


def test_web_search_tool_returns_sources(tmp_path):
    c, p, _ = make([[ToolCallEvent(ToolCall("web_search", {"query": "acme"}))], [TextDelta("ok")]], tmp_path)
    with c.websocket_connect(f"/ws/{SID}") as ws:
        ws.send_json({"type": "user_message", "text": "find acme"})
        tool = [e for e in collect(ws) if e["type"] == "tool"][0]
    assert tool["result"]["sources"][0]["url"].startswith("https://")
