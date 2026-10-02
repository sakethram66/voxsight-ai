import asyncio
import logging

from .providers.base import (Done, LLMProvider, MediaPart, Message, ProviderError,
                             TextDelta, ToolCallEvent, ToolResult)
from .tools.base import ToolRegistry

log = logging.getLogger("voxsight.agent")
MAX_STEPS = 6
_RESPONSE_LANGUAGE_PROMPTS = {
    "en-IN": "Respond in natural English.",
    "te-IN": "Respond in natural Telugu (తెలుగు script). Keep the answer concise and conversational.",
    "hi-IN": "Respond in natural Hindi (देवनागरी script). Keep the answer concise and conversational.",
}

SYSTEM_PROMPT = """You are VoxSight AI, a real-time voice and multimodal assistant. The user talks to you
and can show you things; you hear, see, understand, and act.

How input reaches you:
- The user's words come from speech recognition (or typing), so expect small transcription errors; infer intent.
- Visual inputs are labelled: [Image: name], [PDF document: name], [Camera snapshot (live)], [Screen capture (live)].
  The newest camera/screen frame is what the user currently sees. Text documents appear inline.
- Words like "this", "here", "it", "that error" refer to the most recent thing shown or discussed. Do not ask
  the user to re-upload something that is already in the conversation.

Style: your answers are spoken aloud. Be concise and natural (usually 1-4 sentences). For step-by-step fixes give
short numbered steps. Put code in fenced blocks and say it is shown on screen. No tables.

Honesty: describe only what is actually visible or in the document. If an image is blurry, cropped or unreadable,
say so instead of guessing. If you need one missing detail, ask one short question.

Tools: use them when they help (exact math -> calculator; current facts -> web_search; time -> get_datetime).
save_note and send_email are real actions and the user must confirm them first. Never say an action happened
unless its tool result says so; if the user cancelled or it failed, say that plainly."""


def describe(attachments) -> str:
    n_img = sum(1 for a in attachments if a.kind == "image" and a.tag == "upload")
    parts = []
    if n_img: parts.append(f"Analyzing {n_img} image{'s' if n_img > 1 else ''}")
    if any(a.kind == "pdf" for a in attachments): parts.append("Reading PDF")
    if any(a.kind == "text" for a in attachments): parts.append("Reading document")
    if any(a.tag == "camera" for a in attachments): parts.append("Looking at camera frame")
    if any(a.tag == "screen" for a in attachments): parts.append("Looking at screen")
    return " · ".join(parts)


def build_user_message(text: str, attachments) -> Message:
    """Context fusion: the words, images/frames, PDFs and document text go into ONE user message."""
    if not attachments:
        return Message("user", text)
    media, docs = [], []
    for a in attachments:
        if a.kind == "text":
            docs.append(f"[Attached document: {a.name}]\n{a.text}\n[End of document: {a.name}]")
        else:
            label = a.name if a.tag != "upload" else (f"PDF document: {a.name}" if a.kind == "pdf" else f"Image: {a.name}")
            media.append(MediaPart(a.mime, a.data, name=label, tag=a.tag))
    body = "\n\n".join(docs + [f"User request (spoken or typed): {text}"])
    return Message("user", body, media=media)


