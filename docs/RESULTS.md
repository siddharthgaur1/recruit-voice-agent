# Results

**What this is:** an outbound recruitment voice agent that cold-calls a
candidate, runs a fixed 6-slot screening script (interested, years of
experience, domain, city, notice period, confirmation) through a
deterministic LangGraph state machine, and stores the structured result —
built with zero paid services (Groq/Gemini/Ollama free tiers, local
faster-whisper + Piper for voice, SQLite, a mock telephony provider). This
document is the honest numbers from actually running it, not projections.

Every figure here came from a real command (`python -m src.sim.eval_report`,
`python -m src.sim.escalation_rate`, `python -m src.sim.latency_diagnosis`,
or a manual mic-loop run) — see each script for how to reproduce it. Where a
number is small-sample or unresolved, that's stated, not smoothed over.

## Accuracy

Extraction runs on `openai/gpt-oss-20b` (fast tier), escalating to
`openai/gpt-oss-120b` only when the fast tier's own confidence is below
0.7. Two metrics, always reported separately: **fill rate** (did the
extractor commit to a value at all) and **accuracy** (of the ones it
committed to, how many were right). A slot correctly left blank (a
genuinely vague answer) counts toward neither.

| Persona set | fill rate | accuracy (of filled) | overall correct/attempted |
|---|---|---|---|
| 8 frozen personas (dual-tier, 5-run aggregate) | 21/24 (87.5%) | 100.0% | 120/120 (100.0%) |
| 5 held-out personas, untuned (dual-tier, one run) | 26/30 (86.7%) | 92.3% | 27/30 (90.0%) |
| 5 held-out personas, untuned (fast-tier-only rerun) | 28/30 (93.3%) | 96.4% | 29/30 (96.7%) |

Stability: identical across all 5 runs of the 8-persona set (0 unstable
cases). Held-out mismatches, both runs: `Fragmentary` persona's terse
one-word answers (a bare "yeah" for `confirmed` was missed on one run,
correctly caught on another — genuine non-determinism at `temperature=0`,
observed directly); `Heavy-Hinglish`'s domain phrasing ("Python and cloud"
vs "Python, Cloud") is now moot — domain canonicalization (below) collapses
both to the same tag.

## Escalation rate: is the 120b tier earning its keep?

Computed from the fast tier's own reported confidence, zero calls to the
heavier model: **4/39 real LLM turns (10.3%)** would escalate, concentrated
almost entirely in deliberately-ambiguous personas — `Vague` (42.9%),
`Negotiating` (16.7%), the `yoe` slot generally (40%). `Cooperative`,
`Hinglish`, `Suspicious`, and the `domain`/`interested`/`confirmed` slots:
0%.

**All 4 escalating cases had an expected value of `None`** (the correct
answer was "unfillable," not a specific value). Ran the same 4 prompts
through `GeminiClient` as a stand-in for the unavailable 120b tier (its
daily quota was exhausted — see below): Gemini also returned empty slots
on all 4, matching the fast tier's own confidence-gated outcome exactly. On
this small sample, escalating changed nothing — both tiers agree, and the
confidence threshold alone already gets there. This is suggestive, not
conclusive: 4 cases is not enough to retire the tier on, and none of the 4
tests whether the fast tier under-confidently missed a *real* value the
escalation tier would have caught. The direct gpt-oss-120b comparison is
still pending a real quota reset.

## Latency

Target: extraction p95 < 800ms. **Not met.**

| Stage | p50 | p95 | n |
|---|---|---|---|
| Baseline (no changes) | 2805ms | 3766ms | 50 |
| + `reasoning_effort=low` only | 1422ms | 4765ms | 50 |
| + deterministic fast path (small sample) | 453ms | 2937ms | 38 |
| + fast path, at scale (run A) | 2453ms | 3688ms | 156 |
| + fast path, at scale (run B, ~21min later) | 2422ms | 3344ms | 232 |

The two at-scale runs (~21 minutes apart, same evening) landed within
~1-3% of each other: same p50, same ~72-75% of calls clustered in the
2000-4000ms histogram bucket, **0/156 and 0/232 JSON-parse retries** in
both. That rules out the retry path conclusively (0% at n>350 combined),
but **matching shape across two runs 21 minutes apart does not distinguish
structural-per-prompt from queueing** — both hypotheses predict the same
result when the samples are taken 21 minutes apart under identical load.
That was flagged as a limitation and correctly called out as such; the
initial write-up still leaned toward "structural" from that evidence,
which was wrong to do.

