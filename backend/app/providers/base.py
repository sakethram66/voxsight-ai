"""Provider-neutral types. Agent code only ever imports from here."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional


class ProviderError(Exception):
    """Failure talking to an LLM provider. transient=True means one retry is reasonable."""
    def __init__(self, message: str, transient: bool = False):
        super().__init__(message)
        self.transient = transient


@dataclass
class MediaPart:
    mime_type: str          # image/png, application/pdf, ...
    data: bytes
    name: str = ""          # human label shown to the model, e.g. "Screen capture (live)"
    tag: str = "upload"     # upload | camera | screen  (drives context compaction)


@dataclass
class ToolCall:
    name: str
    args: dict
    id: Optional[str] = None


@dataclass
class ToolResult:
    name: str
    response: dict
    id: Optional[str] = None


@dataclass
class Message:
    role: str               # "user" | "model"
    text: str = ""
    media: list = field(default_factory=list)
    tool_calls: list = field(default_factory=list)
    tool_results: list = field(default_factory=list)
    raw: Any = None         # provider-native replay object (Gemini thought signatures)


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict


@dataclass(frozen=True)
class ProviderCapabilities:
    text: bool = True
    vision: bool = False
    documents: bool = False
    audio: bool = False
    streaming: bool = True
    tools: bool = False
    web_search: bool = False

    def unsupported(self, messages: list, tools: list) -> str:
        if messages and not self.text:
            return "text"
        if tools and not self.tools:
            return "tool calling"
        for message in messages:
            for media in message.media:
                mime = media.mime_type.lower()
                if mime.startswith("image/") and not self.vision:
                    return "images"
                if mime == "application/pdf" and not self.documents:
                    return "PDF documents"
                if mime.startswith("audio/") and not self.audio:
                    return "audio"
                if not (mime.startswith("image/") or mime == "application/pdf" or mime.startswith("audio/")):
                    return f"{mime} media"
        return ""


@dataclass
class TextDelta:
    text: str


@dataclass
class ToolCallEvent:
    call: ToolCall


@dataclass
class Done:
    raw: Any = None


class LLMProvider(ABC):
    name: str = "base"
    capabilities = ProviderCapabilities()

    def begin_turn(self, mode: Optional[str] = None):
        return None

    def end_turn(self, token) -> None:
        return None

    @abstractmethod
    def stream(self, system: str, messages: list, tools: list) -> AsyncIterator:
        """Yield TextDelta / ToolCallEvent, then one Done. Raise ProviderError on failure."""

    async def grounded_search(self, query: str) -> dict:
        """Optional: web-grounded answer -> {"answer": str, "sources": [{"title","url"}]}."""
        raise ProviderError("This provider does not support web search.")
