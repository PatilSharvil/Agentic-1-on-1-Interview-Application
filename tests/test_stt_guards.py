from app.stt import (
    _polish_guard,
    clean_text_deterministic,
    is_hallucination,
    remove_overlap,
)

PROMPT = "Technical software engineering job interview between an interviewer and a candidate."


def test_known_silence_hallucinations_are_dropped():
    for text in [
        "Thank you.",
        "Thanks for watching!",
        "I'm not sure what I'm doing.",
        "Please subscribe",
        "you",
        "bye",
        "Technical terms.",
        "and more.",
    ]:
        assert is_hallucination(text), text


def test_real_sentences_are_kept():
    for text in [
        "I built a REST API with FastAPI and PostgreSQL.",
        "We reduced latency by forty percent using Redis.",
        "I have never used Kubernetes in production.",
        "My name is Sharun Patil and I am a backend engineer.",
    ]:
        assert not is_hallucination(text), text


def test_prompt_echo_is_dropped():
    assert is_hallucination(
        "Technical software engineering job interview.",
        PROMPT,
    )


def test_non_english_output_is_dropped():
    for text in [
        "Je suis un ingénieur logiciel.",
        "Hola, soy un ingeniero de software.",
        "Ich bin ein Softwareingenieur.",
        "Eu sou engenheiro de software.",
        "Main ek engineer hoon aur mujhe Python pasand hai.",
        "मैं एक सॉफ्टवेयर इंजीनियर हूँ।",
    ]:
        assert is_hallucination(text), text


def test_english_only_does_not_drop_normal_interview_sentences():
    for text in [
        "I design distributed systems and review code.",
        "The service had a small sin in the retry logic.",
        "We use a queue in front of the database.",
        "My experience is mostly backend and infrastructure.",
    ]:
        assert not is_hallucination(text), text


def test_deterministic_cleanup_fixes_known_asr_term_variants():
    cleaned = clean_text_deterministic(
        "I have never used KubeEarnets, but we used GitHub Actions for CI-CD and Teraform, "
        "and added a readies cache."
    )
    assert "Kubernetes" in cleaned
    assert "CI/CD" in cleaned
    assert "Terraform" in cleaned
    assert "Redis cache" in cleaned


def test_repetition_loop_is_dropped():
    assert is_hallucination("thank you thank you thank you thank you")


def test_low_confidence_short_text_is_dropped():
    assert is_hallucination("and more.", avg_logprob=-1.2)


def test_overlap_removal():
    assert remove_overlap("I built a REST API with FastAPI", "FastAPI and PostgreSQL") == "and PostgreSQL"
    assert remove_overlap("I built a REST API", "I built a REST API") == ""
    assert remove_overlap("we used docker and kubernetes", "kubernetes in production") == "in production"
    assert remove_overlap("hello world", "completely new sentence") == "completely new sentence"


def test_deterministic_cleanup_removes_fillers_and_fixes_tech_terms():
    cleaned = clean_text_deterministic(
        "um so i built a fast api using pie thon and post gres, and i i deployed it on a w s"
    )
    assert "FastAPI" in cleaned
    assert "Python" in cleaned
    assert "PostgreSQL" in cleaned
    assert "AWS" in cleaned
    assert " um " not in f" {cleaned.lower()} "
    assert "i i" not in cleaned.lower()
    assert cleaned.endswith(".")


def test_deterministic_cleanup_preserves_meaning_words():
    raw = "I worked at TechCorp on a payments service and reduced p95 latency by forty percent"
    cleaned = clean_text_deterministic(raw)
    assert "TechCorp" in cleaned
    assert "payments service" in cleaned
    assert "forty percent" in cleaned


def test_polish_guard_rejects_rewrites_and_inventions():
    raw = "I built a REST API with FastAPI and deployed it on AWS."
    assert _polish_guard(raw, "I built a REST API with FastAPI and deployed it on AWS.") is True
    assert _polish_guard(raw, "I architected a global microservices platform handling billions of requests.") is False
    assert _polish_guard(raw, "I built a REST API with FastAPI and deployed it on AWS. I also speak Japanese fluently.") is False
    assert _polish_guard(raw, "Sure! Here is the cleaned transcript: I built an API.") is False


def test_polish_guard_rejects_new_numbers():
    raw = "I reduced latency by forty percent."
    assert _polish_guard(raw, "I reduced latency by 40 percent.") is False
