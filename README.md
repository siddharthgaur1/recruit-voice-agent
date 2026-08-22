# recruit-agent

Outbound recruitment voice agent: a deterministic LangGraph slot-filling
conversation, LLM extraction (Groq, with a local/free fast path for the
common case), local voice (faster-whisper + Piper), a mock-provider dialer
with retry/backoff, and SQLite persistence. See `docs/RESULTS.md` for the
honest numbers (accuracy, latency, escalation rate, and the incidents found
along the way) and `CLAUDE_CODE_PROMPT.md` for the full phased build spec
this followed.

## Quickstart (5 minutes, no API key needed)

```
git clone <this repo> && cd recruit-agent
python -m venv .venv && .venv\Scripts\activate      # Windows; source .venv/bin/activate elsewhere
pip install -r requirements.txt
python demo.py
```

That's the whole pipeline in one script, using a scripted fake LLM (no
network, no API key): CSV lead import -> dialer with retry/backoff ->
real conversation state machine on answered calls -> a dashboard listing
-> a real SQL query ("Java candidates in Mumbai under 60 days notice").
Takes a few seconds. `pytest -q` (140 tests, also no API key needed) is the
other thing worth running cold.

Everything past this point (the real Groq-backed extractor, the persona
accuracy harness, the local voice loop, real CSV imports) needs a step or
two more setup -- covered section by section below, starting with `Setup`.

## Setup

