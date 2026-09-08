"""python -m src.sim.latency_diagnosis

Diagnoses (not just re-measures) extraction latency:
  - LLM-call latency (only turns that actually reached an LLM) reported
    SEPARATELY from end-to-end per-turn latency (which includes fast-pathed,
    ~0ms turns) -- the two are not the same population and conflating them
    was the mistake in the previous round's benchmark.
  - Every JSON-parse retry logged; reports what fraction of LLM calls retry,
    and whether retried calls are concentrated in the p95 tail (bimodal =
    retry path) vs spread evenly (queueing/provider variance).
  - A full histogram, not just p50/p95.

Pass --tier fast|escalation|dual to pick which LLM(s) to hit (default dual,
i.e. the real production build_llm_client()).
"""

import statistics
import sys
import time

from src.agent.graph import build_graph, opening_message, run_turn_verbose
from src.agent.llm import EscalatingLLMClient, GroqClient, build_llm_client
from src.agent.session import new_call_state
from src.config import settings
from src.sim.held_out_personas import HELD_OUT_PERSONAS
from src.sim.personas import PERSONAS


def _histogram(latencies: list[float], buckets_ms=(100, 250, 500, 1000, 2000, 4000, 8000)) -> str:
    counts = [0] * (len(buckets_ms) + 1)
    for lat in latencies:
        for i, edge in enumerate(buckets_ms):
            if lat < edge:
                counts[i] += 1
                break
        else:
            counts[-1] += 1

    labels = []
    prev = 0
    for edge in buckets_ms:
        labels.append(f"{prev}-{edge}ms")
        prev = edge
    labels.append(f"{prev}ms+")

    lines = []
    max_count = max(counts) or 1
    for label, count in zip(labels, counts, strict=True):
        bar = "#" * int(count / max_count * 40)
        lines.append(f"  {label:>12}: {count:>3}  {bar}")
    return "\n".join(lines)


def run_diagnosis(llm, min_llm_calls: int = 1) -> None:
    graph = build_graph(llm)

    end_to_end_ms: list[float] = []
    llm_only_ms: list[float] = []
    retried_flags: list[bool] = []
    # (slot, utterance, word_count, latency_ms) per LLM-reaching turn -- the
    # SAME (slot, utterance) pair recurs every pass (deterministic replies),
    # so this doubles as the cheap discriminator: does a given prompt's
    # latency stay consistent across passes (structural/prompt-driven) or
    # swing wildly (time-dependent/queueing)?
    call_details: list[tuple[str, str, int, float]] = []

    # One pass over both persona sets yields ~39 turns that reach an LLM
    # (the rest fast-path). For a real latency sample (n>=200), repeat full
    # passes -- the text is deterministic but real network/provider latency
    # varies call to call, so repeated passes are a legitimate latency
    # sample even though they're not fresh accuracy data.
    pass_num = 0
    while len(llm_only_ms) < min_llm_calls:
        pass_num += 1
        for persona in PERSONAS + HELD_OUT_PERSONAS:
            state, _ = opening_message(new_call_state("lead", "att"))
            for reply in persona.replies:
                current_slot = state["current_slot"]
                t0 = time.monotonic()
                verbose = run_turn_verbose(graph, state, reply)
                elapsed_ms = (time.monotonic() - t0) * 1000
                state = verbose["state"]

                end_to_end_ms.append(elapsed_ms)
                if not verbose["fast_pathed"]:
                    llm_only_ms.append(elapsed_ms)
                    retried_flags.append(bool(verbose["retried"]))
                    call_details.append((current_slot, reply, len(reply.split()), elapsed_ms))

                if verbose["outcome"]:
                    break
        print(f"  ...pass {pass_num} done, {len(llm_only_ms)}/{min_llm_calls} LLM-only samples so far")

    def report(label, data):
        if not data:
            print(f"{label}: n=0 (no turns in this population)")
            return
        data_sorted = sorted(data)
        n = len(data_sorted)
        p50 = statistics.median(data_sorted)
        p95 = data_sorted[int(n * 0.95) - 1] if n >= 20 else data_sorted[-1]
        print(f"{label}: n={n} min={min(data_sorted):.0f}ms p50={p50:.0f}ms "
              f"p95={p95:.0f}ms max={max(data_sorted):.0f}ms")

    print("=== End-to-end per-turn latency (includes fast-pathed ~0ms turns) ===")
    report("  end-to-end", end_to_end_ms)
    print(_histogram(end_to_end_ms))

    print("\n=== LLM-call latency ONLY (excludes fast-pathed turns) ===")
    report("  llm-only", llm_only_ms)
    print(_histogram(llm_only_ms))

    if llm_only_ms:
        retry_rate = sum(retried_flags) / len(retried_flags) * 100
        print("\n=== Retry analysis ===")
        print(f"  {sum(retried_flags)}/{len(retried_flags)} LLM calls retried ({retry_rate:.1f}%)")

        n = len(llm_only_ms)
        sorted_pairs = sorted(zip(llm_only_ms, retried_flags, strict=True), key=lambda p: p[0])
        p95_cutoff_idx = int(n * 0.95)
        tail = sorted_pairs[p95_cutoff_idx:]
        body = sorted_pairs[:p95_cutoff_idx]
        tail_retry_rate = (sum(r for _, r in tail) / len(tail) * 100) if tail else 0.0
        body_retry_rate = (sum(r for _, r in body) / len(body) * 100) if body else 0.0
        print(f"  retry rate in the p95+ tail: {tail_retry_rate:.1f}%  "
              f"(n={len(tail)})")
        print(f"  retry rate in the body (below p95): {body_retry_rate:.1f}%  "
              f"(n={len(body)})")
        if tail_retry_rate > body_retry_rate * 1.5:
            print("  -> tail is retry-correlated (bimodal): the JSON-parse retry is "
                  "a real contributor to p95.")
        else:
            print("  -> tail is NOT clearly retry-correlated: looks like provider-side "
                  "latency variance/queueing, not the retry path.")

    if call_details:
        _report_discriminator(call_details)


