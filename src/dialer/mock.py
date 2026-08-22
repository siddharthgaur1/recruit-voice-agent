import random

from src.dialer.provider import CallOutcome, TelephonyProvider


class MockProvider(TelephonyProvider):
    """Configurable-outcome fake dialer.

    weights: dict[CallOutcome, float] -- random.choices per call.
    scripted: fixed sequence of outcomes returned in order (deterministic tests);
              takes priority over weights when both are given.
    """

    def __init__(self, weights: dict[CallOutcome, float] | None = None,
                 scripted: list[CallOutcome] | None = None):
        self._scripted = list(scripted) if scripted is not None else None
        if self._scripted is None:
            self._weights = weights or {CallOutcome.HUMAN_ANSWERED: 1.0}
        else:
            self._weights = None

    def place_call(self, phone: str) -> CallOutcome:
        if self._scripted is not None:
            if not self._scripted:
                raise RuntimeError("MockProvider scripted outcomes exhausted")
            return self._scripted.pop(0)
        outcomes = list(self._weights.keys())
        weights = list(self._weights.values())
        return random.choices(outcomes, weights=weights, k=1)[0]