```
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

Copy `env.example.txt` to `.env` and fill in `GROQ_API_KEY` (free tier key from
https://console.groq.com/keys). Nothing else in Phase 1–3 costs money.

Note: `llama-3.3-70b-versatile` (the model this spec originally targeted) has
been decommissioned on Groq's free tier. Default is now `openai/gpt-oss-120b`
(`GROQ_MODEL` in `.env` to change it) — re-check `client.models.list()` if
this one also disappears.

## Run the CLI

```
python -m src.cli
```

Type the candidate's replies at the `YOU:` prompt. The conversation walks
through six slots (interested, years of experience, domain, city, notice
period, confirmation) and ends with a row in `recruit_agent.db`
(`leads`, `call_attempts`, `conversations`, `candidate_profiles`).

## Persona simulator (Phase 2)

```
python -m src.sim.run_sim
```

Runs 8 scripted personas (`src/sim/personas.py`) through the real extractor
and prints a slot-accuracy report (personas 1, 2, 5, 6 — target >= 95%) and
an intent-accuracy report (personas 3, 4, 7, 8), plus every mismatch found.
Needs `GROQ_API_KEY` set — this makes real LLM calls, one per scripted turn.

## Local voice loop (Phase 3)

One-time model downloads (both fully local/free, no API keys):

```
python -m piper.download_voices en_US-lessac-medium --download-dir models
```

faster-whisper downloads its model automatically on first use (default
`small`, multilingual — needed for Hinglish; set `WHISPER_MODEL=base` in
`.env` for a faster/smaller download if `small` is too slow on your machine).

Run the server:

```
uvicorn src.api.main:app --reload
```

Open http://localhost:8000 , click **Start Call**, grant mic access, and talk.
The page shows the agent's replies and per-turn STT/LLM/TTS latency in
milliseconds. Barge-in (speaking while the agent is talking) cuts the agent's
audio immediately; ~7s of silence gets an "are you still there?", ~12s ends
the call. The completed call lands in SQLite exactly like the CLI/persona
paths.

## Dialer + scheduler (Phase 4)

```
python -m src.dialer.import_csv leads.csv        # columns: phone,name,dnc_flag
python -m src.dialer.demo                        # 20-lead deterministic retry demo
```

`src/dialer/provider.py` defines the `TelephonyProvider` ABC + `CallOutcome`
enum; `MockProvider` (weighted-random or scripted) is the only implementation
until Phase 5. `src/dialer/scheduler.py` has the retry backoff (+15min,
+2h, next-day-different-bucket, give up after 4), the 09:00-21:00 IST
calling-hours gate, and `DialerEngine` (places calls, updates
lead/call_attempt rows). `RecruitScheduler` wraps APScheduler with a
SQLAlchemy jobstore (same sqlite file) so retries survive a process restart.

`GET /dashboard` (on the same FastAPI app as Phase 3) lists every lead with
status, attempt count, next retry time, `terminal_reason`, and its captured
slots.

On `HUMAN_ANSWERED`, `DialerEngine` runs the actual LangGraph conversation
(via an injected `graph` + `conversation_replies` — scripted candidate
utterances, standing in for what a live telephony audio stream will supply
once Phase 5 exists) and the conversation's own outcome (COMPLETED /
NOT_INTERESTED / DNC) becomes the lead's final status — a lead is never left
sitting at IN_PROGRESS once a campaign resolves it. If the process crashes
mid-call, the FastAPI startup sweep resets any lead still IN_PROGRESS after
10 minutes back to QUEUED.

`status=UNREACHABLE` is a rollup; `leads.terminal_reason` records which
`CallOutcome` (or conversation outcome) actually caused it. `FAILED` is
treated as an infra error, not a lead problem: its own 5-minute backoff, and
it does **not** count against `leads.attempts` — capped at 3 consecutive
FAILED retries (`leads.failed_retry_count`, resets on any non-FAILED
outcome) before giving up and marking `UNREACHABLE`/`terminal_reason=FAILED`.

## Eval hardening

```
python -m src.sim.eval_report
```

Runs the 8-persona harness 5 times (per-run + aggregate fill-rate and
accuracy, and flags any (persona, slot/intent) that isn't stable across all
5 runs), then — prompt frozen, no tuning after this point — runs 5 held-out
personas (`src/sim/held_out_personas.py`: self-correcting, negotiating,
fragmentary/bad-line, out-of-order-contradicting, heavy Hinglish) once and
reports the raw result, then benchmarks extraction latency (p50/p95) over
50 calls. Extraction temperature is 0 (`src/agent/llm.py`). Needs
`GROQ_API_KEY`; makes ~250 real LLM calls.

Fill rate (`filled / attempted`) and accuracy (`correct / filled`) are
reported as two separate numbers everywhere, not folded into one — a slot
correctly left blank (e.g. a genuinely vague answer) counts toward neither.

## Latency + eval integrity (round 2)

Extraction was measured unusably slow for a live voice loop (p50~2.8s,
p95~3.8s). Four changes, cumulative:

1. `reasoning_effort="low"` on gpt-oss models (`src/agent/llm.py`).
2. A deterministic pre-pass (`src/agent/extractor.py::_fast_path`) handles
   short, unambiguous yes/no and number replies -- including Hinglish
   ("haan", "ji", "nahi") -- with **zero LLM calls**. Multi-slot, hedged
   ("maybe", "depends"), and terminal-intent-shaped replies still go to the
   LLM. This is also what fixed the earlier terse-"yeah" `confirmed` miss.
3. `EscalatingLLMClient` (`src/agent/llm.py`): tries `gpt-oss-20b` first,
   escalates to `gpt-oss-120b` only when the fast tier's own confidence is
   below 0.7 (llama-3.1-8b-instant, the spec's original pick, isn't
   available on this Groq account).
4. TTS pre-rendering (`src/voice/tts.py::Synthesizer.warm_cache`): the
   disclosure line, all 6 slot questions, and the literal opening line are
   pre-rendered at FastAPI startup and cached by exact text; only reprompts
   pay live-synthesis latency.

Measured (real per-turn latency across full persona conversations, not an
artificial fixed-slot benchmark):

| Stage | p50 | p95 |
|---|---|---|
| Baseline (no changes) | 2805ms | 3766ms |
| + reasoning_effort=low only | 1422ms | 4765ms |
| + fast path (single model) | 414ms | 4469ms |

`gpt-oss-120b` hit Groq's free-tier daily cap (200k TPD, exhausted by
cumulative eval usage) partway through the dual-tier benchmark — every
number from that point is **explicitly labeled FAST-TIER ONLY**
(`python -m src.sim.escalation_rate`, zero calls to the escalation model):

- Fast-tier-only accuracy matched (8-persona: 100%) or exceeded (held-out:
  96.7% vs. the earlier dual-tier run's 90.0%) the dual-tier numbers.
- Escalation rate (fast-tier confidence < 0.7, computed from its own
  reported confidence, no 120b calls needed): **4/39 real LLM turns
  (10.3%)**, concentrated almost entirely in the intentionally-ambiguous
  cases — Vague persona (42.9%), Negotiating (16.7%), the `yoe` slot in
  general (40%). Cooperative/Hinglish/Suspicious personas and the
  domain/interested/confirmed slots: 0%.
- On this small sample, the escalation tier looks like it's *mostly* not
  needed — but 39 real LLM turns is not enough to retire it on. Re-run the
  full dual-tier delta (`step-3`), the item-5 held-out 5x rerun, and the
  mic-loop test's escalation path after the Groq daily quota resets.

`GroqClient`/`EscalatingLLMClient` now track `total_tokens`/`call_count` so
a harness prints cumulative usage before it silently hits a quota wall.

A third provider, `GeminiClient` (`src/agent/llm.py`, `LLM_PROVIDER=gemini`
in `.env`), is wired up as a real fallback with its own separate quota —
not the default, verified with one live extraction call through
`build_llm_client()` end-to-end (JSON parsing, slot normalization, the
works).

### Domain: canonical tags, not free text

`src/agent/slots.py::normalize_domain_tag` maps free text to a fixed
`DOMAIN_TAGS` vocabulary (Java, Python, JavaScript, DevOps, Data Science,
QA/Testing, Cloud, Mobile, Backend, Frontend, Full Stack, Other) via an
alias table — casing/whitespace never reach the grader, and unmapped
answers fall back to `"Other"` rather than staying unfilled. The candidate's
original wording is preserved separately in `candidate_profiles.domain_raw`
(`CallState.domain_raw`, threaded through the graph and `save_conversation_result`).
This makes "Java candidates in Mumbai under 60 days notice" a real,
exact-match SQLAlchemy query — see `tests/test_candidate_query.py`.

### Mic-loop integration (real STT, not scripted text)

Ran a full conversation through the real pipeline (Piper synthesizes each
candidate line — the closest available substitute for a live mic in this
environment — faster-whisper transcribes it, the transcript, not the
original text, drives the actual agent turn).

**First run** (`vad_filter=False`, no homophone handling) surfaced two real
breaks: "Four" → "for years." (homophone) broke `yoe` extraction; "Java" (a
~0.5s clip) made faster-whisper hallucinate "Thanks for watching. See you
in the next video. Bye." — a known Whisper failure mode on short/low-energy
audio — which the extractor then reasonably (but wrongly) classified as a
hang-up, ending the call outright.

**After the Whisper safety fixes (below), re-ran the identical script —
full success:**

```
CANDIDATE said: 'Yes'          WHISPER heard: 'Yes.'          -> interested=True
CANDIDATE said: 'Four years'   WHISPER heard: 'Four years.'   -> yoe=4.0
CANDIDATE said: 'Java'         WHISPER heard: 'Java.'         -> domain='Java'  (no more hallucination)
CANDIDATE said: 'Mumbai'       WHISPER heard: 'Mumbai.'       -> city='Mumbai'
CANDIDATE said: 'Two months'   WHISPER heard: 'Two months.'   -> notice_period_days=60
CANDIDATE said: 'Yes, send it' WHISPER heard: 'Yes, send it.' -> confirmed=True
=== CALL ENDED: COMPLETED ===
```

`vad_filter=True` alone eliminated the hallucination in this run (Whisper
transcribed "Java." correctly instead of hallucinating); the homophone
fallback (see below) wasn't even needed here, but stays in as defense for
cases where it does occur.

## Latency diagnosis + Whisper safety (round 3)

### Whisper safety (a live-call bug, fixed first)

`src/voice/stt.py::Transcriber`:
- `vad_filter=True`, `condition_on_previous_text=False`,
  `no_speech_threshold=0.6` — the standard mitigation for Whisper
  hallucinating fluent-sounding text on silence/short clips.
- Clips under `MIN_AUDIO_DURATION_S=0.5s` never reach the model at all —
  returns `""` immediately (also skips per-segment `no_speech_prob>0.6`
  segments from whatever `vad_filter` still lets through).
- An `initial_prompt` biasing Whisper toward the actual call vocabulary
  (years of experience, tech stacks, Indian cities, notice period).

`src/agent/graph.py`: HANGUP can no longer be triggered by a bare intent
label alone (`_hangup_corroborated`) — it additionally requires the
utterance to contain an explicit hang-up phrase ("goodbye", "hang up",
"gotta go", etc.) AND confidence ≥ 0.7. A hallucinated/misheard transcript
that superficially resembles a sign-off no longer ends the call.
`tests/test_graph.py` covers all three cases (no corroboration, low
confidence, both present); `tests/test_stt_safety.py` proves a 0.3s clip
never reaches the model (`transcriber._model is None` after the call).

`src/agent/extractor.py::_resolve_number_homophones`: STT number-word
homophones (for→four, to/too→two, ate→eight) as a fallback within the fast
path's already-short, already-filtered replies. Known residual risk, left
in deliberately: "for now" → "four now" → 4.0 is a false positive this
doesn't catch — the homophone list is common enough words that resolving
them unconditionally elsewhere would misfire constantly.

### Latency diagnosis (`python -m src.sim.latency_diagnosis [fast|escalation|dual]`)

Reports LLM-call latency separately from end-to-end (the fast path changed
the turn population, so they're no longer the same thing), logs every
JSON-parse retry, and prints a full histogram.

**Fast tier only** (n=38 real LLM calls, 65 turns total):

```
end-to-end: n=65 min=0ms   p50=375ms p95=2438ms max=3438ms
llm-only:   n=38 min=157ms p50=453ms p95=2937ms max=3438ms

