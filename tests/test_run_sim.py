from src.sim.personas import PERSONAS
from src.sim.run_sim import PersonaRun, score_personas


def test_eight_personas_defined_with_required_kinds():
    assert len(PERSONAS) == 8
    slot_graded = [p for p in PERSONAS if p.expected_slots is not None]
    intent_graded = [p for p in PERSONAS if p.expected_first_intent is not None]
    assert {p.id for p in slot_graded} == {1, 2, 5, 6}
    assert {p.id for p in intent_graded} == {3, 4, 7, 8}


def test_score_personas_perfect_match():
    persona = next(p for p in PERSONAS if p.id == 1)
    run = PersonaRun(
        persona=persona, final_slots=persona.expected_slots,
        final_outcome=persona.expected_outcome, first_intent=None,
    )
    report = score_personas([run])
    assert report["slot_correct"] == report["slot_total"]
    assert report["slot_mismatches"] == []


def test_score_personas_reports_mismatch():
    persona = next(p for p in PERSONAS if p.id == 4)
    run = PersonaRun(
        persona=persona, final_slots={}, final_outcome="NOT_INTERESTED",
        first_intent="UNCLEAR",
    )
    report = score_personas([run])
    assert report["intent_correct"] == 0
    assert report["intent_mismatches"] == [
        {"persona": "Not interested", "expected": "NOT_INTERESTED", "actual": "UNCLEAR"}
    ]


def test_score_personas_slot_mismatch_recorded():
    persona = next(p for p in PERSONAS if p.id == 6)  # Vague
    bad_slots = dict(persona.expected_slots)
    bad_slots["domain"] = "wrong"
    run = PersonaRun(persona=persona, final_slots=bad_slots, final_outcome=None, first_intent=None)
    report = score_personas([run])
    assert any(m["slot"] == "domain" for m in report["slot_mismatches"])
    assert report["slot_correct"] == report["slot_total"] - 1
