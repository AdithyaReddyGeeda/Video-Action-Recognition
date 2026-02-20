"""
Configuration loader for Twitter Style Automator.
Uses environment variables via python-dotenv; no secrets in code.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project directory
_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(_env_path)


def get_env(key: str, default: str = "") -> str:
    """Get environment variable with optional default."""
    return os.getenv(key, default).strip()


# X (Twitter) API
X_API_KEY = get_env("X_API_KEY")
X_API_SECRET = get_env("X_API_SECRET")
X_ACCESS_TOKEN = get_env("X_ACCESS_TOKEN")
X_ACCESS_TOKEN_SECRET = get_env("X_ACCESS_TOKEN_SECRET")
X_BEARER_TOKEN = get_env("X_BEARER_TOKEN")

# AI provider: "openai" or "anthropic" (Claude)
AI_PROVIDER = get_env("AI_PROVIDER", "anthropic").lower()
if AI_PROVIDER not in ("openai", "anthropic"):
    AI_PROVIDER = "anthropic"
OPENAI_API_KEY = get_env("OPENAI_API_KEY")
ANTHROPIC_API_KEY = get_env("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = get_env("ANTHROPIC_MODEL", "claude-3-5-haiku-20241022")

# Target handle (without @)
X_HANDLE = get_env("X_HANDLE", "mcisaul_").lstrip("@")

# Paths
PROJECT_DIR = Path(__file__).resolve().parent
DB_PATH = PROJECT_DIR / "tweets.db"
STYLE_PROFILE_PATH = PROJECT_DIR / "style_profile.json"

# Delays (seconds) for human-like behavior
MIN_DELAY_SEC = int(get_env("MIN_DELAY_SEC", "30"))
MAX_DELAY_SEC = int(get_env("MAX_DELAY_SEC", "120"))

# Autonomous posting safeguards
MAX_POSTS_PER_DAY = int(get_env("MAX_POSTS_PER_DAY", "5"))
ENABLE_SAFETY_CHECK = get_env("ENABLE_SAFETY_CHECK", "true").lower() in ("true", "1", "yes")
# Comma-separated words/phrases that will block a tweet if present (case-insensitive)
BLOCKLIST = [w.strip().lower() for w in get_env("BLOCKLIST", "").split(",") if w.strip()]
POST_LOG_PATH = PROJECT_DIR / "posted_tweets.log"
POST_COUNT_FILE = PROJECT_DIR / "post_count_date.txt"
