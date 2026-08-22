"""Conversation state shared across all LangGraph nodes."""

from typing import Any, TypedDict


class CallState(TypedDict):
    lead_id: str
    call_attempt_id: str
    company: str
    transcript: list[dict]  # [{"role": "agent"|"candidate", "text": str, "ts": float}]
    slots: dict[str, Any]  # slot_name -> value | None
    current_slot: str
    retry_count: int  # per-slot reprompt counter, resets on fill
    turn_count: int  # global, hard cap 25
    outcome: str | None
    disclosed: bool  # AI disclosure said?
    domain_raw: str | None  # candidate's literal words behind slots["domain"]'s canonical tag


TERMINAL_INTENTS = {
    "NOT_INTERESTED",
    "CALLBACK_LATER",
    "WRONG_NUMBER",
    "HANGUP",
    "LANGUAGE_SWITCH_REQUEST",
}
# ASKED_WHO_IS_THIS is intentionally excluded: it's handled inline, not terminal.

MAX_TURNS = 25
MAX_RETRIES_PER_SLOT = 2
