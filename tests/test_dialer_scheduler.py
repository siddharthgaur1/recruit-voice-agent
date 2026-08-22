from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.dialer.mock import MockProvider
from src.dialer.provider import CallOutcome
from src.dialer.scheduler import (
    IST,
    DialerEngine,
    bucket_for,
    compute_next_attempt,
    is_within_calling_hours,
    next_bucket,
    push_into_calling_hours,
)
from src.db.models import Lead
from src.db.repo import create_lead, make_engine, make_session_factory


def ist(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=IST)


def naive(dt: datetime) -> datetime:
    """SQLite/SQLAlchemy round-trips DateTime columns as naive -- compare on that basis."""
    return dt.replace(tzinfo=None)


def resp(intent="ANSWER", slots=None, confidence=0.9):
    return {"intent": intent, "slots": slots or {}, "confidence": confidence}


# --- calling-hours gate -----------------------------------------------------

@pytest.mark.parametrize("dt,expected", [
    (ist(2026, 1, 5, 9, 0), True),
    (ist(2026, 1, 5, 20, 59), True),
    (ist(2026, 1, 5, 21, 0), False),
    (ist(2026, 1, 5, 8, 59), False),
    (ist(2026, 1, 5, 3, 0), False),
])
def test_is_within_calling_hours(dt, expected):
    assert is_within_calling_hours(dt) == expected


def test_push_into_calling_hours_noop_when_already_valid():
    dt = ist(2026, 1, 5, 15, 0)
    assert push_into_calling_hours(dt) == dt


def test_push_into_calling_hours_pushes_late_night_to_next_morning():
    dt = ist(2026, 1, 5, 22, 30)
    pushed = push_into_calling_hours(dt)
    assert pushed == ist(2026, 1, 6, 10, 0)


def test_push_into_calling_hours_pushes_early_morning_to_same_day_bucket():
    dt = ist(2026, 1, 5, 3, 0)
    pushed = push_into_calling_hours(dt)
    assert pushed == ist(2026, 1, 5, 10, 0)


# --- bucket rotation ---------------------------------------------------------

def test_bucket_for_named_windows():
    assert bucket_for(ist(2026, 1, 5, 10, 30)) == "MORNING"
    assert bucket_for(ist(2026, 1, 5, 15, 0)) == "AFTERNOON"
    assert bucket_for(ist(2026, 1, 5, 19, 0)) == "EVENING"
    assert bucket_for(ist(2026, 1, 5, 13, 0)) is None


def test_next_bucket_rotates_and_never_repeats_immediately():
    assert next_bucket("MORNING") == "AFTERNOON"
    assert next_bucket("AFTERNOON") == "EVENING"
    assert next_bucket("EVENING") == "MORNING"
    assert next_bucket(None) == "MORNING"


# --- backoff schedule --------------------------------------------------------

def test_attempt_1_backs_off_fifteen_minutes():
    now = ist(2026, 1, 5, 11, 0)
    next_at, bucket = compute_next_attempt(now, attempt_number=1, last_bucket="MORNING")
    assert next_at == ist(2026, 1, 5, 11, 15)
    assert bucket == "MORNING"


def test_attempt_2_backs_off_two_hours():
    now = ist(2026, 1, 5, 11, 15)
    next_at, bucket = compute_next_attempt(now, attempt_number=2, last_bucket="MORNING")
    assert next_at == ist(2026, 1, 5, 13, 15)


def test_attempt_3_moves_to_next_day_different_bucket():
    now = ist(2026, 1, 5, 13, 15)
    next_at, bucket = compute_next_attempt(now, attempt_number=3, last_bucket="MORNING")
    assert next_at == ist(2026, 1, 6, 14, 0)  # next day, AFTERNOON start
    assert bucket == "AFTERNOON"


