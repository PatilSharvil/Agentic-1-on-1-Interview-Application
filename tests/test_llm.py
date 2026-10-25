import pytest

from app import llm
from app.llm import LLMError, chat_sync, parse_json_loose, provider_chain


def test_parse_plain_json():
    assert parse_json_loose('{"a": 1}') == {"a": 1}


def test_parse_fenced_json():
    assert parse_json_loose('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_json_with_prose_around_it():
    assert parse_json_loose('Here you go:\n{"questions": ["why?"]}\nHope it helps') == {"questions": ["why?"]}


def test_parse_json_with_trailing_comma():
    assert parse_json_loose('{"a": 1, "b": [1, 2,],}') == {"a": 1, "b": [1, 2]}


def test_parse_json_array():
    assert parse_json_loose('[{"a": 1}]') == [{"a": 1}]


def test_parse_json_rejects_garbage():
    with pytest.raises(ValueError):
        parse_json_loose("no json here")


def test_provider_chain_starts_with_groq_and_has_openrouter_fallback():
    chain = provider_chain()
    assert chain[0][0] == "groq"
    assert chain[0][1] == "openai/gpt-oss-20b"
    providers = [p for p, _ in chain]
    assert "openrouter" in providers
    # no duplicate (provider, model) pairs
    assert len(chain) == len(set(chain))


def test_chat_sync_falls_back_to_openrouter(monkeypatch):
    calls = {"groq": 0, "openrouter": 0}

    def boom(*args, **kwargs):
        calls["groq"] += 1
        raise RuntimeError("groq down")

    def ok(*args, **kwargs):
        calls["openrouter"] += 1
        return "fallback answer"

    monkeypatch.setattr(llm, "_call_groq", boom)
    monkeypatch.setattr(llm, "_call_openrouter", ok)
    assert chat_sync("hello") == "fallback answer"
    assert calls["groq"] >= 1
    assert calls["openrouter"] >= 1


def test_chat_sync_raises_when_everything_fails(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(llm, "_call_groq", boom)
    monkeypatch.setattr(llm, "_call_openrouter", boom)
    with pytest.raises(LLMError):
        chat_sync("hello")


def test_json_mode_retries_once_on_malformed_output(monkeypatch):
    outputs = iter(["not json at all", '{"ok": true}'])

    def fake_chat(*args, **kwargs):
        return next(outputs)

    monkeypatch.setattr(llm, "chat_sync", fake_chat)
    # chat_json_sync calls chat_sync (patched at module level) then repairs
    assert llm.chat_json_sync("give json") == {"ok": True}
