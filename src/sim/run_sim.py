"""Phase 2: batch persona simulator. Runs every scripted persona against the
real extractor and prints a slot-accuracy / intent-accuracy report.

    python -m src.sim.run_sim
"""

from dataclasses import dataclass

from src.agent.graph import build_graph, opening_message, run_turn_verbose
from src.agent.llm import build_llm_client
from src.agent.slots import SLOT_ORDER
from src.config import settings
from src.sim.personas import PERSONAS, Persona

SLOT_GRADED_IDS = {1, 2, 5, 6}
INTENT_GRADED_IDS = {3, 4, 7, 8}


@dataclass
class PersonaRun:
    persona: Persona
    final_slots: dict
    final_outcome: str | None
    first_intent: str | None


def _new_state() -> dict:
    return {
        "lead_id": "sim", "call_attempt_id": "sim",
        "company": settings.company_name,
        "transcript": [],
        "slots": {name: None for name in SLOT_ORDER},
        "current_slot": SLOT_ORDER[0],
        "retry_count": 0, "turn_count": 0,
        "outcome": None, "disclosed": False,
    }


def run_persona(graph, persona: Persona) -> PersonaRun:
    state, _ = opening_message(_new_state())
    first_intent = None

    for reply in persona.replies:
        verbose = run_turn_verbose(graph, state, reply)
        state = verbose["state"]
        if first_intent is None:
            first_intent = verbose["intent"]
        if verbose["outcome"]:
            break

    return PersonaRun(
        persona=persona, final_slots=state["slots"],
        final_outcome=state["outcome"], first_intent=first_intent,
    )


def score_personas(runs: list[PersonaRun]) -> dict:
    """Pure scoring over already-collected runs — no LLM calls here.

    Two distinct slot metrics are reported, never just one:
      - fill_rate  = filled / attempted  (did the extractor commit to a value at all)
      - accuracy   = correct / filled    (of the ones it committed to, how many were right)
    A slot correctly left unfilled (expected=None, actual=None) counts toward
    neither "filled" nor "correct" -- it's not a mismatch, but it's not a
    "filled and right" case either.
    """
    slot_total = 0
    slot_correct = 0
    slot_mismatches = []

    intent_total = 0
    intent_correct = 0
    intent_mismatches = []

    per_persona: dict[str, dict] = {}

    for run in runs:
        p = run.persona
        if p.expected_slots is not None:
            attempted = filled = correct_filled = 0
            for slot_name, expected in p.expected_slots.items():
                slot_total += 1
                attempted += 1
                actual = run.final_slots.get(slot_name)
                is_correct = actual == expected
                if is_correct:
                    slot_correct += 1
                if actual is not None:
                    filled += 1
                    if is_correct:
                        correct_filled += 1
                if not is_correct:
                    slot_mismatches.append({
                        "persona": p.name, "slot": slot_name,
                        "expected": expected, "actual": actual,
                        "kind": "wrong" if actual is not None else "missed",
                    })
            per_persona[p.name] = {
                "attempted": attempted,
                "filled": filled,
                "correct": correct_filled,
                "fill_rate": (filled / attempted * 100) if attempted else None,
                "accuracy": (correct_filled / filled * 100) if filled else None,
            }

        if p.expected_first_intent is not None:
            intent_total += 1
            ok = run.first_intent == p.expected_first_intent
            if ok:
                intent_correct += 1
            else:
                intent_mismatches.append({
                    "persona": p.name,
                    "expected": p.expected_first_intent,
                    "actual": run.first_intent,
                })
            per_persona[p.name] = {
                "expected_intent": p.expected_first_intent,
                "actual_intent": run.first_intent,
                "correct": ok,
            }

    total_filled = sum(v["filled"] for v in per_persona.values() if "filled" in v)
    total_attempted = sum(v["attempted"] for v in per_persona.values() if "attempted" in v)
    total_correct_filled = sum(v["correct"] for v in per_persona.values() if "filled" in v)

    return {
        "slot_accuracy": (slot_correct / slot_total * 100) if slot_total else None,
        "slot_correct": slot_correct,
        "slot_total": slot_total,
        "slot_mismatches": slot_mismatches,
        "fill_rate": (total_filled / total_attempted * 100) if total_attempted else None,
        "fill_rate_filled": total_filled,
        "fill_rate_attempted": total_attempted,
        "filled_accuracy": (total_correct_filled / total_filled * 100) if total_filled else None,
        "intent_accuracy": (intent_correct / intent_total * 100) if intent_total else None,
        "intent_correct": intent_correct,
        "intent_total": intent_total,
        "intent_mismatches": intent_mismatches,
        "per_persona": per_persona,
    }


def print_report(runs: list[PersonaRun], report: dict) -> None:
    print("=== Persona results ===")
    for run in runs:
        print(f"  {run.persona.id}. {run.persona.name}: "
              f"outcome={run.final_outcome} first_intent={run.first_intent} "
              f"slots={run.final_slots}")

    print("\n=== Slot extraction: fill rate and accuracy, per persona (1, 2, 5, 6) ===")
    for run in runs:
        p = run.persona
        stats = report["per_persona"].get(p.name)
        if stats is None or "filled" not in stats:
            continue
        fill_rate = f"{stats['fill_rate']:.1f}%" if stats["fill_rate"] is not None else "n/a"
        accuracy = f"{stats['accuracy']:.1f}%" if stats["accuracy"] is not None else "n/a (nothing filled)"
        print(f"  {p.name}: fill_rate={stats['filled']}/{stats['attempted']} ({fill_rate})  "
              f"accuracy={stats['correct']}/{stats['filled']} ({accuracy})")
    print(f"  AGGREGATE: fill_rate={report['fill_rate_filled']}/{report['fill_rate_attempted']} "
          f"({report['fill_rate']:.1f}%)  "
          f"accuracy(of filled)={report['filled_accuracy']:.1f}%  "
          f"overall correct/attempted={report['slot_correct']}/{report['slot_total']} "
          f"({report['slot_accuracy']:.1f}%) — target >= 95%")
    for m in report["slot_mismatches"]:
        print(f"  MISMATCH [{m['persona']}] {m['slot']} ({m['kind']}): "
              f"expected={m['expected']!r} actual={m['actual']!r}")

    print("\n=== Terminal-intent accuracy (personas 3, 4, 7, 8) ===")
    if report["intent_total"]:
        print(f"  {report['intent_correct']}/{report['intent_total']} "
              f"({report['intent_accuracy']:.1f}%)")
    for m in report["intent_mismatches"]:
        print(f"  MISMATCH [{m['persona']}] expected={m['expected']} actual={m['actual']}")


def main() -> None:
    llm = build_llm_client()
    graph = build_graph(llm)
    runs = [run_persona(graph, persona) for persona in PERSONAS]
    report = score_personas(runs)
    print_report(runs, report)


if __name__ == "__main__":
    main()
