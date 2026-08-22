import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    phone: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="NEW")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_bucket: Mapped[str | None] = mapped_column(String, nullable=True)
    dnc_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    # which CallOutcome (or conversation outcome) produced a terminal rollup status
    terminal_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    # consecutive infra-error (FAILED) retries, capped independently of `attempts`
    failed_retry_count: Mapped[int] = mapped_column(Integer, default=0)
    # when status last became IN_PROGRESS; lets a startup sweep find stuck leads
    in_progress_since: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CallAttempt(Base):
    __tablename__ = "call_attempts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    lead_id: Mapped[str] = mapped_column(String, ForeignKey("leads.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    provider: Mapped[str] = mapped_column(String, default="mock")
    recording_path: Mapped[str | None] = mapped_column(String, nullable=True)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    call_attempt_id: Mapped[str] = mapped_column(String, ForeignKey("call_attempts.id"))
    slots_json: Mapped[str] = mapped_column(Text)
    transcript_json: Mapped[str] = mapped_column(Text)
    slots_filled_count: Mapped[int] = mapped_column(Integer, default=0)
    outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    link_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CandidateProfile(Base):
    """Queryable columns for the slots, e.g. 'all Java candidates in Mumbai under 60 days'."""

    __tablename__ = "candidate_profiles"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    lead_id: Mapped[str] = mapped_column(String, ForeignKey("leads.id"))
    conversation_id: Mapped[str] = mapped_column(String, ForeignKey("conversations.id"))
    interested: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    yoe: Mapped[float | None] = mapped_column(Float, nullable=True)
    domain: Mapped[str | None] = mapped_column(String, nullable=True)  # canonical tag, see slots.DOMAIN_TAGS
    domain_raw: Mapped[str | None] = mapped_column(String, nullable=True)  # candidate's literal words
    city: Mapped[str | None] = mapped_column(String, nullable=True)
    notice_period_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confirmed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
