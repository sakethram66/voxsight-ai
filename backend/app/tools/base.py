from abc import ABC, abstractmethod
from ..providers.base import ToolSpec


class Tool(ABC):
    name: str
    description: str
    parameters: dict = {"type": "object", "properties": {}}
    requires_confirmation: bool = False  # True => user must Confirm before run()

    def confirmation_summary(self, args: dict) -> str:
        return f"Run {self.name} with {args}"

    @abstractmethod
    async def run(self, **kwargs) -> dict: ...

    def spec(self) -> ToolSpec:
        return ToolSpec(self.name, self.description, self.parameters)


class ToolRegistry:
    def __init__(self):
        self._tools = {}

    def register(self, tool: Tool):
        self._tools[tool.name] = tool
        return self

    def get(self, name: str):
        return self._tools.get(name)

    def names(self) -> list:
        return list(self._tools)

    def specs(self) -> list:
        return [t.spec() for t in self._tools.values()]
