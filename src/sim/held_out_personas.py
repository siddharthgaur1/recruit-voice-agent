"""Held-out personas, frozen and unused during prompt development.

These exist to answer one question honestly: "how does the frozen prompt
behave on inputs it was never tuned against?" They are run exactly ONCE
after the prompt is frozen (see eval_report.py) and the result is reported
raw, mismatches included -- do not edit the extraction prompt in response to
a bad result here without re-declaring a new baseline.
"""

from src.sim.personas import Persona

HELD_OUT_PERSONAS: list[Persona] = [
    Persona(
        id=101, name="Self-correcting",
        replies=["yes", "3 years, sorry, 3 and a half years actually",
                  "Python", "Bangalore", "1 month", "yes go ahead"],
        expected_slots={
            "interested": True, "yoe": 3.5, "domain": "Python", "city": "Bengaluru",
            "notice_period_days": 30, "confirmed": True,
        },
    ),
    Persona(
        id=102, name="Negotiating",
        replies=["yes", "5 years", "DevOps", "Pune",
                  "depends on the package you're offering",
                  "depends what you offer honestly",
                  "only if the offer is good",
                  "let's see the offer first"],
        expected_slots={
            "interested": True, "yoe": 5.0, "domain": "DevOps", "city": "Pune",
            "notice_period_days": None, "confirmed": None,
        },
    ),
    Persona(
        id=103, name="Fragmentary",
        replies=["yeah", "four", "java", "pune", "two", "yeah"],
        expected_slots={
            "interested": True, "yoe": 4.0, "domain": "Java", "city": "Pune",
            "notice_period_days": None, "confirmed": True,
        },
    ),
    Persona(
        id=104, name="Out-of-order-contradicting",
        replies=["yes, 4 years experience, based in Mumbai", "Java",
                  "actually I'm based in Pune now, not Mumbai", "2 months", "yes"],
        expected_slots={
            "interested": True, "yoe": 4.0, "domain": "Java", "city": "Pune",
            "notice_period_days": 60, "confirmed": True,
        },
    ),
    Persona(
        id=105, name="Heavy-Hinglish",
        replies=["haan bilkul, dekhna chahta hoon", "paanch saal se IT mein hoon",
                  "mostly Python aur cloud pe kaam karta hoon", "Pune mein rehta hoon abhi",
                  "ek mahine ka notice period hai bas", "haan zaroor bhej dijiye"],
        expected_slots={
            "interested": True, "yoe": 5.0, "domain": "Python", "city": "Pune",
            "notice_period_days": 30, "confirmed": True,
        },
    ),
]

HELD_OUT_IDS = {p.id for p in HELD_OUT_PERSONAS}
