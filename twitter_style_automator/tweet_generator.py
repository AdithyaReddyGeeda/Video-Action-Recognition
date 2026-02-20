"""
Tweet generator module: generates new tweets from the style profile
using AI (OpenAI or Claude), for given topics or auto-suggested ones.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from ai_client import chat
from style_analyzer import load_style_profile

logger = logging.getLogger(__name__)


def build_generation_prompt(
    profile: Dict[str, Any],
    topic: Optional[str] = None,
    extra_instructions: Optional[str] = None,
) -> str:
    """Build the system prompt for tweet generation from style profile."""
    handle = profile.get("handle", "user")
    template = profile.get("prompt_template", "")
    topics = profile.get("topics", [])
    tone = profile.get("tone", "casual")
    avg_len = profile.get("avg_length_words", 20)
    emoji = profile.get("emoji_usage", "")
    hashtag = profile.get("hashtag_style", "")
    lang = profile.get("language_patterns", "")

    if not template:
        template = (
            f"Write a single tweet in the style of @{handle}. "
            f"Topics often include: {', '.join(topics)}. Tone: {tone}. "
            f"Length around {avg_len} words. Emoji: {emoji}. Hashtags: {hashtag}. "
            f"Language: {lang}. Output only the tweet text, no quotes or explanation."
        )
    else:
        template = template.replace("{handle}", handle)
        template = template.replace("{topics}", ", ".join(topics))
        template = template.replace("{tone}", tone)
        template = template.replace("{avg_length_words}", str(avg_len))
        template = template.replace("{extra_guidance}", f"Emoji: {emoji}. Hashtags: {hashtag}.")

    instruction = f"Topic or theme for this tweet: {topic}" if topic else "Choose a theme from the user's usual topics or something timely and on-brand."
    if extra_instructions:
        instruction += f"\nAdditional instructions: {extra_instructions}"
    return template + "\n\n" + instruction


def generate_tweet(
    topic: Optional[str] = None,
    api_key_override: Optional[str] = None,
    profile_path: Optional[Path] = None,
    extra_instructions: Optional[str] = None,
) -> str:
    """
    Generate one tweet matching the style profile. Returns the tweet text only.
    Uses OpenAI or Claude depending on AI_PROVIDER in .env.
    """
    profile = load_style_profile(profile_path)
    prompt = build_generation_prompt(profile, topic=topic, extra_instructions=extra_instructions)

    text = chat(
        system="You output only the exact tweet text, no quotes, no preamble, no explanation. Maximum 280 characters.",
        user_content=prompt,
        max_tokens=150,
        temperature=0.8,
        api_key_override=api_key_override,
    )
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
    if len(text) > 280:
        text = text[:277] + "..."
    return text


def suggest_topics(profile_path: Optional[Path] = None) -> List[str]:
    """Return a short list of topic suggestions based on the style profile."""
    profile = load_style_profile(profile_path)
    return list(profile.get("topics", [])[:5])
