"""
Poster module: post tweets, schedule jobs, reply to mentions,
like/retweet by keywords. Uses OAuth 1.0a for write operations.
"""

import logging
import random
import time
from pathlib import Path
from typing import Callable, List, Optional

import tweepy

from accounts import get_credentials_for_handle
from config import (
    DB_PATH,
    ENABLE_SAFETY_CHECK,
    MAX_DELAY_SEC,
    MAX_POSTS_PER_DAY,
    MIN_DELAY_SEC,
    POST_COUNT_FILE,
    POST_LOG_PATH,
    STYLE_PROFILE_PATH,
    X_API_KEY,
    X_API_SECRET,
    X_BEARER_TOKEN,
    X_HANDLE,
    get_post_count_file_for_handle,
    get_post_log_path_for_handle,
    get_style_profile_for_posting,
    get_style_profile_path_for_handle,
)
from tweet_generator import generate_tweet
from media_helper import get_and_upload_media

logger = logging.getLogger(__name__)

# Rate limit: avoid bursting; space out writes
MIN_POST_INTERVAL_SEC = 300  # 5 min between posts when scheduling
RATE_LIMIT_WAIT = 900
RETRY_WAIT = 60


def _random_delay() -> None:
    """Human-like delay between automated actions."""
    delay = random.randint(MIN_DELAY_SEC, max(MIN_DELAY_SEC + 1, MAX_DELAY_SEC))
    logger.debug("Sleeping %s sec (human-like delay)", delay)
    time.sleep(delay)


def get_tweepy_api(handle: Optional[str] = None) -> tweepy.API:
    """Build Tweepy API with OAuth 1.0a for read/write. Uses handle from accounts.json or .env."""
    if not X_API_KEY or not X_API_SECRET:
        raise ValueError("X_API_KEY and X_API_SECRET required for posting")
    access_token, access_token_secret = get_credentials_for_handle(
        handle, X_API_KEY, X_API_SECRET
    )
    auth = tweepy.OAuth1UserHandler(
        X_API_KEY,
        X_API_SECRET,
        access_token,
        access_token_secret,
    )
    return tweepy.API(auth, wait_on_rate_limit=True)


def get_tweepy_client_v2(handle: Optional[str] = None) -> tweepy.Client:
    """Client for API v2 (posting tweets). Uses handle from accounts.json or .env."""
    if not X_API_KEY or not X_API_SECRET:
        raise ValueError("X_API_KEY and X_API_SECRET required for posting")
    access_token, access_token_secret = get_credentials_for_handle(
        handle, X_API_KEY, X_API_SECRET
    )
    return tweepy.Client(
        consumer_key=X_API_KEY,
        consumer_secret=X_API_SECRET,
        access_token=access_token,
        access_token_secret=access_token_secret,
        wait_on_rate_limit=True,
    )


def post_tweet(
    text: str,
    dry_run: bool = False,
    media_ids: Optional[List[str]] = None,
    handle: Optional[str] = None,
) -> Optional[str]:
    """
    Post a tweet as the authenticated user. Optionally attach media (image/video).
    handle: account to post as (from accounts.json or .env default).
    Returns tweet id if successful.
    """
    if not text or len(text) > 280:
        logger.warning("Invalid tweet length: %s", len(text))
        return None
    if dry_run:
        logger.info("[DRY RUN] Would post: %s", text[:80])
        if media_ids:
            logger.info("[DRY RUN] With %s media attachment(s)", len(media_ids))
        return "dry_run_id"
    try:
        client = get_tweepy_client_v2(handle=handle)
        kwargs = {"text": text}
        if media_ids:
            kwargs["media_ids"] = [int(m) for m in media_ids]
        response = client.create_tweet(**kwargs)
        if response and response.data and response.data.get("id"):
            tid = response.data["id"]
            logger.info("Posted tweet id %s", tid)
            return tid
    except tweepy.TooManyRequests:
        logger.warning("Rate limited; waiting %s sec", RATE_LIMIT_WAIT)
        time.sleep(RATE_LIMIT_WAIT)
        return post_tweet(text, dry_run=False, media_ids=media_ids)
    except tweepy.TweepyException as e:
        logger.error("Post failed: %s", e)
        return None
    return None


