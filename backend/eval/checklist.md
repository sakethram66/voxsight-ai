# Manual live-Gemini checklist

The scripted scenarios in `scenarios.py` prove the pipeline logic (routing, memory, tools,
confirmation) without an API key or network flakiness affecting pass/fail. They do NOT measure
real Gemini latency or real multimodal accuracy — do that here, with a live key, before the demo.

For each row: run it in the UI, time it with a stopwatch/browser devtools, and judge the reply yourself.

| # | Scenario | Steps | Target latency | Actual latency | Correct? | Notes |
|---|---|---|---|---|---|---|
| 1 | Voice-only | Ask a factual question by voice | ~2s | | | |
| 2 | Image + voice | Upload a photo, ask "what is this?" | ~2-4s | | | |
| 3 | Screenshot + voice | Upload an error screenshot, ask what's wrong, then "how do I fix it?" with NO re-upload | ~2-4s | | | context must persist |
| 4 | PDF + voice | Upload a PDF, ask "summarize this" | ~3-5s | | | |
| 5 | Camera + voice | Start camera, point at an object, ask "what is this?" | ~2-4s | | | |
| 6 | Screen + voice | Share screen, ask "what's wrong here?" | ~2-4s | | | |
| 7 | Multi-turn multimodal | 3+ follow-ups on one screenshot | | | | no repeated uploads |
| 8 | Multiple images | Upload 2 images, ask to compare | | | | |
| 9 | Tool calling | "what's 144 divided by 12 times pi" | | | | uses calculator |
| 10 | Confirmation flow | "remember this as a note: ..." then Confirm | | | | file appears in backend/data/notes |
| 11 | Confirmation decline | Same, then Cancel | | | | no file written |
| 12 | Web search | "search the web for ..." | | | | shows source links |
| 13 | Error recovery | Disconnect network mid-request | | | | UI shows an error, doesn't crash |

Fill in Actual latency / Correct? / Notes during a real run, then copy the summary into `report.json`'s
`measured` block only if you want it alongside the scripted numbers — keep the two clearly labeled.
