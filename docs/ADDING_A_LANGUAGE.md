# Adding a language

Today the agent handles **English and Hinglish**. Hinglish works because the
Hindi words that matter for slot-filling are in the normalizer tables, not
because there is a general multilingual path — that distinction matters if
you are about to add Tamil, Telugu, Marathi or Bengali.

A request to switch language is currently *detected and ended politely*:
`LANGUAGE_SWITCH_REQUEST` (`src/agent/extractor.py`) closes the call via
`src/agent/graph.py`. That is a deliberate stopgap, not support.

This document lists every seam a real second language has to pass through.
It is written so the work can be scoped honestly — none of it is stubbed
out or half-built anywhere in the tree.

## The five seams

### 1. Number words — `src/agent/slots.py::_WORD_NUMBERS`

Drives both `normalize_yoe` and `normalize_notice_period_days`. Currently
English plus Hinglish (`ek`, `do`, `teen`, `char`, `paanch`…). A new
language needs its digits 0–12 plus the common round numbers, in the
romanized spelling **your STT will actually emit** — which is not always the
dictionary spelling, and is worth checking against real Whisper output
before writing the table.

### 2. Notice-period units — `src/agent/slots.py::_NOTICE_UNIT_TO_DAYS`

Day/week/month/year in the target language (`din`, `hafte`, `mahine`,
`saal` are the Hinglish entries). Note both tables feed a compiled regex
(`_NOTICE_QTY_UNIT_RE`) built at import time by longest-first alternation,
so adding entries is safe, but adding one that is a *prefix* of another
needs the ordering to stay longest-first.

### 3. City aliases — `src/agent/slots.py::_CITY_ALIASES`

Maps to the canonical form (`bombay` → `Mumbai`). A new language mostly
means new *spellings* of the same cities, not new cities. Anything unmatched
falls through to `.title()`, so a missing alias silently produces a
near-miss like `"Bengaluru"` vs `"Bangalore"` — which is exactly the class
of bug `tests/test_persona_ground_truth.py` guards the answer keys against.

### 4. STT — `src/voice/stt.py`

Two things:
- `language=None` (line ~64) lets Whisper auto-detect. That is correct for
  code-switching, but auto-detect on a short, noisy clip is itself a
  hallucination risk — see the Whisper incident in `docs/RESULTS.md`. Pinning
  `language="ta"` is more reliable *if* you know the call is monolingual.
- `initial_prompt` biases Whisper toward the call's vocabulary. It is
  currently English-only and must be rewritten in the target language, or it
  works against you.

The `small` multilingual model is already the default (not `small.en`) —
that part needs no change.

### 5. TTS — `src/voice/tts.py` + the agent's own lines

The larger half of the work.
- Piper needs a **voice model per language** (`python -m piper.download_voices
  <voice> --download-dir models`). There is no Piper voice for every Indian
  language; check availability before promising one.
- `settings.piper_model_path` is a single path, so real support means making
  voice selection per-call rather than per-process.
- Every fixed line — the disclosure, all six slot questions, the reprompts,
  the fillers in `src/api/session.py::FILLER_PHRASES` — needs translating.
  These are pre-rendered at startup by `Synthesizer.warm_cache`, so the
  cache becomes per-language too.
- `settings.disclosure_text` is legally load-bearing: `docs/COMPLIANCE.md`
  requires an AI disclosure, and a translated one needs the same sign-off
  as the English original. **Do not machine-translate that line.**

## What this does not need

The conversation graph, the extraction prompt's JSON contract, the dialer,
the scheduler and the schema are all language-agnostic. Nothing above
touches `src/agent/graph.py`'s structure or the database.

## Suggested order

1. Tables (1–3) with unit tests. Fully testable with no audio and no API key.
2. Personas in the target language added to `src/sim/held_out_personas.py`,
   run through the real extractor. Measures the text path alone.
3. STT and TTS (4–5) last, since they need model downloads and a human ear.

Stopping after step 2 is a legitimate place to stop: it gives a measured
text-layer result rather than an untested end-to-end claim.
