from src.agent.graph import build_graph, opening_message, run_turn
from src.agent.slots import SLOT_ORDER
from tests.conftest import FakeLLM


def new_state():
    return {
        "lead_id": "lead-1",
        "call_attempt_id": "attempt-1",
        "company": "Acme Corp",
        "transcript": [],
        "slots": dict.fromkeys(SLOT_ORDER),
        "current_slot": SLOT_ORDER[0],
        "retry_count": 0,
        "turn_count": 0,
        "outcome": None,
        "disclosed": False,
    }


def resp(intent="ANSWER", slots=None, confidence=0.9):
    return {"intent": intent, "slots": slots or {}, "confidence": confidence}


def test_opening_message_includes_disclosure_and_first_question():
    state, message = opening_message(new_state())
    assert "automated" in message.lower()
    assert "exploring a job switch" in message
    assert state["current_slot"] == "interested"
    assert state["disclosed"] is True


def test_full_happy_path_conversation_completes():
    # interested/yoe/notice_period_days/confirmed are short unambiguous answers,
    # so the extractor's deterministic fast path handles them with zero LLM
    # calls -- only domain and city are free text and need the LLM.
    llm = FakeLLM([
        resp(slots={"domain": "Java"}),
        resp(slots={"city": "mumbai"}),
    ])
    graph = build_graph(llm)
    state, _ = opening_message(new_state())

    replies = ["yes", "4 years", "Java", "Mumbai", "2 months", "yes send it"]
    outcome = None
    for reply in replies:
        state, message, outcome, dnc = run_turn(graph, state, reply)
        if outcome:
            break

    assert outcome == "COMPLETED"
    assert state["slots"] == {
        "interested": True, "yoe": 4.0, "domain": "Java", "city": "Mumbai",
        "notice_period_days": 60, "confirmed": True,
    }


def test_multi_slot_answer_jumps_to_first_unfilled():
    # "yes" fast-paths (no LLM call); the multi-slot reply has a comma, which
    # the fast path treats as a signal to defer to the LLM.
    llm = FakeLLM([
        resp(slots={"yoe": 4, "domain": "Java", "city": "mumbai"}),
    ])
    graph = build_graph(llm)
    state, _ = opening_message(new_state())

    state, _, _, _ = run_turn(graph, state, "yes")
    state, message, outcome, _ = run_turn(graph, state, "4 years, Java, Mumbai")

    assert state["current_slot"] == "notice_period_days"
    assert state["slots"]["yoe"] == 4.0
    assert state["slots"]["domain"] == "Java"
    assert state["slots"]["city"] == "Mumbai"


def test_retry_then_abandon_slot_after_two_misses():
    # "yes" fast-paths (no LLM call); "huh?"/"what?" have no extractable
    # number so the fast path defers to the LLM, which reports UNCLEAR.
    llm = FakeLLM([
        resp(intent="UNCLEAR", confidence=0.0),  # miss 1 on yoe
        resp(intent="UNCLEAR", confidence=0.0),  # miss 2 on yoe -> abandon
        resp(slots={"domain": "Java"}),
    ])
    graph = build_graph(llm)
    state, _ = opening_message(new_state())

    state, _, _, _ = run_turn(graph, state, "yes")
    state, _, _, _ = run_turn(graph, state, "huh?")
    assert state["current_slot"] == "yoe"
    assert state["retry_count"] == 1

    state, _, _, _ = run_turn(graph, state, "what?")
    assert state["current_slot"] == "domain"  # yoe abandoned, moved on
    assert state["slots"]["yoe"] is None
    assert state["retry_count"] == 0

    state, _, _, _ = run_turn(graph, state, "Java")
    assert state["slots"]["domain"] == "Java"


def test_not_interested_ends_call_immediately():
    llm = FakeLLM([resp(intent="NOT_INTERESTED", confidence=0.9)])
    graph = build_graph(llm)
    state, _ = opening_message(new_state())

    state, message, outcome, dnc = run_turn(graph, state, "not interested, thanks")
    assert outcome == "NOT_INTERESTED"
    assert dnc is False


