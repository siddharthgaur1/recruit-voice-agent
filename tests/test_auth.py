import pytest
from fastapi import HTTPException

from src.api.auth import auth_enabled, require_api_key, websocket_api_key_ok
from src.config import settings


class FakeWebSocket:
    def __init__(self, query_params):
        self.query_params = query_params


def test_auth_disabled_when_key_unset(monkeypatch):
    monkeypatch.setattr(settings, "recruit_agent_api_key", "")
    assert auth_enabled() is False
    require_api_key(x_api_key=None)  # must not raise
    require_api_key(x_api_key="anything")  # must not raise


def test_require_api_key_rejects_missing_or_wrong_key(monkeypatch):
    monkeypatch.setattr(settings, "recruit_agent_api_key", "secret123")
    with pytest.raises(HTTPException) as exc_info:
        require_api_key(x_api_key=None)
    assert exc_info.value.status_code == 401

    with pytest.raises(HTTPException):
        require_api_key(x_api_key="wrong")


def test_require_api_key_accepts_correct_key(monkeypatch):
    monkeypatch.setattr(settings, "recruit_agent_api_key", "secret123")
    require_api_key(x_api_key="secret123")  # must not raise


def test_websocket_api_key_ok_when_auth_disabled(monkeypatch):
    monkeypatch.setattr(settings, "recruit_agent_api_key", "")
    assert websocket_api_key_ok(FakeWebSocket({})) is True


def test_websocket_api_key_ok_checks_query_param(monkeypatch):
    monkeypatch.setattr(settings, "recruit_agent_api_key", "secret123")
    assert websocket_api_key_ok(FakeWebSocket({})) is False
    assert websocket_api_key_ok(FakeWebSocket({"api_key": "wrong"})) is False
    assert websocket_api_key_ok(FakeWebSocket({"api_key": "secret123"})) is True
