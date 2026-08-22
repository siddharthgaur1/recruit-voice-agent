from fastapi.testclient import TestClient

from src.config import settings
from src.db.repo import (
    create_call_attempt,
    create_lead,
    make_engine,
    make_session_factory,
    save_conversation_result,
)


def test_dashboard_lists_leads_with_status_and_slots(tmp_path, monkeypatch):
    db_path = str(tmp_path / "dash.db")
    monkeypatch.setattr(settings, "db_path", db_path)

    engine = make_engine(db_path)
    session = make_session_factory(engine)()
    lead = create_lead(session, phone="+911234567890", name="Test Candidate")
    attempt = create_call_attempt(session, lead.id)
    save_conversation_result(
        session, lead_id=lead.id, call_attempt_id=attempt.id,
        slots={"interested": True, "yoe": 4.0, "domain": "Java", "city": "Mumbai",
               "notice_period_days": 60, "confirmed": True},
        transcript=[], outcome="COMPLETED",
    )
    session.close()

    from src.api.main import app
    client = TestClient(app)
    response = client.get("/dashboard")

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["phone"] == "+911234567890"
    assert rows[0]["status"] == "COMPLETED"
    assert rows[0]["slots"]["city"] == "Mumbai"
    assert rows[0]["slots"]["yoe"] == 4.0