def _report_discriminator(call_details: list[tuple[str, str, int, float]]) -> None:
    """Cheap structural-vs-queueing discriminator, no new API calls: the
    same (slot, utterance) pair recurs every pass. If a given prompt's
    latency is CONSISTENT across its repeats while other prompts are
    consistently different, that's prompt/slot-driven (structural). If a
    given prompt's latency swings as widely across its own repeats as the
    whole population swings, that's time-dependent (queueing/provider)."""
    print("\n=== Structural-vs-queueing discriminator (same prompts, repeated across passes) ===")

    by_slot: dict[str, list[float]] = {}
    for slot, _utterance, _wc, ms in call_details:
        by_slot.setdefault(slot, []).append(ms)

    print("By slot (mean latency):")
    for slot, values in sorted(by_slot.items(), key=lambda kv: -statistics.mean(kv[1])):
        print(f"  {slot:>20}: n={len(values):>3} mean={statistics.mean(values):>7.0f}ms "
              f"median={statistics.median(values):>7.0f}ms")

    by_utterance: dict[tuple[str, str], list[float]] = {}
    for slot, utterance, _wc, ms in call_details:
        by_utterance.setdefault((slot, utterance), []).append(ms)

    repeated = {k: v for k, v in by_utterance.items() if len(v) >= 3}
    if not repeated:
        print("\n(not enough repeats per prompt yet to compute the discriminator -- "
              "increase min_llm_calls so every persona reply recurs at least 3x)")
        return

    overall_stdev = statistics.stdev(ms for values in repeated.values() for ms in values)

    per_prompt_stdevs = [statistics.stdev(v) for v in repeated.values()]
    mean_within_prompt_stdev = statistics.mean(per_prompt_stdevs)

    between_prompt_means = [statistics.mean(v) for v in repeated.values()]
    between_prompt_spread = statistics.stdev(between_prompt_means) if len(between_prompt_means) > 1 else 0.0

    print(f"\n{len(repeated)} distinct (slot, utterance) prompts repeated >=3x "
          f"({sum(len(v) for v in repeated.values())} calls total)")
    print(f"  overall stdev across all calls:            {overall_stdev:>7.0f}ms")
    print(f"  mean stdev WITHIN a single repeated prompt: {mean_within_prompt_stdev:>7.0f}ms  "
          f"(how much a given prompt's own latency swings pass-to-pass)")
    print(f"  stdev BETWEEN different prompts' means:     {between_prompt_spread:>7.0f}ms  "
          f"(how much different prompts differ from each other)")

    if mean_within_prompt_stdev > between_prompt_spread * 0.7:
        print("  -> WITHIN-prompt swing is comparable to or larger than BETWEEN-prompt "
              "spread: the same prompt lands fast one pass, slow another. Points to "
              "time-dependent/queueing variance, NOT a property of the prompt itself.")
    else:
        print("  -> BETWEEN-prompt spread dominates: some prompts are consistently "
              "slower than others across every pass. Points to a structural, "
              "prompt/slot-driven cause, not queueing.")

    print("\nSlowest and fastest individual prompts (by mean latency, n>=3 repeats):")
    ranked = sorted(repeated.items(), key=lambda kv: -statistics.mean(kv[1]))
    for (slot, utterance), values in ranked[:3]:
        print(f"  SLOW  [{slot}] {utterance!r}: mean={statistics.mean(values):.0f}ms "
              f"stdev={statistics.stdev(values):.0f}ms (n={len(values)})")
    for (slot, utterance), values in ranked[-3:]:
        print(f"  FAST  [{slot}] {utterance!r}: mean={statistics.mean(values):.0f}ms "
              f"stdev={statistics.stdev(values):.0f}ms (n={len(values)})")


def main() -> None:
    tier = sys.argv[1] if len(sys.argv) > 1 else "dual"
    min_llm_calls = int(sys.argv[2]) if len(sys.argv) > 2 else 1

    if tier == "fast":
        llm = GroqClient(settings.groq_api_key, settings.groq_model_fast,
                          reasoning_effort=settings.groq_reasoning_effort)
        print("TIER: fast only (gpt-oss-20b)\n")
    elif tier == "escalation":
        llm = GroqClient(settings.groq_api_key, settings.groq_model,
                          reasoning_effort=settings.groq_reasoning_effort)
        print("TIER: escalation only (gpt-oss-120b)\n")
    else:
        llm = build_llm_client()
        print("TIER: dual (production build_llm_client())\n")

    import datetime
    print(f"Started: {datetime.datetime.now().isoformat()}\n")

    run_diagnosis(llm, min_llm_calls=min_llm_calls)

    if isinstance(llm, EscalatingLLMClient):
        print(f"\nToken usage: {llm.total_tokens} across {llm.call_count} calls")
    elif isinstance(llm, GroqClient):
        print(f"\nToken usage: {llm.total_tokens} across {llm.call_count} calls")


if __name__ == "__main__":
    main()
