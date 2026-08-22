import json


class FakeLLM:
    """Returns pre-scripted JSON responses in order, one per .complete() call."""

    def __init__(self, responses: list[dict | str]):
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        response = self._responses.pop(0)
        if isinstance(response, str):
            return response
        return json.dumps(response)