class Agent:
    def __init__(self, provider: LLMProvider, tools: ToolRegistry, request_timeout: float = 60, tool_timeout: float = 30):
        self.provider, self.tools = provider, tools
        self.request_timeout, self.tool_timeout = request_timeout, tool_timeout

    async def run_turn(self, session, text: str, send, attachments=(), provider_override=None,
                       response_language="en-IN"):
        """One user turn: fuse -> model -> tools -> model ... History is committed only if the turn
        completes, so a cancel/failure never leaves a dangling tool call in memory."""
        turn = [build_user_message(text, attachments)]
        records = [{"role": "user", "text": text,
                    "meta": {"attachments": [{"name": a.name, "kind": a.kind} for a in attachments]}}]
        detail = describe(attachments)
        provider_token = None
        provider_started = False
        try:
            provider_token = self.provider.begin_turn(provider_override)
            provider_started = True
            for step in range(MAX_STEPS):
                first = step == 0 and detail
                await send({"type": "status", "state": "analyzing" if first else "thinking",
                            "detail": detail if first else ""})
                buf, calls, raw = await self._call_model(session, turn, send, response_language)
                if buf:
                    records.append({"role": "ai", "text": buf, "meta": {}})
                turn.append(Message("model", buf, tool_calls=calls, raw=raw))
                if not calls:
                    session.commit(turn, records)
                    await send({"type": "done"})
                    return
                turn.append(Message("user", tool_results=await self._run_tools(session, calls, send, records)))
            await send({"type": "error", "message": "Stopped: too many tool steps for one request."})
        except asyncio.CancelledError:
            raise
        except ProviderError as e:
            await send({"type": "error", "message": str(e)})
        except Exception:
            log.exception("turn failed")
            await send({"type": "error", "message": "Something went wrong handling that request."})
        finally:
            if provider_started:
                self.provider.end_turn(provider_token)
            await send({"type": "status", "state": "idle"})

    async def _call_model(self, session, turn, send, response_language="en-IN"):
        for attempt in (0, 1):
            buf, calls, raw, started = "", [], None, False
            try:
                async with asyncio.timeout(self.request_timeout):
                    specs = self.tools.specs()
                    filter_tools = getattr(self.provider, "tools_for_turn", None)
                    if filter_tools:
                        specs = filter_tools(specs)
                    language_prompt = _RESPONSE_LANGUAGE_PROMPTS.get(response_language, _RESPONSE_LANGUAGE_PROMPTS["en-IN"])
                    system = f"{SYSTEM_PROMPT}\n\nResponse language: {language_prompt}"
                    async for ev in self.provider.stream(system, session.model_history(turn), specs):
                        if isinstance(ev, TextDelta):
                            if not started:
                                await send({"type": "status", "state": "generating"})
                            started = True
                            buf += ev.text
                            await send({"type": "delta", "text": ev.text})
                        elif isinstance(ev, ToolCallEvent):
                            started = True
                            calls.append(ev.call)
                        elif isinstance(ev, Done):
                            raw = ev.raw
                return buf, calls, raw
            except TimeoutError:
                raise ProviderError("The AI took too long to respond. Please try again.")
            except ProviderError as e:
                if attempt == 0 and e.transient and not started:  # one quiet retry, only before any output
                    await asyncio.sleep(0.8)
                    continue
                raise

    async def _run_tools(self, session, calls, send, records) -> list:
        results = []
        for c in calls:
            tool = self.tools.get(c.name)
            missing = [k for k in (tool.parameters.get("required", []) if tool else []) if k not in c.args]
            if tool is None:
                out = {"error": f"Unknown tool '{c.name}'."}
            elif missing:
                out = {"error": f"Missing arguments: {', '.join(missing)}."}
            else:
                approved = True
                if tool.requires_confirmation:
                    await send({"type": "status", "state": "awaiting_confirmation", "tool": c.name})
                    approved = await session.request_confirmation(send, tool, c.args)
                if not approved:
                    out = {"error": "User declined or did not respond. The action was NOT performed."}
                else:
                    await send({"type": "status", "state": "using_tool", "tool": c.name})
                    try:
                        out = await asyncio.wait_for(tool.run(**c.args), self.tool_timeout)
                    except asyncio.TimeoutError:
                        out = {"error": "Tool timed out."}
                    except Exception as e:  # a tool failure must not kill the turn
                        out = {"error": f"Tool failed: {e}"}
            await send({"type": "tool", "name": c.name, "args": c.args, "result": out})
            records.append({"role": "tool", "text": c.name, "meta": {"args": c.args, "result": out}})
            results.append(ToolResult(c.name, out, c.id))
        return results
