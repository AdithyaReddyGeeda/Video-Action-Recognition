"""
Multi-account credentials: load per-handle access tokens from accounts.json.
Fallback: use .env X_ACCESS_TOKEN and X_ACCESS_TOKEN_SECRET for default X_HANDLE.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from config import ACCOUNTS_FILE, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET, X_HANDLE

logger = logging.getLogger(__name__)


def load_accounts() -> Dict[str, Dict[str, str]]:
    """Load { handle: { access_token, access_token_secret } } from accounts.json. Empty dict if missing."""
    path = Path(ACCOUNTS_FILE)
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning("Could not load accounts.json: %s", e)
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for handle, creds in data.items():
        h = str(handle).strip().lstrip("@")
        if isinstance(creds, dict) and creds.get("access_token") and creds.get("access_token_secret"):
            out[h] = {
                "access_token": str(creds["access_token"]).strip(),
                "access_token_secret": str(creds["access_token_secret"]).strip(),
            }
    return out


def get_credentials_for_handle(
    handle: Optional[str],
    api_key: str,
    api_secret: str,
) -> tuple:
    """
    Return (access_token, access_token_secret) for the given handle.
    Uses accounts.json if present; else .env for default X_HANDLE.
    """
    h = (handle or "").strip().lstrip("@") or (X_HANDLE or "").strip().lstrip("@")
    accounts = load_accounts()
    if h and h in accounts:
        return accounts[h]["access_token"], accounts[h]["access_token_secret"]
    if X_ACCESS_TOKEN and X_ACCESS_TOKEN_SECRET:
        return X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET
    raise ValueError(
        f"No credentials for handle '{handle or X_HANDLE}'. "
        "Add them to accounts.json or set X_ACCESS_TOKEN and X_ACCESS_TOKEN_SECRET in .env"
    )