def _get_today_post_count(handle: Optional[str] = None) -> int:
    """Read today's post count from disk (date line + count line). Per-handle when handle set."""
    path = get_post_count_file_for_handle(handle or "") if handle else Path(POST_COUNT_FILE)
    if not path.exists():
        return 0
    try:
        with open(path, "r") as f:
            lines = f.read().strip().splitlines()
        if len(lines) >= 2:
            from datetime import datetime
            today = datetime.utcnow().strftime("%Y-%m-%d")
            if lines[0].strip() == today:
                return int(lines[1].strip())
    except Exception:
        pass
    return 0


def _increment_today_post_count(handle: Optional[str] = None) -> None:
    """Increment and write today's post count. Per-handle when handle set."""
    from datetime import datetime
    path = get_post_count_file_for_handle(handle or "") if handle else Path(POST_COUNT_FILE)
    today = datetime.utcnow().strftime("%Y-%m-%d")
    count = _get_today_post_count(handle) + 1
    try:
        with open(path, "w") as f:
            f.write(f"{today}\n{count}\n")
    except Exception as e:
        logger.warning("Could not write post count: %s", e)


def _log_post(
    text: str,
    tweet_id: Optional[str] = None,
    dry_run: bool = False,
    handle: Optional[str] = None,
) -> None:
    """Append to post log for review. Per-handle when handle set."""
    from datetime import datetime
    path = get_post_log_path_for_handle(handle or "") if handle else Path(POST_LOG_PATH)
    try:
        with open(path, "a", encoding="utf-8") as f:
            ts = datetime.utcnow().isoformat() + "Z"
            flag = " [DRY RUN]" if dry_run else ""
            f.write(f"{ts}{flag}\t{tweet_id or ''}\t{text}\n")
    except Exception as e:
        logger.warning("Could not write post log: %s", e)


def post_generated_tweet(
    topic: Optional[str] = None,
    dry_run: bool = False,
    profile_path: Optional[Path] = None,
    confirm: bool = False,
    handle: Optional[str] = None,
) -> Optional[str]:
    """
    Generate a tweet, run safety checks, then post (no user input).
    handle: account to post as; used for credentials and per-handle profile/count/log.
    - Respects MAX_POSTS_PER_DAY per handle.
    - Runs AI safety check and blocklist if ENABLE_SAFETY_CHECK.
    - Skips if too similar to recent tweets in DB for that handle.
    - Logs every post to per-handle or default POST_LOG_PATH.
    """
    _random_delay()
    h = (handle or "").strip().lstrip("@") or (X_HANDLE or "").strip().lstrip("@")
    profile_path = profile_path or get_style_profile_for_posting(h) or get_style_profile_path_for_handle(h) or STYLE_PROFILE_PATH
    path = Path(profile_path)

    if not dry_run and _get_today_post_count(handle=h or None) >= MAX_POSTS_PER_DAY:
        logger.info("Daily post limit reached (%s) for @%s; skipping.", MAX_POSTS_PER_DAY, h or "default")
        return None

    text = generate_tweet(topic=topic, profile_path=path)
    if not text:
        return None

    if not dry_run:
        if ENABLE_SAFETY_CHECK:
            from content_guard import safety_check, is_too_similar_to_recent
            from tweet_fetcher import get_all_tweets_from_db
            approved, reason = safety_check(text, profile_path=path)
            if not approved:
                logger.warning("Safety check rejected: %s. Tweet not posted.", reason)
                return None
            logger.info("Safety check passed: %s", reason)
            recent = [
                t["text"]
                for t in get_all_tweets_from_db(db_path=DB_PATH, limit=30, handle=h or None)
            ]
            if is_too_similar_to_recent(text, recent):
                logger.warning("Tweet too similar to recent; skipping.")
                return None

    if dry_run:
        _log_post(text, dry_run=True, handle=h or None)
        api = get_tweepy_api(handle=h or None)
        media_ids = get_and_upload_media(api, text, topic, dry_run=True)
        return post_tweet(text, dry_run=True, media_ids=media_ids or None, handle=h or None)

    api = get_tweepy_api(handle=h or None)
    media_ids = get_and_upload_media(api, text, topic, dry_run=False)
    tid = post_tweet(text, dry_run=False, media_ids=media_ids or None, handle=h or None)
    if tid:
        _increment_today_post_count(handle=h or None)
        _log_post(text, tweet_id=tid, dry_run=False, handle=h or None)
    return tid


