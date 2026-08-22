"""Optional shared-secret auth. Disabled (with a loud startup warning) when
RECRUIT_AGENT_API_KEY is unset -- see README's Security section."""

from fastapi import Header, HTTPException, WebSocket

from src.config import settings


def auth_enabled() -> bool:
    return bool(settings.recruit_agent_api_key)


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """HTTP dependency for /dashboard etc. No-op when auth is disabled."""
    if not auth_enabled():
        return
    if x_api_key != settings.recruit_agent_api_key:
        raise HTTPException(status_code=401, detail="missing or invalid X-API-Key")


def websocket_api_key_ok(websocket: WebSocket) -> bool:
    """Check for /ws/call: query param ?api_key=... since browsers can't set
    custom headers on a WebSocket handshake. No-op (always True) when auth
    is disabled."""
    if not auth_enabled():
        return True
    return websocket.query_params.get("api_key") == settings.recruit_agent_api_key
