"""Fake providers for tests and the offline eval dry-run. They never claim to be real measurements."""
from .base import (Done, LLMProvider, ProviderError, TextDelta, ToolCall,
                   ToolCallEvent)


class ScriptedProvider(LLMProvider):
    """Each script entry is the event list for one model call (or an Exception to raise)."""
    name = "scripted"

    def __init__(self, script):
        self.script, self.calls = list(script), []

    async def stream(self, system, messages, tools):
        self.calls.append(list(messages))
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        for ev in step:
            yield ev
        yield Done()

    async def grounded_search(self, query):
        return {"answer": f"stub answer for {query}", "sources": [{"title": "stub", "url": "https://example.com"}]}


class DryRunProvider(LLMProvider):
    """Deterministic stand-in: triggers tools by keyword, otherwise reports what it received."""
    name = "dry-run"

    async def stream(self, system, messages, tools):
        last = messages[-1]
        if last.tool_results:
            yield TextDelta("DRYRUN: tool finished.")
        else:
            t = last.text.lower()
            call = (ToolCall("save_note", {"title": "Eval note", "content": "VoxSight eval marker 123"}) if "save a note" in t
                    else ToolCall("calculator", {"expression": "1234*5678"}) if "calculator" in t
                    else ToolCall("get_datetime", {}) if "date" in t
                    else ToolCall("web_search", {"query": "python creator"}) if "search the web" in t else None)
            if call:
                yield ToolCallEvent(call)
            else:
                n = sum(len(m.media) for m in messages)
                yield TextDelta(f"DRYRUN: media parts visible={n}.")
        yield Done()

    async def grounded_search(self, query):
        return {"answer": "DRYRUN stub", "sources": []}
