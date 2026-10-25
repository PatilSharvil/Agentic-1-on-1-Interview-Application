from app.stt import ChainSTT, STTResult, remove_overlap


class Boom:
    def __init__(self):
        self.calls = 0

    def transcribe_detailed(self, audio_bytes, suffix=".webm", prompt=None):
        self.calls += 1
        raise RuntimeError("rate limited")

    def transcribe_bytes(self, audio_bytes, suffix=".webm", prompt=None):
        self.calls += 1
        raise RuntimeError("rate limited")


class Ok:
    def __init__(self):
        self.calls = 0

    def transcribe_detailed(self, audio_bytes, suffix=".webm", prompt=None):
        self.calls += 1
        return STTResult(text="hello world", raw="hello world", status="ok")

    def transcribe_bytes(self, audio_bytes, suffix=".webm", prompt=None):
        self.calls += 1
        return "hello world"


def test_chain_falls_back_to_next_provider():
    boom, ok = Boom(), Ok()
    chain = ChainSTT([("boom", lambda: boom), ("ok", lambda: ok)])
    assert chain.transcribe_bytes(b"x") == "hello world"
    assert chain.active is ok
    # active provider is reused, no more fallbacks
    assert chain.transcribe_bytes(b"x") == "hello world"
    assert boom.calls == 1 and ok.calls == 2


def test_chain_raises_when_all_fail():
    chain = ChainSTT([("boom", lambda: Boom())])
    try:
        chain.transcribe_bytes(b"x")
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "all STT providers failed" in str(e)
        assert "boom" in str(e)


def test_no_speech_result_is_returned_not_raised():
    class Silent:
        def transcribe_detailed(self, audio_bytes, suffix=".webm", prompt=None):
            return STTResult(status="no_speech", reason="silence")

        def transcribe_bytes(self, audio_bytes, suffix=".webm", prompt=None):
            return ""

    chain = ChainSTT([("silent", lambda: Silent())])
    result = chain.transcribe_detailed(b"x")
    assert result.status == "no_speech"
    assert result.text == ""


def test_overlap_is_removed_between_chunks():
    assert remove_overlap("the quick brown fox", "brown fox jumps over") == "jumps over"
    assert remove_overlap("hello", "hello") == ""
