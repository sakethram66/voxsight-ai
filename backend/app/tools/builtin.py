import ast
import asyncio
import operator as op
from datetime import datetime

from ..config import Settings, settings as default_settings
from .actions import SaveNote, SendEmail
from .base import Tool, ToolRegistry

_OPS = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv, ast.Pow: op.pow,
        ast.Mod: op.mod, ast.USub: op.neg, ast.UAdd: op.pos, ast.FloorDiv: op.floordiv}


def _eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        l, r = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(r) > 100:
            raise ValueError("exponent too large")
        return _OPS[type(node.op)](l, r)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("unsupported expression")


class Calculator(Tool):
    name = "calculator"
    description = "Evaluate an arithmetic expression exactly (+ - * / ** % //). Prefer this for any non-trivial math."
    parameters = {"type": "object", "properties": {"expression": {"type": "string", "description": "e.g. '(12.5*4)/3'"}},
                  "required": ["expression"]}

    async def run(self, expression: str) -> dict:
        return {"result": _eval(ast.parse(expression, mode="eval").body)}


class DateTime(Tool):
    name = "get_datetime"
    description = "Get the current local date, time and timezone of the user's machine."

    async def run(self) -> dict:
        return {"iso": datetime.now().astimezone().isoformat()}


class WebSearch(Tool):
    name = "web_search"
    description = ("Search the web for current information (news, companies, docs, error messages, facts). "
                   "Returns a grounded summary plus source links.")
    parameters = {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}

    def __init__(self, provider, timeout: float = 30):
        self.provider, self.timeout = provider, timeout

    async def run(self, query: str) -> dict:
        return await asyncio.wait_for(self.provider.grounded_search(query), self.timeout)


def default_registry(provider=None, s: Settings = default_settings) -> ToolRegistry:
    reg = ToolRegistry().register(Calculator()).register(DateTime())
    if provider is not None:
        reg.register(WebSearch(provider, s.tool_timeout))
    reg.register(SaveNote(s.notes_dir))
    if s.smtp_ready:
        reg.register(SendEmail(s))
    return reg
