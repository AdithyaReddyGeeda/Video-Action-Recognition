"""
Style analyzer module: analyzes stored tweets with AI (OpenAI or Claude) to produce
a reusable "style profile" for tweet generation.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from ai_client import chat
from config import (
    COMBINED_STYLE_PROFILE,
    STYLE_PROFILE_PATH,
    X_HANDLE,
    get_style_profile_path_for_handle,
)
from tweet_fetcher import get_all_tweets_from_db

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert at analyzing writing style from a corpus of short texts (tweets).
Given a list of tweets, extract and summarize:
1. Common topics and themes (e.g., tech, space, humor, motivation).
2. Tone (e.g., humorous, professional, casual, sarcastic, enthusiastic).
3. Typical length in words (average and range).
4. Emoji usage (frequency, which emojis appear often).
5. Hashtag usage (frequency, style: single word, phrases, none).
6. Language patterns (sentence structure, questions vs statements, slang, punctuation).
7. Posting style (threads vs single tweets, call-to-actions, links).
8. Any catchphrases or recurring phrases.

Respond with valid JSON only, no markdown or extra text. Use this exact structure:
{
  "topics": ["topic1", "topic2"],
  "tone": "description in a few words",
  "avg_length_words": number,
  "length_range": [min, max],
  "emoji_usage": "description and examples",
  "hashtag_style": "description",
  "language_patterns": "description",
  "posting_style": "description",
  "prompt_template": "Write a tweet in the style of {handle}. Topics often include: {topics}. Tone: {tone}. Length around {avg_length_words} words. {extra_guidance}"
}
"""


def _tweets_sample_for_analysis(
    tweets: List[dict],
    max_tweets: int = 200,
    max_chars_total: int = 45000,
) -> str:
    """Build a string of tweet texts for the API, respecting token limits."""
    out: List[str] = []
    total = 0
    for t in tweets[:max_tweets]:
        text = (t.get("text") or "").strip()
        if not text:
            continue
        line = text[:280] + "\n"
        if total + len(line) > max_chars_total:
            break
        out.append(line)
        total += len(line)
    return "".join(out) if out else "No tweets available."


def analyze_style(
    api_key_override: Optional[str] = None,
    handle: str = "mcisaul",
    max_tweets: int = 200,
    db_path: Optional[Path] = None,
    profile_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Load tweets from DB, call AI (OpenAI or Claude) to analyze style, return and save profile.
    When profile_path is None, uses per-handle path (style_profiles/{handle}.json).
    """
    tweets = get_all_tweets_from_db(
        db_path=db_path, limit=max_tweets * 2, handle=handle
    )
    if not tweets:
        raise ValueError(
            "No tweets in database. Run fetch-tweets first."
        )

    sample = _tweets_sample_for_analysis(tweets, max_tweets=max_tweets)
    user_content = (
        f"Analyze the following tweets from user @{handle} and extract the style profile.\n\n"
        f"Tweets:\n{sample}"
    )

    text = chat(
        system=SYSTEM_PROMPT,
        user_content=user_content,
        max_tokens=2000,
        temperature=0.3,
        api_key_override=api_key_override,
    )
    text = text.strip()
    if text.startswith("```"):
        for start in ("```json", "```"):
            if text.startswith(start):
                text = text[len(start) :].strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    profile = json.loads(text)
    profile["handle"] = handle.lstrip("@")
    profile["analyzed_count"] = len(tweets)

    out_path = profile_path or get_style_profile_path_for_handle(handle) or STYLE_PROFILE_PATH
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)
    logger.info("Style profile saved to %s", out_path)
    return profile


def analyze_style_combined(
    handles: List[str],
    api_key_override: Optional[str] = None,
    max_tweets_per_user: int = 200,
    db_path: Optional[Path] = None,
    profile_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Load tweets from multiple handles, combine into one corpus, and build a single
    blended style profile. Use when learning from many accounts and posting as one.
    """
    if not handles:
        raise ValueError("handles must be a non-empty list (e.g. SOURCE_HANDLES).")
    combined: List[dict] = []
    for h in handles:
        h_clean = (h or "").strip().lstrip("@")
        if not h_clean:
            continue
        tweets = get_all_tweets_from_db(
            db_path=db_path,
            limit=max_tweets_per_user * 2,
            handle=h_clean,
        )
        combined.extend(tweets)
    if not combined:
        raise ValueError(
            "No tweets in database for any of the source handles. "
            "Run fetch-tweets --all-sources first."
        )

    sample = _tweets_sample_for_analysis(
        combined,
        max_tweets=min(500, len(combined)),
        max_chars_total=50000,
    )
    handles_str = ", ".join(f"@{h.strip().lstrip('@')}" for h in handles if (h or "").strip())
    user_content = (
        "Analyze the following tweets from multiple users (combined) and extract "
        "a single blended style profile. The tweets are from: " + handles_str + ".\n\n"
        "Produce one style that captures common themes, tone, length, and patterns across all. "
        "Use handle 'combined' in the output.\n\n"
        f"Tweets:\n{sample}"
    )

    text = chat(
        system=SYSTEM_PROMPT,
        user_content=user_content,
        max_tokens=2000,
        temperature=0.3,
        api_key_override=api_key_override,
    )
    text = text.strip()
    if text.startswith("```"):
        for start in ("```json", "```"):
            if text.startswith(start):
                text = text[len(start) :].strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    profile = json.loads(text)
    profile["handle"] = "combined"
    profile["source_handles"] = [h.strip().lstrip("@") for h in handles if (h or "").strip()]
    profile["analyzed_count"] = len(combined)

    out_path = profile_path or COMBINED_STYLE_PROFILE
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)
    logger.info("Combined style profile saved to %s (from %d tweets, %d handles)", out_path, len(combined), len(profile.get("source_handles", [])))
    return profile


def get_default_style_profile() -> Dict[str, Any]:
    """Return a minimal style profile when no analyzed profile exists (e.g. before fetch/analyze)."""
    handle = X_HANDLE or "user"
    return {
        "handle": handle,
        "topics": ["tech", "productivity", "ideas"],
        "tone": "casual and friendly",
        "avg_length_words": 25,
        "length_range": [15, 40],
        "emoji_usage": "light, occasional",
        "hashtag_style": "optional, 0-2 per tweet",
        "language_patterns": "conversational",
        "posting_style": "single tweets",
        "prompt_template": (
            f"Write a single tweet in the style of @{handle}. "
            "Topics often include: tech, productivity, ideas. Tone: casual and friendly. "
            "Length around 25 words. Output only the tweet text, no quotes or explanation."
        ),
        "analyzed_count": 0,
    }


def load_style_profile(profile_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load style profile from JSON file. Raises FileNotFoundError if missing."""
    path = profile_path or STYLE_PROFILE_PATH
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Style profile not found at {path}. Run analyze-style first."
        )
    with open(path, encoding="utf-8") as f:
        return json.load(f)
