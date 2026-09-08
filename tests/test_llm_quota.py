"""A spent daily quota must abort loudly; ordinary rate limiting must not.

docs/RESULTS.md: a single day of eval traffic exhausted the gpt-oss-120b
200k-token daily budget, and it surfaced as a generic API error partway
through a benchmark. These tests pin the distinction -- no network, no key.
"""

import pytest

from src.agent.llm import QuotaExhaustedError, _is_quota_exhausted


class _FakeStatusError(Exception):
    def __init__(self, message, status_code):
        super().__init__(message)
        self.status_code = status_code


class _FakeCompletions:
    def __init__(self, exc):
        self._exc = exc

    def create(self, **kwargs):
        raise self._exc


def _client_raising(exc):
    """A GroqClient with its SDK handle swapped for one that always raises."""
    from src.agent.llm import GroqClient

    client = GroqClient.__new__(GroqClient)  # skip __init__: no SDK, no key, no network
    client._client = type("C", (), {"chat": type("Ch", (), {"completions": _FakeCompletions(exc)})()})()
    client._model = "openai/gpt-oss-120b"
    client._reasoning_effort = None
    client.total_tokens = 0
    client.call_count = 0
    return client


@pytest.mark.parametrize("message", [
    "Rate limit reached for model gpt-oss-120b: limit 200000 tokens per day",
    "You exceeded your current quota",
    "Daily token limit reached",
])
def test_daily_quota_raises_quota_exhausted(message):
    client = _client_raising(_FakeStatusError(message, 429))
    with pytest.raises(QuotaExhaustedError) as excinfo:
        client.complete("sys", "user")
    assert "gpt-oss-120b" in str(excinfo.value)


def test_per_minute_rate_limit_is_not_treated_as_quota():
    """The SDK's own backoff handles per-minute limits -- aborting the run
    would be wrong here, so the original error must propagate unchanged."""
    exc = _FakeStatusError("Rate limit reached: 30 requests per minute", 429)
    client = _client_raising(exc)
    with pytest.raises(_FakeStatusError):
        client.complete("sys", "user")


def test_non_429_errors_propagate_unchanged():
    exc = _FakeStatusError("Internal server error", 500)
    client = _client_raising(exc)
    with pytest.raises(_FakeStatusError):
        client.complete("sys", "user")


@pytest.mark.parametrize("text,expected", [
    ("limit 200000 tokens per day", True),
    ("you exceeded your current quota", True),
    ("30 requests per minute", False),
    ("rpm limit", False),
    ("connection reset", False),
])
def test_quota_classifier(text, expected):
    assert _is_quota_exhausted(Exception(text)) is expected
