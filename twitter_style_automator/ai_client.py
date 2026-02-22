"""
Unified AI client: OpenAI, Anthropic (Claude), or Ollama (local).
Uses AI_PROVIDER and the corresponding config from .env.
"""

import logging
from typing import Optional

from config import (
    AI_PROVIDER,
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OPENAI_API_KEY,
)

logger = logging.getLogger(__name__)


def chat(
    system: str,
    user_content: str,
    max_tokens: int = 1024,
    temperature: float = 0.3,
    api_key_override: Optional[str] = None,
) -> str:
    """
    Send a chat completion request to the configured provider.
    Returns the assistant's reply text.
    """
    if AI_PROVIDER == "ollama":
        return _ollama_chat(
            system=system,
            user_content=user_content,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    if AI_PROVIDER == "anthropic":
        key = api_key_override or ANTHROPIC_API_KEY
        if not key:
            raise ValueError(
                "ANTHROPIC_API_KEY is required. Set it in .env or use AI_PROVIDER=ollama for local."
            )
        return _anthropic_chat(
            system=system,
            user_content=user_content,
            max_tokens=max_tokens,
            temperature=temperature,
            api_key=key,
            model=ANTHROPIC_MODEL,
        )
    key = api_key_override or OPENAI_API_KEY
    if not key:
        raise ValueError(
            "OPENAI_API_KEY is required. Set it in .env or use AI_PROVIDER=anthropic or AI_PROVIDER=ollama."
        )
    return _openai_chat(
        system=system,
        user_content=user_content,
        max_tokens=max_tokens,
        temperature=temperature,
        api_key=key,
    )


def _openai_chat(
    system: str,
    user_content: str,
    max_tokens: int,
    temperature: float,
    api_key: str,
) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return (response.choices[0].message.content or "").strip()


def _anthropic_chat(
    system: str,
    user_content: str,
    max_tokens: int,
    temperature: float,
    api_key: str,
    model: Optional[str] = None,
) -> str:
    from anthropic import Anthropic
    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model or ANTHROPIC_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_content}],
        temperature=temperature,
    )
    if response.content and len(response.content) > 0:
        block = response.content[0]
        if hasattr(block, "text"):
            return block.text.strip()
    return ""


def _ollama_chat(
    system: str,
    user_content: str,
    max_tokens: int,
    temperature: float,
) -> str:
    """Call local Ollama API. No API key required; ensure Ollama is running and model is pulled."""
    import requests
    base = OLLAMA_BASE_URL.rstrip("/")
    url = f"{base}/api/chat"
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user_content}]
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }
    try:
        r = requests.post(url, json=payload, timeout=120)
        r.raise_for_status()
        data = r.json()
        msg = data.get("message") or {}
        text = (msg.get("content") or "").strip()
        return text
    except requests.exceptions.ConnectionError:
        raise ValueError(
            f"Could not reach Ollama at {base}. Is Ollama running? Start it with: ollama serve"
        )
    except requests.exceptions.RequestException as e:
        raise ValueError(f"Ollama request failed: {e}")
