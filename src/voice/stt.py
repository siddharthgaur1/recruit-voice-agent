"""faster-whisper wrapper. Model loads lazily (first call) so importing this
module and building the app costs nothing until a real transcription runs.

Safety: Whisper is known to hallucinate fluent, plausible-looking text
("Thanks for watching...") on short or low-energy/silent clips -- a live
call must never let that hallucinated text drive a real decision (see
graph.py's HANGUP guard, which additionally never trusts STT output alone).
The first line of defense is here: clips too short to contain real speech,
or that Whisper's own no-speech detector flags, never even reach the
extractor -- transcribe_pcm16 returns "" instead.
"""

import numpy as np

from src.config import settings

SAMPLE_RATE = 16000

# Below this, there's no realistic amount of real speech to transcribe --
# skip the model call entirely rather than risk a hallucinated guess.
MIN_AUDIO_DURATION_S = 0.5

# A candidate-recruiting-call vocabulary hint, reduces homophone confusion
# on domain words faster-whisper otherwise has no context for.
_INITIAL_PROMPT = (
    "A recruiting phone call. The candidate discusses years of experience, "
    "a tech stack or domain such as Java, Python, JavaScript, DevOps, "
    "cloud, an Indian city such as Mumbai, Pune, Bangalore, Delhi, "
    "Hyderabad, and a notice period in days or months."
)


class Transcriber:
    def __init__(self, model_size: str | None = None, device: str | None = None,
                 compute_type: str | None = None):
        self._model_size = model_size or settings.whisper_model
        self._device = device or settings.whisper_device
        self._compute_type = compute_type or settings.whisper_compute_type
        self._model = None

    def _ensure_loaded(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self._model_size, device=self._device, compute_type=self._compute_type
            )

    def transcribe_pcm16(self, pcm_bytes: bytes) -> str:
        """pcm_bytes: mono 16-bit PCM at SAMPLE_RATE. Returns the joined
        transcript text, or "" if the clip is too short or looks like
        silence/noise rather than real speech (never guesses)."""
        if not pcm_bytes:
            return ""

        duration_s = len(pcm_bytes) / 2 / SAMPLE_RATE
        if duration_s < MIN_AUDIO_DURATION_S:
            return ""

        self._ensure_loaded()
        audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _info = self._model.transcribe(
            audio,
            language=None,
            vad_filter=True,
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
            initial_prompt=_INITIAL_PROMPT,
        )
        # vad_filter already drops non-speech regions; this is a second,
        # per-segment check against whatever it still let through.
        real_segments = [seg for seg in segments if seg.no_speech_prob < 0.6]
        return " ".join(seg.text.strip() for seg in real_segments).strip()


_shared_transcriber: Transcriber | None = None


def get_transcriber() -> Transcriber:
    global _shared_transcriber
    if _shared_transcriber is None:
        _shared_transcriber = Transcriber()
    return _shared_transcriber
