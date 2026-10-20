from app.stt import ChainSTT, GroqSTT


class Boom:
    def __init__(self):
        self.calls = 0

    def transcribe_bytes(self, audio_bytes, suffix=".webm", prompt=None):
        self.calls += 1
        raise RuntimeError("rate limited")


class Ok:
    def __init__(self):
        self.calls = 0

    def transcribe_bytes(self, audio_bytes, suffix=".webm", prompt=None):
        self.calls += 1
        return "hello world"


def test_chain_falls_back_to_next_provider():
    boom, ok = Boom(), Ok()
    chain = ChainSTT([lambda: boom, lambda: ok])
    assert chain.transcribe_bytes(b"x") == "hello world"
    assert chain.active is ok
    # active provider is reused, no more fallbacks
    assert chain.transcribe_bytes(b"x") == "hello world"
    assert boom.calls == 1 and ok.calls == 2


def test_chain_raises_when_all_fail():
    chain = ChainSTT([lambda: Boom()])
    try:
        chain.transcribe_bytes(b"x")
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "all STT providers failed" in str(e)
