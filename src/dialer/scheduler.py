"""Retry backoff, calling-hours gate, and the dialer engine that ties a
TelephonyProvider to lead/call_attempt persistence.

All the retry math is pure (takes `now` as a parameter) so it can be pinned
down with a fake clock in tests, independent of any real scheduler.
"""

from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from src.agent.graph import run_turn_verbose
from src.agent.session import new_call_state
from src.db.models import CallAttempt, Lead
from src.db.repo import save_conversation_result
from src.dialer.provider import RETRYABLE_OUTCOMES, CallOutcome, TelephonyProvider

IST = ZoneInfo("Asia/Kolkata")

CALLING_HOURS_START = dtime(9, 0)
CALLING_HOURS_END = dtime(21, 0)

BUCKETS = ["MORNING", "AFTERNOON", "EVENING"]
BUCKET_START_HOUR = {"MORNING": 10, "AFTERNOON": 14, "EVENING": 18}

BACKOFF_BY_ATTEMPT = {1: timedelta(minutes=15), 2: timedelta(hours=2)}
MAX_ATTEMPTS = 4

FAILED_BACKOFF = timedelta(minutes=5)
MAX_CONSECUTIVE_FAILED = 3


def is_within_calling_hours(dt: datetime) -> bool:
    t = dt.astimezone(IST).time()
    return CALLING_HOURS_START <= t < CALLING_HOURS_END


def bucket_for(dt: datetime) -> str | None:
    hour = dt.astimezone(IST).hour
    if 10 <= hour < 12:
        return "MORNING"
    if 14 <= hour < 17:
        return "AFTERNOON"
    if 18 <= hour < 20:
        return "EVENING"
    return None


def next_bucket(last_bucket: str | None) -> str:
    if last_bucket not in BUCKETS:
        return BUCKETS[0]
    idx = BUCKETS.index(last_bucket)
    return BUCKETS[(idx + 1) % len(BUCKETS)]


def _bucket_start(day: datetime, bucket: str) -> datetime:
    ist_day = day.astimezone(IST)
    return ist_day.replace(hour=BUCKET_START_HOUR[bucket], minute=0, second=0, microsecond=0)


def push_into_calling_hours(dt: datetime) -> datetime:
    """If dt falls outside 09:00-21:00 IST, push to the next day's MORNING bucket start."""
    if is_within_calling_hours(dt):
        return dt
    ist_dt = dt.astimezone(IST)
    day = ist_dt if ist_dt.time() < CALLING_HOURS_START else ist_dt + timedelta(days=1)
    return _bucket_start(day, "MORNING")


def compute_next_attempt(now: datetime, attempt_number: int,
                          last_bucket: str | None) -> tuple[datetime | None, str | None]:
    """attempt_number: the attempt that just happened (1-indexed).
    Returns (next_attempt_at, next_bucket), or (None, None) once retries are exhausted."""
    if attempt_number >= MAX_ATTEMPTS:
        return None, None

    if attempt_number in BACKOFF_BY_ATTEMPT:
        candidate = now + BACKOFF_BY_ATTEMPT[attempt_number]
        candidate = push_into_calling_hours(candidate)
        bucket = bucket_for(candidate) or last_bucket
        return candidate, bucket

    # attempt_number == 3: next day, a different time-of-day bucket
    bucket = next_bucket(last_bucket)
    candidate = _bucket_start(now + timedelta(days=1), bucket)
    candidate = push_into_calling_hours(candidate)
    return candidate, bucket


