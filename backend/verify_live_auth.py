import json
import os
import re
from pathlib import Path

import httpx
from google import genai

from app.config import Settings


def sanitize(value: str) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ")
    text = re.sub(r"(?i)(Authorization\s*:\s*Bearer\s+[A-Za-z0-9._~+/=-]+)", "Authorization: Bearer <redacted>", text)
    text = re.sub(r"(?i)(sk-or-[A-Za-z0-9._-]+|gsk_[A-Za-z0-9._-]+|AIza[A-Za-z0-9_-]+|AQ\.[A-Za-z0-9._-]+)", "<redacted>", text)
    return text[:500]


root = Path(__file__).resolve().parent
os.chdir(root)
s = Settings()
print("backend_root=" + str(root))
print("dotenv_file=" + str((root / '.env').exists()))
print("GEMINI_API_KEY=" + ("present" if bool(s.gemini_api_key) else "missing"))
print("GEMINI_MODEL=" + ("present" if bool(s.gemini_model) else "missing"))
print("OPENROUTER_API_KEY=" + ("present" if bool(s.openrouter_api_key) else "missing"))
print("OPENROUTER_MODEL=" + ("present" if bool(s.openrouter_model) else "missing"))
print("AI_PROVIDER=" + ("present" if bool(s.provider) else "missing"))

try:
    client = genai.Client(api_key=s.gemini_api_key)
    resp = client.models.generate_content(model=s.gemini_model, contents="Say OK")
    print("gemini_status=200")
    print("gemini_ok=yes")
except Exception as exc:
    status = getattr(exc, 'code', 'n/a')
    print("gemini_status=" + str(status))
    print("gemini_error=" + sanitize(exc))

try:
    r = httpx.post(
        'https://openrouter.ai/api/v1/chat/completions',
        headers={'Authorization': 'Bearer ' + s.openrouter_api_key, 'Content-Type': 'application/json'},
        json={'model': s.openrouter_model, 'messages': [{'role': 'user', 'content': 'Say OK'}], 'max_tokens': 32},
        timeout=60,
    )
    print('openrouter_status=' + str(r.status_code))
    print('openrouter_body=' + sanitize(r.text))
except Exception as exc:
    print('openrouter_status=n/a')
    print('openrouter_error=' + sanitize(exc))
