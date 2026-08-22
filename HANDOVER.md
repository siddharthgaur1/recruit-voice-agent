# Handover

**Repo:** <repo-url>

## What this is

An outbound recruitment voice agent that cold-calls a candidate, runs a
fixed 6-slot screening script (interested, years of experience, domain,
city, notice period, confirmation) through a deterministic LangGraph state
machine, and stores the structured result — built with zero paid services
(Groq/Gemini/Ollama free tiers for LLM extraction, local faster-whisper +
Piper for voice, SQLite, a mock telephony provider with retry/backoff).

## Start here

```
python demo.py      # full pipeline, no API key needed: CSV -> dialer -> conversation -> dashboard -> query
pytest -q           # 140 tests, no API key needed
```

Then read, in this order:
1. `docs/RESULTS.md` — accuracy, fill rate, latency, escalation rate, and
   two incidents worth knowing about (a Whisper hallucination that would
   have hung up on a live candidate, and a model quota that a single day
   of testing exhausted).
2. `docs/COMPLIANCE.md` — what's required before any real call can be
   placed (DLT registration, DND/NCPR, TRAI calling hours, AI disclosure,
   recording consent, data retention) and an explicit open-questions list
   for legal review.
3. `README.md` — the quickstart above, plus setup for the parts that need
   an API key or a model download (real Groq extraction, the persona
   accuracy harness, the local voice loop).
4. `CLAUDE_CODE_PROMPT.md` (one directory up from this repo) — the
   original phased build spec this followed.

## Status

- **Phases 1-4 built and eval-hardened**: text conversation engine, persona
  accuracy harness, local voice loop, dialer + scheduler.
- **Phase 5 is deliberately stubbed, not implemented.** `ExotelProvider`
  and `PlivoProvider` raise `NotImplementedError` — no credentials, no
  network calls, no real call has been placed. This is gated on the
  compliance work in `docs/COMPLIANCE.md`, most importantly DLT
  registration and legal sign-off on consent/calling-hours/disclosure
  wording. **Do not wire up real telephony credentials without reading
  that document first.**
- Extraction defaults to Groq (`gpt-oss-20b` fast tier, escalating to
  `gpt-oss-120b` on low confidence); Gemini and a local Ollama spike are
  both wired up behind the same interface but not the default — see
  `docs/RESULTS.md` for why (Ollama on CPU-only hardware was measured too
  slow and less accurate; see that doc before assuming a GPU host would
  need re-testing rather than just re-enabling it).
- Extraction p95 latency did not hit its original 800ms target even after
  optimization; masking it with filler audio (near-instant, `docs/RESULTS.md`)
  was more effective than any attempt to actually reduce it.

## What's not in the repo

- A `.env` with real API keys — copy `env.example.txt` and fill in your
  own (see that file for where to get each key).
- The Piper voice model (`models/en_US-lessac-medium.onnx`) — one command
  to download, in `README.md`'s voice-loop section.
- Any real candidate data, recordings, or call history — nothing has been
  placed against a real phone line at any point in this project.
