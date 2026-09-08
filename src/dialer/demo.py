"""python -m src.dialer.demo   (or: python demo.py, from the repo root)

The single, no-API-key-needed, end-to-end walkthrough: CSV import -> dialer
-> conversation -> dashboard -> the "Java, Mumbai, under 60 days" query.

Deterministic: imports 20 fake leads, then fast-forwards a fake clock
lead-by-lead (jumping straight to each lead's next_attempt_at, like a
discrete-event simulation) so the whole multi-day retry campaign --
including a couple of infra FAILED blips that don't burn a lead's real
attempt budget -- is observable in under a second.

Conversations are driven by scripted candidate replies + a FakeLLM (no real
model calls) purely to prove the wiring end to end; Phase 2's persona
simulator (`python -m src.sim.run_sim`) is what actually grades extraction
quality against the real model.
"""

import csv
import logging
import random
from collections import Counter
from datetime import datetime
from pathlib import Path

from src.agent.graph import build_graph
from src.db.models import CandidateProfile, Lead
from src.db.repo import import_leads_csv, make_engine, make_session_factory
from src.dialer.mock import MockProvider
from src.dialer.provider import CallOutcome
from src.dialer.scheduler import IST, DialerEngine
from tests.conftest import FakeLLM

START = datetime(2026, 1, 5, 11, 0, tzinfo=IST)


def _resp(intent="ANSWER", slots=None, confidence=0.9):
    return {"intent": intent, "slots": slots or {}, "confidence": confidence}


# interested/yoe/notice_period_days/confirmed fast-path deterministically
# (short, unambiguous replies) -- only domain and city reach the LLM.
_COOPERATIVE_LLM_RESPONSES = [
    _resp(slots={"domain": "Java"}),
    _resp(slots={"city": "mumbai"}),
]
_COOPERATIVE_REPLIES = ["yes", "4 years", "Java", "Mumbai", "1 month", "yes send it"]

_DECLINE_LLM_RESPONSES = [_resp(intent="NOT_INTERESTED", confidence=0.9)]
_DECLINE_REPLIES = ["not interested, thanks"]

# (call-outcome script, conversation llm responses or None, conversation replies or None)
_LEAD_SCRIPTS = (
    [([CallOutcome.HUMAN_ANSWERED], _COOPERATIVE_LLM_RESPONSES, _COOPERATIVE_REPLIES)] * 4
    + [([CallOutcome.HUMAN_ANSWERED], _DECLINE_LLM_RESPONSES, _DECLINE_REPLIES)] * 2
    + [([CallOutcome.NO_ANSWER, CallOutcome.HUMAN_ANSWERED], _COOPERATIVE_LLM_RESPONSES, _COOPERATIVE_REPLIES)] * 3
    + [([CallOutcome.BUSY, CallOutcome.NO_ANSWER, CallOutcome.SWITCHED_OFF, CallOutcome.BUSY], None, None)] * 5
    + [([CallOutcome.VOICEMAIL], None, None)] * 2
    + [([CallOutcome.DNC], None, None)] * 2
    + [([CallOutcome.FAILED, CallOutcome.FAILED, CallOutcome.HUMAN_ANSWERED], _COOPERATIVE_LLM_RESPONSES, _COOPERATIVE_REPLIES)] * 1
    + [([CallOutcome.FAILED] * 4, None, None)] * 1
)
assert len(_LEAD_SCRIPTS) == 20


def _write_sample_csv(path: Path, n: int = 20) -> None:
    rng = random.Random(42)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["phone", "name", "dnc_flag"])
        for i in range(n):
            phone = f"+9198{rng.randint(10000000, 99999999)}"
            writer.writerow([phone, f"Candidate {i + 1}", ""])


class FakeClock:
    def __init__(self, start: datetime):
        self.current = start

    def __call__(self) -> datetime:
        return self.current

    def advance_to(self, dt: datetime) -> None:
        self.current = dt


