from src.db.models import CandidateProfile, Lead
from src.db.repo import (
    create_call_attempt,
    create_lead,
    make_engine,
    make_session_factory,
    save_conversation_result,
)


def make_session(tmp_path):
    engine = make_engine(str(tmp_path / "test.db"))
    return make_session_factory(engine)()


def test_completed_conversation_persists_normalised_slots(tmp_path):
    session = make_session(tmp_path)
    lead = create_lead(session, phone="+911234567890")
    attempt = create_call_attempt(session, lead.id)

    slots = {
        "interested": True, "yoe": 4.0, "domain": "Java", "city": "Mumbai",
        "notice_period_days": 60, "confirmed": True,
    }
    save_conversation_result(
        session, lead_id=lead.id, call_attempt_id=attempt.id,
        slots=slots, transcript=[{"role": "agent", "text": "hi", "ts": 0.0}],
        outcome="COMPLETED",
    )

    profile = session.query(CandidateProfile).filter_by(lead_id=lead.id).one()
    assert profile.yoe == 4.0
    assert profile.city == "Mumbai"
    assert profile.notice_period_days == 60

    refreshed_lead = session.get(Lead, lead.id)
    assert refreshed_lead.status == "COMPLETED"
    assert refreshed_lead.attempts == 1
    assert refreshed_lead.dnc_flag is False


def test_opt_out_sets_dnc_flag(tmp_path):
    session = make_session(tmp_path)
    lead = create_lead(session, phone="+911234567890")
    attempt = create_call_attempt(session, lead.id)

    save_conversation_result(
        session, lead_id=lead.id, call_attempt_id=attempt.id,
        slots=dict.fromkeys(["interested", "yoe", "domain", "city", "notice_period_days", "confirmed"]),
        transcript=[], outcome="NOT_INTERESTED", dnc=True,
    )

    refreshed_lead = session.get(Lead, lead.id)
    assert refreshed_lead.dnc_flag is True
    assert refreshed_lead.status == "DNC"
