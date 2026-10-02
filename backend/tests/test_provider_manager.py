import asyncio
import logging
from unittest.mock import AsyncMock

import pytest

from app.providers.base import (Done, LLMProvider, Message, ProviderCapabilities,
                                ProviderError, TextDelta, ToolCall, ToolCallEvent)
from app.providers.manager import ProviderManager
from app.config import Settings
from app.providers import get_provider
from app.agent import Agent
from app.session import Session
from app.tools.builtin import default_registry


class FakeProvider(LLMProvider):
    def __init__(self, name, results=(), capabilities=None):
        self.name = name
        self.results = list(results)
        self.capabilities = capabilities or ProviderCapabilities(tools=True)
        self.calls = []

    async def stream(self, system, messages, tools):
        self.calls.append((messages, tools))
        result = self.results.pop(0) if self.results else [TextDelta(self.name), Done()]
        if isinstance(result, Exception):
            raise result
        for event in result:
            yield event


def run_stream(manager, messages=None, tools=None, mode="auto"):
    async def run():
        token = manager.begin_turn(mode)
        try:
            return [event async for event in manager.stream("sys", messages or [Message("user", "hi")], tools or [])]
        finally:
            manager.end_turn(token)
    return asyncio.run(run())


def test_gemini_success_stays_primary():
    gemini, groq, router = (FakeProvider(name) for name in ("gemini", "groq", "openrouter"))
    events = run_stream(ProviderManager({"gemini": gemini, "groq": groq, "openrouter": router}))
    assert events[0].text == "gemini"
    assert len(gemini.calls) == 1 and not groq.calls and not router.calls


@pytest.mark.parametrize("code", [429, 503])
def test_gemini_transient_error_falls_back_to_groq(code):
    gemini = FakeProvider("gemini", [ProviderError("retryable", transient=True)])
    groq, router = FakeProvider("groq"), FakeProvider("openrouter")
    events = run_stream(ProviderManager({"gemini": gemini, "groq": groq, "openrouter": router}))
    assert events[0].text == "groq"
    assert len(gemini.calls) == 1 and len(groq.calls) == 1 and not router.calls


def test_fallback_provider_keeps_search_tool_when_search_is_available_elsewhere():
    gemini = FakeProvider("gemini", [ProviderError("quota", transient=True)],
                          capabilities=ProviderCapabilities(tools=True, web_search=True))
    groq = FakeProvider("groq", capabilities=ProviderCapabilities(tools=True))
    specs = [type("Spec", (), {"name": name})() for name in ("calculator", "web_search")]
    run_stream(ProviderManager({"gemini": gemini, "groq": groq}), tools=specs)
    assert [tool.name for tool in groq.calls[0][1]] == ["calculator", "web_search"]


def test_search_falls_back_to_openrouter_even_when_chat_provider_is_groq():
    class SearchProvider(FakeProvider):
        async def grounded_search(self, query):
            return {"answer": self.name, "sources": []}

    gemini = FakeProvider("gemini", capabilities=ProviderCapabilities(web_search=True))
    async def fail_search(query):
        raise ProviderError("quota", transient=False)
    gemini.grounded_search = fail_search
    groq = FakeProvider("groq")
    router = SearchProvider("openrouter", capabilities=ProviderCapabilities(web_search=True))
    manager = ProviderManager({"gemini": gemini, "groq": groq, "openrouter": router})
    token = manager.begin_turn("groq")
    try:
        result = asyncio.run(manager.grounded_search("query"))
    finally:
        manager.end_turn(token)

    assert result["answer"] == "openrouter"


def test_groq_failure_falls_through_to_openrouter():
    providers = {
        "gemini": FakeProvider("gemini", [ProviderError("quota")]),
        "groq": FakeProvider("groq", [ProviderError("offline")]),
        "openrouter": FakeProvider("openrouter"),
    }
    events = run_stream(ProviderManager(providers))
    assert events[0].text == "openrouter"


def test_last_provider_retries_one_transient_transport_failure(monkeypatch):
    provider = FakeProvider("openrouter", [ProviderError("connection timed out", transient=True)])
    sleep = AsyncMock()
    monkeypatch.setattr("app.providers.manager.asyncio.sleep", sleep)

    events = run_stream(ProviderManager({"openrouter": provider}))

    assert events[0].text == "openrouter"
    assert len(provider.calls) == 2
    sleep.assert_awaited_once_with(0.25)


def test_all_provider_failures_are_clear_and_do_not_leak_error_payloads():
    providers = {name: FakeProvider(name, [ProviderError("request failed")])
                 for name in ("gemini", "groq", "openrouter")}
    with pytest.raises(ProviderError, match="All compatible AI providers failed"):
        run_stream(ProviderManager(providers))


