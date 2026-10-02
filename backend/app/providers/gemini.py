import asyncio
import random
from typing import AsyncIterator

from google import genai
from google.genai import types

from .base import (Done, LLMProvider, ProviderCapabilities, ProviderError, TextDelta, ToolCall,
                   ToolCallEvent)

_RETRYABLE_ERRORS = {429, 500, 502, 503, 504}
_RETRY_DELAYS = (2, 4, 8)


def _retry_delay(retry: int) -> float:
    return _RETRY_DELAYS[retry] * random.uniform(0.8, 1.2)


def classify_error(e: Exception, model: str) -> ProviderError:
    """Turn assorted SDK/network exceptions into one actionable ProviderError."""
    code, text = getattr(e, "code", None), str(e)
    short = text[:200]
    if "ACCESS_TOKEN_TYPE_UNSUPPORTED" in text:
        return ProviderError("Google rejected GEMINI_API_KEY (ACCESS_TOKEN_TYPE_UNSUPPORTED). "
                             "Verify the key is active in Google AI Studio and permitted for the "
                             "Gemini API, then update backend/.env if it is not.")
    if code in (401, 403) or "API key not valid" in text:
        return ProviderError("Gemini rejected the API key. Check GEMINI_API_KEY in backend/.env.")
    if code == 404:
        return ProviderError(f"Gemini model '{model}' was not found. Check GEMINI_MODEL.")
    if code == 429:
        quota_exhausted = "quota" in text.casefold() or "resource_exhausted" in text.casefold()
        return ProviderError("Gemini rate limit or quota reached. Wait a moment and try again.",
                             transient=not quota_exhausted)
    if code in _RETRYABLE_ERRORS - {429}:
        return ProviderError("Gemini is temporarily unavailable.", transient=True)
    if code == 400:
        return ProviderError(f"Gemini rejected the request: {short}")
    n = type(e).__name__.lower()
    if isinstance(e, (ConnectionError, TimeoutError, OSError)) or "connect" in n or "timeout" in n:
        return ProviderError("Network problem reaching Gemini.")
    return ProviderError(f"Gemini request failed: {short}")


class GeminiProvider(LLMProvider):
    name = "gemini"
    capabilities = ProviderCapabilities(
        text=True, vision=True, documents=True, streaming=True, tools=True, web_search=True)

    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise ProviderError("GEMINI_API_KEY is not set. Add it to backend/.env.")
        self.model = model
        self.client = genai.Client(api_key=api_key)

    def _contents(self, messages: list) -> list:
        out = []
        for m in messages:
            if m.raw is not None:
                out.append(m.raw)
                continue
            parts = []
            for p in m.media:
                if p.name:  # label so the model can tell uploads / camera / screen apart
                    parts.append(types.Part.from_text(text=f"[{p.name}]"))
                parts.append(types.Part.from_bytes(data=p.data, mime_type=p.mime_type))
            if m.text:
                parts.append(types.Part.from_text(text=m.text))
            for r in m.tool_results:
                parts.append(types.Part.from_function_response(name=r.name, response=r.response))
            out.append(types.Content(role=m.role, parts=parts))
        return out

    def _config(self, system: str, tools: list) -> types.GenerateContentConfig:
        decls = [types.FunctionDeclaration(name=t.name, description=t.description,
                                           parameters_json_schema=t.parameters) for t in tools]
        return types.GenerateContentConfig(
            system_instruction=system,
            tools=[types.Tool(function_declarations=decls)] if decls else None,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    async def stream(self, system: str, messages: list, tools: list) -> AsyncIterator:
        retry = 0
        while True:
            raw_parts, finish, emitted = [], None, False
            try:
                resp = await self.client.aio.models.generate_content_stream(
                    model=self.model, contents=self._contents(messages), config=self._config(system, tools))
                async for chunk in resp:
                    for cand in chunk.candidates or []:
                        finish = cand.finish_reason or finish
                        for part in (cand.content.parts if cand.content else None) or []:
                            raw_parts.append(part)
                            if part.function_call:
                                fc = part.function_call
                                emitted = True
                                yield ToolCallEvent(ToolCall(fc.name, dict(fc.args or {}), getattr(fc, "id", None)))
                            elif part.text and not getattr(part, "thought", False):
                                emitted = True
                                yield TextDelta(part.text)
                if not raw_parts:
                    raise ProviderError(f"Gemini returned no answer (finish reason: {finish or 'unknown'}). "
                                        "It may have been blocked by a safety filter; try rephrasing.")
                yield Done(raw=types.Content(role="model", parts=raw_parts))
                return
            except ProviderError:
                raise
            except Exception as e:
                if getattr(e, "code", None) in _RETRYABLE_ERRORS:
                    if getattr(e, "code", None) != 429 and not emitted and retry < len(_RETRY_DELAYS):
                        await asyncio.sleep(_retry_delay(retry))
                        retry += 1
                        continue
                    error = classify_error(e, self.model)
                    if getattr(e, "code", None) == 429:
                        raise error from e
                    raise ProviderError(str(error)) from e
                raise classify_error(e, self.model) from e

    async def grounded_search(self, query: str) -> dict:
        """Google Search grounding in a separate call, so it never conflicts with our function tools."""
        for retry in range(len(_RETRY_DELAYS) + 1):
            try:
                r = await self.client.aio.models.generate_content(
                    model=self.model, contents=query,
                    config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())]))
                break
            except Exception as e:
                code = getattr(e, "code", None)
                if code in _RETRYABLE_ERRORS and code != 429 and retry < len(_RETRY_DELAYS):
                    await asyncio.sleep(_retry_delay(retry))
                    continue
                error = classify_error(e, self.model)
                if code in _RETRYABLE_ERRORS:
                    if code == 429:
                        raise error from e
                    raise ProviderError(str(error)) from e
                raise error from e
        cand = (r.candidates or [None])[0]
        gm = getattr(cand, "grounding_metadata", None)
        sources, seen = [], set()
        for ch in getattr(gm, "grounding_chunks", None) or []:
            w = getattr(ch, "web", None)
            if w and w.uri and w.uri not in seen:
                seen.add(w.uri)
                sources.append({"title": w.title or w.uri, "url": w.uri})
        return {"answer": r.text or "", "sources": sources[:6]}