def test_attempt_3_never_repeats_the_same_bucket_twice():
    now = ist(2026, 1, 5, 19, 30)
    next_at, bucket = compute_next_attempt(now, attempt_number=3, last_bucket="EVENING")
    assert bucket == "MORNING"
    assert next_at == ist(2026, 1, 6, 10, 0)


def test_attempt_4_exhausts_retries():
    now = ist(2026, 1, 6, 10, 0)
    next_at, bucket = compute_next_attempt(now, attempt_number=4, last_bucket="MORNING")
    assert next_at is None
    assert bucket is None


def test_backoff_landing_outside_hours_is_pushed_to_next_valid_bucket():
    now = ist(2026, 1, 5, 20, 50)  # +15 min would land at 21:05, outside hours
    next_at, _ = compute_next_attempt(now, attempt_number=1, last_bucket="EVENING")
    assert next_at == ist(2026, 1, 6, 10, 0)


# --- DialerEngine end-to-end with a fake clock and MockProvider -------------

class FakeClock:
    def __init__(self, start: datetime):
        self.current = start

    def __call__(self) -> datetime:
        return self.current

    def advance_to(self, dt: datetime) -> None:
        self.current = dt


def make_engine_and_lead(tmp_path, phone="+911111111111", dnc=False):
    db_engine = make_engine(str(tmp_path / "dialer_test.db"))
    session_factory = make_session_factory(db_engine)
    session = session_factory()
    lead = create_lead(session, phone=phone)
    if dnc:
        lead.dnc_flag = True
        session.commit()
    lead_id = lead.id
    session.close()
    return session_factory, lead_id


def test_dialer_engine_full_retry_campaign_then_unreachable(tmp_path):
    session_factory, lead_id = make_engine_and_lead(tmp_path)
    clock = FakeClock(ist(2026, 1, 5, 11, 0))
    provider = MockProvider(scripted=[
        CallOutcome.BUSY, CallOutcome.NO_ANSWER, CallOutcome.SWITCHED_OFF, CallOutcome.BUSY,
    ])
    dialer = DialerEngine(session_factory=session_factory, provider=provider, clock=clock)

    outcome = dialer.attempt_call(lead_id)
    assert outcome == CallOutcome.BUSY
    session = session_factory()
    lead = session.get(Lead, lead_id)
    assert lead.attempts == 1
    assert lead.status == "QUEUED"
    assert lead.next_attempt_at == naive(ist(2026, 1, 5, 11, 15))
    session.close()

    clock.advance_to(lead.next_attempt_at.replace(tzinfo=IST))
    dialer.attempt_call(lead_id)
    session = session_factory()
    lead = session.get(Lead, lead_id)
    assert lead.attempts == 2
    assert lead.next_attempt_at == naive(ist(2026, 1, 5, 13, 15))
    session.close()

    clock.advance_to(lead.next_attempt_at.replace(tzinfo=IST))
    dialer.attempt_call(lead_id)
    session = session_factory()
    lead = session.get(Lead, lead_id)
    assert lead.attempts == 3
    assert lead.last_bucket in ("AFTERNOON",)  # rotated away from MORNING
    third_next = lead.next_attempt_at.replace(tzinfo=IST)
    session.close()

    clock.advance_to(third_next)
    outcome = dialer.attempt_call(lead_id)
    assert outcome == CallOutcome.BUSY
    session = session_factory()
    lead = session.get(Lead, lead_id)
    assert lead.attempts == 4
    assert lead.status == "UNREACHABLE"
    assert lead.next_attempt_at is None
    session.close()


def test_dialer_engine_human_answered_without_graph_falls_back_to_in_progress(tmp_path):
    # A DialerEngine with no conversation wired at all (e.g. a dialer-only test
    # double) can't resolve the call further -- this is the opt-in surface,
    # not what production/the demo actually uses (see the wired test below).
    session_factory, lead_id = make_engine_and_lead(tmp_path)
    clock = FakeClock(ist(2026, 1, 5, 11, 0))
    provider = MockProvider(scripted=[CallOutcome.HUMAN_ANSWERED])
    dialer = DialerEngine(session_factory=session_factory, provider=provider, clock=clock)

    dialer.attempt_call(lead_id)
    session = session_factory()
    lead = session.get(Lead, lead_id)
    assert lead.status == "IN_PROGRESS"
    assert lead.next_attempt_at is None
    session.close()


