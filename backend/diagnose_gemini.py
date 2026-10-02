import asyncio
import os
from importlib.metadata import version

import httpx

from app.config import BASE, settings
from google import genai


def key_prefix(key: str) -> str:
    if key.startswith("AQ."):
        return "AQ."
    if key.startswith("AIza"):
        return "AIza"
    return key[:3]


def report_error(exc: Exception) -> None:
    payload = getattr(exc, "details", None)
    if isinstance(payload, dict):
        payload = payload.get("error", payload)
    error = payload if isinstance(payload, dict) else {}
    message = str(error.get("message", getattr(exc, "message", "unavailable")))
    if settings.gemini_api_key:
        message = message.replace(settings.gemini_api_key, "[REDACTED]")

    print(f"HTTP_STATUS={getattr(exc, 'code', 'unavailable')}")
    print(f"ERROR_STATUS={error.get('status', getattr(exc, 'status', 'unavailable'))}")
    print(f"ERROR_MESSAGE={message}")
    details = error.get("details", [])
    for index, detail in enumerate(details if isinstance(details, list) else []):
        if not isinstance(detail, dict):
            continue
        metadata = detail.get("metadata") or {}
        print(f"ERROR_DETAILS_{index}_REASON={detail.get('reason', 'not present')}")
        print(f"ERROR_DETAILS_{index}_METADATA_SERVICE={metadata.get('service', 'not present')}")
        print(f"ERROR_DETAILS_{index}_METADATA_METHOD_NAME={metadata.get('methodName', 'not present')}")
        if "method" in metadata:
            print(f"ERROR_DETAILS_{index}_METADATA_METHOD={metadata['method']}")
    if not details:
        print("ERROR_DETAILS=none")


async def probe(client: genai.Client) -> None:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent"
    payload = {"contents": [{"parts": [{"text": "Reply only: OK"}]}]}
    async with httpx.AsyncClient(timeout=20) as http:
        for label, headers in (
            ("x-goog-api-key", {"x-goog-api-key": settings.gemini_api_key}),
            ("authorization-bearer", {"Authorization": f"Bearer {settings.gemini_api_key}"}),
        ):
            try:
                response = await http.post(url, headers=headers, json=payload)
                print(f"HEADER_PROBE_{label.upper().replace('-', '_')}_HTTP_STATUS={response.status_code}")
                if response.is_success:
                    continue
                error = response.json().get("error", {})
                message = str(error.get("message", "unavailable"))
                message = message.replace(settings.gemini_api_key, "[REDACTED]")
                print(f"HEADER_PROBE_{label.upper().replace('-', '_')}_ERROR_STATUS={error.get('status', 'unavailable')}")
                print(f"HEADER_PROBE_{label.upper().replace('-', '_')}_ERROR_MESSAGE={message[:240]}")
            except Exception as exc:
                print(f"HEADER_PROBE_{label.upper().replace('-', '_')}_ERROR_TYPE={type(exc).__name__}")
    try:
        await client.aio.models.generate_content(
            model=settings.gemini_model,
            contents="Reply only: OK",
        )
        print("HTTP_STATUS=200")
        print("ERROR_STATUS=none")
        print("ERROR_MESSAGE=none")
        print("ERROR_DETAILS=none")
    except Exception as exc:
        report_error(exc)
    finally:
        await client.aio.aclose()


def main() -> None:
    key = settings.gemini_api_key
    print(f"GEMINI_MODEL={settings.gemini_model}")
    print(f"API_KEY_PREFIX={key_prefix(key)}")
    print(f"API_KEY_LENGTH={len(key)}")
    print(f"GOOGLE_GENAI_VERSION={version('google-genai')}")

    if not key:
        print("HTTP_STATUS=not queried (key missing)")
        return

    client = genai.Client(api_key=key)
    http_options = getattr(getattr(client, "_api_client", None), "_http_options", None)
    api_version = getattr(http_options, "api_version", "SDK default")
    headers = getattr(http_options, "headers", None) or {}
    normalized_headers = {str(name).lower() for name in headers}
    print(f"GEMINI_API_VERSION={api_version}")
    print(f"X_GOOG_API_KEY_HEADER_CONFIGURED={'x-goog-api-key' in normalized_headers}")
    print(f"AUTHORIZATION_HEADER_CONFIGURED={'authorization' in normalized_headers}")
    asyncio.run(probe(client))


if __name__ == "__main__":
    main()
