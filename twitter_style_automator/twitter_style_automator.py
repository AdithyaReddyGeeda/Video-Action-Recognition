#!/usr/bin/env python3
"""
Twitter Style Automator – main entry point.

Commands:
  run              Full automation: fetch + analyze if needed, then run scheduler (one command)
  fetch-tweets     Fetch user timeline and store in SQLite
  analyze-style    Analyze stored tweets with OpenAI and save style profile
  generate-tweet   Generate a tweet (optionally for a topic)
  post-tweet       Generate and post one tweet (use with cron for no long-running process)
  schedule-posts   Run scheduler to post on an interval (keeps running until Ctrl+C)
  reply-mentions   Fetch mentions and optionally reply (placeholder)
  like-retweet     Like/retweet tweets matching keywords

Usage:
  python twitter_style_automator.py fetch-tweets
  python twitter_style_automator.py analyze-style
  python twitter_style_automator.py generate-tweet --topic "space exploration"
  python twitter_style_automator.py post-tweet [--dry-run]
  python twitter_style_automator.py schedule-posts [--interval-hours 24] [--dry-run]
"""

import argparse
import logging
import sys
from pathlib import Path

from config import (
    DB_PATH,
    SOURCE_HANDLES,
    STYLE_PROFILE_PATH,
    X_HANDLE,
    get_style_profile_for_posting,
    get_style_profile_path_for_handle,
)
from poster import (
    get_tweepy_api,
    run_like_retweet_job,
    run_mentions_reply_job,
    schedule_posts,
)
from style_analyzer import analyze_style, analyze_style_combined, load_style_profile
from tweet_fetcher import fetch_user_tweets, get_all_tweets_from_db
from tweet_generator import generate_tweet, suggest_topics

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("automator")


def cmd_fetch_tweets(args: argparse.Namespace) -> int:
    """Fetch tweets for the configured handle (or all SOURCE_HANDLES if --all-sources) and store in DB."""
    from config import X_BEARER_TOKEN

    use_all_sources = getattr(args, "all_sources", False)
    if use_all_sources:
        if not SOURCE_HANDLES:
            logger.error("SOURCE_HANDLES is empty. Set SOURCE_HANDLES=user1,user2,... in .env for --all-sources.")
            return 1
        bearer = args.bearer_token or X_BEARER_TOKEN
        max_tweets = args.max_tweets or 3200
        total = 0
        try:
            for handle in SOURCE_HANDLES:
                count = fetch_user_tweets(
                    bearer_token=bearer,
                    username=handle,
                    max_tweets=max_tweets,
                    db_path=args.db,
                    store_handle=handle,
                )
                total += count
                logger.info("Fetched and stored %d tweets for @%s", count, handle)
            logger.info("Total: %d tweets from %d source accounts", total, len(SOURCE_HANDLES))
            return 0
        except Exception as e:
            logger.exception("Fetch failed: %s", e)
            return 1

    handle = args.handle or X_HANDLE
    max_tweets = args.max_tweets or 3200
    try:
        count = fetch_user_tweets(
            bearer_token=args.bearer_token or X_BEARER_TOKEN,
            username=handle,
            max_tweets=max_tweets,
            db_path=args.db,
            store_handle=handle,
        )
        logger.info("Fetched and stored %d tweets for @%s", count, handle)
        return 0
    except Exception as e:
        logger.exception("Fetch failed: %s", e)
        return 1


def cmd_analyze_style(args: argparse.Namespace) -> int:
    """Analyze stored tweets and write style profile (single handle or combined from SOURCE_HANDLES)."""
    use_combined = getattr(args, "combined", False)
    if use_combined:
        if not SOURCE_HANDLES:
            logger.error("SOURCE_HANDLES is empty. Set SOURCE_HANDLES=user1,user2,... in .env for --combined.")
            return 1
        try:
            profile = analyze_style_combined(
                handles=SOURCE_HANDLES,
                max_tweets_per_user=args.max_tweets or 200,
                db_path=args.db,
                profile_path=args.profile,
            )
            logger.info("Combined style profile saved. Topics: %s", profile.get("topics", []))
            return 0
        except Exception as e:
            logger.exception("Analyze failed: %s", e)
            return 1

    handle = args.handle or X_HANDLE
    try:
        profile = analyze_style(
            handle=handle,
            max_tweets=args.max_tweets or 200,
            db_path=args.db,
            profile_path=args.profile,
        )
        logger.info("Style profile saved. Topics: %s", profile.get("topics", []))
        return 0
    except Exception as e:
        logger.exception("Analyze failed: %s", e)
        return 1


