# VoxSight AI
**HEAR IT. SEE IT. UNDERSTAND IT. ACT ON IT.**

A real-time voice + multimodal AI agent. Talk to it while showing it a screenshot, PDF, your
camera, or your screen; ask follow-ups without re-uploading anything; it can call tools
(calculator, date/time, web search) and take one real, confirmation-gated action (save a note,
optionally send an email) — never claiming an action happened unless it actually did.

## Run it
```
cp .env.example backend/.env       # add GEMINI_API_KEY: https://aistudio.google.com/apikey
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload      # http://localhost:8000

cd frontend && npm install && npm run dev   # http://localhost:5173 (dev, hot reload)
```
For a single-process demo build the UI once and let FastAPI serve it:
`cd frontend && npm run build`, then just run uvicorn and open **http://localhost:8000**.

Voice needs Chrome, Edge, or Safari (Web Speech API) and a mic-permitted, HTTPS-or-localhost origin.
Everything else (upload, camera, screen share, tools) works without voice too — typing always works.

## Test
```
cd backend && pip install -r requirements-dev.txt && python -m pytest      # backend tests
cd backend && python -m eval.scenarios                                     # 10 scripted eval scenarios -> eval/report.json
cd frontend && npm test                                                    # speech/TTS chunking unit tests
```
`eval/checklist.md` is the manual pass-through-the-UI checklist for real Gemini latency/accuracy —
the automated eval uses a scripted fake model so it's deterministic and needs no API key; its
"measured" numbers are explicitly labeled as harness-only, never conflated with `eval/checklist.md`'s
real numbers or with `TARGETS`.

## Demo flow (matches the brief's Section 17)
1. Open the app, tap the mic.
2. Upload a screenshot of an error (or paste one with Ctrl/Cmd+V).
3. Say "VoxSight, look at this and tell me what's wrong." → it analyzes voice + image together.
4. Ask "how do I fix it?" with **no re-upload** → it still has the screenshot in context.
5. Try a second modality: upload a PDF and ask it to summarize, or open the camera/screen share.
6. Ask something needing a tool ("what's 18% of 245?", "search the web for the FastAPI release notes").
7. Say "remember this as a note" → a Confirm/Cancel dialog appears; nothing is written until you confirm.

## What's implemented vs. what needs setup
- **Implemented and real:** streaming Gemini multimodal chat (text/image/PDF/text-docs), browser
  STT/TTS with barge-in and hands-free mode, camera + screen snapshot capture, session memory with
  context fusion and compaction, calculator/date-time/web-search tools, a real `save_note` action
  (writes a file), full error handling (mic/camera/screen permission, bad files, API/network/timeout,
  tool failure), conversation history sidebar (text-only, persisted in SQLite), eval harness.
- **Needs setup, not fake:** `send_email` only appears in the tool list once `SMTP_*` is set in
  `backend/.env` — until then it's simply absent, not a non-functional button. Live audio/video
  *streaming* to Gemini isn't implemented; camera/screen use timed snapshots (per the brief's
  "controlled frame processing" guidance) rather than continuous video, to keep latency and cost bounded.

## Architecture
```
Browser (React)                     FastAPI backend
 mic → Web Speech STT  ──text──▶     WebSocket /ws/{session}
 speechSynthesis  ◀──stream text──   Agent (tool loop, MAX_STEPS, timeouts, retry)
 camera/screen → snapshot ──────▶    Session (history + attachment cache + compaction)
 upload → POST /api/.../attachments  Store (SQLite: text-only conversation log)
                                     ToolRegistry (calculator, get_datetime, web_search,
                                                   save_note, [send_email])
                                     ProviderManager (Gemini → Groq → OpenRouter)
                                       ├── Gemini adapter (Google types/auth)
                                       └── OpenAI-compatible adapters (Groq/OpenRouter)
```
- **New provider = one file.** Everything outside `app/providers/gemini.py` speaks the neutral
  types in `app/providers/base.py` (`Message`, `MediaPart`, `ToolCall`, ...). Add
  `app/providers/openai.py` implementing `LLMProvider.stream()` and add one branch in
  `app/providers/__init__.py`; the agent, tools, session, and UI need no changes.
- **Context fusion** happens in `agent.build_user_message()`: the transcript/typed text, every
  image/PDF, and extracted document text are combined into **one** Gemini message per turn, plus
  the full prior conversation, so "this/it/here" resolve correctly.
- **Session memory:** `session.py`'s `compact()` keeps only the newest camera frame and newest
  screen frame (older live frames are stale) plus the last 8 uploaded files, so a long session
  can't blow up the context window; `store.py` persists text-only history to SQLite (media bytes
  are never written to disk) so a page reload doesn't lose the conversation.
- **Confirmation gating:** `session.request_confirmation()` suspends the tool loop on an
  `asyncio.Future` until the UI sends `{"type":"confirm", approved}`; declining or timing out
  (120s) returns an explicit "NOT performed" tool result to the model, so it can never claim success.
- **Never crashes:** every tool call has an individual timeout and try/except; model calls have a
  request timeout and one quiet retry only on classified-transient errors (429/5xx/network) before
  any text has streamed; WebSocket send failures are swallowed, not raised.

## Folder structure
```
backend/app/
  providers/   base.py (neutral types/capabilities) · manager.py · gemini.py
               openai_compatible.py (Groq/OpenRouter) · testing.py (fakes for tests/eval)
  tools/       base.py (Tool, ToolRegistry) · builtin.py (calculator/datetime/web_search)
                        · actions.py (save_note, send_email — the confirmation-gated real actions)
  agent.py     system prompt, context fusion, streaming tool loop
  session.py   per-connection state, attachment cache, context compaction, confirmation futures
  store.py     SQLite text-history persistence
  uploads.py   file sniffing/validation (images, PDF, .docx, text/code) + live-frame validation
  main.py      FastAPI app: /api/health, /api/sessions*, /ws/{session}
backend/eval/  scenarios.py (10 scripted end-to-end scenarios) · checklist.md (manual live-Gemini pass)
frontend/src/
  hooks/       useVoice (STT/TTS/barge-in) · useCapture (camera/screen) · useAgent (WebSocket) · useSettings
  lib/         speech.js (sentence chunking for TTS, unit-tested) · image.js (frame capture)
  components/  Stage, Messages, Composer, Sidebar, ConfirmModal, SettingsPanel, StatusStrip, Waveform
```

## Config (`backend/.env`, see `.env.example`)
`AI_PROVIDER` defaults to `auto` and tries Gemini, Groq, then OpenRouter. Set it to `gemini`, `groq`,
or `openrouter` to use only that provider. `GEMINI_API_KEY` and `GEMINI_MODEL` (default
`gemini-3.8-flash`) configure the primary provider. Optional `GROQ_API_KEY`/`GROQ_MODEL` and
`OPENROUTER_API_KEY`/`OPENROUTER_MODEL` enable fallbacks. Provider keys are backend-only.

Fallback providers declare their capabilities; unknown model IDs are treated as text-only and
without tool support. PDF binaries stay on Gemini unless a configured provider explicitly supports
documents. `CORS_ORIGINS`, `REQUEST_TIMEOUT_S`, `TOOL_TIMEOUT_S`, `VOXSIGHT_DB`,
`VOXSIGHT_NOTES_DIR`, and optional `SMTP_HOST`/`SMTP_PORT`/`SMTP_USER`/`SMTP_PASSWORD`/`SMTP_FROM`
to enable `send_email` are also supported.
