"""
Style analyzer module: analyzes stored tweets with AI (OpenAI or Claude) to produce
a reusable "style profile" for tweet generation.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from ai_client import chat
from config import STYLE_PROFILE_PATH
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
    """
    tweets = get_all_tweets_from_db(db_path=db_path, limit=max_tweets * 2)
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

    out_path = profile_path or STYLE_PROFILE_PATH
    out_path = Path(out_path)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)
    logger.info("Style profile saved to %s", out_path)
    return profile


def load_style_profile(profile_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load style profile from JSON file."""
    path = profile_path or STYLE_PROFILE_PATH
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Style profile not found at {path}. Run analyze-style first."
        )
    with open(path, encoding="utf-8") as f:
        return json.load(f)
