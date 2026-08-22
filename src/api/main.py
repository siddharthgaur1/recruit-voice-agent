from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from src.agent.graph import fixed_agent_lines
from src.api.session import FILLER_PHRASES
from src.api.ws import router as ws_router
from src.config import settings
from src.db.models import CandidateProfile, Lead
from src.db.repo import make_engine, make_session_factory, sweep_stale_in_progress_leads
from src.voice.tts import get_synthesizer, voice_model_available


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """A crashed/killed process can leave a lead stuck IN_PROGRESS forever
    (mid live call). Reset anything older than 10 minutes back to QUEUED."""
    engine = make_engine(settings.db_path)
    session = make_session_factory(engine)()
    try:
        reset_count = sweep_stale_in_progress_leads(session, datetime.now(timezone.utc))
        if reset_count:
            print(f"Startup sweep: reset {reset_count} stale IN_PROGRESS lead(s) to QUEUED")
    finally:
        session.close()

    if voice_model_available():
        rendered = get_synthesizer().warm_cache(fixed_agent_lines() + FILLER_PHRASES)
        print(f"TTS warm cache: pre-rendered {rendered} fixed line(s)")

    yield


app = FastAPI(title="recruit-agent voice simulator", lifespan=_lifespan)
app.include_router(ws_router)

WEB_DIR = Path(__file__).resolve().parent.parent.parent / "web"


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/dashboard")
def dashboard() -> list[dict]:
    engine = make_engine(settings.db_path)
    session = make_session_factory(engine)()
    try:
        rows = []
        for lead in session.query(Lead).order_by(Lead.created_at.desc()).all():
            profile = (
                session.query(CandidateProfile)
                .filter_by(lead_id=lead.id)
                .order_by(CandidateProfile.id.desc())
                .first()
            )
            rows.append({
                "lead_id": lead.id,
                "phone": lead.phone,
                "name": lead.name,
                "status": lead.status,
                "attempts": lead.attempts,
                "next_attempt_at": lead.next_attempt_at.isoformat() if lead.next_attempt_at else None,
                "last_bucket": lead.last_bucket,
                "dnc_flag": lead.dnc_flag,
                "terminal_reason": lead.terminal_reason,
                "slots": {
                    "interested": profile.interested,
                    "yoe": profile.yoe,
                    "domain": profile.domain,
                    "domain_raw": profile.domain_raw,
                    "city": profile.city,
                    "notice_period_days": profile.notice_period_days,
                    "confirmed": profile.confirmed,
                } if profile else None,
            })
        return rows
    finally:
        session.close()
