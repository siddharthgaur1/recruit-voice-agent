from src.voice.vad import EndpointDetector


class ScriptedVad:
    """Ignores actual audio content; returns a scripted True/False per call."""

    def __init__(self, script: list[bool]):
        self._script = list(script)

    def is_speech(self, frame: bytes, sample_rate: int) -> bool:
        return self._script.pop(0)


FRAME = b"\x00\x00" * 320  # content irrelevant, ScriptedVad ignores it


def test_pure_silence_stays_silence():
    detector = EndpointDetector(silence_ms_to_end=60, vad=ScriptedVad([False, False, False]))
    for _ in range(3):
        assert detector.process_frame(FRAME) == "silence"
    assert detector.in_speech is False


def test_speech_then_enough_silence_signals_end_of_utterance():
    # 20ms frames, 60ms silence-to-end => 3 silence frames needed after speech
    detector = EndpointDetector(silence_ms_to_end=60, vad=ScriptedVad(
        [True, False, False, False]
    ))
    assert detector.process_frame(FRAME) == "speech"
    assert detector.process_frame(FRAME) == "silence"
    assert detector.process_frame(FRAME) == "silence"
    assert detector.process_frame(FRAME) == "end_of_utterance"
    assert detector.in_speech is False


def test_brief_silence_inside_speech_does_not_end_utterance():
    detector = EndpointDetector(silence_ms_to_end=60, vad=ScriptedVad(
        [True, False, True, False, False, False]
    ))
    assert detector.process_frame(FRAME) == "speech"
    assert detector.process_frame(FRAME) == "silence"
    assert detector.process_frame(FRAME) == "speech"  # resets silence run
    assert detector.process_frame(FRAME) == "silence"
    assert detector.process_frame(FRAME) == "silence"
    assert detector.process_frame(FRAME) == "end_of_utterance"


def test_is_speech_frame_does_not_mutate_state():
    detector = EndpointDetector(silence_ms_to_end=60, vad=ScriptedVad([True, True]))
    assert detector.is_speech_frame(FRAME) is True
    assert detector.in_speech is False  # process_frame not called, no state change
