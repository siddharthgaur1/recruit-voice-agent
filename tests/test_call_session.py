import time

from tests.conftest import FakeLLM

from src.agent.graph import build_graph
from src.agent.session import new_call_state
from src.api.session import MAX_SPEECH_BUFFER_BYTES, CallSession
from src.voice.vad import EndpointDetector, frame_bytes

FRAME = b"\x00\x00" * (frame_bytes() // 2)


class ScriptedVad:
    def __init__(self, script):
        self._script = list(script)

    def is_speech(self, frame, sample_rate):
        return self._script.pop(0)


class FakeTranscriber:
    def __init__(self, texts):
        self._texts = list(texts)

    def transcribe_pcm16(self, audio: bytes) -> str:
        return self._texts.pop(0)


class FakeSynth:
    def synthesize_pcm16(self, text: str):
        return (b"\x00\x00" * 100, 16000)  # 100 samples -> 100/16000s duration


def resp(intent="ANSWER", slots=None, confidence=0.9):
    return {"intent": intent, "slots": slots or {}, "confidence": confidence}


class SlowFakeTranscriber:
    """Simulates real STT+LLM+TTS latency to prove the filler doesn't wait on it."""

    def __init__(self, texts, delay_s=0.2):
        self._texts = list(texts)
        self._delay_s = delay_s

    def transcribe_pcm16(self, audio: bytes) -> str:
        time.sleep(self._delay_s)
        return self._texts.pop(0)


def test_filler_is_near_instant_even_when_real_processing_is_slow():
    llm = FakeLLM([resp(slots={"interested": True})])
    graph = build_graph(llm)
    detector = EndpointDetector(silence_ms_to_end=60, vad=ScriptedVad([True, False, False, False]))
    session = CallSession(
        state=new_call_state("lead-1", "attempt-1"), graph=graph,
        transcriber=SlowFakeTranscriber(["yes"], delay_s=0.2), synthesizer=FakeSynth(),
        detector=detector,
    )
    session.muted_until = 0.0

    t0 = time.monotonic()
    for _ in range(3):
        session.handle_frame(FRAME)
    events = session.handle_frame(FRAME)
    filler_elapsed_ms = (time.monotonic() - t0) * 1000

    assert filler_elapsed_ms < 50  # filler available near-instantly, real work not yet started
    assert events[0]["type"] == "filler"

    t1 = time.monotonic()
    session.process_utterance(events[1]["audio"])
    real_elapsed_ms = (time.monotonic() - t1) * 1000
    assert real_elapsed_ms >= 200  # the slow work actually happened, just after the filler


def make_session(vad_script, texts, llm_responses):
    llm = FakeLLM(llm_responses)
    graph = build_graph(llm)
    detector = EndpointDetector(silence_ms_to_end=60, vad=ScriptedVad(vad_script))
    session = CallSession(
        state=new_call_state("lead-1", "attempt-1"),
        graph=graph,
        transcriber=FakeTranscriber(texts),
        synthesizer=FakeSynth(),
        detector=detector,
    )
    return session


def test_continuous_speech_never_grows_buffer_past_the_cap():
    # A client that never pauses (malicious, faulty, or just noise the VAD
    # reads as speech) must not grow speech_buffer without bound.
    frame_count = MAX_SPEECH_BUFFER_BYTES // len(FRAME) + 3
    session = make_session(
        vad_script=[True] * frame_count,
        texts=["whatever was heard"],
        llm_responses=[],
    )
    session.muted_until = 0.0

    cut_off = False
    for _ in range(frame_count):
        events = session.handle_frame(FRAME)
        assert len(session.speech_buffer) <= MAX_SPEECH_BUFFER_BYTES
        if events:
            assert events[0]["type"] == "filler"
            assert events[1]["type"] == "process_utterance"
            cut_off = True
            break

    assert cut_off  # the cap forced a cutoff well before frame_count frames


def test_opening_produces_agent_message_with_audio():
    session = make_session(vad_script=[], texts=[], llm_responses=[])
    event = session.opening()
    assert event["type"] == "agent_message"
    assert "automated" in event["text"].lower()
    assert event["audio"]
    assert session.muted_until > time.monotonic()


def test_speech_then_silence_triggers_filler_then_utterance_processing():
    session = make_session(
        vad_script=[True, False, False, False],
        texts=["yes"],
        llm_responses=[resp(slots={"interested": True})],
    )
    session.muted_until = 0.0  # not in a TTS window

    assert session.handle_frame(FRAME) == []  # speech frame, buffering
    assert session.handle_frame(FRAME) == []  # silence 1
    assert session.handle_frame(FRAME) == []  # silence 2
    events = session.handle_frame(FRAME)      # silence 3 -> end_of_utterance

    # Filler fires immediately; the real work is handed off as a marker
    # event (the transport layer runs it off-thread -- see ws.py).
    assert len(events) == 2
    assert events[0]["type"] == "filler"
    assert events[0]["audio"]
    assert events[1]["type"] == "process_utterance"
    assert session.state["slots"]["interested"] is None  # not processed yet

    real_events = session.process_utterance(events[1]["audio"])
    assert len(real_events) == 1
    assert real_events[0]["type"] == "agent_message"
    assert session.state["slots"]["interested"] is True


def test_filler_phrases_rotate_across_turns():
    session = make_session(
        vad_script=[True, False, False, False, True, False, False, False],
        texts=[],
        llm_responses=[],
    )
    session.muted_until = 0.0

    for _ in range(3):
        session.handle_frame(FRAME)
    first_filler = session.handle_frame(FRAME)[0]

    session.muted_until = 0.0
    for _ in range(3):
        session.handle_frame(FRAME)
    second_filler = session.handle_frame(FRAME)[0]

    assert first_filler["text"] != second_filler["text"]


def test_barge_in_detected_during_tts_window():
    session = make_session(vad_script=[True], texts=[], llm_responses=[])
    session.muted_until = time.monotonic() + 10  # simulate TTS still "playing"
    session.speech_buffer.extend(b"leftover")

    events = session.handle_frame(FRAME)
    assert events == [{"type": "barge_in"}]
    assert session.muted_until == 0.0
    assert bytes(session.speech_buffer) == b""


def test_silence_frame_during_tts_window_is_ignored():
    session = make_session(vad_script=[False], texts=[], llm_responses=[])
    session.muted_until = time.monotonic() + 10
    assert session.handle_frame(FRAME) == []


def test_empty_transcript_produces_no_real_events_and_does_not_advance():
    session = make_session(
        vad_script=[True, False, False, False],
        texts=[""],  # STT returned nothing (noise)
        llm_responses=[],
    )
    session.muted_until = 0.0
    for _ in range(3):
        session.handle_frame(FRAME)
    events = session.handle_frame(FRAME)
    assert events[1]["type"] == "process_utterance"

    real_events = session.process_utterance(events[1]["audio"])
    assert real_events == []
    assert session.state["current_slot"] == "interested"  # unchanged


def test_silence_timeout_prompts_then_closes():
    session = make_session(vad_script=[], texts=[], llm_responses=[])
    session.last_activity_ts = time.monotonic() - 8  # past the 7s prompt threshold

    events = session.check_silence_timeout()
    assert len(events) == 1
    assert "still there" in events[0]["text"].lower()
    assert session.asked_are_you_there is True

    session.last_activity_ts = time.monotonic() - 13  # past the 12s close threshold
    events = session.check_silence_timeout()
    assert events[-1] == {"type": "call_ended", "outcome": "SILENCE_TIMEOUT"}
    assert session.state["outcome"] == "SILENCE_TIMEOUT"
