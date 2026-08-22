"""Scripted candidate personas for batch accuracy testing (Phase 2).

Each persona is a fixed script of candidate replies. `expected_slots` is the
ground truth used to score slot-extraction accuracy (only set for the
personas the spec grades on accuracy: cooperative, multi-slot, hinglish,
vague). `expected_first_intent` is the ground truth for personas graded on
intent classification instead (suspicious, not-interested, callback, wrong
number) — checked against the extractor's intent on their first reply.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Persona:
    id: int
    name: str
    replies: list[str]
    expected_slots: dict | None = None
    expected_first_intent: str | None = None
    expected_outcome: str | None = None


_COOPERATIVE_SLOTS = {
    "interested": True, "yoe": 4.0, "domain": "Java", "city": "Mumbai",
    "notice_period_days": 60, "confirmed": True,
}

PERSONAS: list[Persona] = [
    Persona(
        id=1, name="Cooperative",
        replies=["yes", "4 years", "Java", "Mumbai", "2 months", "yes, please send it"],
        expected_slots=_COOPERATIVE_SLOTS,
        expected_outcome="COMPLETED",
    ),
    Persona(
        id=2, name="Multi-slot",
        replies=["yes", "4 years, Java, Mumbai", "2 months", "yes send it"],
        expected_slots=_COOPERATIVE_SLOTS,
        expected_outcome="COMPLETED",
    ),
    Persona(
        id=3, name="Suspicious",
        replies=["Who is this? How did you get my number?", "yes", "4 years",
                  "Java", "Mumbai", "2 months", "yes"],
        expected_first_intent="ASKED_WHO_IS_THIS",
    ),
    Persona(
        id=4, name="Not interested",
        replies=["not interested, thanks"],
        expected_first_intent="NOT_INTERESTED",
        expected_outcome="NOT_INTERESTED",
    ),
    Persona(
        id=5, name="Hinglish",
        replies=["haan dekh raha hoon", "4 saal", "Java", "Mumbai",
                  "do mahine", "haan bhej do"],
        expected_slots=_COOPERATIVE_SLOTS,
        expected_outcome="COMPLETED",
    ),
    Persona(
        id=6, name="Vague",
        # Each ambiguous slot gets two vague misses (retry_count hits 2 -> abandoned)
        # before moving on, so the script must supply two fillers per vague slot
        # to deterministically reach every later slot in one run.
        replies=["yes", "few years", "not sure exactly", "backend",
                  "somewhere in Maharashtra", "not sure which city",
                  "depends", "hard to say", "sure"],
        expected_slots={
            "interested": True, "yoe": None, "domain": "Backend", "city": None,
            "notice_period_days": None, "confirmed": True,
        },
    ),
    Persona(
        id=7, name="Callback",
        replies=["I'm in a meeting, call me at 6"],
        expected_first_intent="CALLBACK_LATER",
        expected_outcome="CALLBACK_LATER",
    ),
    Persona(
        id=8, name="Wrong number",
        replies=["I think you have the wrong person."],
        expected_first_intent="WRONG_NUMBER",
        expected_outcome="WRONG_NUMBER",
    ),
]
