import asyncio
import json
import re

from app.config import Settings
from app.providers import get_provider


def sanitize(value):
    text = str(value).replace("\\r", " ").replace("\\n", " ")
    text = re.sub(r"(?i)(Bearer\\s+[A-Za-z0-9._~+/=-]+)", "<redacted>", text)
    text = re.sub(r"(?i)(sk-or-[A-Za-z0-9._-]+|gsk_[A-Za-z0-9._-]+|AIza[A-Za-z0-9_-]+|AQ\\.[A-Za-z0-9._-]+)", "<redacted>", text)
    return text[:800]


async def main():
    s = Settings()
    print(f"provider={s.provider}")
    print(f"gemini_key_present={bool(s.gemini_api_key)}")
    print(f"gemini_key_prefix={s.gemini_api_key[:3] if s.gemini_api_key else 'missing'}")
    print(f"openrouter_model={s.openrouter_model}")
    env_model = __import__('os').getenv('OPENROUTER_MODEL')
    print(f"OPENROUTER_MODEL_env={env_model}")
    pm = get_provider(s)
    print(f"provider_order={','.join(name for name in ('gemini','groq','openrouter') if name in pm.providers)}")
    print(f"auto_order={','.join(name for name in pm._ordered('auto'))}")

    if 'gemini' in pm.providers:
        try:
            print('calling_gemini_grounded_search=1')
            await pm.providers['gemini'].grounded_search('latest AI news')
            print('gemini_ok=1')
        except Exception as exc:
            print(f"gemini_status={getattr(exc, 'code', 'n/a')}")
            print(f"gemini_error={sanitize(exc)}")

    if 'openrouter' in pm.providers:
        try:
            print('calling_openrouter_grounded_search=1')
            await pm.providers['openrouter'].grounded_search('latest AI news')
            print('openrouter_ok=1')
        except Exception as exc:
            status = getattr(exc, 'status_code', getattr(exc, 'code', 'n/a'))
            body = getattr(exc, 'body', None)
            print(f"openrouter_status={status}")
            if isinstance(body, (dict, list)):
                print(f"openrouter_body={sanitize(json.dumps(body, default=str))}")
            else:
                print(f"openrouter_body={sanitize(body)}")
            print(f"openrouter_error={sanitize(exc)}")

asyncio.run(main())
