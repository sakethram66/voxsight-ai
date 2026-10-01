import re

from app.config import settings
from openai import OpenAI
from app.providers.openai_compatible import _GROQ_MODELS


def report_error(exc: Exception) -> None:
    payload = getattr(exc, "body", None)
    error = payload.get("error", payload) if isinstance(payload, dict) else {}
    message = error.get("message", getattr(exc, "message", "")) if isinstance(error, dict) else ""
    if not isinstance(message, str) or not message:
        message = str(exc)
    if settings.groq_api_key:
        message = message.replace(settings.groq_api_key, "[REDACTED]")
    message = re.sub(r"(?i)bearer\s+[^\s,]+", "Bearer [REDACTED]", message)

    print(f"HTTP_STATUS={getattr(exc, 'status_code', 'unavailable')}")
    print(f"ERROR_TYPE={type(exc).__name__}")
    print(f"ERROR_CODE={getattr(exc, 'code', 'unavailable')}")
    print(f"ERROR_MESSAGE={message[:500] or 'unavailable'}")


def main() -> None:
    print(f"GROQ_MODEL={settings.groq_model}")
    print(f"GROQ_API_KEY_CONFIGURED={bool(settings.groq_api_key.strip())}")
    if not settings.groq_api_key.strip():
        print("HTTP_STATUS=not queried (key missing)")
        return

    try:
        with OpenAI(api_key=settings.groq_api_key, base_url="https://api.groq.com/openai/v1",
                    timeout=20) as client:
            available = sorted(model.id for model in client.models.list()
                               if model.id in _GROQ_MODELS)
            print("AVAILABLE_VOXSIGHT_MODELS=" + ",".join(available))
            client.chat.completions.create(
                model=settings.groq_model,
                messages=[{"role": "user", "content": "Reply only: OK"}],
                max_tokens=8,
            )
        print("HTTP_STATUS=200")
        print("ERROR_MESSAGE=none")
    except Exception as exc:
        report_error(exc)


if __name__ == "__main__":
    main()