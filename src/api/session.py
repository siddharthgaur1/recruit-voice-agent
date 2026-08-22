"""Per-call state machine driving one WebSocket voice conversation.

Deliberately has no asyncio/WebSocket dependency: it consumes raw PCM frames
and returns plain-data "events" (dicts, optionally carrying raw audio bytes
under an "audio" key) for the transport layer to actually send. That keeps
it unit-testable with fake STT/TTS/LLM components.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from src.agent.graph import opening_message, run_turn_verbose
from src.agent.state import CallState
from src.config import settings
from src.voice.vad import EndpointDetector

logger = logging.getLogger(__name__)

# Spoken the instant an utterance ends, before STT/LLM/TTS run -- covers the
# real processing latency (seconds) with near-zero perceived silence.
# Rotated so back-to-back turns don't audibly loop the same clip.
FILLER_PHRASES = ["Got it.", "Mm-hmm.", "Okay, one moment.", "Sure."]

# No real slot answer needs this long; caps speech_buffer growth so a client
# that never pauses (malicious, faulty, or just continuous noise the VAD
# reads as speech) can't grow it unbounded -- security review finding.
_MAX_UTTERANCE_S = 15.0
_SAMPLE_RATE = 16000
MAX_SPEECH_BUFFER_BYTES = int(_SAMPLE_RATE * 2 * _MAX_UTTERANCE_S)


@dataclass
class CallSession:
    state: CallState
    graph: Any
    transcriber: Any
    synthesizer: Any
    detector: EndpointDetector = field(default_factory=EndpointDetector)
    speech_buffer: bytearray = field(default_factory=bytearray)
    muted_until: float = 0.0  # monotonic timestamp; frames before this are the TTS window
    last_activity_ts: float = field(default_factory=time.monotonic)
    asked_are_you_there: bool = False
    dnc: bool = False
    _filler_index: int = 0

    def opening(self) -> dict:
        self.state, text = opening_message(self.state)
        return self._speak(text)

    def _speak(self, text: str, latency_ms: dict | None = None) -> dict:
        t0 = time.monotonic()
        pcm, sample_rate = self.synthesizer.synthesize_pcm16(text)
        tts_ms = (time.monotonic() - t0) * 1000
        duration_s = (len(pcm) / 2 / sample_rate) if sample_rate else 0.0
        self.muted_until = time.monotonic() + duration_s
        return {
            "type": "agent_message",
            "text": text,
            "sample_rate": sample_rate,
            "audio": pcm,
            "latency_ms": {**(latency_ms or {}), "tts": round(tts_ms, 1)},
        }

    def handle_frame(self, frame: bytes) -> list[dict]:
        """frame: one VAD-sized chunk of mono 16-bit PCM at 16kHz."""
        now = time.monotonic()

        if now < self.muted_until:
            if self.detector.is_speech_frame(frame):
                self.muted_until = 0.0
                self.detector.reset()
                self.speech_buffer.clear()
                return [{"type": "barge_in"}]
            return []

        event = self.detector.process_frame(frame)
        if event == "speech":
            self.speech_buffer.extend(frame)
            self.last_activity_ts = now
            self.asked_are_you_there = False
            if len(self.speech_buffer) >= MAX_SPEECH_BUFFER_BYTES:
                # On a real call this means the VAD never detected silence for
                # 15s straight -- a real candidate's slot answer never runs
                # that long, so this is a signal something's wrong (VAD
                # misconfigured, noisy line, or abuse), not routine truncation.
                logger.warning(
                    "speech_buffer hit the %.0fs cap (lead_id=%s) -- forcing an "
                    "endpoint. Investigate if this fires on real calls.",
                    _MAX_UTTERANCE_S, self.state.get("lead_id"),
                )
                self.detector.reset()  # force an endpoint; caller never said end_of_utterance
                return self._cut_utterance()
            return []
        if event == "end_of_utterance":
            self.last_activity_ts = time.monotonic()
            self.asked_are_you_there = False
            return self._cut_utterance(trailing_frame=frame)
        return []

    def _cut_utterance(self, trailing_frame: bytes | None = None) -> list[dict]:
        if trailing_frame is not None:
            self.speech_buffer.extend(trailing_frame)
        audio = bytes(self.speech_buffer)
        self.speech_buffer.clear()
        # Filler is sent immediately (near-0ms, pre-warmed cache hit);
        # the actual STT/LLM/TTS work is flagged for the transport layer
        # to run off the event loop (see ws.py) so the filler audio
        # isn't itself delayed by the processing it's meant to cover.
        return [self._next_filler(), {"type": "process_utterance", "audio": audio}]

    def _next_filler(self) -> dict:
        phrase = FILLER_PHRASES[self._filler_index % len(FILLER_PHRASES)]
        self._filler_index += 1
        pcm, sample_rate = self.synthesizer.synthesize_pcm16(phrase)
        return {"type": "filler", "text": phrase, "sample_rate": sample_rate, "audio": pcm}

    def process_utterance(self, audio: bytes) -> list[dict]:
        t0 = time.monotonic()
        text = self.transcriber.transcribe_pcm16(audio)
        stt_ms = (time.monotonic() - t0) * 1000

        if not text:
            return []

        t1 = time.monotonic()
        verbose = run_turn_verbose(self.graph, self.state, text)
        llm_ms = (time.monotonic() - t1) * 1000
        self.state = verbose["state"]
        self.dnc = self.dnc or verbose["dnc"]

        events: list[dict] = []
        if verbose["message"]:
            events.append(self._speak(
                verbose["message"], {"stt": round(stt_ms, 1), "llm": round(llm_ms, 1)}
            ))
        if verbose["outcome"]:
            events.append({"type": "call_ended", "outcome": verbose["outcome"]})
        return events

    def check_silence_timeout(self) -> list[dict]:
        """Call this periodically (e.g. every ~1s) while no audio is arriving."""
        elapsed = time.monotonic() - self.last_activity_ts
        if elapsed >= settings.silence_close_after_s and self.asked_are_you_there:
            self.state["outcome"] = "SILENCE_TIMEOUT"
            closing = self._speak(
                "It seems we've lost connection. I'll try you again another time. Goodbye!"
            )
            return [closing, {"type": "call_ended", "outcome": "SILENCE_TIMEOUT"}]
        if elapsed >= settings.silence_prompt_after_s and not self.asked_are_you_there:
            self.asked_are_you_there = True
            return [self._speak("Are you still there?")]
        return []
