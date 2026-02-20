"""
Tweet fetcher module: fetches user timeline via X API v2 (Tweepy).
Handles pagination, rate limits, and stores tweets in SQLite.
"""

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Generator, List, Optional

import tweepy

from config import DB_PATH, X_BEARER_TOKEN, X_HANDLE

logger = logging.getLogger(__name__)

# API allows ~3200 tweets without archive; we respect rate limits
MAX_TWEETS_PER_REQUEST = 100
RATE_LIMIT_WAIT_SEC = 900  # 15 min if rate limited
RETRY_AFTER_ERROR_SEC = 60


def get_db_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Return a connection to the tweets SQLite database."""
    path = db_path or DB_PATH
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Optional[Path] = None) -> None:
    """Create tweets table if it does not exist."""
    conn = get_db_connection(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tweets (
                id TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                created_at TEXT,
                retweet_count INTEGER,
                like_count INTEGER,
                reply_count INTEGER,
                quote_count INTEGER,
                hashtags TEXT,
                mentions TEXT,
                raw_json TEXT
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tweets_created_at ON tweets(created_at)"
        )
        conn.commit()
    finally:
        conn.close()


def tweet_to_row(tweet: Any) -> tuple:
    """Convert Tweepy Tweet object to a row tuple for SQLite."""
    entities = getattr(tweet, "entities", None) or {}
    if isinstance(entities, dict):
        hashtags = json.dumps([h.get("tag", h) for h in entities.get("hashtags", [])])
        mentions = json.dumps(
            [m.get("username", m) for m in entities.get("mentions", [])]
        )
    else:
        hashtags = "[]"
        mentions = "[]"
    created = getattr(tweet, "created_at", None)
    if hasattr(created, "isoformat"):
        created = created.isoformat()
    raw = tweet._json if hasattr(tweet, "_json") else {}
    if not raw and hasattr(tweet, "data"):
        raw = tweet.data
    return (
        str(getattr(tweet, "id", "")),
        getattr(tweet, "text", "") or "",
        created,
        getattr(tweet, "public_metrics", None) or {},
        hashtags,
        mentions,
        json.dumps(raw) if raw else "",
    )


def _public_metrics_to_ints(metrics: dict) -> tuple:
    """Extract (retweet_count, like_count, reply_count, quote_count)."""
    return (
        int(metrics.get("retweet_count", 0)),
        int(metrics.get("like_count", 0)),
        int(metrics.get("reply_count", 0)),
        int(metrics.get("quote_count", 0)),
    )


def insert_tweet(conn: sqlite3.Connection, tweet: Any) -> None:
    """Insert or replace a single tweet row."""
    row = tweet_to_row(tweet)
    rt, like, reply, quote = _public_metrics_to_ints(row[3])
    conn.execute(
        """
        INSERT OR REPLACE INTO tweets (
            id, text, created_at, retweet_count, like_count,
            reply_count, quote_count, hashtags, mentions, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row[0],
            row[1],
            row[2],
            rt,
            like,
            reply,
            quote,
            row[4],
            row[5],
            row[6],
        ),
    )


def fetch_user_tweets(
    bearer_token: str,
    username: str,
    max_tweets: Optional[int] = 3200,
    db_path: Optional[Path] = None,
) -> int:
    """
    Fetch timeline for the given username using API v2 and store in SQLite.
    Returns count of tweets stored in this run.
    """
    if not bearer_token:
        raise ValueError("X_BEARER_TOKEN is required for fetching tweets")

    init_db(db_path)
    client = tweepy.Client(
        bearer_token=bearer_token,
        wait_on_rate_limit=True,
    )

    # Resolve username to user id
    try:
        user = client.get_user(username=username.lstrip("@"))
        if not user.data:
            raise ValueError(f"User not found: {username}")
        user_id = user.data.id
    except tweepy.TweepyException as e:
        logger.error("Failed to resolve user: %s", e)
        raise

    count = 0
    pagination_token = None

    while True:
        try:
            response = client.get_users_tweets(
                id=user_id,
                max_results=min(MAX_TWEETS_PER_REQUEST, max_tweets - count if max_tweets else MAX_TWEETS_PER_REQUEST),
                exclude=["replies", "retweets"],
                tweet_fields=["created_at", "public_metrics", "entities"],
                user_auth=False,
                pagination_token=pagination_token,
            )
        except tweepy.TooManyRequests:
            logger.warning("Rate limited; waiting %s sec", RATE_LIMIT_WAIT_SEC)
            time.sleep(RATE_LIMIT_WAIT_SEC)
            continue
        except tweepy.TweepyException as e:
            logger.error("API error: %s", e)
            time.sleep(RETRY_AFTER_ERROR_SEC)
            continue

        if not response.data:
            break

        conn = get_db_connection(db_path)
        try:
            for tweet in response.data:
                insert_tweet(conn, tweet)
                count += 1
                if max_tweets and count >= max_tweets:
                    break
            conn.commit()
        finally:
            conn.close()

        logger.info("Fetched %d tweets so far (batch size %d)", count, len(response.data))

        if max_tweets and count >= max_tweets:
            break

        meta = getattr(response, "meta", {}) or {}
        pagination_token = meta.get("next_token")
        if not pagination_token:
            break

        time.sleep(1)  # Gentle delay between pages

    return count


def get_all_tweets_from_db(
    db_path: Optional[Path] = None,
    limit: Optional[int] = None,
) -> List[dict]:
    """Read stored tweets from SQLite as list of dicts for analysis."""
    conn = get_db_connection(db_path)
    try:
        sql = "SELECT id, text, created_at, hashtags, mentions FROM tweets ORDER BY created_at DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        rows = conn.execute(sql).fetchall()
        return [
            {
                "id": r["id"],
                "text": r["text"],
                "created_at": r["created_at"],
                "hashtags": json.loads(r["hashtags"] or "[]"),
                "mentions": json.loads(r["mentions"] or "[]"),
            }
            for r in rows
        ]
    finally:
        conn.close()
