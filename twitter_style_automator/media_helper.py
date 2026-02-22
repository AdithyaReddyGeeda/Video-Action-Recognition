"""
Media helper: get relevant image/video for a tweet and upload to Twitter.
- Image: AI-generated (DALL·E), from folder (AI pick), or from Twitter search (scrape & reuse).
- Video: from folder (AI pick) or from Twitter search (scrape & reuse).
Twitter allows 1 video OR up to 4 images per tweet; we use 1 image or 1 video per tweet.
Reusing media from Twitter may have copyright/ToS implications; use responsibly.
"""

import logging
import tempfile
from pathlib import Path
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

# Supported extensions
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm"}


def _pick_from_folder_with_ai(
    tweet_text: str,
    topic: Optional[str],
    folder_path: str,
    extensions: set,
    file_kind: str,
) -> Optional[Path]:
    """Use AI to pick the most relevant file from folder for this tweet."""
    from ai_client import chat

    folder = Path(folder_path).expanduser().resolve()
    if not folder.is_dir():
        logger.warning("Media folder is not a directory: %s", folder)
        return None
    files = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in extensions]
    if not files:
        logger.warning("No %s files in %s", file_kind, folder)
        return None
    # Build a list of filenames (no path) for the prompt
    names = [f.name for f in files]
    prompt = (
        f"Tweet text: \"{tweet_text[:200]}\"\n"
        f"Topic: {topic or 'general'}\n"
        f"Which ONE filename below is most relevant to this tweet? Reply with only that exact filename, nothing else.\n"
        f"Filenames:\n" + "\n".join(names)
    )
    try:
        reply = chat(
            system="You reply with exactly one filename from the list, the best match for the tweet. No explanation.",
            user_content=prompt,
            max_tokens=100,
            temperature=0,
        )
        chosen = (reply or "").strip().strip('"')
        for f in files:
            if f.name == chosen:
                return f
        # Fallback: first file
        return files[0]
    except Exception as e:
        logger.warning("AI pick failed for %s: %s; using first file", file_kind, e)
        return files[0]


def _generate_image_with_ai(tweet_text: str, topic: Optional[str]) -> Optional[Path]:
    """Generate an image with OpenAI DALL·E that matches the tweet/topic."""
    from openai import OpenAI
    from config import OPENAI_API_KEY, OPENAI_IMAGE_MODEL

    if not OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY required for AI image; skipping image.")
        return None
    prompt = f"Create a single, shareable image suitable for a tweet. Tweet theme: {topic or 'general'}. Tweet text: {tweet_text[:150]}. Style: clear, engaging, no text overlay."
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        resp = client.images.generate(
            model=OPENAI_IMAGE_MODEL,
            prompt=prompt[:1000],
            size="1024x1024",
            n=1,
            response_format="url",
        )
        url = resp.data[0].url if resp.data else None
        if not url:
            return None
        import requests
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        suffix = ".png"
        f = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        f.write(r.content)
        f.close()
        return Path(f.name)
    except Exception as e:
        logger.warning("DALL·E image generation failed: %s", e)
        return None


def get_relevant_image(
    tweet_text: str,
    topic: Optional[str],
    dry_run: bool = False,
) -> Optional[Path]:
    """
    Return path to a relevant image for this tweet.
    - If IMAGE_SOURCE=ai: generate with DALL·E (skipped in dry_run to avoid cost).
    - If IMAGE_SOURCE=folder: pick from IMAGE_FOLDER_PATH using AI.
    - If IMAGE_SOURCE=twitter: search X for recent tweets with images, pick best with AI, download and reuse.
    """
    from config import ENABLE_IMAGE, IMAGE_SOURCE, IMAGE_FOLDER_PATH
    from twitter_media_search import get_media_from_twitter

    if not ENABLE_IMAGE:
        return None
    if IMAGE_SOURCE == "twitter":
        return get_media_from_twitter(tweet_text, topic, "photo", dry_run=dry_run)
    if IMAGE_SOURCE == "folder":
        if not IMAGE_FOLDER_PATH:
            logger.warning("IMAGE_FOLDER_PATH not set; skipping image.")
            return None
        return _pick_from_folder_with_ai(
            tweet_text, topic, IMAGE_FOLDER_PATH, IMAGE_EXT, "image"
        )
    if dry_run:
        logger.info("[DRY RUN] Would generate image with DALL·E (skipped to save cost).")
        return None
    return _generate_image_with_ai(tweet_text, topic)


def get_relevant_video(
    tweet_text: str,
    topic: Optional[str],
    dry_run: bool = False,
) -> Optional[Path]:
    """
    Return path to a relevant video for this tweet.
    - If VIDEO_SOURCE=folder: pick from VIDEO_FOLDER_PATH using AI.
    - If VIDEO_SOURCE=twitter: search X for recent tweets with video, pick best with AI, download and reuse.
    """
    from config import ENABLE_VIDEO, VIDEO_SOURCE, VIDEO_FOLDER_PATH
    from twitter_media_search import get_media_from_twitter

    if not ENABLE_VIDEO:
        return None
    if VIDEO_SOURCE == "twitter":
        return get_media_from_twitter(tweet_text, topic, "video", dry_run=dry_run)
    if not VIDEO_FOLDER_PATH:
        return None
    return _pick_from_folder_with_ai(
        tweet_text, topic, VIDEO_FOLDER_PATH, VIDEO_EXT, "video"
    )


def upload_media_to_twitter(api: Any, file_path: Path) -> Optional[str]:
    """
    Upload a media file (image or video) via Twitter v1.1 API. Returns media_id.
    """
    path = Path(file_path)
    if not path.is_file():
        return None
    try:
        media = api.media_upload(filename=str(path))
        return str(media.media_id)
    except Exception as e:
        logger.error("Media upload failed for %s: %s", path, e)
        return None


def get_and_upload_media(
    api: Any,
    tweet_text: str,
    topic: Optional[str],
    dry_run: bool = False,
) -> List[str]:
    """
    Get relevant image and/or video, upload to Twitter, return list of media_ids.
    Twitter: 1 video OR up to 4 images per tweet. We return at most 1 video or 1 image.
    """
    from config import ENABLE_VIDEO, ENABLE_IMAGE

    media_ids: List[str] = []
    temp_paths: List[Path] = []

    try:
        # Prefer video if enabled and we find one; else use image
        if ENABLE_VIDEO:
            video_path = get_relevant_video(tweet_text, topic, dry_run=dry_run)
            if video_path:
                temp_paths.append(video_path)
                if dry_run:
                    logger.info("[DRY RUN] Would attach video: %s", video_path.name)
                    return []
                mid = upload_media_to_twitter(api, video_path)
                if mid:
                    media_ids.append(mid)
                    return media_ids  # One video per tweet

        if ENABLE_IMAGE:
            image_path = get_relevant_image(tweet_text, topic, dry_run=dry_run)
            if image_path:
                temp_paths.append(image_path)
                if dry_run:
                    logger.info("[DRY RUN] Would attach image: %s", image_path.name)
                    return []
                mid = upload_media_to_twitter(api, image_path)
                if mid:
                    media_ids.append(mid)
    finally:
        # Clean up temp files (e.g. from DALL·E)
        for p in temp_paths:
            try:
                if str(p).startswith(tempfile.gettempdir()) and p.exists():
                    p.unlink()
            except Exception:
                pass

    return media_ids
