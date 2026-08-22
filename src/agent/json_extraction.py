"""Shared JSON-parsing helpers for LLM extraction output.

Split out from extractor.py so llm.py's EscalatingLLMClient can peek at a
response's confidence (to decide whether to escalate) without extractor.py
and llm.py importing each other.
"""

import json
import re

CONFIDENCE_THRESHOLD = 0.7


def strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(json)?", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"```$", "", text).strip()
    return text


def try_parse_json(raw: str) -> dict | None:
    try:
        data = json.loads(strip_fences(raw))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data
