"""Text-only conversation history (SQLite). Media bytes are never persisted."""
import json
import sqlite3
import threading
import time
from pathlib import Path


class Store:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock:
            self.db.executescript("""
              CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, title TEXT, created REAL, updated REAL);
              CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT,
                role TEXT, text TEXT, meta TEXT, ts REAL);
              CREATE INDEX IF NOT EXISTS idx_msg_session ON messages(session_id, id);""")

    def add(self, sid: str, records: list):
        now = time.time()
        with self.lock:
            if not self.db.execute("SELECT 1 FROM sessions WHERE id=?", (sid,)).fetchone():
                first = next((r["text"] for r in records if r["role"] == "user"), "New conversation")
                self.db.execute("INSERT INTO sessions VALUES(?,?,?,?)", (sid, first[:48], now, now))
            for r in records:
                self.db.execute("INSERT INTO messages(session_id,role,text,meta,ts) VALUES(?,?,?,?,?)",
                                (sid, r["role"], r["text"], json.dumps(r.get("meta") or {}, default=str), now))
            self.db.execute("UPDATE sessions SET updated=? WHERE id=?", (now, sid))
            self.db.commit()

    def messages(self, sid: str) -> list:
        with self.lock:
            rows = self.db.execute("SELECT role,text,meta,ts FROM messages WHERE session_id=? ORDER BY id", (sid,)).fetchall()
        return [{"role": r[0], "text": r[1], "meta": json.loads(r[2] or "{}"), "ts": r[3]} for r in rows]

    def sessions(self) -> list:
        with self.lock:
            rows = self.db.execute("SELECT id,title,updated FROM sessions ORDER BY updated DESC LIMIT 100").fetchall()
        return [{"id": r[0], "title": r[1], "updated": r[2]} for r in rows]

    def delete(self, sid: str):
        with self.lock:
            self.db.execute("DELETE FROM messages WHERE session_id=?", (sid,))
            self.db.execute("DELETE FROM sessions WHERE id=?", (sid,))
            self.db.commit()
