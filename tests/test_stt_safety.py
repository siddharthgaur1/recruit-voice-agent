from src.voice.stt import MIN_AUDIO_DURATION_S, SAMPLE_RATE, Transcriber


def _pcm_of_duration(seconds: float) -> bytes:
    n_samples = int(SAMPLE_RATE * seconds)
    return b"\x00\x00" * n_samples  # silence; content doesn't matter, only duration


def test_clip_shorter_than_minimum_duration_never_reaches_the_model():
    transcriber = Transcriber(model_size="small")
    short_clip = _pcm_of_duration(0.3)  # below MIN_AUDIO_DURATION_S

    result = transcriber.transcribe_pcm16(short_clip)

    assert result == ""
    assert transcriber._model is None  # model was never even loaded, let alone called


def test_empty_audio_returns_empty_string():
    transcriber = Transcriber(model_size="small")
    assert transcriber.transcribe_pcm16(b"") == ""
    assert transcriber._model is None


def test_minimum_duration_constant_is_reasonable():
    # sanity check the threshold itself hasn't regressed to something useless
    assert 0.3 < MIN_AUDIO_DURATION_S < 2.0
