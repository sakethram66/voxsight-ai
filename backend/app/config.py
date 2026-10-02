import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent.parent
load_dotenv(BASE / ".env")


@dataclass(frozen=True)
class Settings:
    provider: str = os.getenv("AI_PROVIDER", os.getenv("LLM_PROVIDER", "auto")).strip().lower()
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_model: str = os.getenv("GROQ_MODEL", "") or "openai/gpt-oss-120b"
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_model: str = os.getenv("OPENROUTER_MODEL", "") or "qwen/qwen3.8-27b:free"
    cors_origins: tuple = tuple(o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","))
    db_path: str = os.getenv("VOXSIGHT_DB", str(BASE / "data" / "voxsight.db"))
    notes_dir: str = os.getenv("VOXSIGHT_NOTES_DIR", str(BASE / "data" / "notes"))
    request_timeout: float = float(os.getenv("REQUEST_TIMEOUT_S", "60"))
    tool_timeout: float = float(os.getenv("TOOL_TIMEOUT_S", "30"))
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_from: str = os.getenv("SMTP_FROM", "")
    max_image_mb: int = 10
    max_pdf_mb: int = 15
    max_text_mb: int = 1
    max_docx_mb: int = 5

    @property
    def smtp_ready(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)


settings = Settings()
