import asyncio

from app.agent import Agent
from app.providers.base import ProviderError, TextDelta, ToolCall, ToolCallEvent
from app.providers.testing import ScriptedProvider
from app.session import Session
from app.tools.base import Tool
from app.tools.builtin import default_registry


class Danger(Tool):
    name, description, requires_confirmation = "danger", "test", True
    parameters = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
    ran = False
    async def run(self, **kw):
        Danger.ran = True
        return {"ok": True}


def run(agent, session, text="hi", on_event=None, response_language="en-IN"):
    events = []
    async def send(e):
        events.append(e)
        if on_event: await on_event(e)
    asyncio.run(agent.run_turn(session, text, send, response_language=response_language))
    return events


def test_text_stream_and_memory():
    p = ScriptedProvider([[TextDelta("Hel"), TextDelta("lo")], [TextDelta("again")]])
    a, s = Agent(p, default_registry()), Session("x")
    ev = run(a, s, "one"); run(a, s, "two")
    assert "".join(e["text"] for e in ev if e["type"] == "delta") == "Hello"
    assert len(s.history) == 4 and len(p.calls[1]) == 3


def test_selected_response_language_is_applied_to_model_prompt():
    class RecordingProvider(ScriptedProvider):
        def __init__(self):
            super().__init__([[TextDelta("నమస్కారం")], [TextDelta("नमस्ते")]])
            self.prompts = []

        async def stream(self, system, messages, tools):
            self.prompts.append(system)
            async for event in super().stream(system, messages, tools):
                yield event

    provider = RecordingProvider()
    agent = Agent(provider, default_registry())
    run(agent, Session("te"), response_language="te-IN")
    run(agent, Session("hi"), response_language="hi-IN")

    assert "natural Telugu" in provider.prompts[0]
    assert "తెలుగు" in provider.prompts[0]
    assert "natural Hindi" in provider.prompts[1]
    assert "देवनागरी" in provider.prompts[1]


def test_tool_loop():
    p = ScriptedProvider([[ToolCallEvent(ToolCall("calculator", {"expression": "2*21"}))], [TextDelta("42")]])
    ev = run(Agent(p, default_registry()), Session("x"))
    assert [e for e in ev if e["type"] == "tool"][0]["result"] == {"result": 42}


def test_direct_tool_action_runs_without_a_model_call():
    provider = ScriptedProvider([])
    agent, session = Agent(provider, default_registry()), Session("direct-tool")
    events = []

    async def send(event):
        events.append(event)

    asyncio.run(agent.run_tool_action(session, "calculator", {"expression": "6*7"}, send))

    tool_event = next(event for event in events if event["type"] == "tool")
    assert tool_event["result"] == {"result": 42}
    assert any(event["type"] == "done" for event in events)
    assert provider.calls == []
    assert len(session.history) == 2


def test_confirmation_declined_and_approved():
    for approve in (False, True):
        Danger.ran = False
        reg = default_registry().register(Danger())
        p = ScriptedProvider([[ToolCallEvent(ToolCall("danger", {"x": "1"}))], [TextDelta("ok")]])
        s = Session("x")
        async def answer(e, s=s, approve=approve):
            if e["type"] == "confirmation_request": s.resolve_confirmation(e["id"], approve)
        ev = run(Agent(p, reg), s, on_event=answer)
        assert Danger.ran is approve and any(e["type"] == "confirmation_request" for e in ev)


def test_missing_args_do_not_even_ask_for_confirmation():
    Danger.ran = False
    reg = default_registry().register(Danger())
    p = ScriptedProvider([[ToolCallEvent(ToolCall("danger", {}))], [TextDelta("hm")]])
    ev = run(Agent(p, reg), Session("x"))
    assert not any(e["type"] == "confirmation_request" for e in ev) and not Danger.ran


def test_provider_error_reported_history_clean():
    s = Session("x")
    ev = run(Agent(ScriptedProvider([ProviderError("quota")]), default_registry()), s)
    assert any(e["type"] == "error" and "quota" in e["message"] for e in ev) and s.history == []


def test_transient_error_retried_once_but_permanent_is_not():
    p = ScriptedProvider([ProviderError("blip", transient=True), [TextDelta("ok")]])
    ev = run(Agent(p, default_registry()), Session("x"))
    assert any(e["type"] == "done" for e in ev) and len(p.calls) == 2
    p2 = ScriptedProvider([ProviderError("bad key"), [TextDelta("never")]])
    ev2 = run(Agent(p2, default_registry()), Session("x"))
    assert len(p2.calls) == 1 and any(e["type"] == "error" for e in ev2)


def test_model_timeout_becomes_friendly_error():
    class Slow(ScriptedProvider):
        async def stream(self, *a):
            await asyncio.sleep(5)
            yield TextDelta("x")
    ev = run(Agent(Slow([]), default_registry(), request_timeout=0.1), Session("x"))
    assert any("too long" in e.get("message", "") for e in ev)


def test_tool_timeout_and_crash_do_not_kill_turn():
    class Hang(Tool):
        name, description = "hang", "t"
        async def run(self): await asyncio.sleep(5)
    class Boom(Tool):
        name, description = "boom", "t"
        async def run(self): raise RuntimeError("kaput")
    reg = default_registry().register(Hang()).register(Boom())
    p = ScriptedProvider([[ToolCallEvent(ToolCall("hang", {})), ToolCallEvent(ToolCall("boom", {}))], [TextDelta("recovered")]])
    ev = run(Agent(p, reg, tool_timeout=0.1), Session("x"))
    res = [e["result"]["error"] for e in ev if e["type"] == "tool"]
    assert "timed out" in res[0] and "kaput" in res[1] and any(e["type"] == "done" for e in ev)
