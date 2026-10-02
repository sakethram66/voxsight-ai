import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from app.providers.base import (Done, MediaPart, Message, ProviderError, TextDelta,
                                ToolCall, ToolCallEvent, ToolResult, ToolSpec)
from app.providers import gemini as gemini_module
from app.providers.gemini import GeminiProvider, classify_error
from app.providers.openai_compatible import OpenAICompatibleProvider
from google.genai import types


def test_api_key_uses_api_key_header_not_bearer():
    api_key = "test-api-key-not-secret"
    provider = GeminiProvider(api_key, "m")
    headers = {name.lower(): value for name, value in provider.client._api_client._http_options.headers.items()}
    assert headers.get("x-goog-api-key") == api_key
    assert "authorization" not in headers


def test_openai_compatible_provider_converts_tool_history_and_streams_tool_calls():
    provider = OpenAICompatibleProvider(
        "groq", "test-key-not-secret", "openai/gpt-oss-120b", "https://api.groq.com/openai/v1")
    messages = [
        Message("user", "calculate"),
        Message("model", tool_calls=[ToolCall("calculator", {"expression": "1+1"}, "call-1")]),
        Message("user", tool_results=[ToolResult("calculator", {"result": 2}, "call-1")]),
    ]
    converted = provider._messages("system", messages)
    assert converted[1]["role"] == "user"
    assert converted[2]["tool_calls"][0]["id"] == "call-1"
    assert converted[3] == {"role": "tool", "tool_call_id": "call-1", "content": '{"result": 2}'}

    async def response():
        yield NS(choices=[NS(delta=NS(content=None, tool_calls=[NS(
            index=0, id="call-2", function=NS(name="calculator", arguments='{"expression":"2+2"}'))]))])

    request = AsyncMock(return_value=response())
    provider.client = NS(chat=NS(completions=NS(create=request)))

    async def collect():
        return [event async for event in provider.stream("system", [Message("user", "calculate")], [ToolSpec(
            "calculator", "math", {"type": "object"})])]

    events = asyncio.run(collect())
    call = next(event.call for event in events if isinstance(event, ToolCallEvent))
    assert call == ToolCall("calculator", {"expression": "2+2"}, "call-2")
    assert request.await_args.kwargs["stream"] is True


def test_unknown_openai_compatible_model_defaults_to_text_only():
    provider = OpenAICompatibleProvider("openrouter", "test-key", "custom/unknown", "https://example.test/v1")
    media_message = Message("user", media=[MediaPart("image/png", b"image")])
    assert provider.capabilities.unsupported([media_message], []) == "images"
    assert provider.capabilities.unsupported([Message("user", "text")], [ToolSpec("x", "x", {})]) == "tool calling"


def test_verified_free_openrouter_model_supports_images_and_tools():
    provider = OpenAICompatibleProvider(
        "openrouter", "test-key", "qwen/qwen3.8-27b:free", "https://example.test/v1")
    image = Message("user", "describe this", media=[MediaPart("image/png", b"image")])

    assert provider.capabilities.unsupported([image], [ToolSpec("calculator", "math", {})]) == ""


@pytest.mark.parametrize("error_type", ["APITimeoutError", "APIConnectionError"])
def test_openai_compatible_transport_errors_are_transient(error_type):
    provider = OpenAICompatibleProvider("openrouter", "test-key", "openai/gpt-4o-mini", "https://example.test/v1")
    error = type(error_type, (Exception,), {})("temporary connection failure")
    request = AsyncMock(side_effect=error)
    provider.client = NS(chat=NS(completions=NS(create=request)))

    async def collect():
        return [event async for event in provider.stream("system", [Message("user", "hi")], [])]

    with pytest.raises(ProviderError, match="temporarily unavailable") as exc:
        asyncio.run(collect())
    assert exc.value.transient


def test_openrouter_payment_error_is_reported_explicitly():
    provider = OpenAICompatibleProvider("openrouter", "test-key", "openai/gpt-4o-mini", "https://example.test/v1")
    error = type("PaymentRequiredError", (Exception,), {"status_code": 402})("payment required")
    provider.client = NS(chat=NS(completions=NS(create=AsyncMock(side_effect=error))))

    async def collect():
        return [event async for event in provider.stream("system", [Message("user", "hi")], [])]

    with pytest.raises(ProviderError, match="credits or billing"):
        asyncio.run(collect())


def test_conversion_labels_media_and_config():
    g = GeminiProvider("fake-key", "gemini-3.8-flash")
    msgs = [Message("user", "what is this?", media=[MediaPart("image/png", b"\x89PNG", name="Screen capture (live)")]),
            Message("user", tool_results=[ToolResult("calculator", {"result": 1})])]
    c = g._contents(msgs)
    assert c[0].parts[0].text == "[Screen capture (live)]" and c[0].parts[1].inline_data.mime_type == "image/png"
    assert c[1].parts[0].function_response.name == "calculator"
    cfg = g._config("sys", [ToolSpec("calculator", "d", {"type": "object", "properties": {}})])
    assert cfg.tools[0].function_declarations[0].name == "calculator"


def test_grounded_search_parsing():
    g = GeminiProvider("fake-key", "m")
    web = NS(uri="https://a.example", title="A")
    resp = NS(text="answer", candidates=[NS(grounding_metadata=NS(grounding_chunks=[NS(web=web), NS(web=web)]))])
    g.client = NS(aio=NS(models=NS(generate_content=AsyncMock(return_value=resp))))
    out = asyncio.run(g.grounded_search("q"))
    assert out == {"answer": "answer", "sources": [{"title": "A", "url": "https://a.example"}]}


