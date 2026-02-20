"""
Content guard: checks tweets before posting so the automator is careful.
- AI safety check: appropriate, on-brand, no hate/misinformation.
- Blocklist: reject if any configured word/phrase appears.
- Optional: avoid posting near-duplicates of recent tweets.
Uses OpenAI or Claude depending on AI_PROVIDER in .env.
"""

import logging
from pathlib import Path
from typing import List, Optional, Tuple

from ai_client import chat
from config import BLOCKLIST
from style_analyzer import load_style_profile

logger = logging.getLogger(__name__)

SAFETY_SYSTEM = """You are a content safety reviewer for tweets. Given a tweet and the account's style profile, rate it on a scale of 1-5 for SAFE TO POST (5 = definitely safe, 1 = do not post).

Consider:
- No hate speech, slurs, or harassment
- No misinformation or unverified claims presented as fact
- No excessive controversy unrelated to the account's usual topics
- Matches the account's typical tone and topics (from the style profile)
- Nothing that could damage the account holder's reputation
- No spam, all-caps rants, or off-brand political takes (unless that's the brand)

Reply with ONLY a single digit 1-5, then a space, then one short reason (e.g. "5 On-brand and safe" or "2 Too aggressive")."""


def _blocklist_reject(text: str) -> Optional[str]:
    """Return reason string if text hits blocklist, else None."""
    if not BLOCKLIST:
        return None
    lower = text.lower()
    for phrase in BLOCKLIST:
        if phrase in lower:
            return f"Blocklist hit: '{phrase}'"
    return None


def safety_check(
    text: str,
    profile_path: Optional[Path] = None,
    api_key_override: Optional[str] = None,
    min_score: int = 4,
) -> Tuple[bool, str]:
    """
    Run AI safety check on tweet. Returns (approved: bool, reason: str).
    Uses OpenAI or Claude depending on AI_PROVIDER. If no key for that provider, skips check.
    """
    block_reason = _blocklist_reject(text)
    if block_reason:
        return False, block_reason

    try:
        profile = load_style_profile(profile_path)
        topics = ", ".join(profile.get("topics", [])[:5])
        tone = profile.get("tone", "casual")
    except Exception as e:
        logger.warning("Could not load profile for safety context: %s", e)
        topics = ""
        tone = ""

    user_content = (
        f"Style profile (topics: {topics}, tone: {tone}).\n\n"
        f"Tweet to rate:\n{text}"
    )
    try:
        reply = chat(
            system=SAFETY_SYSTEM,
            user_content=user_content,
            max_tokens=80,
            temperature=0,
            api_key_override=api_key_override,
        )
        reply = (reply or "").strip()
        # Parse "5 On-brand" or "3 Reason"
        parts = reply.split(None, 1)
        score_str = parts[0] if parts else "0"
        reason = parts[1] if len(parts) > 1 else reply
        try:
            score = int(score_str)
        except ValueError:
            score = 0
        approved = score >= min_score
        return approved, f"Score {score}: {reason}"
    except ValueError as e:
        if "required" in str(e).lower() or "api_key" in str(e).lower():
            logger.warning("No API key for safety check; skipping (post allowed).")
            return True, "No API key (check skipped)"
        raise
    except Exception as e:
        logger.error("Safety check failed: %s", e)
        # Fail closed: do not post if check errors
        return False, f"Safety check error: {e}"


def is_too_similar_to_recent(
    text: str,
    recent_tweets: List[str],
    min_edit_ratio: float = 0.85,
) -> bool:
    """
    True if text is very similar to any recent tweet (simple ratio of shared words).
    Used to avoid posting near-duplicates.
    """
    if not recent_tweets or not text:
        return False
    text_words = set(text.lower().split())
    if len(text_words) < 3:
        return False
    for prev in recent_tweets[:20]:
        prev_words = set(prev.lower().split())
        overlap = len(text_words & prev_words) / max(len(text_words), 1)
        if overlap >= min_edit_ratio:
            return True
    return False
