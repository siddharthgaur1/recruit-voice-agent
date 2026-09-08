from src.db.models import CandidateProfile
from src.db.repo import (
    create_call_attempt,
    create_lead,
    make_engine,
    make_session_factory,
    save_conversation_result,
)


def _seed(session, phone, domain_tag, domain_raw, city, notice_period_days):
    lead = create_lead(session, phone=phone)
    attempt = create_call_attempt(session, lead.id)
    save_conversation_result(
        session, lead_id=lead.id, call_attempt_id=attempt.id,
        slots={
            "interested": True, "yoe": 4.0, "domain": domain_tag, "city": city,
            "notice_period_days": notice_period_days, "confirmed": True,
        },
        transcript=[], outcome="COMPLETED", domain_raw=domain_raw,
    )


def test_java_candidates_in_mumbai_under_60_days_is_a_real_query(tmp_path):
    engine = make_engine(str(tmp_path / "query_test.db"))
    session = make_session_factory(engine)()

    _seed(session, "+911111111111", "Java", "I mostly write Java and Spring", "Mumbai", 30)
    _seed(session, "+912222222222", "Java", "java, spring boot mostly", "Mumbai", 90)  # too long notice
    _seed(session, "+913333333333", "Python", "Django and Python", "Mumbai", 15)  # wrong domain
    _seed(session, "+914444444444", "Java", "JAVA developer", "Pune", 20)  # wrong city
    _seed(session, "+915555555555", "Java", "I work in Java mostly", "Mumbai", 45)

    results = (
        session.query(CandidateProfile)
        .filter(CandidateProfile.domain == "Java")
        .filter(CandidateProfile.city == "Mumbai")
        .filter(CandidateProfile.notice_period_days < 60)
        .all()
    )

    assert len(results) == 2
    # the two matches must be two distinct leads, not one lead counted twice
    assert len({r.lead_id for r in results}) == 2
    for row in results:
        assert row.domain == "Java"
        assert row.city == "Mumbai"
        assert row.notice_period_days < 60
        assert row.domain_raw  # the original wording survives, separately
