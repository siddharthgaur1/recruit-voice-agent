import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.api import rate_limit
from src.api.ws import CLOSE_RATE_LIMITED, CLOSE_UNAUTHORIZED
from src.config import settings


@pytest.fixture(autouse=True)
def _clean_rate_limit_state():
    rate_limit.reset_for_tests()
    yield
    rate_limit.reset_for_tests()


def test_ws_call_rejects_missing_api_key_before_accept(monkeypatch):
    monkeypatch.setattr(settings, "recruit_agent_api_key", "secret123")
    from src.api.main import app
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/call"):
            pass
    assert exc_info.value.code == CLOSE_UNAUTHORIZED


def test_ws_call_rejects_wrong_api_key(monkeypatch):
    monkeypatch.setattr(settings, "recruit_agent_api_key", "secret123")
    from src.api.main import app
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/call?api_key=wrong"):
            pass
    assert exc_info.value.code == CLOSE_UNAUTHORIZED


def test_ws_call_rate_limits_concurrent_connections(monkeypatch):
    monkeypatch.setattr(settings, "recruit_agent_api_key", "")
    monkeypatch.setattr(settings, "max_concurrent_calls", 0)  # nothing can get through
    from src.api.main import app
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/call"):
            pass
    assert exc_info.value.code == CLOSE_RATE_LIMITED
