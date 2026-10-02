import base64
import json
from dataclasses import replace

from openai import AsyncOpenAI

from .base import (Done, LLMProvider, Message, ProviderCapabilities, ProviderError,
                   TextDelta, ToolCall, ToolCallEvent)

_GROQ_MODELS = {
    "meta-llama/llama-4-scout-17b-16e-instruct": ProviderCapabilities(
        vision=True, streaming=True, tools=True),
    "openai/gpt-oss-120b": ProviderCapabilities(streaming=True, tools=True),
    "llama-3.3-70b-versatile": ProviderCapabilities(streaming=True, tools=True),
}
_OPENROUTER_MODELS = {
    "openai/gpt-4.1-mini": ProviderCapabilities(vision=True, streaming=True, tools=True),
    "openai/gpt-4o-mini": ProviderCapabilities(vision=True, streaming=True, tools=True),
    "qwen/qwen3.8-27b:free": ProviderCapabilities(vision=True, streaming=True, tools=True),
    "anthropic/claude-sonnet-4.5": ProviderCapabilities(vision=True, streaming=True, tools=True),
    "google/gemini-3.8-flash": ProviderCapabilities(vision=True, streaming=True, tools=True),
}


class OpenAICompatibleProvider(LLMProvider):
    def __init__(self, name: str, api_key: str, model: str, base_url: str):
        if not api_key:
            raise ProviderError(f"{name} is not configured. Set its API key in backend/.env.")
        self.name = name
        self.model = model
        known = _GROQ_MODELS if name == "groq" else _OPENROUTER_MODELS
        capabilities = known.get(model, ProviderCapabilities())
        self.capabilities = replace(capabilities, web_search=True) if name == "openrouter" else capabilities
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    def _messages(self, system: str, messages: list) -> list:
        result = [{"role": "system", "content": system}]
        pending_tool_ids = {}
        synthetic_id = 0

        for message in messages:
            if message.role == "model":
                if message.tool_calls:
                    calls = []
                    for call in message.tool_calls:
                        call_id = call.id or f"vox_call_{synthetic_id}"
                        synthetic_id += 1
                        pending_tool_ids.setdefault(call.name, []).append(call_id)
                        calls.append({
                            "id": call_id,
                            "type": "function",
                            "function": {"name": call.name, "arguments": json.dumps(call.args)},
                        })
                    result.append({"role": "assistant", "content": message.text or None, "tool_calls": calls})
                elif message.text:
                    result.append({"role": "assistant", "content": message.text})
                continue

            if message.text or message.media:
                if message.media:
                    content = []
                    if message.text:
                        content.append({"type": "text", "text": message.text})
                    for media in message.media:
                        data = base64.b64encode(media.data).decode("ascii")
                        content.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:{media.mime_type};base64,{data}"},
                        })
                    result.append({"role": "user", "content": content})
                else:
                    result.append({"role": "user", "content": message.text})

            for tool_result in message.tool_results:
                waiting = pending_tool_ids.get(tool_result.name, [])
                call_id = tool_result.id or (waiting.pop(0) if waiting else f"vox_call_{synthetic_id}")
                if not waiting and not tool_result.id:
                    synthetic_id += 1
                result.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": json.dumps(tool_result.response),
                })
        return result

    async def stream(self, system: str, messages: list, tools: list):
        request = {
            "model": self.model,
            "messages": self._messages(system, messages),
            "stream": True,
        }
        if tools:
            request["tools"] = [{
                "type": "function",
                "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
            } for t in tools]

        pending_calls = {}
        try:
            response = await self.client.chat.completions.create(**request)
            async for chunk in response:
                for choice in chunk.choices or []:
                    delta = choice.delta
                    if delta.content:
                        yield TextDelta(delta.content)
                    for call in delta.tool_calls or []:
                        entry = pending_calls.setdefault(call.index, {"id": "", "name": "", "arguments": ""})
                        if call.id:
                            entry["id"] += call.id
                        if call.function:
                            entry["name"] += call.function.name or ""
                            entry["arguments"] += call.function.arguments or ""
            for index in sorted(pending_calls):
                call = pending_calls[index]
                try:
                    args = json.loads(call["arguments"] or "{}")
                except json.JSONDecodeError as exc:
                    raise ProviderError(f"{self.name} returned malformed tool arguments.") from exc
                yield ToolCallEvent(ToolCall(call["name"], args, call["id"] or None))
            yield Done()
        except ProviderError:
            raise
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            error_type = type(exc).__name__
            if status == 402:
                raise ProviderError(f"{self.name} requires credits or billing (HTTP 402).") from exc
            if status == 429:
                raise ProviderError(f"{self.name} rate limit reached (HTTP 429). Check the model's rate limits or billing.",
                                    transient=True) from exc
            if isinstance(status, int) and status >= 500:
                raise ProviderError(f"{self.name} is temporarily unavailable.", transient=True) from exc
            if status in (400, 401, 403, 404):
                raise ProviderError(f"{self.name} rejected the request (HTTP {status}).") from exc
            if (isinstance(exc, (TimeoutError, ConnectionError, OSError)) or
                    error_type in {"APITimeoutError", "APIConnectionError"}):
                raise ProviderError(f"{self.name} is temporarily unavailable.", transient=True) from exc
            raise ProviderError(f"{self.name} request failed.") from exc

    async def grounded_search(self, query: str) -> dict:
        if self.name != "openrouter":
            raise ProviderError("This provider does not support web search.")
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": query}],
                max_tokens=700,
                extra_body={"plugins": [{"id": "web", "max_results": 5}]},
            )
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            if status == 402:
                raise ProviderError("OpenRouter web search requires credits or billing (HTTP 402).") from exc
            if status == 429:
                raise ProviderError("OpenRouter web search is rate limited (HTTP 429).", transient=True) from exc
            if isinstance(status, int) and status >= 500:
                raise ProviderError("OpenRouter web search is temporarily unavailable.", transient=True) from exc
            raise ProviderError("OpenRouter web search request failed.") from exc

        message = response.choices[0].message if response.choices else None
        answer = getattr(message, "content", "") or ""
        sources, seen = [], set()
        for annotation in getattr(message, "annotations", None) or []:
            citation = annotation.get("url_citation") if isinstance(annotation, dict) else getattr(annotation, "url_citation", None)
            if isinstance(citation, dict):
                url, title = citation.get("url"), citation.get("title")
            else:
                url, title = getattr(citation, "url", None), getattr(citation, "title", None)
            if url and url not in seen:
                seen.add(url)
                sources.append({"title": title or url, "url": url})
        if not answer and not sources:
            raise ProviderError("OpenRouter returned no web search results.")
        return {"answer": answer, "sources": sources[:6]}