import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse

from src.agent.graph import fixed_agent_lines
from src.api.auth import require_api_key
from src.api.session import FILLER_PHRASES
from src.api.ws import router as ws_router
from src.config import settings, setup_logging
from src.db.models import CandidateProfile, Lead
from src.db.repo import make_engine, make_session_factory, sweep_stale_in_progress_leads
from src.voice.tts import get_synthesizer, voice_model_available

logger = logging.getLogger(__name__)

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


class InsecureBindError(RuntimeError):
    """Raised at startup: bound to a non-local host with auth disabled."""


@asynccontextmanager
async def _lifespan(app: FastAPI):
    setup_logging()
    if settings.bind_host not in _LOCAL_HOSTS and not settings.recruit_agent_api_key:
        raise InsecureBindError(
            f"Refusing to start: BIND_HOST={settings.bind_host!r} is not localhost and "
            "RECRUIT_AGENT_API_KEY is unset. Anyone who can reach this host could read "
            "every lead's PII (/dashboard) or run up your LLM bill (/ws/call). Set "
            "RECRUIT_AGENT_API_KEY in .env, or bind to 127.0.0.1."
        )
    if not settings.recruit_agent_api_key:
        logger.warning(
            "RECRUIT_AGENT_API_KEY is not set -- /dashboard and /ws/call are "
            "UNAUTHENTICATED. Fine for local-only use (default bind is 127.0.0.1); "
            "do not expose this beyond localhost without setting a key."
        )

    """A crashed/killed process can leave a lead stuck IN_PROGRESS forever
    (mid live call). Reset anything older than 10 minutes back to QUEUED."""
    engine = make_engine(settings.db_path)
    session = make_session_factory(engine)()
    try:
        reset_count = sweep_stale_in_progress_leads(session, datetime.now(timezone.utc))
        if reset_count:
            logger.info("Startup sweep: reset %d stale IN_PROGRESS lead(s) to QUEUED", reset_count)
    finally:
        session.close()

    if voice_model_available():
        rendered = get_synthesizer().warm_cache(fixed_agent_lines() + FILLER_PHRASES)
        logger.info("TTS warm cache: pre-rendered %d fixed line(s)", rendered)

    yield


app = FastAPI(title="recruit-agent voice simulator", lifespan=_lifespan)
app.include_router(ws_router)

WEB_DIR = Path(__file__).resolve().parent.parent.parent / "web"


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/dashboard", dependencies=[Depends(require_api_key)])
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


if __name__ == "__main__":
    # The recommended way to run this app: binds exactly to settings.bind_host,
    # so the lifespan's bind-safety check is checking the truth, not a guess.
    # A bare `uvicorn src.api.main:app --host 0.0.0.0` bypasses that check --
    # this entrypoint exists specifically so you don't have to remember that.
    import uvicorn

    uvicorn.run(app, host=settings.bind_host, port=settings.bind_port)