**The actual discriminator** (`python -m src.sim.latency_diagnosis fast
150`, run once, no new API cost since the fast tier isn't quota-limited):
the same (slot, utterance) prompt repeats every pass across the persona
scripts, so its latency can be compared against itself across passes,
independent of which prompt it is.

| | latency |
|---|---|
| stdev across all calls | 1024ms |
| stdev of a single repeated prompt against itself, averaged across 34 distinct prompts | 1010ms |
| stdev between different prompts' mean latencies | 428ms |

A prompt's own latency swings pass-to-pass by almost as much as the entire
population swings (1010ms vs. 1024ms) — the identical utterance
`"not interested, thanks"` ran in as little as ~600ms on one pass and over
2500ms on another (stdev 1209ms across 4 repeats). Meanwhile the spread
*between* different prompts' averages is under half that (428ms). **This
resolves it: the latency is time-dependent (provider-side queueing/serving
variance), not a property of the prompt.** Longer or more "complex" slot
questions are not consistently slower — the same exact call is fast one
moment and slow the next.

**What did move the needle:** fast-pathed turns (short, unambiguous
yes/no/number replies, ~40% of turns in a typical conversation) went from
~2.5s to ~0ms, since they never call an LLM at all. The remaining p95 is
entirely a property of the ~60% of turns that still need a real LLM call.

**Filler audio** doesn't fix the underlying latency — it hides it. Measured
directly: perceived silence (time from end-of-utterance to *any* audio
back) went from ~2984ms to ~0ms (a pre-rendered, rotating acknowledgement
plays immediately; the real reply follows once processing actually
finishes, 2-3s later, same as before).

**Local Ollama (llama3.2:3b) was spiked and rejected.** On this machine
(CPU-only, no GPU): cold call 28.2s, warm calls 4.0-5.9s each — 5-7x over
budget even warm, and this is a *smaller* model than the Groq fast tier.
It also hallucinated slot values not present in the input (`domain: "IT"`,
`city: "Mumbai"` from an utterance that only mentioned years of
experience). `OllamaClient` is left in the codebase behind the same
`LLMClient` interface, unused and undefaulted — the latency finding is
scoped to this CPU-only host; a GPU-equipped box would likely change the
verdict entirely.

**gpt-oss-120b's 200k-token daily quota was fully exhausted by this
session's own testing** — confirmed twice, ~199,900-199,920/200,000 used,
no headroom for even one more real call. That's a finding in itself: a
single day of persona/eval traffic (a few hundred calls) maxed out the
escalation tier's entire daily budget on this free-tier account. Whatever
its accuracy, that quota profile is hard to reconcile with a system meant
to place many real calls a day.

## The Whisper hallucination incident

First real mic-loop run (`vad_filter=False`, no homophone handling, no
`initial_prompt`):

```
CANDIDATE said: 'Four years'   WHISPER heard: 'for years.'        -> yoe extraction FAILED
CANDIDATE said: 'Java'         WHISPER heard: 'Thanks for watching. See you in the next video. Bye.'
                                                -> misclassified as NOT_INTERESTED, call ended wrongly
```

Root cause: faster-whisper hallucinating fluent, plausible-sounding text on
short/low-energy audio (~0.5s clip) is a known failure mode, compounded by
a homophone miss on a legitimate word ("four" → "for").

Fix, in order of what actually mattered:
1. `vad_filter=True`, `condition_on_previous_text=False`,
   `no_speech_threshold=0.6` — this alone eliminated the hallucination on
   re-run.
2. Clips under 0.5s never reach the model (`MIN_AUDIO_DURATION_S`); a
   0.3s test clip is proven (via `_model is None` after the call) to never
   even load the model.
3. HANGUP can no longer be triggered by a bare intent label: requires
   confidence ≥ 0.7 **and** an explicit corroborating phrase ("goodbye",
   "hang up", etc.) in the actual words. A hallucinated sign-off no longer
   ends a call.
4. Homophone fallback (for→four, to/too→two, ate→eight) and an
   `initial_prompt` biasing Whisper toward the call's actual vocabulary —
   neither was needed on the successful re-run, but both stay in as
   defense; the homophone list is a known, accepted false-positive risk
   ("for now" → "four now" → `4.0`) scoped to the fast path's
   already-short, already-filtered replies.

Re-run of the identical script after the fix: all 6 slots filled
correctly, call reached `COMPLETED`, no hallucination.

## Domain canonicalization

`domain` is now a fixed 12-tag vocabulary (Java, Python, JavaScript,
DevOps, Data Science, QA/Testing, Cloud, Mobile, Backend, Frontend, Full
Stack, Other) via an alias table; the candidate's literal words are kept
separately in `candidate_profiles.domain_raw`. This makes "Java candidates
in Mumbai under 60 days notice" a real, exact-match SQL query — demonstrated
live in `python demo.py` (STEP 5) and `tests/test_candidate_query.py`.

## What has NOT been measured

`src/sim/held_out_personas.py` grew from 5 personas to 12 (ids 106-112:
fresher, serving-notice, asks-to-repeat, over-explainer,
reluctant-then-willing, career-switcher, fractional-units). **None of the
seven has been run.** Every accuracy figure above is still the original
5-persona result. Their answer keys are checked for internal consistency
by `tests/test_persona_ground_truth.py` (canonical city/domain forms,
correct types) -- that is a typo guard on the answer key, not a
measurement of the extractor.

Two of the seven encode a deliberately contested ground truth, and are
expected to be hard:
- `Career-switcher` -- "I was in QA for years but I've been doing Kubernetes
  and CI/CD for the last two" is keyed `DevOps`. Feeding that whole sentence
  to `normalize_domain_tag` returns `QA/Testing`; the key is the current
  role, which is what the question actually asks.
- `Fractional-units` -- "one and a half years" is keyed `1.5`. A
  first-integer-wins parse returns `1.0`.

## What's unresolved

- The real gpt-oss-120b vs. fast-tier-only accuracy/latency delta (blocked
  on the daily quota; substituted Gemini for the escalation-rate question
  only, not latency).
- Whether the queueing variance (now confirmed as the cause of the p95
  tail, see above) itself varies by time of day — resolving *that* the same
  latency is queueing rather than structural doesn't establish when the
  queueing is worst; a genuine off-peak-vs-peak comparison hasn't been run.
