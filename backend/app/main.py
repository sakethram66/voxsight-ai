import asyncio
import json
import logging
import re
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agent import Agent
from .config import Settings, settings as default_settings
from .providers import get_provider
from .providers.base import ProviderError
from .session import SessionStore
from .speech import synthesize_speech
from .store import Store
from .tools.builtin import default_registry
from .uploads import UploadError, classify, frame_to_attachment

logging.basicConfig(level=logging.INFO)
SID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
DEFAULT_PROMPT = "Please look at what I've shared and tell me what stands out."
DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
_RESPONSE_LANGUAGES = {"en-IN", "te-IN", "hi-IN"}


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1600)
    language: str


def create_app(s: Settings = default_settings, agent: Agent = None, store: Store = None) -> FastAPI:
    app = FastAPI(title="VoxSight AI")
    app.add_middleware(CORSMiddleware, allow_origins=list(s.cors_origins), allow_methods=["*"], allow_headers=["*"])
    store = store or Store(s.db_path)
    sessions = SessionStore(store)
    agent_error = None
    if agent is None:
        try:
            provider = get_provider(s)
            agent = Agent(provider, default_registry(provider, s), s.request_timeout, s.tool_timeout)
        except ProviderError as e:  # server still boots; the UI shows the config problem
            agent_error = str(e)

    def check_sid(sid: str):
        if not SID_RE.match(sid):
            raise HTTPException(400, "Invalid session id.")

    @app.get("/api/health")
    def health():
        return {"ok": agent is not None, "error": agent_error, "provider": s.provider,
            "available_providers": agent.provider.available_names if agent and hasattr(agent.provider, "available_names") else [],
            "model": s.gemini_model,
                "tools": agent.tools.names() if agent else [], "email_enabled": s.smtp_ready}

    @app.post("/api/speech")
    async def speech(payload: SpeechRequest):
        if payload.language not in {"te-IN", "hi-IN"}:
            raise HTTPException(422, "Speech language must be Telugu or Hindi.")
        try:
            audio = await synthesize_speech(payload.text, payload.language)
        except Exception as exc:
            log.warning("speech synthesis failed (%s)", type(exc).__name__)
            raise HTTPException(502, "Hindi/Telugu speech is temporarily unavailable. Check the server connection.") from exc
        return Response(audio, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})

    @app.get("/api/sessions")
    def list_sessions():
        return store.sessions()

    @app.get("/api/sessions/{sid}")
    def get_session(sid: str):
        check_sid(sid)
        return store.messages(sid)

    @app.delete("/api/sessions/{sid}")
    def delete_session(sid: str):
        check_sid(sid)
        store.delete(sid)
        sessions.drop(sid)
        return {"deleted": True}

    @app.post("/api/sessions/{sid}/attachments")
    async def upload(sid: str, file: UploadFile):
        check_sid(sid)
        cap = 20 * 1024 * 1024
        data = await file.read(cap + 1)
        try:
            if len(data) > cap:
                raise UploadError(413, "File is too large (max 20 MB).")
            a = classify(file.filename or "file", data, s)
            sessions.get(sid).add_attachment(a)
        except UploadError as e:
            raise HTTPException(e.status, e.message)
        except ValueError as e:
            raise HTTPException(429, str(e))
        return {"id": a.id, "name": a.name, "kind": a.kind, "mime": a.mime, "size": len(data)}

    @app.websocket("/ws/{sid}")
    async def ws_endpoint(ws: WebSocket, sid: str):
        if not SID_RE.match(sid):
            await ws.close(code=4400)
            return
        await ws.accept()
        session = sessions.get(sid)

        async def send(ev: dict):
            try:
                await ws.send_json(ev)
            except Exception:
                pass  # client gone; never crash the agent

        task = None
        try:
            while True:
                try:
                    msg = json.loads(await ws.receive_text())
                except json.JSONDecodeError:
                    await send({"type": "error", "message": "Malformed message."})
                    continue
                kind = msg.get("type") if isinstance(msg, dict) else None
                if kind == "user_message":
                    if agent is None:
                        await send({"type": "error", "message": agent_error or "Agent unavailable."})
                        continue
                    if task and not task.done():
                        await send({"type": "error", "message": "Still working on the previous request."})
                        continue
                    provider_override = msg.get("provider") if isinstance(msg, dict) else None
                    if provider_override is not None and provider_override not in {"auto", "gemini", "groq", "openrouter"}:
                        await send({"type": "error", "message": "Unknown AI provider selection."})
                        continue
                    response_language = msg.get("language", "en-IN")
                    if response_language not in _RESPONSE_LANGUAGES:
                        await send({"type": "error", "message": "Unknown response language selection."})
                        continue
                    text = str(msg.get("text") or "").strip()
                    ids, frames = msg.get("attachment_ids") or [], msg.get("frames") or []
                    try:
                        if not isinstance(ids, list) or not isinstance(frames, list):
                            raise UploadError(400, "Malformed attachments.")
                        atts = []
                        for i in ids[:10]:
                            a = session.attachments.get(i)
                            if a is None:
                                raise UploadError(404, "An attachment is no longer available. Please upload it again.")
                            atts.append(a)
                        atts += [frame_to_attachment(f, s) for f in frames[:2]]
                    except UploadError as e:
                        await send({"type": "error", "message": e.message})
                        continue
                    if text or atts:
                        task = asyncio.create_task(agent.run_turn(
                            session, text or DEFAULT_PROMPT, send, atts,
                            provider_override=provider_override, response_language=response_language))
                elif kind == "tool_action":
                    if agent is None:
                        await send({"type": "error", "message": agent_error or "Agent unavailable."})
                        continue
                    if task and not task.done():
                        await send({"type": "error", "message": "Still working on the previous request."})
                        continue
                    provider_override = msg.get("provider")
                    if provider_override is not None and provider_override not in {"auto", "gemini", "groq", "openrouter"}:
                        await send({"type": "error", "message": "Unknown AI provider selection."})
                        continue
                    task = asyncio.create_task(agent.run_tool_action(
                        session, msg.get("name"), msg.get("args", {}), send, provider_override))
                elif kind == "confirm":
                    session.resolve_confirmation(str(msg.get("id", "")), bool(msg.get("approved")))
                elif kind == "cancel" and task and not task.done():
                    task.cancel()  # wait for the turn to unwind so the next message never races it
                    await asyncio.gather(task, return_exceptions=True)
                    await send({"type": "status", "state": "idle"})
        except WebSocketDisconnect:
            pass
        finally:
            if task and not task.done():
                task.cancel()

    if DIST.exists():  # single-process demo: `npm run build` once, then only run uvicorn
        app.mount("/", StaticFiles(directory=DIST, html=True), name="ui")
    return app


app = create_app()