def test_opt_out_phrase_sets_dnc():
    llm = FakeLLM([resp(intent="NOT_INTERESTED", confidence=0.9)])
    graph = build_graph(llm)
    state, _ = opening_message(new_state())

    state, message, outcome, dnc = run_turn(graph, state, "please stop calling me")
    assert outcome == "NOT_INTERESTED"
    assert dnc is True
    assert "list" in message.lower()


def test_interested_false_slot_answer_also_ends_call():
    llm = FakeLLM([resp(slots={"interested": False}, confidence=0.9)])
    graph = build_graph(llm)
    state, _ = opening_message(new_state())

    state, message, outcome, dnc = run_turn(graph, state, "no thanks")
    assert outcome == "NOT_INTERESTED"


def test_asked_who_is_this_is_not_terminal_and_repeats_disclosure():
    llm = FakeLLM([
        resp(intent="ASKED_WHO_IS_THIS", confidence=0.9),
        resp(slots={"interested": True}),
    ])
    graph = build_graph(llm)
    state, _ = opening_message(new_state())

    state, message, outcome, dnc = run_turn(graph, state, "who is this?")
    assert outcome is None
    assert state["current_slot"] == "interested"
    assert state["retry_count"] == 0
    assert "automated" in message.lower()

    state, message, outcome, dnc = run_turn(graph, state, "yes")
    assert state["slots"]["interested"] is True


def test_wrong_number_terminal():
    llm = FakeLLM([resp(intent="WRONG_NUMBER", confidence=0.9)])
    graph = build_graph(llm)
    state, _ = opening_message(new_state())
    state, message, outcome, dnc = run_turn(graph, state, "wrong number")
    assert outcome == "WRONG_NUMBER"


def test_callback_later_terminal():
    llm = FakeLLM([resp(intent="CALLBACK_LATER", confidence=0.9)])
    graph = build_graph(llm)
    state, _ = opening_message(new_state())
    state, message, outcome, dnc = run_turn(graph, state, "call me back at 6")
    assert outcome == "CALLBACK_LATER"


def test_hangup_without_corroborating_words_does_not_end_the_call():
    # A hallucinated/misheard transcript can make the model "confidently"
    # claim HANGUP even though the words don't say anything like it -- the
    # call must not end on that alone (see graph.py::_hangup_corroborated).
    llm = FakeLLM([resp(intent="HANGUP", confidence=0.95)])
    graph = build_graph(llm)
    state, _ = opening_message(new_state())

    state, message, outcome, dnc = run_turn(
        graph, state, "Thanks for watching. See you in the next video. Bye."
    )

    assert outcome is None  # never terminated
    assert state["current_slot"] == "interested"  # still asking the same question


def test_hangup_with_low_confidence_does_not_end_the_call():
    llm = FakeLLM([resp(intent="HANGUP", confidence=0.4)])
    graph = build_graph(llm)
    state, _ = opening_message(new_state())

    state, message, outcome, dnc = run_turn(graph, state, "hang up now")

    assert outcome is None


def test_hangup_with_high_confidence_and_corroborating_words_does_end_the_call():
    llm = FakeLLM([resp(intent="HANGUP", confidence=0.9)])
    graph = build_graph(llm)
    state, _ = opening_message(new_state())

    state, message, outcome, dnc = run_turn(graph, state, "I have to go now, goodbye")

    assert outcome == "HANGUP"


def test_max_turns_closes_call():
    # ASKED_WHO_IS_THIS never advances a slot or abandons it, so turn_count
    # climbs indefinitely until the hard cap kicks in.
    llm = FakeLLM([resp(intent="ASKED_WHO_IS_THIS", confidence=0.9) for _ in range(30)])
    graph = build_graph(llm)
    state, _ = opening_message(new_state())

    outcome = None
    for _ in range(30):
        state, message, outcome, dnc = run_turn(graph, state, "who is this again?")
        if outcome:
            break

    assert outcome == "MAX_TURNS"
    assert state["turn_count"] > 25
