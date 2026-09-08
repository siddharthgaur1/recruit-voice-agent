"""Provider-agnostic LLM client. Default: Groq free tier."""

from typing import Protocol

from src.agent.json_extraction import CONFIDENCE_THRESHOLD, try_parse_json
from src.config import settings


class LLMClient(Protocol):
    def complete(self, system: str, user: str) -> str: ...


# gpt-oss reasoning models accept a reasoning_effort knob; a plain chat model
# (e.g. llama) rejects the param outright, so only send it where it's known
# to be accepted.
_REASONING_MODEL_PREFIX = "openai/gpt-oss"


class QuotaExhaustedError(RuntimeError):
    """A provider daily/token quota is spent -- retrying will not help.

    Worth its own type: a whole day of eval traffic once exhausted the
    gpt-oss-120b 200k/day budget (docs/RESULTS.md), and it surfaced as a
    generic API error deep inside a benchmark run. A harness can now catch
    this specifically and stop, rather than burning the rest of its script
    against a tier that has nothing left.
    """


class GroqClient:
    def __init__(self, api_key: str, model: str, reasoning_effort: str | None = None,
                 max_retries: int | None = None, timeout_s: float | None = None):
        from groq import Groq  # imported lazily so tests never need the SDK/network

        # The SDK retries 429/5xx/connection errors with exponential backoff
        # itself; these just make its budget configurable.
        self._client = Groq(
            api_key=api_key,
            max_retries=settings.groq_max_retries if max_retries is None else max_retries,
            timeout=settings.groq_timeout_s if timeout_s is None else timeout_s,
        )
        self._model = model
        self._reasoning_effort = reasoning_effort
        # Visible so a harness can print cumulative usage as it runs and
        # notice it's approaching a provider's daily quota before a call
        # fails outright, instead of finding out mid-benchmark.
        self.total_tokens = 0
        self.call_count = 0

    def complete(self, system: str, user: str) -> str:
        kwargs: dict = dict(  # noqa: C408 -- kwargs are conditionally extended below
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0,
        )
        if self._reasoning_effort and self._model.startswith(_REASONING_MODEL_PREFIX):
            kwargs["reasoning_effort"] = self._reasoning_effort

        try:
            response = self._client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 -- re-raised below, only 429 is special-cased
            # Checked by attribute rather than by SDK exception class so this
            # keeps working across groq-python versions.
            if getattr(exc, "status_code", None) == 429 and _is_quota_exhausted(exc):
                raise QuotaExhaustedError(
                    f"{self._model}: provider quota exhausted, retrying will not help. "
                    "Wait for the daily reset, switch LLM_PROVIDER (gemini/ollama), "
                    "or disable EXTRACTION_ESCALATION_ENABLED to stay on the fast tier."
                ) from exc
            raise

        usage = getattr(response, "usage", None)
        if usage is not None:
            self.total_tokens += getattr(usage, "total_tokens", 0) or 0
        self.call_count += 1

        return response.choices[0].message.content or ""


def _is_quota_exhausted(exc: Exception) -> bool:
    """Distinguish a spent daily/token budget from ordinary per-minute rate
    limiting -- the SDK's own backoff handles the latter, and only the former
    is worth aborting a run over."""
    text = str(exc).lower()
    per_minute = ("per minute" in text or "requests per minute" in text or "rpm" in text)
    return not per_minute and any(
        k in text for k in ("quota", "per day", "daily", "tokens per day", "tpd", "limit reached")
    )


class GeminiClient:
    """Google Gemini, behind the same LLMClient interface. Not the default
    provider -- exists so a quota-exhausted Groq tier has a real fallback
    with its own separate free-tier quota, without touching extractor.py or
    graph.py (they only ever depend on the LLMClient.complete() shape)."""

    def __init__(self, api_key: str, model: str = "gemini-3.6-flash"):
        from google import genai  # imported lazily so tests never need the SDK/network

        self._client = genai.Client(api_key=api_key)
        self._model = model
        self.total_tokens = 0
        self.call_count = 0

    def complete(self, system: str, user: str) -> str:
        from google.genai import types

        response = self._client.models.generate_content(
            model=self._model,
            contents=user,
            config=types.GenerateContentConfig(system_instruction=system, temperature=0),
        )

        usage = getattr(response, "usage_metadata", None)
        if usage is not None:
            self.total_tokens += getattr(usage, "total_token_count", 0) or 0
        self.call_count += 1

        return response.text or ""


class OllamaClient:
    """Local Ollama, behind the same LLMClient interface. A spike, not the
    default: no quota, no queueing, no per-call cost -- but only worth
    switching to if latency and accuracy actually hold up on real hardware."""

    def __init__(self, model: str = "llama3.2:latest", host: str = "http://localhost:11434"):
        import httpx  # already a project dependency, no new package needed

        self._client = httpx.Client(base_url=host, timeout=60.0)
        self._model = model
        self.total_tokens = 0
        self.call_count = 0

    def complete(self, system: str, user: str) -> str:
        response = self._client.post("/api/chat", json={
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"temperature": 0},
        })
        response.raise_for_status()
        data = response.json()

        self.total_tokens += (data.get("prompt_eval_count", 0) or 0) + (data.get("eval_count", 0) or 0)
        self.call_count += 1

        return data.get("message", {}).get("content", "") or ""


class EscalatingLLMClient:
    """Tries a fast/cheap model first; escalates to a stronger model only
    when the fast model's own reported confidence is below threshold (or it
    failed to produce parseable JSON at all). Exposes `last_used` so callers
    can measure how often each tier actually gets used."""

    def __init__(self, fast: LLMClient, escalation: LLMClient,
                 threshold: float = CONFIDENCE_THRESHOLD):
        self._fast = fast
        self._escalation = escalation
        self._threshold = threshold
        self.last_used: str | None = None  # "fast" | "escalation"

    def complete(self, system: str, user: str) -> str:
        raw = self._fast.complete(system, user)
        data = try_parse_json(raw)
        confidence = float(data.get("confidence", 0.0) or 0.0) if data else 0.0

        if data is not None and confidence >= self._threshold:
            self.last_used = "fast"
            return raw

        self.last_used = "escalation"
        return self._escalation.complete(system, user)

    @property
    def total_tokens(self) -> int:
        return getattr(self._fast, "total_tokens", 0) + getattr(self._escalation, "total_tokens", 0)

    @property
    def call_count(self) -> int:
        return getattr(self._fast, "call_count", 0) + getattr(self._escalation, "call_count", 0)


def build_llm_client() -> LLMClient:
    if settings.llm_provider == "gemini":
        return GeminiClient(settings.gemini_api_key, settings.gemini_model)

    if settings.llm_provider == "ollama":
        return OllamaClient(settings.ollama_model, settings.ollama_host)

    if settings.llm_provider != "groq":
        raise ValueError(f"Unsupported LLM_PROVIDER: {settings.llm_provider}")

    escalation = GroqClient(
        settings.groq_api_key, settings.groq_model,
        reasoning_effort=settings.groq_reasoning_effort,
    )
    if not settings.extraction_escalation_enabled:
        return escalation

    fast = GroqClient(
        settings.groq_api_key, settings.groq_model_fast,
        reasoning_effort=settings.groq_reasoning_effort,
    )
    return EscalatingLLMClient(fast, escalation)