def cmd_generate_tweet(args: argparse.Namespace) -> int:
    """Generate one tweet, optionally for a topic. Uses combined profile if SOURCE_HANDLES is set."""
    handle = args.handle or X_HANDLE
    profile_path = args.profile
    if profile_path == STYLE_PROFILE_PATH:
        profile_path = get_style_profile_for_posting(handle) or (get_style_profile_path_for_handle(handle) if handle else STYLE_PROFILE_PATH)
    topic = args.topic
    if not topic and args.suggest:
        suggestions = suggest_topics(profile_path)
        logger.info("Topic suggestions: %s", suggestions)
        topic = suggestions[0] if suggestions else None
    try:
        text = generate_tweet(
            topic=topic,
            profile_path=profile_path,
            extra_instructions=args.extra,
        )
        print(text)
        return 0
    except Exception as e:
        logger.exception("Generate failed: %s", e)
        return 1


def cmd_post_tweet(args: argparse.Namespace) -> int:
    """Generate a tweet, run safety checks, and post (no prompt)."""
    from poster import post_generated_tweet

    handle = getattr(args, "handle", None) or X_HANDLE
    topic = getattr(args, "topic", None) or None
    try:
        post_generated_tweet(
            topic=topic,
            dry_run=args.dry_run,
            profile_path=args.profile,
            confirm=False,
            handle=handle,
        )
        return 0
    except Exception as e:
        logger.exception("Post failed: %s", e)
        return 1


def cmd_schedule_posts(args: argparse.Namespace) -> int:
    """Run the posting scheduler (blocks). Posts automatically with safety checks."""
    handle = args.handle or X_HANDLE
    profile_path = args.profile
    if profile_path == STYLE_PROFILE_PATH:
        profile_path = get_style_profile_for_posting(handle) or (get_style_profile_path_for_handle(handle) if handle else STYLE_PROFILE_PATH)
    try:
        sched = schedule_posts(
            topic=getattr(args, "topic", None) or None,
            interval_hours=float(args.interval_hours or 24),
            profile_path=profile_path,
            dry_run=args.dry_run,
            handle=handle,
        )
        sched.start()
        return 0
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user")
        return 0
    except Exception as e:
        logger.exception("Scheduler failed: %s", e)
        return 1


def cmd_reply_mentions(args: argparse.Namespace) -> int:
    """Fetch mentions; optional reply generator not wired (placeholder)."""
    handle = args.handle or X_HANDLE
    try:
        run_mentions_reply_job(
            reply_generator=None, dry_run=args.dry_run, handle=handle
        )
        return 0
    except Exception as e:
        logger.exception("Mentions job failed: %s", e)
        return 1


def cmd_like_retweet(args: argparse.Namespace) -> int:
    """Like/retweet tweets matching given keywords."""
    keywords = getattr(args, "keywords", None) or []
    handle = args.handle or X_HANDLE
    try:
        run_like_retweet_job(
            keywords=keywords,
            count=args.count or 5,
            dry_run=args.dry_run,
            handle=handle,
        )
        return 0
    except Exception as e:
        logger.exception("Like/retweet failed: %s", e)
        return 1


