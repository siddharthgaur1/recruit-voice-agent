"""webrtcvad-based endpointing: turns a stream of fixed-size PCM frames into
speech/silence/end-of-utterance events. Also used standalone for barge-in
detection (is a frame speech, regardless of turn state)."""

from typing import Protocol

from src.config import settings

SAMPLE_RATE = 16000


class VadLike(Protocol):
    def is_speech(self, frame: bytes, sample_rate: int) -> bool: ...


def frame_bytes(frame_ms: int | None = None, sample_rate: int = SAMPLE_RATE) -> int:
    ms = frame_ms or settings.vad_frame_ms
    return int(sample_rate * ms / 1000) * 2  # 16-bit mono


class EndpointDetector:
    def __init__(self, aggressiveness: int | None = None, silence_ms_to_end: int | None = None,
                 vad: VadLike | None = None):
        if vad is None:
            import webrtcvad

            vad = webrtcvad.Vad(aggressiveness if aggressiveness is not None
                                 else settings.vad_aggressiveness)
        self._vad = vad
        frame_ms = settings.vad_frame_ms
        silence_ms = silence_ms_to_end if silence_ms_to_end is not None else settings.vad_endpoint_silence_ms
        self._silence_frames_to_end = max(1, silence_ms // frame_ms)
        self.reset()

    def reset(self) -> None:
        self.in_speech = False
        self._silence_run = 0

    def is_speech_frame(self, frame: bytes) -> bool:
        return self._vad.is_speech(frame, SAMPLE_RATE)

    def process_frame(self, frame: bytes) -> str:
        """Returns 'speech', 'silence', or 'end_of_utterance'."""
        if self.is_speech_frame(frame):
            self.in_speech = True
            self._silence_run = 0
            return "speech"

        if self.in_speech:
            self._silence_run += 1
            if self._silence_run >= self._silence_frames_to_end:
                self.reset()
                return "end_of_utterance"
        return "silence"
