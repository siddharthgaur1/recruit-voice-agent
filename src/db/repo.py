import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base, CallAttempt, CandidateProfile, Conversation, Lead


def make_engine(db_path: str):
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    return engine


def make_session_factory(engine) -> sessionmaker:
    return sessionmaker(bind=engine)


def create_lead(session: Session, phone: str, name: str | None = None) -> Lead:
    lead = Lead(phone=phone, name=name, status="IN_PROGRESS", in_progress_since=datetime.now(timezone.utc))
    session.add(lead)
    session.commit()
    return lead


def sweep_stale_in_progress_leads(session: Session, now: datetime, older_than_minutes: int = 10) -> int:
    """Reset leads stuck IN_PROGRESS (e.g. the process crashed mid-call) back to
    QUEUED so the scheduler picks them up again. Returns how many were reset."""
    from datetime import timedelta

    cutoff = now - timedelta(minutes=older_than_minutes)
    stale = (
        session.query(Lead)
        .filter(Lead.status == "IN_PROGRESS")
        .filter(Lead.in_progress_since.isnot(None))
        .filter(Lead.in_progress_since < cutoff)
        .all()
    )
    for lead in stale:
        lead.status = "QUEUED"
        lead.next_attempt_at = now
        lead.in_progress_since = None
    session.commit()
    return len(stale)


def import_leads_csv(session: Session, csv_path: str | Path) -> list[Lead]:
    """CSV columns: phone (required), name (optional), dnc_flag (optional, true/1/yes)."""
    leads = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            dnc_raw = (row.get("dnc_flag") or "").strip().lower()
            lead = Lead(
                phone=row["phone"].strip(),
                name=(row.get("name") or "").strip() or None,
                status="QUEUED",
                dnc_flag=dnc_raw in ("true", "1", "yes"),
            )
            session.add(lead)
            leads.append(lead)
    session.commit()
    return leads


def create_call_attempt(session: Session, lead_id: str) -> CallAttempt:
    attempt = CallAttempt(lead_id=lead_id, provider="mock")
    session.add(attempt)
    session.commit()
    return attempt


def save_conversation_result(
    session: Session,
    lead_id: str,
    call_attempt_id: str,
    slots: dict,
    transcript: list[dict],
    outcome: str,
    dnc: bool = False,
    increment_attempts: bool = True,
    domain_raw: str | None = None,
) -> Conversation:
    slots_filled_count = sum(1 for v in slots.values() if v is not None)
    link_sent_at = datetime.now(timezone.utc) if outcome == "COMPLETED" else None

    conversation = Conversation(
        call_attempt_id=call_attempt_id,
        slots_json=json.dumps(slots),
        transcript_json=json.dumps(transcript),
        slots_filled_count=slots_filled_count,
        outcome=outcome,
        link_sent_at=link_sent_at,
    )
    session.add(conversation)
    session.flush()  # populate conversation.id

    profile = CandidateProfile(
        lead_id=lead_id,
        conversation_id=conversation.id,
        interested=slots.get("interested"),
        yoe=slots.get("yoe"),
        domain=slots.get("domain"),
        domain_raw=domain_raw,
        city=slots.get("city"),
        notice_period_days=slots.get("notice_period_days"),
        confirmed=slots.get("confirmed"),
    )
    session.add(profile)

    lead = session.get(Lead, lead_id)
    if dnc:
        lead.status = "DNC"
        lead.dnc_flag = True
        lead.terminal_reason = "DNC"
    elif outcome in ("COMPLETED", "NOT_INTERESTED"):
        lead.status = outcome
        lead.terminal_reason = None
    else:
        # WRONG_NUMBER, CALLBACK_LATER, HANGUP, LANGUAGE_SWITCH_REQUEST, MAX_TURNS,
        # SILENCE_TIMEOUT -- the conversation ended without a clean resolution;
        # roll up to UNREACHABLE but keep the specific reason for debugging.
        lead.status = "UNREACHABLE"
        lead.terminal_reason = outcome
    lead.in_progress_since = None
    if increment_attempts:
        lead.attempts += 1

    call_attempt = session.get(CallAttempt, call_attempt_id)
    call_attempt.ended_at = datetime.now(timezone.utc)
    call_attempt.outcome = outcome

    session.commit()
    return conversation