@pytest.mark.parametrize("code", [429, 503])
def test_grounded_search_retries_transient_errors(code, monkeypatch):
    g = GeminiProvider("fake-key", "m")
    response = NS(text="answer", candidates=[])
    request = AsyncMock(side_effect=[_api_error(code), response])
    g.client = NS(aio=NS(models=NS(generate_content=request)))
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)
    monkeypatch.setattr(gemini_module.random, "uniform", lambda low, high: 1.0)

    result = asyncio.run(g.grounded_search("q"))

    assert result == {"answer": "answer", "sources": []}
    assert request.await_count == 2
    assert [call.args[0] for call in sleep.await_args_list] == [2]


def _api_error(code):
    return type("E", (Exception,), {"code": code})("temporary failure")


@pytest.mark.parametrize("code", [429, 503])
def test_stream_retries_transient_errors_with_exponential_backoff(code, monkeypatch):
    async def response():
        yield NS(candidates=[NS(finish_reason=None, content=NS(parts=[types.Part.from_text(text="ok")]))])

    g = GeminiProvider("fake-key", "m")
    request = AsyncMock(side_effect=[_api_error(code), _api_error(code), _api_error(code), response()])
    g.client = NS(aio=NS(models=NS(generate_content_stream=request)))
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)
    monkeypatch.setattr(gemini_module.random, "uniform", lambda low, high: 1.0)

    async def collect():
        return [event async for event in g.stream("s", [Message("user", "x")], [])]

    events = asyncio.run(collect())
    assert request.await_count == 4
    assert [call.args[0] for call in sleep.await_args_list] == [2, 4, 8]
    assert isinstance(events[0], TextDelta) and events[0].text == "ok"
    assert isinstance(events[-1], Done)


@pytest.mark.parametrize("code,expected_message", [
    (429, "Gemini rate limit or quota reached"),
    (503, "Gemini is temporarily unavailable"),
])
def test_stream_exhausts_transient_retries_with_friendly_error(code, expected_message, monkeypatch):
    g = GeminiProvider("fake-key", "m")
    request = AsyncMock(side_effect=[_api_error(code) for _ in range(4)])
    g.client = NS(aio=NS(models=NS(generate_content_stream=request)))
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)
    monkeypatch.setattr(gemini_module.random, "uniform", lambda low, high: 1.0)

    async def collect():
        return [event async for event in g.stream("s", [Message("user", "x")], [])]

    with pytest.raises(ProviderError, match=expected_message) as exc:
        asyncio.run(collect())
    assert request.await_count == 4
    assert [call.args[0] for call in sleep.await_args_list] == [2, 4, 8]
    assert not exc.value.transient


def test_stream_does_not_retry_503_after_emitting_text(monkeypatch):
    async def partial_response():
        yield NS(candidates=[NS(finish_reason=None, content=NS(parts=[types.Part.from_text(text="partial")]))])
        raise _api_error(503)

    g = GeminiProvider("fake-key", "m")
    request = AsyncMock(return_value=partial_response())
    g.client = NS(aio=NS(models=NS(generate_content_stream=request)))
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)
    emitted = []

    async def collect():
        async for event in g.stream("s", [Message("user", "x")], []):
            emitted.append(event)

    with pytest.raises(ProviderError, match="Gemini is temporarily unavailable"):
        asyncio.run(collect())
    assert [event.text for event in emitted if isinstance(event, TextDelta)] == ["partial"]
    assert request.await_count == 1
    sleep.assert_not_awaited()


@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_stream_does_not_retry_non_server_errors(code, monkeypatch):
    g = GeminiProvider("fake-key", "m")
    request = AsyncMock(side_effect=_api_error(code))
    g.client = NS(aio=NS(models=NS(generate_content_stream=request)))
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)
    monkeypatch.setattr(gemini_module.random, "uniform", lambda low, high: 1.0)

    async def collect():
        return [event async for event in g.stream("s", [Message("user", "x")], [])]

    with pytest.raises(ProviderError):
        asyncio.run(collect())
    assert request.await_count == 1
    sleep.assert_not_awaited()


@pytest.mark.parametrize("code,needle,transient", [(401, "API key", False), (404, "GEMINI_MODEL", False),
                                                    (429, "rate limit", True), (503, "unavailable", True)])
def test_error_classification(code, needle, transient):
    e = classify_error(NS(code=code) and type("E", (Exception,), {"code": code})("boom"), "m")
    assert needle in str(e) and e.transient is transient


def test_unsupported_auth_type_classification():
    error = type("E", (Exception,), {"code": 401})("ACCESS_TOKEN_TYPE_UNSUPPORTED")
    message = str(classify_error(error, "m"))
    assert "ACCESS_TOKEN_TYPE_UNSUPPORTED" in message
    assert "Google AI Studio" in message
    assert "Bearer" not in message


def test_empty_response_is_an_error():
    g = GeminiProvider("k", "m")
    async def empty(): 
        return
        yield
    g.client = NS(aio=NS(models=NS(generate_content_stream=AsyncMock(return_value=empty()))))
    async def go():
        async for _ in g.stream("s", [Message("user", "x")], []): pass
    with pytest.raises(ProviderError, match="no answer"):
        asyncio.run(go())
