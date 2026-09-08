import logging

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: str = "groq"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"  # escalation tier
    # Fast tier: llama-3.1-8b-instant (spec's original pick) isn't available
    # on this Groq account/tier -- substituting the smaller gpt-oss reasoning
    # model, which is actually available and benchmarks fast at low effort.
    groq_model_fast: str = "openai/gpt-oss-20b"
    groq_reasoning_effort: str = "low"
    extraction_escalation_enabled: bool = True
    # The SDK already retries 429/5xx with backoff (its own default is 2).
    # Surfaced here so a flaky-network run can raise it without a code change.
    groq_max_retries: int = 3
    groq_timeout_s: float = 30.0

    # Alternate provider (src/agent/llm.py::GeminiClient) -- not the default,
    # exists as a real fallback with its own separate quota. Set
    # LLM_PROVIDER=gemini to switch.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"

    # Local Ollama spike -- no quota, no cost, but CPU-only inference on
    # unaccelerated hardware may not be fast enough (see docs/RESULTS.md).
    ollama_model: str = "llama3.2:latest"
    ollama_host: str = "http://localhost:11434"

    company_name: str = "Acme Corp"
    disclosure_text: str = (
        "Hi, this is an automated recruiting assistant calling on behalf of {company}."
    )

    recording_enabled: bool = False
    db_path: str = "recruit_agent.db"
    log_level: str = "INFO"

    # Phase 3: local voice loop
    whisper_model: str = "small"  # multilingual (not "small.en") -- needed for Hinglish
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"

    piper_model_path: str = "models/en_US-lessac-medium.onnx"

    vad_aggressiveness: int = 2  # 0-3, higher = more aggressive about filtering non-speech
    vad_frame_ms: int = 20
    vad_endpoint_silence_ms: int = 700  # trailing silence to consider an utterance finished

    # Consecutive speech required to cancel the agent mid-sentence. A single
    # 20ms frame is not enough: on a real line the agent's own audio echoing
    # back would cut it off constantly.
    barge_in_min_speech_ms: int = 120

    silence_prompt_after_s: float = 7.0   # "Are you still there?"
    silence_close_after_s: float = 12.0   # give up and end the call

    # --- API server security ------------------------------------------------
    # Empty (default) = auth disabled; the app prints a loud startup warning.
    # Set to require a matching key on /dashboard (header) and /ws/call (query
    # param) -- see README's Security section.
    recruit_agent_api_key: str = ""

    # The host/port this app's own runner (`python -m src.api.main`) binds to,
    # ALSO used as the source of truth for the startup bind-safety check: if
    # this isn't localhost and no API key is set, the app refuses to start.
    # Running via a bare `uvicorn ... --host 0.0.0.0` bypasses this check (the
    # app can't see uvicorn's CLI flags) -- `python -m src.api.main` is the
    # recommended entrypoint precisely because it keeps the two in sync.
    bind_host: str = "127.0.0.1"
    bind_port: int = 8000

    # /ws/call abuse guards -- independent of auth: a valid key doesn't stop
    # a buggy client from draining the LLM quota or pegging the CPU.
    max_concurrent_calls: int = 5
    max_calls_per_ip_per_minute: int = 3


settings = Settings()


def setup_logging() -> None:
    """Call once from an entrypoint. Library code just uses logging.getLogger(__name__)."""
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    )


def mask_phone(phone: str | None) -> str:
    """Candidate phone numbers are PII -- log the last 4 digits only."""
    if not phone:
        return "<none>"
    return f"***{phone[-4:]}"
