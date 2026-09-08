"""Phase 1: text-only agent. Type the candidate's replies at the prompt."""

from src.agent.graph import build_graph, opening_message, run_turn
from src.agent.llm import build_llm_client
from src.agent.session import new_call_state
from src.config import settings, setup_logging
from src.db.repo import (
    create_call_attempt,
    create_lead,
    make_engine,
    make_session_factory,
    save_conversation_result,
)


def run_cli() -> None:
    setup_logging()
    engine = make_engine(settings.db_path)
    session_factory = make_session_factory(engine)
    session = session_factory()

    lead = create_lead(session, phone="+91-0000000000", name="CLI Candidate")
    attempt = create_call_attempt(session, lead.id)

    state = new_call_state(lead.id, attempt.id)
    state, message = opening_message(state)
    print(f"AGENT: {message}")

    llm = build_llm_client()
    graph = build_graph(llm)

    dnc = False
    while state["outcome"] is None:
        utterance = input("YOU: ").strip()
        state, agent_message, outcome, dnc = run_turn(graph, state, utterance)
        if agent_message:
            print(f"AGENT: {agent_message}")
        if outcome:
            break

    save_conversation_result(
        session,
        lead_id=state["lead_id"],
        call_attempt_id=state["call_attempt_id"],
        slots=state["slots"],
        transcript=state["transcript"],
        outcome=state["outcome"],
        dnc=dnc,
        domain_raw=state.get("domain_raw"),
    )
    session.close()

    print(f"\n--- Call ended: {state['outcome']} ---")
    print(f"Slots captured: {state['slots']}")


if __name__ == "__main__":
    run_cli()
