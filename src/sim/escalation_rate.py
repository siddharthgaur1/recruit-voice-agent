"""python -m src.sim.escalation_rate

FAST-TIER ONLY: runs both persona sets through gpt-oss-20b alone (no
escalation model ever consulted), reporting:
  - fast-tier-only accuracy on both persona sets (is the escalation tier
    actually pulling its weight, or is fast-tier alone just as good?)
  - the escalation rate that WOULD have fired (fast-tier confidence < the
    threshold), broken down by slot and by persona -- computed purely from
    the fast tier's own reported confidence, zero calls to the heavier model
  - cumulative token usage for this run

Every number this script prints is fast-tier-only. Re-run the real dual-tier
comparison after the Groq daily quota resets.
"""

from collections import defaultdict

from src.agent.graph import build_graph, opening_message, run_turn_verbose
from src.agent.json_extraction import CONFIDENCE_THRESHOLD
from src.agent.llm import GroqClient
from src.agent.session import new_call_state
from src.config import settings
from src.sim.held_out_personas import HELD_OUT_PERSONAS
from src.sim.personas import PERSONAS
from src.sim.run_sim import PersonaRun, score_personas


def run_persona_set(llm: GroqClient, persona_set) -> tuple[list[PersonaRun], list[tuple]]:
    graph = build_graph(llm)
    runs = []
    escalation_events = []  # (persona_name, slot_asked, would_escalate)

    for persona in persona_set:
        state, _ = opening_message(new_call_state("lead", "att"))
        for reply in persona.replies:
            calls_before = llm.call_count
            current_slot = state["current_slot"]
            verbose = run_turn_verbose(graph, state, reply)
            state = verbose["state"]

            reached_llm = llm.call_count > calls_before
            if reached_llm:
                confidence = verbose["confidence"] or 0.0
                escalation_events.append((persona.name, current_slot, confidence < CONFIDENCE_THRESHOLD))

            if verbose["outcome"]:
                break

        runs.append(PersonaRun(
            persona=persona, final_slots=state["slots"],
            final_outcome=state["outcome"], first_intent=None,
        ))

    return runs, escalation_events


def main() -> None:
    print("FAST-TIER ONLY -- every number below comes from gpt-oss-20b alone, "
          "zero calls to the escalation model.\n")

    fast = GroqClient(
        settings.groq_api_key, settings.groq_model_fast,
        reasoning_effort=settings.groq_reasoning_effort,
    )

    all_events = []
    for label, persona_set in [("8-persona", PERSONAS), ("held-out", HELD_OUT_PERSONAS)]:
        runs, events = run_persona_set(fast, persona_set)
        all_events.extend((label, *e) for e in events)
        report = score_personas(runs)
        print(f"[FAST-TIER ONLY] {label}: "
              f"fill_rate={report['fill_rate_filled']}/{report['fill_rate_attempted']} ({report['fill_rate']:.1f}%)  "
              f"accuracy(of filled)={report['filled_accuracy']:.1f}%  "
              f"overall={report['slot_correct']}/{report['slot_total']} ({report['slot_accuracy']:.1f}%)")
        for m in report["slot_mismatches"]:
            print(f"    MISMATCH [{m['persona']}] {m['slot']} ({m['kind']}): "
                  f"expected={m['expected']!r} actual={m['actual']!r}")

    by_slot: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    by_persona: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for label, persona_name, slot, would_escalate in all_events:
        by_slot[slot][1] += 1
        by_persona[(label, persona_name)][1] += 1
        if would_escalate:
            by_slot[slot][0] += 1
            by_persona[(label, persona_name)][0] += 1

    print(f"\n=== Escalation rate (fast-tier confidence < {CONFIDENCE_THRESHOLD}) ===")
    print("(computed from fast-tier confidence scores only -- zero 120b calls)")
    print(f"Turns that reached an LLM at all (excludes fast-path hits): {len(all_events)}")

    print("\nBy slot:")
    for slot, (esc, total) in sorted(by_slot.items()):
        pct = esc / total * 100 if total else 0.0
        print(f"  {slot}: {esc}/{total} would escalate ({pct:.1f}%)")

    print("\nBy persona:")
    for (label, name), (esc, total) in sorted(by_persona.items()):
        pct = esc / total * 100 if total else 0.0
        print(f"  [{label}] {name}: {esc}/{total} would escalate ({pct:.1f}%)")

    print(f"\nToken usage this run (gpt-oss-20b only): "
          f"{fast.total_tokens} tokens across {fast.call_count} calls")


if __name__ == "__main__":
    main()
