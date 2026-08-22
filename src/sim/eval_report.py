"""Eval hardening: python -m src.sim.eval_report

1. Runs the 8-persona harness 5 times, reporting per-run and aggregate
   fill-rate/accuracy, plus any (persona, slot/intent) that isn't stable
   across all 5 runs.
2. Then -- prompt frozen, no tuning after this point -- runs the 5 held-out
   personas ONCE and reports the raw result, mismatches included.
3. Benchmarks raw extraction latency (p50/p95) over 50 calls.

Needs GROQ_API_KEY. Makes real LLM calls: 5*8 + 5 + 50 turns, roughly a
minute depending on Groq's queue.
"""

import statistics
import time

from src.agent.extractor import extract
from src.agent.graph import build_graph
from src.agent.llm import build_llm_client
from src.sim.held_out_personas import HELD_OUT_PERSONAS
from src.sim.personas import PERSONAS
from src.sim.run_sim import INTENT_GRADED_IDS, SLOT_GRADED_IDS, run_persona, score_personas

N_RUNS = 5
N_LATENCY_CALLS = 50


def run_stability_eval(graph) -> None:
    print("#" * 78)
    print(f"# 1-3. {N_RUNS}-run stability + fill-rate/accuracy report ({len(PERSONAS)} personas)")
    print("#" * 78)

    all_runs_by_iteration = []
    for i in range(N_RUNS):
        runs = [run_persona(graph, persona) for persona in PERSONAS]
        all_runs_by_iteration.append(runs)
        report = score_personas(runs)
        print(f"\n--- Run {i + 1}/{N_RUNS} ---")
        print(f"  fill_rate={report['fill_rate_filled']}/{report['fill_rate_attempted']} "
              f"({report['fill_rate']:.1f}%)  "
              f"accuracy(of filled)={report['filled_accuracy']:.1f}%  "
              f"overall={report['slot_correct']}/{report['slot_total']} ({report['slot_accuracy']:.1f}%)  "
              f"intent={report['intent_correct']}/{report['intent_total']} ({report['intent_accuracy']:.1f}%)")
        for m in report["slot_mismatches"]:
            print(f"    MISMATCH [{m['persona']}] {m['slot']} ({m['kind']}): "
                  f"expected={m['expected']!r} actual={m['actual']!r}")
        for m in report["intent_mismatches"]:
            print(f"    MISMATCH [{m['persona']}] expected={m['expected']} actual={m['actual']}")

    # Aggregate across all 5 runs (flatten every run's PersonaRun list).
    flattened = [run for runs in all_runs_by_iteration for run in runs]
    agg_report = score_personas(flattened)
    print(f"\n--- Aggregate across {N_RUNS} runs ({len(flattened)} persona-runs total) ---")
    print(f"  fill_rate={agg_report['fill_rate_filled']}/{agg_report['fill_rate_attempted']} "
          f"({agg_report['fill_rate']:.1f}%)")
    print(f"  accuracy(of filled)={agg_report['filled_accuracy']:.1f}%")
    print(f"  overall correct/attempted={agg_report['slot_correct']}/{agg_report['slot_total']} "
          f"({agg_report['slot_accuracy']:.1f}%)")
    print(f"  intent={agg_report['intent_correct']}/{agg_report['intent_total']} "
          f"({agg_report['intent_accuracy']:.1f}%)")

    print("\n--- Stability across the 5 runs (any case that differs is flagged) ---")
    unstable_found = False
    for idx, persona in enumerate(PERSONAS):
        if persona.id in SLOT_GRADED_IDS and persona.expected_slots is not None:
            for slot_name in persona.expected_slots:
                per_run = [runs[idx].final_slots.get(slot_name) for runs in all_runs_by_iteration]
                if len(set(per_run)) > 1:
                    unstable_found = True
                    print(f"  UNSTABLE [{persona.name}] slot={slot_name} across runs: {per_run}")
        if persona.id in INTENT_GRADED_IDS and persona.expected_first_intent is not None:
            per_run = [runs[idx].first_intent for runs in all_runs_by_iteration]
            if len(set(per_run)) > 1:
                unstable_found = True
                print(f"  UNSTABLE [{persona.name}] first_intent across runs: {per_run}")
    if not unstable_found:
        print("  none -- every graded (persona, slot/intent) was identical across all 5 runs")


def run_held_out_eval(graph) -> None:
    print("\n" + "#" * 78)
    print("# 4. Held-out personas (frozen prompt, run ONCE, no tuning after this)")
    print("#" * 78)

    runs = [run_persona(graph, persona) for persona in HELD_OUT_PERSONAS]
    for run in runs:
        print(f"\n  {run.persona.name}: outcome={run.final_outcome} "
              f"first_intent={run.first_intent}")
        print(f"    expected: {run.persona.expected_slots}")
        print(f"    actual:   {run.final_slots}")

    report = score_personas(runs)
    print(f"\n  RAW RESULT -- fill_rate={report['fill_rate_filled']}/{report['fill_rate_attempted']} "
          f"({report['fill_rate']:.1f}%)  "
          f"accuracy(of filled)={report['filled_accuracy']:.1f}%  "
          f"overall={report['slot_correct']}/{report['slot_total']} ({report['slot_accuracy']:.1f}%)")
    for m in report["slot_mismatches"]:
        print(f"    MISMATCH [{m['persona']}] {m['slot']} ({m['kind']}): "
              f"expected={m['expected']!r} actual={m['actual']!r}")


def run_latency_benchmark(llm) -> None:
    print("\n" + "#" * 78)
    print(f"# 5. Extraction latency benchmark ({N_LATENCY_CALLS} calls)")
    print("#" * 78)

    utterances = []
    for persona in PERSONAS + HELD_OUT_PERSONAS:
        utterances.extend(persona.replies)
    # Cycle through the pooled utterances to reach exactly N_LATENCY_CALLS calls.
    calls = [utterances[i % len(utterances)] for i in range(N_LATENCY_CALLS)]

    latencies_ms = []
    for utterance in calls:
        t0 = time.monotonic()
        extract(llm, "yoe", utterance)
        latencies_ms.append((time.monotonic() - t0) * 1000)

    latencies_ms.sort()
    p50 = statistics.median(latencies_ms)
    p95 = latencies_ms[int(len(latencies_ms) * 0.95) - 1]
    print(f"  n={len(latencies_ms)}  min={min(latencies_ms):.0f}ms  "
          f"p50={p50:.0f}ms  p95={p95:.0f}ms  max={max(latencies_ms):.0f}ms")


def main() -> None:
    llm = build_llm_client()
    graph = build_graph(llm)

    run_stability_eval(graph)
    run_held_out_eval(graph)
    run_latency_benchmark(llm)


if __name__ == "__main__":
    main()