def cmd_run(args: argparse.Namespace) -> int:
    """
    Full automation: ensure we have tweets and a style profile, then run the
    posting scheduler. If SOURCE_HANDLES is set, fetches all sources and builds
    combined profile; posts as X_HANDLE only.
    """
    from config import X_BEARER_TOKEN, COMBINED_STYLE_PROFILE
    from poster import schedule_posts

    db_path = args.db
    profile_path = args.profile
    handle = args.handle or X_HANDLE
    use_sources = bool(SOURCE_HANDLES)

    # 1. Fetch tweets
    if not getattr(args, "no_fetch", False):
        try:
            from datetime import datetime
            db_path_p = Path(db_path)
            db_mtime = db_path_p.stat().st_mtime if db_path_p.exists() else 0
            refresh_days = getattr(args, "refresh_days", 7)
            need_fetch = refresh_days <= 0 or not db_path_p.exists() or (
                (datetime.utcnow().timestamp() - db_mtime) > refresh_days * 86400
            )
            if use_sources:
                # Check we have tweets for at least one source
                any_tweets = False
                for h in SOURCE_HANDLES:
                    if get_all_tweets_from_db(db_path=db_path, limit=1, handle=h):
                        any_tweets = True
                        break
                need_fetch = need_fetch or not any_tweets
            else:
                tweets = get_all_tweets_from_db(db_path=db_path, limit=1, handle=handle)
                need_fetch = need_fetch or not tweets

            if need_fetch:
                if use_sources:
                    logger.info("Fetching tweets for %d source accounts...", len(SOURCE_HANDLES))
                    for h in SOURCE_HANDLES:
                        fetch_user_tweets(
                            bearer_token=X_BEARER_TOKEN,
                            username=h,
                            max_tweets=getattr(args, "max_tweets", 3200),
                            db_path=db_path,
                            store_handle=h,
                        )
                else:
                    logger.info("Fetching tweets for @%s...", handle)
                    fetch_user_tweets(
                        bearer_token=X_BEARER_TOKEN,
                        username=handle,
                        max_tweets=getattr(args, "max_tweets", 3200),
                        db_path=db_path,
                        store_handle=handle,
                    )
            else:
                logger.info("Tweets DB already has data and is recent; skipping fetch.")
        except Exception as e:
            logger.warning("Fetch step failed (continuing): %s", e)
    else:
        logger.info("Skipping fetch (--no-fetch).")

    # 2. Analyze style (combined or single)
    if not getattr(args, "no_analyze", False):
        try:
            if use_sources:
                profile_path_p = Path(profile_path) if profile_path != STYLE_PROFILE_PATH else COMBINED_STYLE_PROFILE
                profile_exists = profile_path_p.exists()
                db_path_p = Path(db_path)
                db_newer = profile_exists and db_path_p.exists() and db_path_p.stat().st_mtime > profile_path_p.stat().st_mtime
                if not profile_exists or db_newer:
                    logger.info("Building combined style profile from %d sources...", len(SOURCE_HANDLES))
                    analyze_style_combined(
                        handles=SOURCE_HANDLES,
                        max_tweets_per_user=200,
                        db_path=db_path,
                        profile_path=profile_path_p,
                    )
                else:
                    logger.info("Combined style profile exists and is current; skipping analyze.")
            else:
                profile_path_resolved = get_style_profile_path_for_handle(handle) if (handle and profile_path == STYLE_PROFILE_PATH) else profile_path
                profile_path_p = Path(profile_path_resolved)
                db_path_p = Path(db_path)
                profile_exists = profile_path_p.exists()
                db_newer = db_path_p.exists() and profile_path_p.exists() and db_path_p.stat().st_mtime > profile_path_p.stat().st_mtime
                if not profile_exists or db_newer:
                    logger.info("Building or updating style profile...")
                    analyze_style(handle=handle, max_tweets=200, db_path=db_path, profile_path=profile_path_p)
                else:
                    logger.info("Style profile exists and is current; skipping analyze.")
        except Exception as e:
            logger.warning("Analyze step failed (continuing): %s", e)
    else:
        logger.info("Skipping analyze (--no-analyze).")

    # 3. Run the posting scheduler (blocks until Ctrl+C). Post as handle only.
    profile_path_sched = get_style_profile_for_posting(handle) if profile_path == STYLE_PROFILE_PATH else profile_path
    logger.info("Starting posting scheduler (interval: %s hours). Stop with Ctrl+C.", args.interval_hours)
    try:
        sched = schedule_posts(
            topic=getattr(args, "topic", None) or None,
            interval_hours=float(args.interval_hours or 24),
            profile_path=profile_path_sched,
            dry_run=args.dry_run,
            handle=handle,
        )
        sched.start()
        return 0
    except KeyboardInterrupt:
        logger.info("Stopped by user.")
        return 0
    except Exception as e:
        logger.exception("Scheduler failed: %s", e)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Twitter Style Automator – fetch, analyze, generate, post.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DB_PATH,
        help="Path to SQLite DB for tweets",
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=STYLE_PROFILE_PATH,
        help="Path to style profile JSON",
    )
    parser.add_argument(
        "--handle",
        default=X_HANDLE,
        help="X handle (without @) to analyze/post as",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not post or like/retweet; only log",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # run (full flow: fetch + analyze + scheduler)
    p_run = subparsers.add_parser(
        "run",
        help="Full automation: fetch/analyze if needed, then run posting scheduler",
    )
    p_run.add_argument("--interval-hours", type=float, default=24)
    p_run.add_argument("--topic", "-t", type=str, help="Default topic for scheduled tweets")
    p_run.add_argument("--no-fetch", action="store_true", help="Skip fetch step (use existing DB)")
    p_run.add_argument("--no-analyze", action="store_true", help="Skip analyze step (use existing profile)")
    p_run.add_argument("--refresh-days", type=int, default=7, help="Re-fetch tweets if DB older than N days (0=always use existing)")
    p_run.add_argument("--max-tweets", type=int, default=3200)
    p_run.set_defaults(run=cmd_run)

    # fetch-tweets
    p_fetch = subparsers.add_parser("fetch-tweets", help="Fetch user timeline(s) into DB")
    p_fetch.add_argument("--max-tweets", type=int, default=3200)
    p_fetch.add_argument("--bearer-token", default=None, help="Override X_BEARER_TOKEN")
    p_fetch.add_argument("--all-sources", action="store_true", help="Fetch all SOURCE_HANDLES (learn from many; only Bearer token needed)")
    p_fetch.set_defaults(run=cmd_fetch_tweets)

    # analyze-style
    p_analyze = subparsers.add_parser("analyze-style", help="Analyze tweets and build style profile (single or combined)")
    p_analyze.add_argument("--max-tweets", type=int, default=200)
    p_analyze.add_argument("--combined", action="store_true", help="Build one blended profile from all SOURCE_HANDLES (learn from many, post as one)")
    p_analyze.set_defaults(run=cmd_analyze_style)

    # generate-tweet
    p_gen = subparsers.add_parser("generate-tweet", help="Generate one tweet (print only)")
    p_gen.add_argument("--topic", "-t", type=str, help="Topic for the tweet")
    p_gen.add_argument("--suggest", action="store_true", help="Use first suggested topic")
    p_gen.add_argument("--extra", type=str, help="Extra instructions for generation")
    p_gen.set_defaults(run=cmd_generate_tweet)

    # Subparsers need a parent with --dry-run so "post-tweet --dry-run" works (argparse parses rest with subparser)
    _dry_run_parent = argparse.ArgumentParser(add_help=False)
    _dry_run_parent.add_argument("--dry-run", action="store_true", help="Do not post; only generate and log")

    # post-tweet
    p_post = subparsers.add_parser("post-tweet", parents=[_dry_run_parent], help="Generate, safety-check, and post one tweet (no prompt)")
    p_post.add_argument("--topic", "-t", type=str, help="Topic for the tweet")
    p_post.set_defaults(run=cmd_post_tweet)

    # schedule-posts
    p_sched = subparsers.add_parser("schedule-posts", parents=[_dry_run_parent], help="Run scheduler to post on interval (fully automatic)")
    p_sched.add_argument("--interval-hours", type=float, default=24)
    p_sched.add_argument("--topic", "-t", type=str, help="Default topic for scheduled tweets")
    p_sched.set_defaults(run=cmd_schedule_posts)

    # reply-mentions
    p_mentions = subparsers.add_parser("reply-mentions", parents=[_dry_run_parent], help="Fetch and log mentions")
    p_mentions.set_defaults(run=cmd_reply_mentions)

    # like-retweet
    p_rt = subparsers.add_parser("like-retweet", parents=[_dry_run_parent], help="Like/retweet by keywords")
    p_rt.add_argument("--keywords", "-k", nargs="+", required=True, help="Keywords to search")
    p_rt.add_argument("--count", type=int, default=5)
    p_rt.set_defaults(run=cmd_like_retweet)

    args = parser.parse_args()
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
