import asyncio
from contextvars import ContextVar, Token
from dataclasses import dataclass

from .base import (Done, LLMProvider, ProviderCapabilities, ProviderError,
                   TextDelta, ToolCallEvent)

_PROVIDER_ORDER = ("gemini", "groq", "openrouter")
_PROVIDER_MODES = {*_PROVIDER_ORDER, "auto"}


@dataclass
class _TurnState:
    providers: list[LLMProvider]
    active_index: int = 0


class ProviderManager(LLMProvider):
    """Capability-aware provider routing, sticky for one agent turn."""

    name = "provider-manager"
    capabilities = ProviderCapabilities(text=True, streaming=True)

    def __init__(self, providers: dict[str, LLMProvider], default_mode: str = "auto"):
        self.providers = providers
        self.default_mode = default_mode
        self._turn = ContextVar(f"provider_turn_{id(self)}", default=None)

    @property
    def available_names(self) -> list[str]:
        return [name for name in _PROVIDER_ORDER if name in self.providers]

    def _ordered(self, mode: str) -> list[LLMProvider]:
        mode = (mode or self.default_mode).strip().lower()
        if mode not in _PROVIDER_MODES:
            raise ProviderError("Unknown AI_PROVIDER. Choose auto, gemini, groq, or openrouter.")
        names = _PROVIDER_ORDER if mode == "auto" else (mode,)
        providers = [self.providers[name] for name in names if name in self.providers]
        if not providers:
            label = "any provider" if mode == "auto" else mode
            raise ProviderError(f"No credentials are configured for {label}. Check backend/.env.")
        return providers

    def begin_turn(self, mode: str | None = None) -> Token:
        return self._turn.set(_TurnState(self._ordered(mode or self.default_mode)))

    def end_turn(self, token: Token) -> None:
        self._turn.reset(token)

    def _state(self) -> _TurnState:
        state = self._turn.get()
        if state is None:
            state = _TurnState(self._ordered(self.default_mode))
        return state

    def tools_for_turn(self, tools: list) -> list:
        state = self._state()
        index = min(state.active_index, len(state.providers) - 1)
        if not state.providers[index].capabilities.web_search:
            return [tool for tool in tools if tool.name != "web_search"]
        return tools

    async def stream(self, system: str, messages: list, tools: list):
        state = self._state()
        skipped, failed = [], []
        start = min(state.active_index, len(state.providers) - 1)
        for index in range(start, len(state.providers)):
            provider = state.providers[index]
            provider_tools = tools if provider.capabilities.web_search else [
                tool for tool in tools if tool.name != "web_search"]
            reason = provider.capabilities.unsupported(messages, provider_tools)
            if not provider.capabilities.streaming:
                reason = reason or "streaming"
            if reason:
                skipped.append(f"{provider.name} does not support {reason}")
                state.active_index = index + 1
                continue

            attempt = 0
            while True:
                emitted = False
                try:
                    async for event in provider.stream(system, messages, provider_tools):
                        if isinstance(event, (TextDelta, ToolCallEvent)):
                            emitted = True
                        yield event
                    state.active_index = index
                    return
                except ProviderError as exc:
                    if emitted:
                        raise
                    if provider.name in {"groq", "openrouter"} and exc.transient and attempt == 0:
                        attempt += 1
                        await asyncio.sleep(0.25)
                        continue
                    failed.append(f"{provider.name}: {exc}")
                    state.active_index = index + 1
                    break
                except Exception:
                    if emitted:
                        raise ProviderError(f"{provider.name} failed after streaming began; no fallback was attempted.")
                    failed.append(f"{provider.name} request failed")
                    state.active_index = index + 1
                    break

        if failed:
            raise ProviderError("All compatible AI providers failed: " + "; ".join(failed) + ".")
        detail = "; ".join(skipped) or "no configured provider is compatible"
        raise ProviderError(f"No compatible AI provider is available for this request: {detail}.")

    async def grounded_search(self, query: str) -> dict:
        state = self._state()
        failures = []
        start = min(state.active_index, len(state.providers) - 1)
        for provider in state.providers[start:]:
            if not provider.capabilities.web_search:
                continue
            try:
                return await provider.grounded_search(query)
            except ProviderError as exc:
                failures.append(f"{provider.name} {'temporarily unavailable' if exc.transient else 'request failed'}")
        if failures:
            raise ProviderError("Web search failed: " + "; ".join(failures) + ".")
        raise ProviderError("Web search is not supported by the configured AI providers.")