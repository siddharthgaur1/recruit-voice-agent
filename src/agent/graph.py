"""LangGraph conversation state machine.

The LLM never decides what to ask next. Each invoke() processes exactly one
candidate utterance: extract -> check terminal intent -> advance the slot
machine deterministically.
"""

import time
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from src.agent.extractor import extract
from src.agent.json_extraction import CONFIDENCE_THRESHOLD
from src.agent.llm import LLMClient
from src.agent.slots import SLOT_ORDER, SLOTS_BY_NAME, first_unfilled_slot
from src.agent.state import MAX_RETRIES_PER_SLOT, MAX_TURNS, TERMINAL_INTENTS, CallState
from src.config import settings


class _GraphState(TypedDict, total=False):
    """CallState plus the transient, single-turn scratch fields the graph nodes pass along."""

    lead_id: str
    call_attempt_id: str
    company: str
    transcript: list[dict]
    slots: dict[str, Any]
    current_slot: str
    retry_count: int
    turn_count: int
    outcome: str | None
    disclosed: bool
    domain_raw: str | None
    _utterance: str
    _intent: str
    _extracted_slots: dict[str, Any]
    _confidence: float
    _fast_pathed: bool
    _retried: bool
    _agent_message: str
    _route: str
    _dnc: bool

_OPT_OUT_PHRASES = (
    "stop calling", "don't call", "do not call", "remove me",
    "take me off", "stop contacting", "unsubscribe",
)


def _is_opt_out(utterance: str) -> bool:
    text = utterance.lower()
    return any(phrase in text for phrase in _OPT_OUT_PHRASES)


# A live call must never end on STT output alone (a misheard or hallucinated
# transcript can "confidently" get classified as HANGUP). Ending the call on
# HANGUP additionally requires the actual words to explicitly corroborate it.
_HANGUP_PHRASES = (
    "hang up", "hanging up", "goodbye", "good bye", "bye now",
    "gotta go", "got to go", "have to go", "need to go",
    "end the call", "ending the call", "disconnect",
)


def _hangup_corroborated(utterance: str) -> bool:
    text = utterance.lower()
    return any(phrase in text for phrase in _HANGUP_PHRASES)


CLOSING_MESSAGES = {
    "NOT_INTERESTED": "No problem at all, thanks for your time. Have a great day!",
    "CALLBACK_LATER": "Sure, no problem — I'll call back at a better time. Thanks!",
    "WRONG_NUMBER": "Apologies for the confusion, have a great day!",
    "HANGUP": "",
    "LANGUAGE_SWITCH_REQUEST": (
        "Sorry, I can only continue in English right now. I'll have someone follow up. Thanks!"
    ),
}


def _say(state: dict, text: str) -> list[dict]:
    return state["transcript"] + [{"role": "agent", "text": text, "ts": time.time()}]


def fixed_agent_lines(company: str | None = None) -> list[str]:
    """Every deterministic, company-name-only-templated line CallSession can
    speak outside of a reprompt/closing message: the disclosure line, each
    of the 6 slot questions, and the actual opening line (disclosure + first
    question, concatenated -- that's the literal string opening_message()
    synthesizes). Pre-render TTS for these at startup so only reprompts pay
    live-synthesis latency.
    """
    company = company or settings.company_name
    disclosure = settings.disclosure_text.format(company=company)
    questions = [SLOTS_BY_NAME[name].question.format(company=company) for name in SLOT_ORDER]
    opening = f"{disclosure} {questions[0]}"
    return [disclosure, *questions, opening]


def opening_message(state: CallState) -> tuple[CallState, str]:
    """Produce the very first agent utterance: disclosure + first slot question."""
    disclosure = settings.disclosure_text.format(company=state["company"])
    first_slot = SLOT_ORDER[0]
    question = SLOTS_BY_NAME[first_slot].question.format(company=state["company"])
    message = f"{disclosure} {question}"
    new_state = {
        **state,
        "current_slot": first_slot,
        "disclosed": True,
        "transcript": _say(state, message),
    }
    return new_state, message