llm-only histogram:
     100-250ms:   1  ##
     250-500ms:  19  ########################################
    500-1000ms:   7  ##############
   1000-2000ms:   3  ######
   2000-4000ms:   8  ################
```

**Retry rate: 0/38 (0.0%)** — retries are not contributing to the tail at
all on the fast tier. The histogram is a smooth-ish spread with a real
second cluster at 2-4s, not a bimodal retry signature — reads as
provider-side latency variance/queueing, not the JSON-retry path.

**Escalation tier (gpt-oss-120b) and the dual-tier re-run are deferred to
after the Groq daily reset.** Confirmed twice in a row that it's genuinely
exhausted (199,907-199,920/200,000 both times, no headroom for even one
real benchmark call) — not the ~2-minute burst window it looked like
earlier. Your instinct that free-tier queueing near the cap contaminated
the earlier reasoning_effort=low benchmark (p95 got *worse*, which doesn't
make sense for that change alone) looks correct. Stopped polling — each
check call itself eats a sliver of the trickle-recovery, which was actively
working against getting real headroom back.

**The cap itself is a finding.** A single day of persona/eval testing (a
few hundred calls) fully exhausted `gpt-oss-120b`'s 200k-token daily
budget on this account. A production system making thousands of real calls
a day cannot run its escalation tier on this model/tier combination as-is
— that's a real constraint on whether gpt-oss-120b belongs in this
architecture at all, independent of whether it's technically the most
capable model available.

**Substitute check while gpt-oss-120b is unavailable:** ran the exact 4
escalating cases (identical system+user prompts) through `GeminiClient`
instead — not a benchmark, just answering "does escalation help here, or
is `None` the correct answer anyway?"

| Slot | Utterance | Fast-tier confidence | Gemini output | Expected |
|---|---|---|---|---|
| yoe | "few years" | 0.3 | `slots: {}` | `None` |
| yoe | "not sure exactly" | 0.6 | `slots: {}` | `None` |
| city | "somewhere in Maharashtra" | 0.4 | `slots: {}` | `None` |
| notice_period_days | "depends what you offer honestly" | 0.6 | `slots: {}` | `None` |

**All 4 expected values are `None`, and Gemini correctly returned an empty
slot dict on every one** — same functional outcome the fast tier already
reaches once its own confidence gate zeroes the slot below 0.7. On this
small sample, escalating changed nothing: both tiers agree the correct
answer is "unfillable," and the confidence threshold alone already gets
there without a second model call. This doesn't prove the escalation tier
is worthless (all 4 sampled cases happen to be genuinely-ambiguous ones;
none tests a case where the fast tier under-confidently missed something
real) — but it's a second independent signal, on top of the fast-tier-only
accuracy match from the previous round, pointing the same direction. The
real test (gpt-oss-120b specifically, plus the full dual-tier latency
histogram) is still deferred to after the Groq reset.

## Security

This is a prototype, not hardened for public exposure. `/dashboard` and
`/ws/call` are **unauthenticated by default** — fine for local-only use,
since the server binds to `127.0.0.1` by default and nothing outside your
own machine can reach it. If you need to expose it beyond localhost:

1. Set `RECRUIT_AGENT_API_KEY` in `.env`. This enforces a matching key on
   `/dashboard` (an `X-API-Key` header) and `/ws/call` (an `?api_key=...`
   query param — browsers can't set custom headers on a WebSocket
   handshake).
2. Run with `python -m src.api.main`, not a bare `uvicorn ...` invocation —
   it binds exactly to `BIND_HOST`/`BIND_PORT` (default `127.0.0.1:8000`),
   which is also what the startup check trusts. **If `BIND_HOST` is set to
   anything non-local and no API key is configured, the app refuses to
   start** rather than silently serving every lead's PII and burning your
   LLM quota to anyone who finds the port. A bare `uvicorn --host 0.0.0.0`
   invocation bypasses this check (the app can't see uvicorn's CLI flags),
   which is exactly why `python -m src.api.main` is the recommended path.
3. `/ws/call` is also rate-limited independently of auth
   (`MAX_CONCURRENT_CALLS`, `MAX_CALLS_PER_IP_PER_MINUTE`, both
   configurable) — a valid key doesn't stop a buggy client from opening
   enough connections to drain your Groq quota or peg the CPU running
   faster-whisper.
4. `speech_buffer` (the audio accumulated per utterance) is capped at 15
   seconds — logs a warning if it ever fires, since no real slot answer
   should run that long; if it does on a real call, that's a VAD problem
   worth investigating, not routine truncation.

None of this is a substitute for deploying behind a real reverse proxy /
auth layer if this is ever meant to be internet-facing.

## Phase 5 — real telephony (stubs only, gated)

`src/dialer/exotel.py` and `src/dialer/plivo.py` implement
`TelephonyProvider` but `place_call` only raises `NotImplementedError` —
no credentials, no network calls. Each file documents the real API shape
(endpoints, auth, how a real call's audio would reach `CallSession`, how
outcomes map to `CallOutcome`) as a comment, for whenever this is actually
wired up.

`docs/COMPLIANCE.md` covers DLT registration, NCPR/DND scrubbing, TCCCPR
calling-hours and consent rules, mandatory AI disclosure, recording
consent, and PII retention — with an open-questions section flagging what
needs legal sign-off before any live call. Written from secondary sources
plus one primary regulation PDF that turned out to be a scanned image and
couldn't be machine-verified; treat it as a briefing document, not legal
advice.

## Tests

```
pytest -q
```

All extractor/graph tests run against a scripted fake LLM client — no network
or API key required to run the suite.

## Status

Phases 1-4 built and eval-hardened; Phase 5 is stubs + compliance doc only
(`ExotelProvider`/`PlivoProvider` raise `NotImplementedError`, no real calls
placed or credentials wired up). See `CLAUDE_CODE_PROMPT.md` for the full
phased spec.
