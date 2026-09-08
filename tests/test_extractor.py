from src.agent.extractor import extract
from tests.conftest import FakeLLM


def test_extract_happy_path():
    llm = FakeLLM([{"intent": "ANSWER", "slots": {"yoe": "4 saal"}, "confidence": 0.9}])
    result = extract(llm, "yoe", "4 saal se kaam kar raha hoon")
    assert result.intent == "ANSWER"
    assert result.slots == {"yoe": 4.0}


def test_extract_strips_markdown_fences():
    raw = '```json\n{"intent": "ANSWER", "slots": {"city": "mumbai"}, "confidence": 0.8}\n```'
    llm = FakeLLM([raw])
    result = extract(llm, "city", "mumbai")
    assert result.slots == {"city": "Mumbai"}


def test_extract_retries_once_on_bad_json_then_succeeds():
    llm = FakeLLM([
        "not json at all",
        {"intent": "ANSWER", "slots": {"domain": "Java"}, "confidence": 0.9},
    ])
    result = extract(llm, "domain", "I work in Java mostly")
    assert result.intent == "ANSWER"
    assert result.slots == {"domain": "Java"}
    assert len(llm.calls) == 2


def test_extract_falls_back_to_unclear_after_two_bad_responses():
    llm = FakeLLM(["garbage", "still garbage"])
    result = extract(llm, "yoe", "huh?")
    assert result.intent == "UNCLEAR"
    assert result.slots == {}
    assert result.confidence == 0.0


def test_extract_drops_slots_below_confidence_threshold():
    llm = FakeLLM([{"intent": "ANSWER", "slots": {"yoe": 4.0}, "confidence": 0.5}])
    result = extract(llm, "yoe", "maybe like 4 years?")
    assert result.slots == {}


def test_extract_invalid_intent_becomes_unclear():
    llm = FakeLLM([{"intent": "BOGUS", "slots": {}, "confidence": 0.9}])
    result = extract(llm, "yoe", "what?")
    assert result.intent == "UNCLEAR"


def test_extract_multi_slot_answer():
    llm = FakeLLM([{
        "intent": "ANSWER",
        "slots": {"yoe": 4, "domain": "Java", "city": "mumbai"},
        "confidence": 0.95,
    }])
    result = extract(llm, "yoe", "4 years, Java, Mumbai")
    assert result.slots == {"yoe": 4.0, "domain": "Java", "city": "Mumbai"}


# --- deterministic fast path: zero LLM calls for short, unambiguous answers --

def test_fast_path_bool_skips_the_llm_entirely():
    llm = FakeLLM([])  # would raise IndexError if extract() called it
    result = extract(llm, "interested", "yes")
    assert result.intent == "ANSWER"
    assert result.slots == {"interested": True}
    assert result.confidence == 1.0
    assert llm.calls == []


def test_fast_path_fixes_terse_yeah_confirmed_miss():
    llm = FakeLLM([])
    result = extract(llm, "confirmed", "yeah")
    assert result.slots == {"confirmed": True}
    assert llm.calls == []


def test_fast_path_handles_hinglish_bool_words():
    llm = FakeLLM([])
    assert extract(llm, "interested", "haan").slots == {"interested": True}
    assert extract(llm, "interested", "ji").slots == {"interested": True}
    assert extract(llm, "interested", "nahi").slots == {"interested": False}


def test_fast_path_resolves_stt_number_homophones():
    # Observed live: faster-whisper transcribed "Four years" as "for years",
    # breaking yoe extraction outright until this fix.
    llm = FakeLLM([])
    assert extract(llm, "yoe", "for years").slots == {"yoe": 4.0}
    assert extract(llm, "notice_period_days", "ate days").slots == {"notice_period_days": 8}


def test_fast_path_handles_plain_numbers():
    llm = FakeLLM([])
    assert extract(llm, "yoe", "4 years").slots == {"yoe": 4.0}
    assert extract(llm, "notice_period_days", "2 months").slots == {"notice_period_days": 60}


def test_fast_path_defers_to_llm_on_hedged_numeric_answer():
    # "maybe" signals a non-committed answer -- must not be fast-pathed,
    # even though a number is present.
    llm = FakeLLM([{"intent": "ANSWER", "slots": {}, "confidence": 0.4}])
    result = extract(llm, "yoe", "maybe like 4 years?")
    assert result.slots == {}
    assert len(llm.calls) == 1


def test_fast_path_defers_to_llm_on_comma_multi_slot_reply():
    llm = FakeLLM([{
        "intent": "ANSWER",
        "slots": {"yoe": 4, "domain": "Java", "city": "mumbai"},
        "confidence": 0.95,
    }])
    result = extract(llm, "yoe", "4 years, Java, Mumbai")
    assert result.slots == {"yoe": 4.0, "domain": "Java", "city": "Mumbai"}
    assert len(llm.calls) == 1


def test_fast_path_defers_to_llm_on_terminal_intent_lookalike():
    llm = FakeLLM([{"intent": "ASKED_WHO_IS_THIS", "slots": {}, "confidence": 0.9}])
    result = extract(llm, "interested", "no wait, who is this?")
    assert result.intent == "ASKED_WHO_IS_THIS"
    assert len(llm.calls) == 1


def test_fast_path_does_not_apply_to_free_text_slots():
    llm = FakeLLM([{"intent": "ANSWER", "slots": {"domain": "Java"}, "confidence": 0.9}])
    result = extract(llm, "domain", "Java")
    assert result.slots == {"domain": "Java"}
    assert len(llm.calls) == 1
