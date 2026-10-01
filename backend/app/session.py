import asyncio
import time
import uuid
from dataclasses import dataclass, replace

from .providers.base import Message


@dataclass
class Attachment:
    id: str
    name: str
    mime: str
    kind: str            # image | pdf | text
    data: bytes = b""
    text: str = ""       # extracted text for kind == "text"
    tag: str = "upload"  # upload | camera | screen


def compact(msgs: list, max_uploads: int = 8) -> list:
    """Bound multimodal context. Newest wins: only the latest camera frame and latest screen
    frame are kept (older live frames are stale), plus the newest `max_uploads` uploaded files."""
    seen, uploads, out = set(), 0, []
    for m in reversed(msgs):
        if m.media:
            keep, dropped = [], []
            for p in reversed(m.media):
                if p.tag in ("camera", "screen"):
                    ok = p.tag not in seen
                    seen.add(p.tag)
                else:
                    uploads += 1
                    ok = uploads <= max_uploads
                (keep if ok else dropped).append(p)
            if dropped:
                names = ", ".join(p.name or p.mime_type for p in reversed(dropped))
                m = replace(m, media=list(reversed(keep)),
                            text=f"[Earlier attachment(s) omitted to save context: {names}]\n{m.text}")
        out.append(m)
    out.reverse()
    return out


def hydrate(rows: list) -> list:
    """Rebuild text-only model history from stored records (media is not stored)."""
    out = []
    for r in rows:
        if r["role"] == "user":
            role, txt = "user", r["text"]
            names = [a["name"] for a in (r["meta"].get("attachments") or [])]
            if names:
                txt = f"[Earlier the user attached: {', '.join(names)} (contents no longer available)]\n{txt}"
        elif r["role"] == "ai":
            role, txt = "model", r["text"]
        else:
            continue
        if out and out[-1].role == role:
            out[-1] = replace(out[-1], text=out[-1].text + "\n" + txt)
        else:
            out.append(Message(role, txt))
    return out


class Session:
    MAX_ATTACHMENTS = 40

    def __init__(self, sid: str, store=None):
        self.id, self.store = sid, store
        self.history = hydrate(store.messages(sid)) if store else []
        self.attachments: dict = {}
        self.created = time.time()
        self._pending: dict = {}

    def add_attachment(self, a: Attachment):
        if len(self.attachments) >= self.MAX_ATTACHMENTS:
            raise ValueError("Too many attachments in this session. Start a new session.")
        self.attachments[a.id] = a

    def model_history(self, extra=()) -> list:
        return compact(self.history + list(extra))

    def commit(self, turn: list, records: list):
        self.history.extend(turn)
        if self.store:
            self.store.add(self.id, records)

    async def request_confirmation(self, send, tool, args: dict, timeout: float = 120) -> bool:
        cid = uuid.uuid4().hex[:8]
        fut = asyncio.get_running_loop().create_future()
        self._pending[cid] = fut
        await send({"type": "confirmation_request", "id": cid, "tool": tool.name,
                    "args": args, "summary": tool.confirmation_summary(args)})
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            return False
        finally:
            self._pending.pop(cid, None)

    def resolve_confirmation(self, cid: str, approved: bool):
        fut = self._pending.get(cid)
        if fut and not fut.done():
            fut.set_result(approved)


class SessionStore:
    def __init__(self, store=None, max_sessions: int = 200):
        self.store, self._s, self.max = store, {}, max_sessions

    def get(self, sid: str) -> Session:
        if sid not in self._s:
            if len(self._s) >= self.max:  # RAM eviction only; text history reloads from the DB
                self._s.pop(min(self._s, key=lambda k: self._s[k].created))
            self._s[sid] = Session(sid, self.store)
        return self._s[sid]

    def drop(self, sid: str):
        self._s.pop(sid, None)