@dataclass
class DialerEngine:
    session_factory: Callable[[], Session]
    provider: TelephonyProvider
    clock: Callable[[], datetime]
    # Compiled LangGraph app (build_graph(llm)) run on HUMAN_ANSWERED. Left None
    # for dialer-only tests/callers that don't care about the conversation step.
    graph: Any = None
    # Given the answered Lead, returns the scripted candidate utterances to feed
    # the graph. MockProvider calls carry no real audio, so this stands in for
    # what a live telephony audio stream would supply once Phase 5 lands.
    conversation_replies: Callable[[Lead], list[str]] | None = None

    def attempt_call(self, lead_id: str) -> CallOutcome | None:
        session = self.session_factory()
        try:
            lead = session.get(Lead, lead_id)
            if lead is None:
                return None

            now = self.clock()

            if lead.dnc_flag:
                lead.status = "DNC"
                lead.terminal_reason = "DNC"
                lead.next_attempt_at = None
                session.commit()
                return CallOutcome.DNC

            outcome = self.provider.place_call(lead.phone)

            attempt = CallAttempt(
                lead_id=lead.id, started_at=now, ended_at=now,
                outcome=outcome.value, provider="mock",
            )
            session.add(attempt)
            session.flush()  # populate attempt.id for a possible conversation

            if outcome != CallOutcome.FAILED:
                lead.failed_retry_count = 0

            if outcome == CallOutcome.FAILED:
                # Infrastructure error, not a lead problem: its own backoff,
                # and it does NOT count against the lead's real attempt budget.
                lead.failed_retry_count += 1
                if lead.failed_retry_count > MAX_CONSECUTIVE_FAILED:
                    lead.status = "UNREACHABLE"
                    lead.terminal_reason = CallOutcome.FAILED.value
                    lead.next_attempt_at = None
                else:
                    lead.status = "QUEUED"
                    lead.next_attempt_at = push_into_calling_hours(now + FAILED_BACKOFF)

            elif outcome == CallOutcome.DNC:
                lead.attempts += 1
                lead.status = "DNC"
                lead.terminal_reason = "DNC"
                lead.next_attempt_at = None

            elif outcome == CallOutcome.HUMAN_ANSWERED:
                lead.attempts += 1
                lead.status = "IN_PROGRESS"
                lead.in_progress_since = now
                session.commit()
                self._run_conversation(session, lead, attempt)

            elif outcome in RETRYABLE_OUTCOMES:
                lead.attempts += 1
                next_at, bucket = compute_next_attempt(now, lead.attempts, lead.last_bucket)
                if next_at is None:
                    lead.status = "UNREACHABLE"
                    lead.terminal_reason = outcome.value
                    lead.next_attempt_at = None
                else:
                    lead.status = "QUEUED"
                    lead.next_attempt_at = next_at
                    lead.last_bucket = bucket

            else:  # VOICEMAIL, INVALID_NUMBER -- not retryable
                lead.attempts += 1
                lead.status = "UNREACHABLE"
                lead.terminal_reason = outcome.value
                lead.next_attempt_at = None

            session.commit()
            return outcome
        finally:
            session.close()

    def _run_conversation(self, session: Session, lead: Lead, attempt: CallAttempt) -> None:
        if self.graph is None or self.conversation_replies is None:
            return  # no conversation wired up; caller only cares about dial outcomes

        state = new_call_state(lead.id, attempt.id)
        dnc = False
        for reply in self.conversation_replies(lead):
            verbose = run_turn_verbose(self.graph, state, reply)
            state = verbose["state"]
            dnc = dnc or verbose["dnc"]
            if verbose["outcome"]:
                break

        # If the script runs out before the graph reaches a natural outcome,
        # fall back to a rollup rather than leaving the lead IN_PROGRESS.
        outcome = state.get("outcome") or "MAX_TURNS"

        save_conversation_result(
            session, lead_id=lead.id, call_attempt_id=attempt.id,
            slots=state["slots"], transcript=state["transcript"],
            outcome=outcome, dnc=dnc, increment_attempts=False,
            domain_raw=state.get("domain_raw"),
        )


class RecruitScheduler:
    """Thin APScheduler wrapper: one job per lead, persisted so retries survive
    a process restart. Each job calls DialerEngine.attempt_call and, if the
    lead should be retried, reschedules itself for the computed next_attempt_at.
    """

    def __init__(self, engine: DialerEngine, db_path: str):
        from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
        from apscheduler.schedulers.background import BackgroundScheduler

        self._dialer = engine
        self._scheduler = BackgroundScheduler(
            jobstores={"default": SQLAlchemyJobStore(url=f"sqlite:///{db_path}")},
            timezone=IST,
        )

    def start(self) -> None:
        self._scheduler.start()

    def shutdown(self) -> None:
        self._scheduler.shutdown()

    def schedule_lead(self, lead_id: str, run_at: datetime) -> None:
        self._scheduler.add_job(
            self._run_job, "date", run_date=run_at,
            args=[lead_id], id=f"lead-{lead_id}", replace_existing=True,
        )

    def _run_job(self, lead_id: str) -> None:
        self._dialer.attempt_call(lead_id)
        session = self._dialer.session_factory()
        try:
            lead = session.get(Lead, lead_id)
            if lead is not None and lead.next_attempt_at is not None:
                self.schedule_lead(lead_id, lead.next_attempt_at)
        finally:
            session.close()
