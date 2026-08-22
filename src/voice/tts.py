"""Piper TTS wrapper. Voice model loads lazily on first synthesize call.

Download a voice (e.g. en_US-lessac-medium) from
https://github.com/OHF-voice/piper1-gpl/releases or the Piper voices repo,
and point PIPER_MODEL_PATH at the .onnx file (its .onnx.json sits alongside it).
"""

from pathlib import Path

from src.config import settings


class Synthesizer:
    def __init__(self, model_path: str | None = None):
        self._model_path = model_path or settings.piper_model_path
        self._voice = None
        self._cache: dict[str, tuple[bytes, int]] = {}

    def _ensure_loaded(self):
        if self._voice is None:
            from piper import PiperVoice

            self._voice = PiperVoice.load(self._model_path)

    def synthesize_pcm16(self, text: str) -> tuple[bytes, int]:
        """Returns (mono 16-bit PCM bytes, sample_rate). Cached by exact text
        match -- callers that pre-warm fixed lines (see warm_cache) get an
        instant cache hit instead of live synthesis."""
        cached = self._cache.get(text)
        if cached is not None:
            return cached

        self._ensure_loaded()
        chunks = list(self._voice.synthesize(text))
        if not chunks:
            result = (b"", 22050)
        else:
            sample_rate = chunks[0].sample_rate
            audio = b"".join(chunk.audio_int16_bytes for chunk in chunks)
            result = (audio, sample_rate)

        self._cache[text] = result
        return result

    def warm_cache(self, texts: list[str]) -> int:
        """Pre-render TTS for a fixed set of lines. Returns how many were
        actually rendered (skips lines already cached)."""
        rendered = 0
        for text in texts:
            if text not in self._cache:
                self.synthesize_pcm16(text)
                rendered += 1
        return rendered


_shared_synthesizer: Synthesizer | None = None


def get_synthesizer() -> Synthesizer:
    global _shared_synthesizer
    if _shared_synthesizer is None:
        _shared_synthesizer = Synthesizer()
    return _shared_synthesizer


def voice_model_available() -> bool:
    return Path(settings.piper_model_path).exists()
