import json
import os
from typing import Any

from openai import OpenAI

from app.config import settings


def _client() -> OpenAI:
    key = settings.openrouter_api_key or os.getenv("OPENROUTER_API_KEY", "")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    return OpenAI(base_url="https://openrouter.ai/api/v1", api_key=key)


def chat(prompt: str, system: str | None = None, model: str | None = None, json_mode: bool = False, max_tokens: int = 2048) -> str:
    client = _client()
    models = [model or settings.openrouter_model, settings.openrouter_fallback]
    last_err = None
    for m in models:
        for attempt in range(3):
            try:
                kwargs: dict[str, Any] = {
                    "model": m,
                    "messages": [],
                    "temperature": 0.3,
                    "max_tokens": max_tokens,
                }
                if system:
                    kwargs["messages"].append({"role": "system", "content": system})
                kwargs["messages"].append({"role": "user", "content": prompt})
                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}
                resp = client.chat.completions.create(**kwargs)
                text = (resp.choices[0].message.content or "").strip()
                if text:
                    return text
            except Exception as e:
                last_err = e
                continue
    raise RuntimeError(f"openrouter failed: {last_err}")


def chat_json(prompt: str, system: str | None = None, model: str | None = None, max_tokens: int = 2048) -> Any:
    raw = chat(prompt, system=system, model=model, json_mode=False, max_tokens=max_tokens)
    # strip markdown fences if present
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # retry: find first { ... } or [ ... ]
        for opener, closer in (("{", "}"), ("[", "]")):
            i = text.find(opener)
            j = text.rfind(closer)
            if i != -1 and j != -1 and j > i:
                try:
                    return json.loads(text[i : j + 1])
                except json.JSONDecodeError:
                    continue
        raise