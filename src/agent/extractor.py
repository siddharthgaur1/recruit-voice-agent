"""LLM-based slot extraction. Strict JSON in, strict JSON out.

A deterministic pre-pass handles the common case (a short, unambiguous
yes/no or number reply, including Hinglish) with zero LLM calls. The LLM is
only consulted when the pre-pass can't confidently resolve the current slot
alone -- multi-slot answers, terminal intents, and anything not covered by
the pre-pass's conservative keyword/regex match still go through it exactly
as before.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from src.agent.json_extraction import CONFIDENCE_THRESHOLD, try_parse_json
from src.agent.llm import LLMClient
from src.agent.slots import SLOTS_BY_NAME, normalize_bool, normalize_notice_period_days, normalize_yoe

VALID_INTENTS = {
    "ANSWER", "NOT_INTERESTED", "CALLBACK_LATER", "WRONG_NUMBER",
    "HANGUP", "ASKED_WHO_IS_THIS", "LANGUAGE_SWITCH_REQUEST", "UNCLEAR",
}

# Keywords suggesting the reply is NOT a plain slot answer (terminal intent,
# a question back, etc.) -- if any of these appear, skip the fast path and
# let the LLM classify it properly instead of risking a wrong deterministic fill.
_NOT_A_PLAIN_ANSWER = re.compile(
    r"\b(who|wrong|number|stop|later|busy|meeting|call\s*back|remove|"
    r"unsubscribe|language|hindi|english|hangup|bye|goodbye)\b",
    re.IGNORECASE,
)

# Hedging language means the reply is NOT a confident, committed answer --
# a real LLM would (and should) omit the slot rather than guess; the
# deterministic pre-pass must defer to it rather than confidently guessing.
_HEDGE = re.compile(
    r"\b(maybe|depends|around|not\s+sure|few|some|probably|think|guess|"
    r"approximately|ish|somewhere)\b",
    re.IGNORECASE,
)

_FAST_PATH_MAX_WORDS = {
    "interested": 4, "confirmed": 4,  # yes/no answers are always short
    "yoe": 4, "notice_period_days": 4,  # numbers may carry a short unit phrase
}

# STT homophones for number words (observed live: faster-whisper transcribed
# "Four years" as "for years", breaking yoe extraction outright). Scoped to
# the fast path's already-short, already-filtered replies only -- "to"/"too"
# are common enough words that resolving them everywhere would misfire
# constantly; within a <=4-word reply already screened for hedges/terminal
# intent, the risk is much smaller but not zero (e.g. "for now" -> "four
# now" -> 4.0 is a real false positive this doesn't catch).
_NUMBER_HOMOPHONES = {"for": "four", "to": "two", "too": "two", "ate": "eight"}


def _resolve_number_homophones(text: str) -> str:
    words = text.split()
    resolved = [_NUMBER_HOMOPHONES.get(w.lower().strip(".,!?"), w) for w in words]
    return " ".join(resolved)


def _fast_path(current_slot: str, utterance: str) -> Any:
    """Best-effort deterministic fill for the slot currently being asked
    about. Returns None (fall through to the LLM) whenever the reply looks
    like anything other than a short, unambiguous, single-fact answer to
    that slot -- multi-slot answers and hedged/vague answers must still go
    through the LLM."""
    max_words = _FAST_PATH_MAX_WORDS.get(current_slot)
    if max_words is None:
        return None
    text = utterance.strip()
    if not text or len(text.split()) > max_words:
        return None
    if "," in text:  # a strong signal of "X, Y, and Z" multi-slot spillover
        return None
    if _NOT_A_PLAIN_ANSWER.search(text) or _HEDGE.search(text):
        return None

    if current_slot in ("interested", "confirmed"):
        return normalize_bool(text)
    if current_slot == "yoe":
        result = normalize_yoe(text)
        return result if result is not None else normalize_yoe(_resolve_number_homophones(text))
    if current_slot == "notice_period_days":
        result = normalize_notice_period_days(text)
        if result is not None:
            return result
        return normalize_notice_period_days(_resolve_number_homophones(text))
    return None

_SYSTEM_PROMPT = """You extract structured data from a recruiting candidate's spoken reply.
Respond with ONLY a JSON object, no prose, no markdown code fences. Schema:
{"intent": "ANSWER|NOT_INTERESTED|CALLBACK_LATER|WRONG_NUMBER|HANGUP|ASKED_WHO_IS_THIS|LANGUAGE_SWITCH_REQUEST|UNCLEAR", "slots": {}, "confidence": 0.0}

Rules:
- "slots" may contain any of: interested (bool), yoe (number, years of experience),
  domain (string), city (string), notice_period_days (number, always in days),
  confirmed (bool). Only include slots you can confidently read off the reply.
- "city" must be a specific city or town (e.g. "Mumbai", "Pune"). A state, region,
  or country ("Maharashtra", "somewhere in the south", "India") is NOT a city --
  do not fill city from those, and do not guess a specific city from a region name.
- Vague hedges ("few years", "somewhere around there", "depends", "not sure exactly")
  are not confident answers -- omit that slot rather than guessing a value.
- The candidate may answer in Hindi/Hinglish. Examples:
  "haan dekh raha hoon" -> interested: true
  "do mahine ka notice hai" -> notice_period_days: 60
  "4 saal se kaam kar raha hoon" -> yoe: 4
- If the candidate gives multiple pieces of information at once
  ("4 years, Java, Mumbai"), fill every slot you can from that single reply.
- "confidence" is your overall confidence (0.0-1.0) in this entire extraction.
"""

_JSON_NUDGE = "\n\nReturn ONLY the JSON object. No prose, no markdown fences."


@dataclass
class ExtractionResult:
    intent: str
    slots: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    fast_pathed: bool = False  # resolved deterministically, zero LLM calls
    retried: bool = False  # first LLM response failed to parse as JSON, retried once


def extract(llm: LLMClient, current_slot: str, utterance: str) -> ExtractionResult:
    fast_value = _fast_path(current_slot, utterance)
    if fast_value is not None:
        return ExtractionResult(
            intent="ANSWER", slots={current_slot: fast_value}, confidence=1.0, fast_pathed=True,
        )

    user_prompt = f"Candidate reply (currently being asked about '{current_slot}'):\n{utterance}"

    raw = llm.complete(_SYSTEM_PROMPT, user_prompt)
    data = try_parse_json(raw)
    retried = False

    if data is None:
        retried = True
        raw_retry = llm.complete(_SYSTEM_PROMPT + _JSON_NUDGE, user_prompt)
        data = try_parse_json(raw_retry)

    if data is None:
        return ExtractionResult(intent="UNCLEAR", slots={}, confidence=0.0, retried=retried)

    intent = data.get("intent")
    if intent not in VALID_INTENTS:
        intent = "UNCLEAR"

    confidence = float(data.get("confidence", 0.0) or 0.0)
    raw_slots = data.get("slots") or {}

    normalized_slots: dict[str, Any] = {}
    if confidence >= CONFIDENCE_THRESHOLD:
        for name, value in raw_slots.items():
            slot = SLOTS_BY_NAME.get(name)
            if slot is None:
                continue
            normalized = slot.normalize(value)
            if normalized is not None:
                normalized_slots[name] = normalized

    return ExtractionResult(
        intent=intent, slots=normalized_slots, confidence=confidence, retried=retried,
    )