def build_graph(llm: LLMClient):
    def extract_node(state: dict) -> dict:
        utterance = state["_utterance"]
        transcript = state["transcript"] + [
            {"role": "candidate", "text": utterance, "ts": time.time()}
        ]
        result = extract(llm, state["current_slot"], utterance)
        return {
            "turn_count": state["turn_count"] + 1,
            "transcript": transcript,
            "_intent": result.intent,
            "_extracted_slots": result.slots,
            "_confidence": result.confidence,
            "_fast_pathed": result.fast_pathed,
            "_retried": result.retried,
        }

    def terminal_node(state: dict) -> dict:
        intent = state["_intent"]

        if intent == "HANGUP":
            confident = state.get("_confidence", 0.0) >= CONFIDENCE_THRESHOLD
            corroborated = _hangup_corroborated(state["_utterance"])
            if not (confident and corroborated):
                intent = "UNCLEAR"  # never trust a bare HANGUP label alone

        if state["turn_count"] > MAX_TURNS:
            message = "We've covered a lot for now — I'll follow up another time. Thanks!"
            return {
                "outcome": "MAX_TURNS",
                "transcript": _say(state, message),
                "_agent_message": message,
                "_route": "closed",
            }

        if intent == "ASKED_WHO_IS_THIS":
            disclosure = settings.disclosure_text.format(company=state["company"])
            question = SLOTS_BY_NAME[state["current_slot"]].question.format(
                company=state["company"]
            )
            message = f"{disclosure} {question}"
            return {
                "transcript": _say(state, message),
                "_agent_message": message,
                "_route": "end_turn",
            }

        if intent in TERMINAL_INTENTS:
            dnc = intent in ("NOT_INTERESTED", "HANGUP") and _is_opt_out(state["_utterance"])
            message = (
                "Understood, I'll take you off our calling list. Apologies for the bother!"
                if dnc
                else CLOSING_MESSAGES.get(intent, "Thanks for your time, goodbye.")
            )
            return {
                "outcome": intent,
                "_dnc": dnc,
                "transcript": _say(state, message) if message else state["transcript"],
                "_agent_message": message,
                "_route": "closed",
            }

        return {"_route": "advance"}

    def advance_node(state: dict) -> dict:
        slots = dict(state["slots"])
        slots.update(state["_extracted_slots"])
        current = state["current_slot"]
        filled_now = current in state["_extracted_slots"]
        retry_count = 0 if filled_now else state["retry_count"] + 1

        # The candidate's literal words behind slots["domain"]'s canonical tag,
        # for humans/audits -- the structured column stays queryable, this doesn't.
        domain_raw = state.get("domain_raw")
        if "domain" in state["_extracted_slots"]:
            domain_raw = state["_utterance"]

        if slots.get("interested") is False:
            dnc = _is_opt_out(state["_utterance"])
            message = (
                "Understood, I'll take you off our calling list. Apologies for the bother!"
                if dnc
                else CLOSING_MESSAGES["NOT_INTERESTED"]
            )
            return {
                "slots": slots,
                "domain_raw": domain_raw,
                "outcome": "NOT_INTERESTED",
                "_dnc": dnc,
                "transcript": _say(state, message),
                "_agent_message": message,
            }

        abandoned = not filled_now and retry_count >= MAX_RETRIES_PER_SLOT
        if abandoned:
            retry_count = 0

        next_slot = first_unfilled_slot(slots, after=current) if (filled_now or abandoned) else current

        if next_slot is None:
            message = (
                "Perfect, that's everything I need. I'll send the details on WhatsApp. "
                "Thanks so much for your time!"
            )
            return {
                "slots": slots,
                "domain_raw": domain_raw,
                "outcome": "COMPLETED",
                "retry_count": retry_count,
                "transcript": _say(state, message),
                "_agent_message": message,
            }

        question = SLOTS_BY_NAME[next_slot].question.format(company=state["company"])
        if next_slot == current and not filled_now:
            question = "Sorry, I didn't quite catch that. " + question

        return {
            "slots": slots,
            "domain_raw": domain_raw,
            "current_slot": next_slot,
            "retry_count": retry_count,
            "transcript": _say(state, question),
            "_agent_message": question,
        }

    def route_after_terminal_check(state: dict) -> str:
        return state["_route"]

    builder = StateGraph(_GraphState)
    builder.add_node("extract", extract_node)
    builder.add_node("terminal_check", terminal_node)
    builder.add_node("advance", advance_node)

    builder.set_entry_point("extract")
    builder.add_edge("extract", "terminal_check")
    builder.add_conditional_edges(
        "terminal_check",
        route_after_terminal_check,
        {"advance": "advance", "end_turn": END, "closed": END},
    )
    builder.add_edge("advance", END)

    return builder.compile()


def run_turn_verbose(graph, state: CallState, utterance: str) -> dict:
    """Run one candidate turn, keeping the extractor's raw intent for inspection
    (used by the persona simulator to score intent classification)."""
    result = graph.invoke({**state, "_utterance": utterance})
    agent_message = result.pop("_agent_message", "")
    dnc = result.pop("_dnc", False)
    intent = result.pop("_intent", None)
    extracted_slots = result.pop("_extracted_slots", None)
    confidence = result.pop("_confidence", None)
    fast_pathed = result.pop("_fast_pathed", None)
    retried = result.pop("_retried", None)
    result.pop("_utterance", None)
    result.pop("_route", None)
    return {
        "state": result,
        "message": agent_message,
        "outcome": result.get("outcome"),
        "dnc": dnc,
        "intent": intent,
        "extracted_slots": extracted_slots,
        "confidence": confidence,
        "fast_pathed": fast_pathed,
        "retried": retried,
    }


def run_turn(graph, state: CallState, utterance: str) -> tuple[CallState, str, str | None, bool]:
    """Run one candidate turn. Returns (new_state, agent_message, outcome_if_any, dnc)."""
    verbose = run_turn_verbose(graph, state, utterance)
    return verbose["state"], verbose["message"], verbose["outcome"], verbose["dnc"]
