# Compliance notes for real outbound calling (Phase 5)

Status: **nothing in this repo places a real call.** `ExotelProvider` and
`PlivoProvider` (`src/dialer/exotel.py`, `src/dialer/plivo.py`) are stubs
that raise `NotImplementedError`. This document exists so that wiring them up
is a deliberate, informed decision, not an accident. It is written by an AI
coding assistant from public secondary sources plus one primary regulation
PDF that could not be machine-read (see caveats below) — **it is not legal
advice and every item here needs sign-off from someone qualified to give it**
before a single real call is placed.

---

## 1. DLT (Distributed Ledger Technology) registration

Under the Telecom Commercial Communications Customer Preference Regulations,
2018 ("TCCCPR 2018", TRAI, issued under the TRAI Act 1997, most recently
amended by regulation notified Feb 2025), any entity sending commercial
voice calls or messages must register on the telecom-operator-run DLT
platform before it can legally originate that traffic:

- Register as a **Principal Entity (PE)** with a DLT operator (each major
  telco — Airtel, Jio, Vi, BSNL — runs/participates in a shared DLT
  ecosystem).
- Register a **header** (sender identity) tied to the business category of
  the calls being made — for this project, recruitment outreach.
- Register the **call flow / script template** actually used, matching the
  header's declared category. The disclosure line, the six-slot script, and
  any variation of it need to be filed, not improvised at call time.
- Use the correct **numbering series**: `140` is reserved for promotional
  voice calls, `160` for transactional/service calls to existing customers.
  A recruitment cold-call to someone who has no prior relationship with the
  company is promotional traffic → `140` series, not a regular business
  number.

**Practical implication for this codebase:** `ExotelProvider`/`PlivoProvider`
would need a DLT-registered virtual number (`exophone` / `from_number`)
before `place_call` can be implemented at all — this is a prerequisite, not
something the code can route around.

## 2. DND / NCPR scrubbing

The **National Customer Preference Register (NCPR)**, formerly the National
Do-Not-Call (NDNC) registry, lets any subscriber opt out of promotional
calls (dial or SMS `1909` to register or check a number's status). TCCCPR
2018 requires telemarketers to check the NCPR before placing promotional
calls and prohibits calling registered numbers for promotional purposes.

- `leads.dnc_flag` in this schema is our own opt-out bit (set when a
  candidate says "stop calling me" etc., per `_is_opt_out` in
  `src/agent/graph.py`) — it is **not** the same as NCPR registration. A
  lead can be NCPR-registered nationally without ever having talked to us.
- A real integration needs a periodic (TRAI expects this checked close to
  call time, not once at import) NCPR scrub of the lead list, before
  `DialerEngine` ever calls `provider.place_call`. Access to the NCPR
  matching API is only granted to TRAI-registered telemarketers/PEs — this
  is another consequence of item 1, not a separate signup.
- Since 2023, TRAI has also been rolling out a **Digital Consent Acquisition
  (DCA)** facility (per TRAI direction dated 2 Oct 2023 under TCCCPR) so
  telecom operators can record a subscriber's specific, revocable digital
  consent to receive commercial communication from a given PE/header — the
  Feb 2025 amendment reportedly removed the older "existing business
  relationship" implied-consent carve-out, meaning consent has to be
  affirmative and current, not inferred from a candidate having applied to
  a job six months ago. **This specific point needs primary-source
  confirmation** (see Open Questions).

## 3. TRAI TCCCPR calling hours and consent rules

- Commercial/promotional voice calls are restricted to **09:00–21:00**
  under TCCCPR 2018 — calls outside that window, and on national holidays,
  are a direct violation regardless of DND status. This matches the
  09:00–21:00 IST gate already implemented in
  `src/dialer/scheduler.py::is_within_calling_hours` — good, but that gate
  currently has no connection to a real DLT/consent check, since
  `MockProvider` doesn't need one.
- Secondary sources (marketing blogs, not the primary regulation text — see
  caveats) claim a **narrower 10:00–19:00 window specifically for
  AI/automated voice calls** under a 2025 TRAI amendment. This directly
  contradicts the more widely-corroborated 09:00–21:00 general rule, and I
  could not verify it against TRAI's own gazette text (the PDF is a scanned
  image, not machine-readable — see caveats). **Treat this as unverified
  and confirm the real window with counsel/TRAI's published circular before
  building against either number.**
- Access providers (telcos) face penalties up to ~₹50 lakh/month per
  licensed service area for failing to curb unsolicited commercial
  communication; the Telecommunications Act, 2023 backs this with a graded
  penalty framework. These penalties land on the telecom operator/PE
  relationship, not just the calling company, which is why DLT registration
  (item 1) is the load-bearing prerequisite for everything else here.

## 4. Mandatory AI disclosure

This codebase already treats AI disclosure as non-negotiable at the
application layer: `settings.disclosure_text` is spoken as the literal
first agent utterance (`src/agent/graph.py::opening_message`), configured
in `.env`, never hardcoded past that one config value, and re-stated if the
candidate asks "who is this" mid-call.

On the regulatory side: secondary sources describe a trend of TRAI
increasingly folding AI-generated/pre-recorded ("robo") calls into the same
UCC framework as human telemarketing, with an expectation that the
automated nature of the call is disclosed **at the very start**, not buried
later in the script. I was not able to confirm a specific, citable clause
number or effective date for this from TRAI's primary text (again, the PDF
would not machine-extract). Until that's confirmed:

- Keep the disclosure-first behavior this app already has — it's a safe
  default regardless of exactly which clause mandates it.
- Get the exact wording checked by counsel: a generic "this is an automated
  assistant" line may or may not satisfy whatever the specific regulatory
  language turns out to require (e.g. naming the company, a callback
  number, an opt-out mechanism in the same breath).

