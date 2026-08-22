import pytest

from src.api import rate_limit
from src.config import settings


@pytest.fixture(autouse=True)
def _clean_rate_limit_state():
    rate_limit.reset_for_tests()
    yield
    rate_limit.reset_for_tests()


def test_allows_up_to_the_concurrent_cap(monkeypatch):
    monkeypatch.setattr(settings, "max_concurrent_calls", 2)
    monkeypatch.setattr(settings, "max_calls_per_ip_per_minute", 100)

    rate_limit.check_and_register("1.1.1.1")
    rate_limit.check_and_register("2.2.2.2")
    with pytest.raises(rate_limit.RateLimitExceeded):
        rate_limit.check_and_register("3.3.3.3")


def test_release_frees_a_concurrent_slot(monkeypatch):
    monkeypatch.setattr(settings, "max_concurrent_calls", 1)
    monkeypatch.setattr(settings, "max_calls_per_ip_per_minute", 100)

    rate_limit.check_and_register("1.1.1.1")
    with pytest.raises(rate_limit.RateLimitExceeded):
        rate_limit.check_and_register("2.2.2.2")

    rate_limit.release()
    rate_limit.check_and_register("2.2.2.2")  # slot freed, no longer raises


def test_per_ip_rate_limit_independent_of_concurrency(monkeypatch):
    monkeypatch.setattr(settings, "max_concurrent_calls", 100)
    monkeypatch.setattr(settings, "max_calls_per_ip_per_minute", 2)

    rate_limit.check_and_register("9.9.9.9")
    rate_limit.release()
    rate_limit.check_and_register("9.9.9.9")
    rate_limit.release()
    with pytest.raises(rate_limit.RateLimitExceeded):
        rate_limit.check_and_register("9.9.9.9")

    # a different IP is unaffected
    rate_limit.check_and_register("8.8.8.8")
