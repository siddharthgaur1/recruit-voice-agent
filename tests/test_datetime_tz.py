"""Datetimes must survive a DB round-trip still timezone-aware.

Every datetime in this codebase is written as UTC-aware (datetime.now(timezone.utc)),
but a bare SQLAlchemy `DateTime` column drops the tzinfo on SQLite. A naive value
read back is then a live bug in two places:

  - RecruitScheduler is constructed with timezone=IST, so APScheduler localizes a
    naive run_date as IST -- a UTC 10:00 retry would fire 5h30m late.
  - push_into_calling_hours() calls .astimezone(IST) on it, which Python resolves
    against *system local* time, not UTC.

These tests expire the session so the values genuinely come back off disk.
"""

from datetime import datetime, timedelta, timezone

import pytest

from src.db.models import CallAttempt, Lead
from src.db.repo import (
    create_call_attempt,
    create_lead,
    make_engine,
    make_session_factory,
    sweep_stale_in_progress_leads,
)


@pytest.fixture
def session(tmp_path):
    engine = make_engine(str(tmp_path / "tz.db"))
    s = make_session_factory(engine)()
    yield s
    s.close()


def test_next_attempt_at_survives_roundtrip_aware(session):
    lead = create_lead(session, phone="+911234567890")
    run_at = datetime(2026, 9, 8, 10, 0, tzinfo=timezone.utc)
    lead.next_attempt_at = run_at
    session.commit()
    session.expire_all()  # force a real read from disk

    got = session.get(Lead, lead.id).next_attempt_at
    assert got.tzinfo is not None, "naive datetime would be localized as IST by APScheduler"
    assert got == run_at


def test_in_progress_since_survives_roundtrip_aware(session):
    lead = create_lead(session, phone="+911234567890")
    session.expire_all()

    got = session.get(Lead, lead.id).in_progress_since
    assert got.tzinfo is not None
    assert got.utcoffset() == timedelta(0)


def test_call_attempt_started_at_survives_roundtrip_aware(session):
    lead = create_lead(session, phone="+911234567890")
    attempt = create_call_attempt(session, lead.id)
    session.expire_all()

    got = session.get(CallAttempt, attempt.id).started_at
    assert got.tzinfo is not None


def test_sweep_compares_correctly_after_roundtrip(session):
    """The stale sweep filters `in_progress_since < cutoff` with an aware bind.
    If the column stores naive text, that comparison is string-vs-string with
    mismatched formats and silently matches the wrong rows."""
    lead = create_lead(session, phone="+911234567890")
    lead.in_progress_since = datetime.now(timezone.utc) - timedelta(minutes=30)
    session.commit()
    session.expire_all()

    reset = sweep_stale_in_progress_leads(session, datetime.now(timezone.utc))
    assert reset == 1
    assert session.get(Lead, lead.id).status == "QUEUED"


def test_fresh_lead_is_not_swept(session):
    """Guard the other direction: a lead that just went IN_PROGRESS must survive."""
    create_lead(session, phone="+911234567890")
    session.expire_all()

    assert sweep_stale_in_progress_leads(session, datetime.now(timezone.utc)) == 0
