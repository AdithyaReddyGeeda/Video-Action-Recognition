"""
Configuration loader for Twitter Style Automator.
Uses environment variables via python-dotenv; no secrets in code.
"""

import os
from pathlib import Path
from typing import Optional

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

# AI provider: "openai", "anthropic" (Claude), or "ollama" (local)
AI_PROVIDER = get_env("AI_PROVIDER", "anthropic").lower()
if AI_PROVIDER not in ("openai", "anthropic", "ollama"):
    AI_PROVIDER = "anthropic"
OPENAI_API_KEY = get_env("OPENAI_API_KEY")
ANTHROPIC_API_KEY = get_env("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = get_env("ANTHROPIC_MODEL", "claude-3-5-haiku-20241022")
# Ollama (local): no API key needed
OLLAMA_BASE_URL = get_env("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = get_env("OLLAMA_MODEL", "llama3.2")

# Target handle (without @) – the one account you post as
X_HANDLE = get_env("X_HANDLE", "mcisaul_").lstrip("@")

# Learn from many, post as one: comma-separated usernames to fetch & analyze (Bearer only; no keys needed).
# Leave empty to use a single account (X_HANDLE) for both learning and posting.
SOURCE_HANDLES = [h.strip().lstrip("@") for h in get_env("SOURCE_HANDLES", "").split(",") if h.strip()]

# Paths
PROJECT_DIR = Path(__file__).resolve().parent
DB_PATH = PROJECT_DIR / "tweets.db"
STYLE_PROFILE_PATH = PROJECT_DIR / "style_profile.json"
STYLE_PROFILES_DIR = PROJECT_DIR / "style_profiles"
ACCOUNTS_FILE = PROJECT_DIR / "accounts.json"
# Combined style profile when using SOURCE_HANDLES (learn from many, post as one)
COMBINED_STYLE_PROFILE = STYLE_PROFILES_DIR / "combined.json"


def get_style_profile_path_for_handle(handle: str) -> Path:
    """Per-handle style profile path for multi-account. Fallback to single STYLE_PROFILE_PATH if one account."""
    h = (handle or "").strip().lstrip("@") or "default"
    return STYLE_PROFILES_DIR / f"{h}.json"


def get_post_count_file_for_handle(handle: str) -> Path:
    """Per-handle post count file for daily limit."""
    h = (handle or "").strip().lstrip("@") or "default"
    return PROJECT_DIR / f"post_count_{h}.txt"


def get_post_log_path_for_handle(handle: str) -> Path:
    """Per-handle post log for multi-account."""
    h = (handle or "").strip().lstrip("@") or "default"
    return PROJECT_DIR / f"post_log_{h}.txt"


def get_style_profile_for_posting(posting_handle: Optional[str] = None) -> Path:
    """
    Profile to use when generating/posting. If SOURCE_HANDLES is set and combined
    profile exists (learn-from-many, post-as-one), return that; else per-handle or default.
    """
    if SOURCE_HANDLES and COMBINED_STYLE_PROFILE.exists():
        return COMBINED_STYLE_PROFILE
    h = (posting_handle or X_HANDLE or "").strip().lstrip("@")
    return get_style_profile_path_for_handle(h) if h else STYLE_PROFILE_PATH

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

# Media (images and videos) for tweets
ENABLE_IMAGE = get_env("ENABLE_IMAGE", "false").lower() in ("true", "1", "yes")
IMAGE_SOURCE = get_env("IMAGE_SOURCE", "ai").lower()  # "ai" | "folder" | "twitter"
IMAGE_FOLDER_PATH = get_env("IMAGE_FOLDER_PATH", "")
ENABLE_VIDEO = get_env("ENABLE_VIDEO", "false").lower() in ("true", "1", "yes")
VIDEO_SOURCE = get_env("VIDEO_SOURCE", "folder").lower()  # "folder" | "twitter"
VIDEO_FOLDER_PATH = get_env("VIDEO_FOLDER_PATH", "")
# For AI image generation (OpenAI DALL·E); uses OPENAI_API_KEY
OPENAI_IMAGE_MODEL = get_env("OPENAI_IMAGE_MODEL", "dall-e-3")