## 5. Call recording consent

- The **Digital Personal Data Protection Act, 2023 (DPDP Act)** treats a
  voice recording as **personal data** whenever a living individual can be
  identified from it. Recording a candidate's voice makes this company a
  **Data Fiduciary** under the Act, which requires:
  - clear, itemized **notice** before or at the time personal data is
    collected (what's recorded, why, how long it's kept, who it's shared
    with),
  - **consent** that is free, specific, informed, unconditional, and
    unambiguous — not bundled into a generic ToS,
  - a way for the candidate (the "Data Principal") to **withdraw consent**
    and request **erasure**.
- This repo's `RECORDING_ENABLED` flag (`src/config.py`, default `false`,
  per the Phase 1 spec) is the right instinct: recording is an explicit,
  reversible decision, not a default. Turning it on for real calls needs the
  DPDP notice-and-consent flow designed and reviewed *before* the flag flips
  — not added retroactively once audio is already being captured.
- Separate from DPDP: telecom license conditions have historically required
  callers to be aware a call may be recorded (this predates DPDP and traces
  back to Indian Telegraph Act-era interception/monitoring rules, now
  partly superseded by the Telecommunications Act, 2023). Practically this
  means an explicit spoken notice ("this call may be recorded for quality
  purposes") is the safer default even independent of DPDP, whenever
  `RECORDING_ENABLED=true`.

## 6. Data retention for candidate PII

- The DPDP Act's retention principle is purpose-limited: personal data
  should not be kept longer than necessary for the purpose it was collected
  for, and must be erased (or the Data Principal notified/allowed to
  request erasure) once that purpose is served or consent is withdrawn.
  Secondary sources describe a commonly-cited **7-year** retention ceiling
  discussed alongside the DPDP Rules, 2025 — I could not confirm this is a
  blanket statutory number vs. a sector-specific (e.g. financial-services)
  convention being generalized by blog commentary. **Needs primary-source
  confirmation**, and in any case "up to 7 years" is a ceiling, not a
  target — candidate data that didn't lead to a hire/placement plausibly
  should be erased much sooner.
- This repo currently has **no retention/erasure job at all** —
  `conversations`, `candidate_profiles`, and any future call recordings
  accumulate indefinitely in SQLite. Before any real PII (real phone
  numbers, real names, real recorded voices) flows through this schema,
  it needs:
  - a defined retention period per data category (transcript vs. recording
    vs. structured slots vs. raw phone number),
  - a scheduled deletion/anonymization job,
  - a way to honor a candidate's erasure request out-of-band (e.g. via the
    opt-out flow already wired to `dnc_flag`, extended to also purge
    stored data, not just stop future calls).
- DPDP also has cross-border data transfer rules (a blacklist-style model
  per the DPDP Rules, 2025) — relevant only if this ever runs on
  infrastructure outside India; noted here so it isn't missed later.

---

## Open questions — needs legal review before any live call

1. **Calling-hours window conflict.** Confirm whether AI/automated voice
   calls specifically fall under the general 09:00–21:00 TCCCPR window, or
   a narrower window some secondary sources claim (10:00–19:00). The
   primary TRAI regulation PDF for the Feb 2025 amendment could not be
   machine-extracted (it appears to be a scanned/image PDF); someone needs
   to read the actual gazette text or get TRAI's helpdesk/counsel to
   confirm.
2. **Consent mechanics.** Confirm whether a candidate's job application
   counts as any form of valid consent to be *called* about it (vs. e.g.
   emailed), and if not, what the actual consent-capture flow needs to look
   like before this system is allowed to dial them — a checkbox at
   application time? A verbal consent captured on a prior human-placed
   call? This determines whether `DialerEngine` can ever legally originate
   the *first* contact, or only continue a conversation a human already
   started.
3. **Exact AI-disclosure wording.** Get counsel to review
   `settings.disclosure_text`'s actual content against whatever TRAI's
   specific disclosure requirement turns out to say (see item 4 above) —
   the current text is a reasonable placeholder, not a reviewed one.
4. **Recording consent flow, if `RECORDING_ENABLED` is ever set to true.**
   Needs a designed notice/consent UX (spoken prompt? explicit yes/no
   before recording starts? what happens if the candidate declines
   mid-call?) reviewed against DPDP before implementation, not after.
5. **Retention schedule per data category**, and who owns actually building
   the deletion job (this repo has zero retention automation today).
6. **DLT registration category and header wording** — recruitment cold
   calls need to be registered accurately; get the registered header,
   template, and PE category reviewed by whoever handles DLT registration
   for the business, and confirm `140`-series is correct for this specific
   use case (vs. some recruitment-specific carve-out, if one exists).
7. **NCPR scrub cadence and access** — who holds the TRAI telemarketer
   registration this system would call through, and how often leads get
   re-scrubbed against NCPR before dialing (once at CSV import time is
   almost certainly not sufficient given how TRAI frames this as a
   near-real-time check).

## Caveats on this document's sourcing

- Regulation names, registers, and general mechanisms (TCCCPR 2018, NCPR/
  `1909`, DLT/PE/header registration, `140`/`160` series, DPDP Act 2023,
  Telecommunications Act 2023) are corroborated across multiple independent
  secondary sources and are reported here with reasonable confidence.
- Specific numeric claims that appeared in only compliance-vendor marketing
  content (the 10:00–19:00 AI-specific calling window, the 7-year retention
  figure, a "disclose within 15 seconds" rule) are flagged inline as
  **unverified** — they read like a vendor's paraphrase of a real rule, not
  a quote of one, and I could not confirm them against TRAI's own text
  because the source PDF is image-based and did not yield extractable text
  through this session's tooling.
- This entire document should be treated as a starting brief for a lawyer
  or compliance specialist, not a substitute for one.
