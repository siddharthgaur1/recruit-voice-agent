import json

from src.agent.llm import EscalatingLLMClient


class StubLLM:
    def __init__(self, response):
        self._response = response
        self.calls = 0

    def complete(self, system: str, user: str) -> str:
        self.calls += 1
        return self._response if isinstance(self._response, str) else json.dumps(self._response)


def test_uses_fast_model_when_confidence_is_high():
    fast = StubLLM({"intent": "ANSWER", "slots": {"yoe": 4}, "confidence": 0.9})
    escalation = StubLLM({"intent": "ANSWER", "slots": {"yoe": 4}, "confidence": 0.9})
    client = EscalatingLLMClient(fast, escalation)

    client.complete("sys", "user")

    assert fast.calls == 1
    assert escalation.calls == 0
    assert client.last_used == "fast"


def test_escalates_when_fast_model_confidence_is_low():
    fast = StubLLM({"intent": "UNCLEAR", "slots": {}, "confidence": 0.3})
    escalation = StubLLM({"intent": "ANSWER", "slots": {"yoe": 4}, "confidence": 0.95})
    client = EscalatingLLMClient(fast, escalation)

    result = client.complete("sys", "user")

    assert fast.calls == 1
    assert escalation.calls == 1
    assert client.last_used == "escalation"
    assert json.loads(result)["confidence"] == 0.95


def test_escalates_when_fast_model_returns_unparseable_json():
    fast = StubLLM("not json at all")
    escalation = StubLLM({"intent": "ANSWER", "slots": {}, "confidence": 0.9})
    client = EscalatingLLMClient(fast, escalation)

    client.complete("sys", "user")

    assert escalation.calls == 1
    assert client.last_used == "escalation"


def test_respects_custom_threshold():
    fast = StubLLM({"intent": "ANSWER", "slots": {}, "confidence": 0.75})
    escalation = StubLLM({"intent": "ANSWER", "slots": {}, "confidence": 0.99})
    client = EscalatingLLMClient(fast, escalation, threshold=0.8)

    client.complete("sys", "user")

    assert client.last_used == "escalation"  # 0.75 < custom threshold 0.8


def test_total_tokens_and_call_count_sum_both_tiers():
    class StubWithUsage(StubLLM):
        def __init__(self, response, tokens_per_call):
            super().__init__(response)
            self.total_tokens = 0
            self.call_count = 0
            self._tokens_per_call = tokens_per_call

        def complete(self, system, user):
            result = super().complete(system, user)
            self.total_tokens += self._tokens_per_call
            self.call_count += 1
            return result

    fast = StubWithUsage({"intent": "UNCLEAR", "slots": {}, "confidence": 0.2}, tokens_per_call=100)
    escalation = StubWithUsage({"intent": "ANSWER", "slots": {}, "confidence": 0.9}, tokens_per_call=300)
    client = EscalatingLLMClient(fast, escalation)

    client.complete("sys", "user")  # escalates: fast (100) + escalation (300)

    assert client.total_tokens == 400
    assert client.call_count == 2
