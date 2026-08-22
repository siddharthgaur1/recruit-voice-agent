from src.agent.graph import fixed_agent_lines
from src.voice.tts import Synthesizer


class CountingFakeVoice:
    """Stands in for piper.PiperVoice -- counts real synthesis calls."""

    def __init__(self):
        self.calls = 0

    def synthesize(self, text):
        self.calls += 1

        class Chunk:
            sample_rate = 16000
            audio_int16_bytes = text.encode()

        return [Chunk()]


def make_synth_with_fake_voice():
    synth = Synthesizer(model_path="unused")
    synth._voice = CountingFakeVoice()  # skip real model loading
    return synth


def test_repeated_synthesize_hits_cache_not_the_voice():
    synth = make_synth_with_fake_voice()
    synth.synthesize_pcm16("hello")
    synth.synthesize_pcm16("hello")
    assert synth._voice.calls == 1


def test_different_text_is_not_cached_together():
    synth = make_synth_with_fake_voice()
    synth.synthesize_pcm16("hello")
    synth.synthesize_pcm16("goodbye")
    assert synth._voice.calls == 2


def test_warm_cache_renders_each_line_once_and_skips_already_cached():
    synth = make_synth_with_fake_voice()
    lines = ["a", "b", "c"]
    rendered = synth.warm_cache(lines)
    assert rendered == 3
    assert synth._voice.calls == 3

    rendered_again = synth.warm_cache(lines)
    assert rendered_again == 0
    assert synth._voice.calls == 3  # no new synthesis


def test_fixed_agent_lines_covers_disclosure_all_six_questions_and_opening():
    lines = fixed_agent_lines(company="Acme Corp")
    assert len(lines) == 8  # disclosure + 6 questions + combined opening
    assert any("automated" in line.lower() for line in lines)
    assert any("years of experience" in line.lower() for line in lines)
    # the opening line is the disclosure and first question concatenated
    assert lines[-1] == f"{lines[0]} {lines[1]}"
