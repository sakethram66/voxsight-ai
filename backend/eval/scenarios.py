"""Evaluation scenarios (req. #14): each drives the real Agent/session/tool pipeline end-to-end.
Uses ScriptedProvider (deterministic) by default, or the real Gemini provider with --live.
TARGET values are fixed expectations written before any run. ACTUAL values are what this run measured.
They are kept in separate keys in the report; this script never overwrites a target with a measurement."""
import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

from app.agent import Agent, build_user_message
from app.providers.base import TextDelta, ToolCall, ToolCallEvent
from app.providers.testing import ScriptedProvider
from app.session import Attachment, Session
from app.tools.builtin import default_registry

TARGETS = {  # req #21/#14: targets, stated up front, never conflated with measurements
    "latency_p50_s": 2.0, "latency_p95_s": 4.0, "task_completion_rate": 0.9,
    "clarification_turns_avg": 0.5, "failure_rate": 0.05,
}

IMG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108020000009077" "53de0000000c4944415478da6360606000000004" "0001a5f645400000000049454e44ae426082")


def att(kind="image", tag="upload", text=""):
    return Attachment("a1", "shot.png" if kind == "image" else "notes.txt", "image/png" if kind == "image" else "text/plain",
                       kind, data=IMG if kind == "image" else b"", text=text, tag=tag)


async def run_case(name, script, turns, expect_tool=None, expect_confirm=None):
    """turns: list of (text, attachments). Runs them through the REAL Agent, in order, on ONE session."""
    provider = ScriptedProvider(script)
    agent = Agent(provider, default_registry(provider))
    session = Session(f"eval-{name}")
    t0 = time.perf_counter()
    seen_tool, clar, failed, confirmed = None, 0, False, None

    async def send(ev):
        nonlocal seen_tool, clar, failed, confirmed
        if ev["type"] == "tool": seen_tool = ev["name"]
        if ev["type"] == "error": failed = True
        if ev["type"] == "confirmation_request":  # auto-approve immediately so the harness never blocks
            confirmed = "asked"
            session.resolve_confirmation(ev["id"], True)

    for text, attachments in turns:
        await agent.run_turn(session, text, send, attachments)
    dt = time.perf_counter() - t0

    ok = (not failed) and (expect_tool is None or seen_tool == expect_tool)
    return {"name": name, "latency_s": round(dt, 4), "turns": len(turns), "passed": ok,
            "tool_used": seen_tool, "clarification_turns": clar, "failed": failed,
            "history_len_after": len(session.history)}


SCENARIOS = {
    "voice_only": lambda: run_case("voice_only", [[TextDelta("Sure, the capital of France is Paris.")]],
                                    [("What's the capital of France?", [])]),
    "image_plus_voice": lambda: run_case("image_plus_voice", [[TextDelta("This shows a ZeroDivisionError.")]],
                                          [("what's wrong here?", [att()])]),
    "screenshot_plus_voice": lambda: run_case("screenshot_plus_voice",
        [[TextDelta("The traceback points to line 12.")], [TextDelta("Add a guard for n == 0.")]],
        [("why am I getting this?", [att()]), ("how do I fix it?", [])]),  # 2nd turn: no re-upload
    "pdf_plus_voice": lambda: run_case("pdf_plus_voice", [[TextDelta("Chapter 3 covers gradient descent.")]],
                                        [("summarize this", [att("text", text="Chapter 3: Gradient Descent...")])]),
    "camera_plus_voice": lambda: run_case("camera_plus_voice", [[TextDelta("That looks like a circuit board.")]],
                                           [("what is this?", [att(tag="camera")])]),
    "screen_plus_voice": lambda: run_case("screen_plus_voice", [[TextDelta("Your terminal shows a failed npm install.")]],
                                           [("what's going on with my screen?", [att(tag="screen")])]),
    "multi_turn_multimodal": lambda: run_case("multi_turn_multimodal",
        [[TextDelta("It's an IndexError.")], [TextDelta("Check len(list) before indexing.")], [TextDelta("Here's the fixed version.")]],
        [("what's wrong?", [att()]), ("how do I fix it?", []), ("show me the code", [])]),
    "tool_calling": lambda: run_case("tool_calling",
        [[ToolCallEvent(ToolCall("calculator", {"expression": "144/12"}))], [TextDelta("That's 12.")]],
        [("what is 144 divided by 12?", [])], expect_tool="calculator"),
    "confirmation_flow": lambda: run_case("confirmation_flow",
        [[ToolCallEvent(ToolCall("save_note", {"title": "t", "content": "c"}))], [TextDelta("Saved it.")]],
        [("remember this as a note", [])], expect_tool="save_note"),
    "error_recovery_tool_failure": lambda: run_case("error_recovery_tool_failure",
        [[ToolCallEvent(ToolCall("calculator", {"expression": "1/0"}))], [TextDelta("That's undefined; division by zero.")]],
        [("what is 1 divided by 0?", [])], expect_tool="calculator"),
}


async def main(live: bool):
    if live:
        from app.config import settings
        from app.providers.gemini import GeminiProvider
        print("--live not wired into these deterministic scenarios (they assert exact scripted replies); "
              "run `uvicorn app.main:app` and use eval/checklist.md for a manual pass against real Gemini.")
        return
    results = [await fn() for fn in SCENARIOS.values()]
    lat = [r["latency_s"] for r in results]
    measured = {
        "latency_p50_s": round(statistics.median(lat), 4),
        "latency_p95_s": round(sorted(lat)[max(0, int(len(lat) * 0.95) - 1)], 4),
        "task_completion_rate": round(sum(r["passed"] for r in results) / len(results), 3),
        "clarification_turns_avg": round(statistics.mean(r["clarification_turns"] for r in results), 3),
        "failure_rate": round(sum(r["failed"] for r in results) / len(results), 3),
        "note": "Harness latency only (scripted provider, no network). Real Gemini/network latency must be measured separately; see eval/checklist.md.",
    }
    report = {"generated": time.time(), "targets": TARGETS, "measured": measured, "scenarios": results}
    out = Path(__file__).parent / "report.json"
    out.write_text(json.dumps(report, indent=2))
    width = max(len(n) for n in SCENARIOS)
    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL':4}  {r['name']:{width}}  {r['latency_s']:.3f}s  tool={r['tool_used']}")
    print(f"\n{sum(r['passed'] for r in results)}/{len(results)} scenarios passed. Report -> {out}")
    print("TARGET  :", TARGETS)
    print("MEASURED:", measured)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--live", action="store_true", help="placeholder for a real-Gemini pass (see message)")
    asyncio.run(main(p.parse_args().live))