def main() -> None:
    # This script narrates itself step by step -- library log records would
    # interleave onto stderr ahead of the banners and read as errors.
    logging.getLogger("src").setLevel(logging.ERROR)

    print("=" * 78)
    print("STEP 1/5: import leads from CSV")
    print("=" * 78)
    csv_path = Path("data/sample_leads.csv")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    _write_sample_csv(csv_path)

    db_engine = make_engine("dialer_demo.db")
    session_factory = make_session_factory(db_engine)
    session = session_factory()
    leads = import_leads_csv(session, csv_path)
    lead_ids = [lead.id for lead in leads]
    session.close()

    print(f"Imported {len(lead_ids)} leads from {csv_path}")

    print()
    print("=" * 78)
    print("STEP 2/5: dialer + scheduler run the campaign (mock provider, fake clock)")
    print("=" * 78)
    clock = FakeClock(START)
    dialers: dict[str, DialerEngine] = {}
    for lead_id, (call_script, llm_responses, replies) in zip(lead_ids, _LEAD_SCRIPTS, strict=True):
        provider = MockProvider(scripted=list(call_script))
        graph = build_graph(FakeLLM(llm_responses)) if llm_responses else None
        conversation_replies = (lambda lead, r=replies: r) if replies else None
        dialers[lead_id] = DialerEngine(
            session_factory=session_factory, provider=provider, clock=clock,
            graph=graph, conversation_replies=conversation_replies,
        )

    timelines: dict[str, list[tuple[datetime, CallOutcome, str | None]]] = {
        lead_id: [] for lead_id in lead_ids
    }

    # Discrete-event loop: repeatedly dial whichever lead's next_attempt_at
    # is earliest, jumping the fake clock straight there.
    pending = set(lead_ids)
    while pending:
        session = session_factory()
        due = []
        for lead_id in pending:
            lead = session.get(Lead, lead_id)
            due.append((lead.next_attempt_at or clock.current, lead_id))
        session.close()
        due.sort(key=lambda pair: pair[0])
        next_time, lead_id = due[0]
        clock.advance_to(next_time)

        outcome = dialers[lead_id].attempt_call(lead_id)

        session = session_factory()
        lead = session.get(Lead, lead_id)
        timelines[lead_id].append((clock.current, outcome, lead.last_bucket))
        if lead.status != "QUEUED":
            pending.discard(lead_id)
        session.close()

    print()
    print("=" * 78)
    print("STEP 3/5: results -- on HUMAN_ANSWERED, the real conversation ran too")
    print("=" * 78)
    print("\n=== Final lead status distribution ===")
    session = session_factory()
    statuses = Counter(session.get(Lead, lead_id).status for lead_id in lead_ids)
    for status, count in sorted(statuses.items()):
        print(f"  {status}: {count}")

    in_progress = [lid for lid in lead_ids if session.get(Lead, lid).status == "IN_PROGRESS"]
    assert not in_progress, f"leads stuck IN_PROGRESS after the campaign: {in_progress}"
    print("\nAssertion passed: no lead remained IN_PROGRESS after the campaign.")

    print("\n=== terminal_reason on every UNREACHABLE lead ===")
    for lead_id in lead_ids:
        lead = session.get(Lead, lead_id)
        if lead.status == "UNREACHABLE":
            print(f"  {lead.phone}: terminal_reason={lead.terminal_reason} attempts={lead.attempts} "
                  f"failed_retry_count={lead.failed_retry_count}")
    session.close()

    print("\n=== Sample retry timeline (a lead that exhausts BUSY/NO_ANSWER retries) ===")
    for _lead_id, events in timelines.items():
        if len(events) == 4 and events[0][1] == CallOutcome.BUSY:
            for i, (at, outcome, bucket) in enumerate(events, start=1):
                print(f"  attempt {i}: {at.astimezone(IST).isoformat()}  outcome={outcome.value}  bucket={bucket}")
            break

    print("\n=== Sample FAILED timeline (infra errors don't burn the attempt budget) ===")
    for lead_id, events in timelines.items():
        if len(events) >= 2 and events[0][1] == CallOutcome.FAILED:
            session = session_factory()
            lead = session.get(Lead, lead_id)
            print(f"  lead attempts={lead.attempts} failed_retry_count={lead.failed_retry_count} "
                  f"status={lead.status} terminal_reason={lead.terminal_reason}")
            for i, (at, outcome, _bucket) in enumerate(events, start=1):
                print(f"    call {i}: {at.astimezone(IST).isoformat()}  outcome={outcome.value}")
            session.close()

    print()
    print("=" * 78)
    print("STEP 4/5: dashboard (GET /dashboard, queried directly here)")
    print("=" * 78)
    session = session_factory()
    for lead in session.query(Lead).order_by(Lead.created_at).all():
        profile = (
            session.query(CandidateProfile)
            .filter_by(lead_id=lead.id)
            .order_by(CandidateProfile.id.desc())
            .first()
        )
        slots_summary = (
            f"domain={profile.domain} city={profile.city} notice={profile.notice_period_days}"
            if profile else "no conversation"
        )
        print(f"  {lead.phone}  status={lead.status:<12} attempts={lead.attempts}  {slots_summary}")
    session.close()

    print()
    print("=" * 78)
    print('STEP 5/5: the real query -- "Java candidates in Mumbai under 60 days notice"')
    print("=" * 78)
    session = session_factory()
    matches = (
        session.query(CandidateProfile)
        .filter(CandidateProfile.domain == "Java")
        .filter(CandidateProfile.city == "Mumbai")
        .filter(CandidateProfile.notice_period_days < 60)
        .all()
    )
    for row in matches:
        print(f"  lead_id={row.lead_id[:8]}...  domain={row.domain!r}  domain_raw={row.domain_raw!r}  "
              f"city={row.city!r}  notice_period_days={row.notice_period_days}")
    print(f"\n{len(matches)} matching candidate(s) out of {len(lead_ids)} total leads.")
    session.close()


if __name__ == "__main__":
    main()
