"""Unified LLM access: Groq first (fast), OpenRouter as fallback.

Every call is resilient:
  * tries the fast Groq model (default `openai/gpt-oss-20b`),
  * then a stronger Groq model,
  * then OpenRouter's primary model,
  * then OpenRouter's router/free fallback.
Provider errors, timeouts and empty completions automatically move on.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from functools import lru_cache
from typing import Any

from app.config import settings

log = logging.getLogger("llm")


class LLMError(RuntimeError):
    pass


@lru_cache(maxsize=4)
def _groq_client():
    from groq import Groq

    key = settings.groq_api_key or os.getenv("GROQ_API_KEY", "")
    if not key:
        raise LLMError("GROQ_API_KEY not set")
    return Groq(api_key=key, timeout=settings.llm_timeout_s, max_retries=0)


@lru_cache(maxsize=4)
def _openrouter_client():
    from openai import OpenAI

    key = settings.openrouter_api_key or os.getenv("OPENROUTER_API_KEY", "")
    if not key:
        raise LLMError("OPENROUTER_API_KEY not set")
    return OpenAI(base_url="https://openrouter.ai/api/v1", api_key=key, timeout=settings.llm_timeout_s, max_retries=0)


def provider_chain(model: str | None = None) -> list[tuple[str, str]]:
    chain: list[tuple[str, str]] = []
    primary = model or settings.llm_model
    candidates = [
        ("groq", primary),
        ("groq", settings.llm_secondary_model),
        ("openrouter", settings.openrouter_model),
        ("openrouter", settings.openrouter_fallback),
    ]
    seen: set[tuple[str, str]] = set()
    for provider, name in candidates:
        if not name or (provider, name) in seen:
            continue
        seen.add((provider, name))
        if provider == "groq" and not (settings.groq_api_key or os.getenv("GROQ_API_KEY")):
            continue
        if provider == "openrouter" and not (settings.openrouter_api_key or os.getenv("OPENROUTER_API_KEY")):
            continue
        chain.append((provider, name))
    if not chain:
        raise LLMError("no LLM provider configured")
    return chain


def _is_retryable(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status in (408, 409, 429, 500, 502, 503, 504):
        return True
    name = type(exc).__name__.lower()
    return any(tok in name for tok in ("ratelimit", "timeout", "connection", "apiconnection", "internalserver"))


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _extract_json_span(text: str) -> str | None:
    """Return the first balanced JSON object/array found in `text`."""
    text = _strip_fences(text)
    try:
        json.loads(text)
        return text
    except Exception:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start == -1:
            continue
        depth = 0
        in_str = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    return None


def parse_json_loose(raw: str) -> Any:
    span = _extract_json_span(raw)
    if span is None:
        raise ValueError("no JSON found in LLM output")
    try:
        return json.loads(span)
    except json.JSONDecodeError:
        # common model slips: trailing commas, smart quotes, stray newlines in strings
        fixed = re.sub(r",\s*([}\]])", r"\1", span)
        fixed = fixed.replace("\u201c", '"').replace("\u201d", '"').replace("\u2019", "'")
        try:
            return json.loads(fixed)
        except json.JSONDecodeError as e:
            raise ValueError(f"invalid JSON: {e}") from e


def _call_groq(model: str, messages: list[dict], json_mode: bool, max_tokens: int, temperature: float) -> str:
    # gpt-oss spends most of its completion budget on reasoning; a small budget
    # yields an empty string (finish_reason=length with only reasoning tokens).
    budget = max(max_tokens, 512) if "gpt-oss" in model else max_tokens
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": budget,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    effort = (settings.llm_reasoning_effort or "").strip().lower()
    if effort in ("low", "medium", "high") and "gpt-oss" in model:
        kwargs["reasoning_effort"] = effort
    resp = _groq_client().chat.completions.create(**kwargs)
    return (resp.choices[0].message.content or "").strip()


def _call_openrouter(model: str, messages: list[dict], json_mode: bool, max_tokens: int, temperature: float) -> str:
    # Free OpenRouter routes are frequently reasoning models: 1024 tokens is the
    # smallest budget that reliably leaves room for an actual answer.
    budget = max(max_tokens, 1024)
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": budget,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = _openrouter_client().chat.completions.create(**kwargs)
    return (resp.choices[0].message.content or "").strip()


def chat_sync(
    prompt: str,
    system: str | None = None,
    model: str | None = None,
    json_mode: bool = False,
    max_tokens: int = 1024,
    temperature: float = 0.2,
) -> str:
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    errors: list[str] = []
    for provider, name in provider_chain(model):
        budget = max(max_tokens, 512)
        for attempt in range(2):
            started = time.time()
            try:
                if provider == "groq":
                    text = _call_groq(name, messages, json_mode, budget, temperature)
                else:
                    text = _call_openrouter(name, messages, json_mode, budget, temperature)
                if text:
                    log.info("%s/%s ok in %.2fs", provider, name, time.time() - started)
                    return text
                errors.append(f"{provider}/{name}: empty completion (max_tokens={budget})")
                # Reasoning models can burn the whole budget before answering.
                if budget < 4096:
                    budget *= 2
                    log.warning("%s/%s returned no content; retrying with max_tokens=%s", provider, name, budget)
                    continue
                break
            except Exception as e:  # noqa: BLE001 - provider errors are expected
                errors.append(f"{provider}/{name}: {type(e).__name__}: {e}")
                log.warning("%s/%s failed in %.2fs: %s", provider, name, time.time() - started, e)
                if attempt == 0 and _is_retryable(e):
                    time.sleep(0.7)
                    continue
                break
    raise LLMError("all LLM providers failed -> " + " | ".join(errors))


def chat_json_sync(
    prompt: str,
    system: str | None = None,
    model: str | None = None,
    max_tokens: int = 1536,
    temperature: float = 0.2,
) -> Any:
    system = (system or "You output only valid JSON, with no markdown fences and no commentary.").strip()
    raw = chat_sync(prompt, system=system, model=model, json_mode=True, max_tokens=max_tokens, temperature=temperature)
    try:
        return parse_json_loose(raw)
    except ValueError:
        # one repair attempt on the same fast chain
        repair = (
            "The following text was supposed to be valid JSON but is malformed. "
            "Return ONLY the corrected, valid JSON. Do not add or remove data.\n\n" + raw
        )
        fixed = chat_sync(repair, system=system, model=model, json_mode=True, max_tokens=max_tokens, temperature=0.0)
        return parse_json_loose(fixed)


async def chat(prompt: str, **kwargs: Any) -> str:
    return await asyncio.to_thread(chat_sync, prompt, **kwargs)


async def chat_json(prompt: str, **kwargs: Any) -> Any:
    return await asyncio.to_thread(chat_json_sync, prompt, **kwargs)
