from datetime import datetime, timedelta, timezone

from src.db.models import Lead
from src.db.repo import create_lead, make_engine, make_session_factory, sweep_stale_in_progress_leads


def test_sweep_resets_stale_in_progress_lead_to_queued(tmp_path):
    engine = make_engine(str(tmp_path / "sweep.db"))
    session = make_session_factory(engine)()
    lead = create_lead(session, phone="+911111111111")

    now = datetime.now(timezone.utc)
    lead.in_progress_since = now - timedelta(minutes=15)  # stale
    session.commit()

    reset_count = sweep_stale_in_progress_leads(session, now)
    assert reset_count == 1

    refreshed = session.get(Lead, lead.id)
    assert refreshed.status == "QUEUED"
    assert refreshed.in_progress_since is None
    assert refreshed.next_attempt_at is not None
    session.close()


def test_sweep_leaves_recent_in_progress_lead_alone(tmp_path):
    engine = make_engine(str(tmp_path / "sweep2.db"))
    session = make_session_factory(engine)()
    lead = create_lead(session, phone="+911111111111")

    now = datetime.now(timezone.utc)
    lead.in_progress_since = now - timedelta(minutes=2)  # fresh
    session.commit()

    reset_count = sweep_stale_in_progress_leads(session, now)
    assert reset_count == 0

    refreshed = session.get(Lead, lead.id)
    assert refreshed.status == "IN_PROGRESS"
    session.close()
