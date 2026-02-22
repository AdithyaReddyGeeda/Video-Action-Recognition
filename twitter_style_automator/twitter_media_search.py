"""
Search Twitter/X for public tweets with media (images or videos) and return
downloadable media URLs. Used to find relevant media to attach to new tweets.

DISCLAIMER: Reusing others' media may violate copyright and X's Terms of Service.
Use only where you have permission or for content clearly licensed for reuse.
You are responsible for compliance.
"""

import logging
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import tweepy

from config import X_BEARER_TOKEN

logger = logging.getLogger(__name__)

# Media types we care about
PHOTO_TYPES = {"photo"}
VIDEO_TYPES = {"video", "animated_gif"}


def _build_search_query(topic: Optional[str], tweet_text: str, max_words: int = 5) -> str:
    """Build a search query from topic and tweet text (no special chars)."""
    words = []
    if topic:
        words.extend(topic.split())
    for w in tweet_text.replace(".", " ").replace(",", " ").split():
        if w.startswith("#") or w.startswith("http") or len(w) < 2:
            continue
        words.append(w)
        if len(words) >= max_words:
            break
    query = " ".join(words[:max_words]) if words else "tech"
    return query.strip()


def search_twitter_for_media(
    query: str,
    media_type: str,
    bearer_token: Optional[str] = None,
    max_results: int = 20,
) -> List[Dict[str, Any]]:
    """
    Search recent tweets for media. Returns list of dicts: {url, type, tweet_text, media_key}.
    media_type: "photo" or "video".
    """
    token = bearer_token or X_BEARER_TOKEN
    if not token:
        logger.warning("X_BEARER_TOKEN required for Twitter media search.")
        return []

    client = tweepy.Client(bearer_token=token, wait_on_rate_limit=True)
    # Query: filter to tweets that have media (filter:images or filter:video in v2)
    if media_type == "photo":
        query = f"{query} has:images"
    else:
        query = f"{query} has:video"

    try:
        response = client.search_recent_tweets(
            query=query[:500],
            max_results=min(max_results, 100),
            expansions=["attachments.media_keys"],
            media_fields=["url", "type", "preview_image_url", "variants"],
            tweet_fields=["text"],
            user_auth=False,
        )
    except tweepy.TweepyException as e:
        logger.error("Twitter search failed: %s", e)
        return []

    if not response.data:
        return []

    includes = getattr(response, "includes", None) or {}
    media_list = getattr(includes, "media", None) or includes.get("media", [])
    media_by_key = {}
    for m in media_list:
        key = getattr(m, "media_key", None) or m.get("media_key")
        if key:
            media_by_key[key] = m

    candidates = []
    for tweet in response.data:
        t = getattr(tweet, "data", tweet)
        if hasattr(t, "get"):
            text = t.get("text", "") or ""
            attachments = t.get("attachments", {}) or {}
        else:
            text = getattr(t, "text", "") or ""
            attachments = getattr(t, "attachments", None) or {}
            if attachments and not hasattr(attachments, "get"):
                attachments = {}
        media_keys = attachments.get("media_keys", []) if hasattr(attachments, "get") else getattr(attachments, "media_keys", []) or []
        for key in media_keys:
            m = media_by_key.get(key)
            if not m:
                continue
            mtype = (getattr(m, "type", None) or m.get("type") or "").lower()
            if media_type == "photo" and mtype not in PHOTO_TYPES:
                continue
            if media_type == "video" and mtype not in VIDEO_TYPES:
                continue
            url = None
            if mtype == "photo":
                url = getattr(m, "url", None) or m.get("url")
            else:
                variants = getattr(m, "variants", None) or m.get("variants") or []
                for v in variants:
                    u = getattr(v, "url", None) if hasattr(v, "url") else (v.get("url") if hasattr(v, "get") else None)
                    ct = getattr(v, "content_type", "") or (v.get("content_type") if hasattr(v, "get") else "") or ""
                    if u and "video" in ct:
                        url = u
                        break
                if not url and variants:
                    v0 = variants[0]
                    url = getattr(v0, "url", None) if hasattr(v0, "url") else (v0.get("url") if hasattr(v0, "get") else None)
            if url:
                candidates.append({"url": url, "type": mtype, "tweet_text": text[:200], "media_key": key})
    return candidates


def _pick_best_media_with_ai(
    candidates: List[Dict[str, Any]],
    our_tweet_text: str,
    topic: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Use AI to pick the most relevant media for our tweet."""
    if not candidates:
        return None
    from ai_client import chat
    shown = candidates[:15]
    lines = [f"{i+1}. Tweet: \"{c['tweet_text'][:120]}...\" URL: {c['url'][:60]}..." for i, c in enumerate(shown)]
    prompt = (
        f"Our tweet: \"{our_tweet_text[:200]}\"\nTopic: {topic or 'general'}\n"
        f"Which item (1 to {len(shown)}) has the most relevant media for our tweet? Reply with only the number."
    )
    prompt += "\n\n" + "\n".join(lines)
    try:
        reply = chat(
            system="Reply with a single number (1 to N) for the best match. No other text.",
            user_content=prompt,
            max_tokens=10,
            temperature=0,
        )
        idx = int((reply or "1").strip().split()[0])
        if 1 <= idx <= len(shown):
            return shown[idx - 1]
    except Exception as e:
        logger.warning("AI pick failed: %s; using first", e)
    return shown[0]


def _download_media(url: str, media_type: str) -> Optional[Path]:
    """Download media from URL to a temp file. Returns path or None."""
    try:
        r = requests.get(url, timeout=30, stream=True)
        r.raise_for_status()
        if media_type in VIDEO_TYPES:
            suffix = ".mp4" if "mp4" in url or "video" in url else ".mp4"
        else:
            suffix = ".jpg" if "jpg" in url or "jpeg" in url else ".png"
        f = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)
        f.close()
        return Path(f.name)
    except Exception as e:
        logger.warning("Download failed for %s: %s", url[:50], e)
        return None


def get_media_from_twitter(
    tweet_text: str,
    topic: Optional[str],
    media_type: str,
    dry_run: bool = False,
) -> Optional[Path]:
    """
    Search Twitter for relevant media (photo or video), pick best with AI, download to temp file.
    Returns path to the downloaded file, or None. Caller must delete the temp file when done.
    """
    query = _build_search_query(topic, tweet_text)
    candidates = search_twitter_for_media(query, media_type, max_results=25)
    if not candidates:
        logger.warning("No %s media found on Twitter for query: %s", media_type, query)
        return None
    chosen = _pick_best_media_with_ai(candidates, tweet_text, topic)
    if not chosen:
        return None
    if dry_run:
        logger.info("[DRY RUN] Would use media from Twitter: %s", chosen.get("url", "")[:60])
        return None
    path = _download_media(chosen["url"], chosen.get("type", media_type))
    return path