def test_dialer_engine_short_circuits_on_dnc_flag(tmp_path):
    session_factory, lead_id = make_engine_and_lead(tmp_path, dnc=True)
    clock = FakeClock(ist(2026, 1, 5, 11, 0))
    provider = MockProvider(scripted=[CallOutcome.HUMAN_ANSWERED])  # should never be consulted
    dialer = DialerEngine(session_factory=session_factory, provider=provider, clock=clock)

    outcome = dialer.attempt_call(lead_id)
    assert outcome == CallOutcome.DNC
    session = session_factory()
    lead = session.get(Lead, lead_id)
    assert lead.status == "DNC"
    assert lead.terminal_reason == "DNC"
    session.close()


# --- terminal_reason on dialer-level rollups ---------------------------------

def test_terminal_reason_recorded_when_retries_exhausted(tmp_path):
    session_factory, lead_id = make_engine_and_lead(tmp_path)
    clock = FakeClock(ist(2026, 1, 5, 11, 0))
    provider = MockProvider(scripted=[CallOutcome.BUSY] * 4)
    dialer = DialerEngine(session_factory=session_factory, provider=provider, clock=clock)

    session = session_factory()
    lead = session.get(Lead, lead_id)
    session.close()
    for _ in range(4):
        dialer.attempt_call(lead_id)
        session = session_factory()
        lead = session.get(Lead, lead_id)
        if lead.next_attempt_at is not None:
            clock.advance_to(lead.next_attempt_at.replace(tzinfo=IST))
        session.close()

    assert lead.status == "UNREACHABLE"
    assert lead.terminal_reason == "BUSY"


def test_terminal_reason_recorded_for_non_retryable_outcome(tmp_path):
    session_factory, lead_id = make_engine_and_lead(tmp_path)
    clock = FakeClock(ist(2026, 1, 5, 11, 0))
    provider = MockProvider(scripted=[CallOutcome.VOICEMAIL])
    dialer = DialerEngine(session_factory=session_factory, provider=provider, clock=clock)

    dialer.attempt_call(lead_id)
    session = session_factory()
    lead = session.get(Lead, lead_id)
    assert lead.status == "UNREACHABLE"
    assert lead.terminal_reason == "VOICEMAIL"
    session.close()


# --- FAILED: infra error, its own backoff, does not touch `attempts` --------

def test_failed_outcome_does_not_increment_attempts_and_uses_own_backoff(tmp_path):
    session_factory, lead_id = make_engine_and_lead(tmp_path)
    clock = FakeClock(ist(2026, 1, 5, 11, 0))
    provider = MockProvider(scripted=[CallOutcome.FAILED])
    dialer = DialerEngine(session_factory=session_factory, provider=provider, clock=clock)

    outcome = dialer.attempt_call(lead_id)
    assert outcome == CallOutcome.FAILED
    session = session_factory()
    lead = session.get(Lead, lead_id)
    assert lead.attempts == 0  # infra error -- not a real dial attempt
    assert lead.status == "QUEUED"
    assert lead.next_attempt_at == naive(ist(2026, 1, 5, 11, 5))  # +5 min, its own backoff
    assert lead.failed_retry_count == 1
    session.close()