def get_mentions(api: tweepy.API, since_id: Optional[str] = None) -> List[dict]:
    """Fetch recent mentions (simplified; uses v1.1 endpoint)."""
    try:
        kwargs = {"count": 20}
        if since_id:
            kwargs["since_id"] = since_id
        mentions = api.mentions_timeline(**kwargs)
        return [
            {"id": str(m.id), "text": m.text, "user": m.user.screen_name, "id_str": m.id_str}
            for m in mentions
        ]
    except tweepy.TweepyException as e:
        logger.error("Failed to get mentions: %s", e)
        return []


def reply_to_mention(
    api: tweepy.API,
    mention_id: str,
    reply_text: str,
    dry_run: bool = False,
) -> bool:
    """Reply to a mention by id."""
    if dry_run:
        logger.info("[DRY RUN] Would reply to %s: %s", mention_id, reply_text[:50])
        return True
    try:
        api.update_status(status=reply_text, in_reply_to_status_id=mention_id)
        _random_delay()
        return True
    except tweepy.TweepyException as e:
        logger.error("Reply failed: %s", e)
        return False


def like_and_retweet_by_keywords(
    api: tweepy.API,
    keywords: List[str],
    count: int = 10,
    dry_run: bool = False,
) -> int:
    """
    Search recent tweets by keywords (v1.1 search), like and retweet up to count.
    Returns number of actions taken.
    """
    if not keywords:
        return 0
    query = " OR ".join(keywords[:5])
    try:
        tweets = api.search_tweets(q=query, count=min(count, 15), result_type="recent")
    except tweepy.TweepyException as e:
        logger.error("Search failed: %s", e)
        return 0
    acted = 0
    for t in tweets:
        if acted >= count:
            break
        try:
            if not t.favorited:
                if not dry_run:
                    api.create_favorite(t.id)
                acted += 1
                _random_delay()
            if not t.retweeted and acted < count:
                if not dry_run:
                    api.retweet(t.id)
                acted += 1
                _random_delay()
        except tweepy.TweepyException as e:
            logger.debug("Skip like/rt: %s", e)
    return acted


def run_scheduled_post(
    topic: Optional[str] = None,
    profile_path: Optional[Path] = None,
    dry_run: bool = False,
    handle: Optional[str] = None,
) -> None:
    """Job entry point for scheduler: generate and post one tweet."""
    post_generated_tweet(
        topic=topic, dry_run=dry_run, profile_path=profile_path, handle=handle
    )


def run_mentions_reply_job(
    reply_generator: Optional[Callable[[dict], str]] = None,
    dry_run: bool = False,
    handle: Optional[str] = None,
) -> None:
    """
    Fetch mentions and reply using reply_generator(mention) -> text.
    If reply_generator is None, does not reply (only logs).
    """
    api = get_tweepy_api(handle=handle)
    mentions = get_mentions(api)
    for m in mentions:
        if not reply_generator:
            logger.info("Mention: %s from @%s", m["text"][:50], m["user"])
            continue
        reply_text = reply_generator(m)
        if reply_text and len(reply_text) <= 280:
            reply_to_mention(api, m["id_str"], reply_text, dry_run=dry_run)
        _random_delay()


def run_like_retweet_job(
    keywords: List[str],
    count: int = 5,
    dry_run: bool = False,
    handle: Optional[str] = None,
) -> None:
    """Like/retweet recent tweets matching keywords."""
    api = get_tweepy_api(handle=handle)
    like_and_retweet_by_keywords(api, keywords, count=count, dry_run=dry_run)


def schedule_posts(
    topic: Optional[str] = None,
    interval_hours: float = 24,
    profile_path: Optional[Path] = None,
    dry_run: bool = False,
    handle: Optional[str] = None,
) -> "APScheduler":
    """
    Start APScheduler to post generated tweets on an interval.
    Returns the scheduler instance so caller can shutdown.
    """
    from apscheduler.schedulers.blocking import BlockingScheduler

    scheduler = BlockingScheduler()
    interval_sec = max(MIN_POST_INTERVAL_SEC, int(interval_hours * 3600))
    scheduler.add_job(
        run_scheduled_post,
        "interval",
        seconds=interval_sec,
        id="style_post",
        kwargs={
            "topic": topic,
            "profile_path": profile_path,
            "dry_run": dry_run,
            "handle": handle,
        },
    )
    logger.info("Scheduled post every %s sec (topic=%s)", interval_sec, topic)
    return scheduler
