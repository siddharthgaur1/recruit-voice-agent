from src.agent.llm import GeminiClient, GroqClient, OllamaClient, build_llm_client
from src.config import settings


def test_gemini_client_is_lazy_and_does_not_import_sdk_at_construction(monkeypatch):
    # Constructing GeminiClient touches the network client immediately (like
    # GroqClient), but must not require network access to instantiate when
    # given a syntactically valid key -- this just proves the class wires
    # up without raising, not that a real call succeeds.
    client = GeminiClient(api_key="fake-key-for-structural-test", model="gemini-2.0-flash")
    assert client.total_tokens == 0
    assert client.call_count == 0
    assert hasattr(client, "complete")


def test_build_llm_client_dispatches_to_gemini_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_api_key", "fake-key")
    client = build_llm_client()
    assert isinstance(client, GeminiClient)


def test_ollama_client_is_lazy_and_does_not_require_network_at_construction():
    client = OllamaClient(model="llama3.2:latest", host="http://localhost:11434")
    assert client.total_tokens == 0
    assert client.call_count == 0
    assert hasattr(client, "complete")


def test_build_llm_client_dispatches_to_ollama_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    client = build_llm_client()
    assert isinstance(client, OllamaClient)


def test_build_llm_client_still_defaults_to_groq_escalation(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "groq")
    monkeypatch.setattr(settings, "extraction_escalation_enabled", True)
    client = build_llm_client()
    from src.agent.llm import EscalatingLLMClient

    assert isinstance(client, EscalatingLLMClient)
    assert isinstance(client._fast, GroqClient)
    assert isinstance(client._escalation, GroqClient)
