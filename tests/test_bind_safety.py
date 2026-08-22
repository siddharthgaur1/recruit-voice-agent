import pytest

from src.api.main import InsecureBindError, _lifespan, app
from src.config import settings


@pytest.mark.asyncio
async def test_refuses_to_start_on_public_bind_without_api_key(monkeypatch):
    monkeypatch.setattr(settings, "bind_host", "0.0.0.0")
    monkeypatch.setattr(settings, "recruit_agent_api_key", "")

    with pytest.raises(InsecureBindError):
        async with _lifespan(app):
            pass


@pytest.mark.asyncio
async def test_allows_public_bind_when_api_key_is_set(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "bind_host", "0.0.0.0")
    monkeypatch.setattr(settings, "recruit_agent_api_key", "secret123")
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "bind_test.db"))

    async with _lifespan(app):
        pass  # must not raise


@pytest.mark.asyncio
async def test_allows_localhost_bind_without_api_key(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "bind_host", "127.0.0.1")
    monkeypatch.setattr(settings, "recruit_agent_api_key", "")
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "bind_test2.db"))

    async with _lifespan(app):
        pass  # must not raise