def test_all_provider_failures_preserve_classified_reasons():
    providers = {
        "gemini": FakeProvider("gemini", [ProviderError("temporarily unavailable", transient=True)]),
        "groq": FakeProvider("groq", [ProviderError("rejected the request (HTTP 400).")]),
        "openrouter": FakeProvider("openrouter", [ProviderError("request failed")]),
    }

    with pytest.raises(ProviderError) as exc:
        run_stream(ProviderManager(providers))

    assert "groq: rejected the request (HTTP 400)." in str(exc.value)


@pytest.mark.parametrize("mode,expected", [
    ("gemini", "gemini"), ("groq", "groq"), ("openrouter", "openrouter"),
])
def test_manual_mode_uses_only_selected_provider(mode, expected):
    providers = {name: FakeProvider(name) for name in ("gemini", "groq", "openrouter")}
    events = run_stream(ProviderManager(providers, mode), mode=mode)
    assert events[0].text == expected
    assert len(providers[expected].calls) == 1
    assert all(not p.calls for name, p in providers.items() if name != expected)


def test_image_is_only_sent_to_vision_capable_provider():
    image = Message("user", "describe", media=[])
    from app.providers.base import MediaPart
    image.media.append(MediaPart("image/png", b"image"))
    gemini = FakeProvider("gemini", capabilities=ProviderCapabilities(vision=False, tools=True))
    groq = FakeProvider("groq", capabilities=ProviderCapabilities(vision=True, tools=True))
    events = run_stream(ProviderManager({"gemini": gemini, "groq": groq}), [image])
    assert events[0].text == "groq"
    assert not gemini.calls and len(groq.calls) == 1


def test_image_falls_back_to_vision_capable_openrouter():
    from app.providers.base import MediaPart
    image = Message("user", "describe", media=[MediaPart("image/png", b"image")])
    gemini = FakeProvider("gemini", [ProviderError("quota", transient=True)],
                          capabilities=ProviderCapabilities(vision=True, tools=True))
    groq = FakeProvider("groq", capabilities=ProviderCapabilities(tools=True))
    router = FakeProvider("openrouter", capabilities=ProviderCapabilities(vision=True, tools=True))

    events = run_stream(ProviderManager({"gemini": gemini, "groq": groq, "openrouter": router}), [image])

    assert events[0].text == "openrouter"
    assert len(gemini.calls) == 1 and not groq.calls and len(router.calls) == 1


def test_unsupported_pdf_is_never_sent_to_text_only_fallbacks():
    from app.providers.base import MediaPart
    pdf = Message("user", "summarize", media=[MediaPart("application/pdf", b"pdf")])
    providers = {name: FakeProvider(name) for name in ("gemini", "groq", "openrouter")}
    with pytest.raises(ProviderError, match="PDF documents"):
        run_stream(ProviderManager(providers), [pdf])
    assert all(not provider.calls for provider in providers.values())


def test_factory_registers_configured_providers_without_exposing_keys(caplog):
    caplog.set_level(logging.DEBUG)
    secrets = ("gemini-test-secret", "groq-test-secret", "router-test-secret")
    manager = get_provider(Settings(
        provider="auto", gemini_api_key=secrets[0], groq_api_key=secrets[1],
        openrouter_api_key=secrets[2]))
    assert manager.available_names == ["gemini", "groq", "openrouter"]
    assert all(secret not in caplog.text for secret in secrets)


def test_factory_requires_key_for_manual_provider():
    with pytest.raises(ProviderError, match="GROQ_API_KEY"):
        get_provider(Settings(provider="groq", groq_api_key=""))


def test_web_search_tool_is_hidden_for_provider_without_grounding():
    gemini = FakeProvider("gemini", capabilities=ProviderCapabilities(tools=True, web_search=True))
    groq = FakeProvider("groq", capabilities=ProviderCapabilities(tools=True))
    manager = ProviderManager({"gemini": gemini, "groq": groq})
    specs = [type("Spec", (), {"name": name})() for name in ("calculator", "web_search")]

    token = manager.begin_turn("groq")
    try:
        assert [tool.name for tool in manager.tools_for_turn(specs)] == ["calculator"]
    finally:
        manager.end_turn(token)


def test_fallback_provider_stays_sticky_through_tool_round_trip():
    gemini = FakeProvider("gemini", [ProviderError("quota", transient=True)])
    groq = FakeProvider("groq", [
        [ToolCallEvent(ToolCall("calculator", {"expression": "6*7"}, "groq-call")), Done()],
        [TextDelta("The answer is 42."), Done()],
    ])
    manager = ProviderManager({"gemini": gemini, "groq": groq})
    agent = Agent(manager, default_registry(manager))
    events = []

    async def send(event):
        events.append(event)

    asyncio.run(agent.run_turn(Session("turn"), "calculate 6 times 7", send))

    assert len(gemini.calls) == 1
    assert len(groq.calls) == 2
    assert any(event.get("type") == "done" for event in events)