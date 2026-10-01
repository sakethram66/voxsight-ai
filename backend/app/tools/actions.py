"""Real, confirmation-gated actions. Each does exactly what its result says."""
import asyncio
import re
import smtplib
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

from .base import Tool

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SaveNote(Tool):
    name = "save_note"
    description = ("Save a note as a Markdown file in VoxSight's notes folder on the user's computer. "
                   "The user is asked to confirm first. Use when the user says 'remember this', 'save this', 'take a note'.")
    parameters = {"type": "object", "properties": {
        "title": {"type": "string"}, "content": {"type": "string", "description": "Markdown body"}},
        "required": ["title", "content"]}
    requires_confirmation = True

    def __init__(self, notes_dir: str):
        self.dir = Path(notes_dir)

    def confirmation_summary(self, args: dict) -> str:
        return f'Save a note titled "{args.get("title", "")}" to {self.dir}\n\n{str(args.get("content", ""))[:600]}'

    async def run(self, title: str, content: str) -> dict:
        def write() -> Path:
            self.dir.mkdir(parents=True, exist_ok=True)
            slug = re.sub(r"[^a-z0-9]+", "-", str(title).lower()).strip("-")[:40] or "note"
            base = self.dir / f"{datetime.now():%Y%m%d-%H%M%S}-{slug}"
            p, n = base.with_suffix(".md"), 1
            while p.exists():
                n += 1
                p = Path(f"{base}-{n}.md")
            p.write_text(f"# {title}\n\n{content}\n", encoding="utf-8")
            return p
        p = await asyncio.to_thread(write)
        return {"saved": True, "path": str(p)}


class SendEmail(Tool):
    name = "send_email"
    description = "Send a plain-text email via the configured SMTP account. The user is asked to confirm first."
    parameters = {"type": "object", "properties": {
        "to": {"type": "string", "description": "single recipient address"},
        "subject": {"type": "string"}, "body": {"type": "string"}}, "required": ["to", "subject", "body"]}
    requires_confirmation = True

    def __init__(self, s):
        self.s = s

    def confirmation_summary(self, args: dict) -> str:
        return (f'Send an email from {self.s.smtp_from}\nTo: {args.get("to", "")}\n'
                f'Subject: {args.get("subject", "")}\n\n{str(args.get("body", ""))[:800]}')

    async def run(self, to: str, subject: str, body: str) -> dict:
        if not EMAIL_RE.match(to) or "\n" in to + subject or "\r" in to + subject:
            raise ValueError("Invalid recipient or subject.")
        s = self.s

        def send():
            msg = EmailMessage()
            msg["From"], msg["To"], msg["Subject"] = s.smtp_from, to, subject
            msg.set_content(body)
            if s.smtp_port == 465:
                smtp = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=20)
            else:
                smtp = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20)
                smtp.starttls()
            with smtp:
                if s.smtp_user:
                    smtp.login(s.smtp_user, s.smtp_password)
                smtp.send_message(msg)
        await asyncio.to_thread(send)
        return {"sent": True, "to": to, "subject": subject}