def test_failed_outcome_caps_at_three_consecutive_retries_then_unreachable(tmp_path):
    session_factory, lead_id = make_engine_and_lead(tmp_path)
    clock = FakeClock(ist(2026, 1, 5, 11, 0))
    provider = MockProvider(scripted=[CallOutcome.FAILED] * 4)
    dialer = DialerEngine(session_factory=session_factory, provider=provider, clock=clock)

    for i in range(4):
        dialer.attempt_call(lead_id)
        session = session_factory()
        lead = session.get(Lead, lead_id)
        if lead.next_attempt_at is not None:
            clock.advance_to(lead.next_attempt_at.replace(tzinfo=IST))
        session.close()

    assert lead.status == "UNREACHABLE"
    assert lead.terminal_reason == "FAILED"
    assert lead.attempts == 0  # still never counted as a real attempt
    assert lead.failed_retry_count == 4


def test_failed_retry_count_resets_after_a_real_outcome(tmp_path):
    session_factory, lead_id = make_engine_and_lead(tmp_path)
    clock = FakeClock(ist(2026, 1, 5, 11, 0))
    provider = MockProvider(scripted=[CallOutcome.FAILED, CallOutcome.BUSY])
    dialer = DialerEngine(session_factory=session_factory, provider=provider, clock=clock)

    dialer.attempt_call(lead_id)  # FAILED -> failed_retry_count = 1
    session = session_factory()
    lead = session.get(Lead, lead_id)
    clock.advance_to(lead.next_attempt_at.replace(tzinfo=IST))
    session.close()

    dialer.attempt_call(lead_id)  # BUSY -> resets failed_retry_count
    session = session_factory()
    lead = session.get(Lead, lead_id)
    assert lead.failed_retry_count == 0
    assert lead.attempts == 1  # only the BUSY call counted
    session.close()


# --- HUMAN_ANSWERED wired to a real conversation ----------------------------

def _cooperative_conversation_replies(lead) -> list[str]:
    return ["yes", "4 years", "Java", "Mumbai", "2 months", "yes send it"]


def _cooperative_llm_responses():
    # interested/yoe/notice_period_days/confirmed fast-path deterministically
    # (short, unambiguous replies) -- only domain and city reach the LLM.
    return [
        resp(slots={"domain": "Java"}),
        resp(slots={"city": "mumbai"}),
    ]


def test_human_answered_runs_conversation_and_sets_final_status(tmp_path):
    from tests.conftest import FakeLLM

    from src.agent.graph import build_graph

    session_factory, lead_id = make_engine_and_lead(tmp_path)
    clock = FakeClock(ist(2026, 1, 5, 11, 0))
    provider = MockProvider(scripted=[CallOutcome.HUMAN_ANSWERED])
    llm = FakeLLM(_cooperative_llm_responses())
    graph = build_graph(llm)

    dialer = DialerEngine(
        session_factory=session_factory, provider=provider, clock=clock,
        graph=graph, conversation_replies=_cooperative_conversation_replies,
    )

    outcome = dialer.attempt_call(lead_id)
    assert outcome == CallOutcome.HUMAN_ANSWERED

    session = session_factory()
    lead = session.get(Lead, lead_id)
    assert lead.status == "COMPLETED"  # conversation outcome, not stuck IN_PROGRESS
    assert lead.in_progress_since is None
    assert lead.attempts == 1  # counted once for the dial, not again for the conversation
    session.close()


def test_human_answered_conversation_decline_sets_not_interested(tmp_path):
    from tests.conftest import FakeLLM

    from src.agent.graph import build_graph

    session_factory, lead_id = make_engine_and_lead(tmp_path)
    clock = FakeClock(ist(2026, 1, 5, 11, 0))
    provider = MockProvider(scripted=[CallOutcome.HUMAN_ANSWERED])
    llm = FakeLLM([resp(intent="NOT_INTERESTED", confidence=0.9)])
    graph = build_graph(llm)

    dialer = DialerEngine(
        session_factory=session_factory, provider=provider, clock=clock,
        graph=graph, conversation_replies=lambda lead: ["not interested, thanks"],
    )

    dialer.attempt_call(lead_id)
    session = session_factory()
    lead = session.get(Lead, lead_id)
    assert lead.status == "NOT_INTERESTED"
    session.close()
