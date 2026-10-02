import asyncio
import base64
import re

from app.config import settings
from app.providers import get_provider
from app.providers.base import MediaPart, Message, TextDelta
from app.tools.builtin import default_registry
from tests.helpers import png_bytes
from openai import OpenAI
from app.providers.openai_compatible import _GROQ_MODELS


def report_error(exc: Exception, api_key: str) -> None:
    payload = getattr(exc, "body", None)
    error = payload.get("error", payload) if isinstance(payload, dict) else {}
    message = error.get("message", getattr(exc, "message", "")) if isinstance(error, dict) else ""
    if not isinstance(message, str) or not message:
        message = str(exc)
    if api_key:
        message = message.replace(api_key, "[REDACTED]")
    message = re.sub(r"(?i)bearer\s+[^\s,]+", "Bearer [REDACTED]", message)

    print(f"HTTP_STATUS={getattr(exc, 'status_code', 'unavailable')}")
    print(f"ERROR_TYPE={type(exc).__name__}")
    print(f"ERROR_CODE={getattr(exc, 'code', 'unavailable')}")
    print(f"ERROR_MESSAGE={message[:500] or 'unavailable'}")


async def probe_auto_chain() -> None:
    manager = get_provider(settings)
    token = manager.begin_turn("auto")
    try:
        tools = default_registry(manager, settings).specs()
        events = [event async for event in manager.stream(
            "Reply only: OK", [Message("user", "Reply only: OK")], tools)]
        state = manager._state()
        selected = state.providers[state.active_index].name
        print(f"AUTO_CHAIN_PROVIDER={selected}")
        print(f"AUTO_CHAIN_RESPONSE_RECEIVED={any(isinstance(event, TextDelta) for event in events)}")
    except Exception as exc:
        message = str(exc)
        for key in (settings.gemini_api_key, settings.groq_api_key, settings.openrouter_api_key):
            if key:
                message = message.replace(key, "[REDACTED]")
        print(f"AUTO_CHAIN_ERROR_TYPE={type(exc).__name__}")
        print(f"AUTO_CHAIN_ERROR={message[:500]}")
    finally:
        manager.end_turn(token)


async def probe_auto_image() -> None:
    manager = get_provider(settings)
    token = manager.begin_turn("auto")
    try:
        message = Message("user", "Describe this test image briefly.",
                          media=[MediaPart("image/png", png_bytes(), name="Diagnostic image")])
        events = [event async for event in manager.stream(
            "Describe images accurately and briefly.", [message], [])]
        state = manager._state()
        print(f"AUTO_IMAGE_PROVIDER={state.providers[state.active_index].name}")
        print(f"AUTO_IMAGE_RESPONSE_RECEIVED={any(isinstance(event, TextDelta) for event in events)}")
    except Exception as exc:
        message = str(exc)
        for key in (settings.gemini_api_key, settings.groq_api_key, settings.openrouter_api_key):
            if key:
                message = message.replace(key, "[REDACTED]")
        print(f"AUTO_IMAGE_ERROR_TYPE={type(exc).__name__}")
        print(f"AUTO_IMAGE_ERROR={message[:500]}")
    finally:
        manager.end_turn(token)


def probe_openrouter_image() -> None:
    try:
        image = base64.b64encode(png_bytes()).decode("ascii")
        content = [
            {"type": "text", "text": "Describe this image briefly."},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image}"}},
        ]
        with OpenAI(api_key=settings.openrouter_api_key, base_url="https://openrouter.ai/api/v1",
                    timeout=20) as client:
            response = client.chat.completions.create(
                model=settings.openrouter_model,
                messages=[{"role": "user", "content": content}],
                max_tokens=128,
                stream=True,
            )
            text = "".join(choice.delta.content or "" for chunk in response for choice in chunk.choices)
        print("OPENROUTER_IMAGE_STREAM_RESPONSE=" + str(bool(text)))
        print("OPENROUTER_IMAGE_STREAM_TEXT=" + text[:240])
    except Exception as exc:
        report_error(exc, settings.openrouter_api_key)


def main() -> None:
    print(f"GROQ_MODEL={settings.groq_model}")
    print(f"GROQ_API_KEY_CONFIGURED={bool(settings.groq_api_key.strip())}")
    if not settings.groq_api_key.strip():
        print("HTTP_STATUS=not queried (key missing)")
        return

    try:
        with OpenAI(api_key=settings.groq_api_key, base_url="https://api.groq.com/openai/v1",
                    timeout=20) as client:
            catalog = list(client.models.list())
            available = sorted(model.id for model in catalog if model.id in _GROQ_MODELS)
            print("ACCESSIBLE_GROQ_MODEL_IDS=" + ",".join(sorted(model.id for model in catalog)))
            print("AVAILABLE_VOXSIGHT_MODELS=" + ",".join(available))
            client.chat.completions.create(
                model=settings.groq_model,
                messages=[{"role": "user", "content": "Reply only: OK"}],
                max_tokens=8,
            )
        print("HTTP_STATUS=200")
        print("ERROR_MESSAGE=none")
    except Exception as exc:
        report_error(exc, settings.groq_api_key)
    asyncio.run(probe_auto_chain())
    asyncio.run(probe_auto_image())
    probe_openrouter()
    probe_openrouter_image()


def probe_openrouter() -> None:
    print(f"OPENROUTER_MODEL={settings.openrouter_model}")
    print(f"OPENROUTER_API_KEY_CONFIGURED={bool(settings.openrouter_api_key.strip())}")
    if not settings.openrouter_api_key.strip():
        print("OPENROUTER_HTTP_STATUS=not queried (key missing)")
        return
    try:
        with OpenAI(api_key=settings.openrouter_api_key, base_url="https://openrouter.ai/api/v1",
                    timeout=20) as client:
            client.chat.completions.create(
                model=settings.openrouter_model,
                messages=[{"role": "user", "content": "Reply only: OK"}],
                max_tokens=8,
            )
        print("OPENROUTER_HTTP_STATUS=200")
    except Exception as exc:
        report_error(exc, settings.openrouter_api_key)


if __name__ == "__main__":
    main()