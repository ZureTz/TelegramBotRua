import html
import json
import logging
import time
from typing import Any
from telebot import types
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

APPVIEW_BASE_URL = "https://public.api.bsky.app"
AUTHOR_FEED_ENDPOINT = "/xrpc/app.bsky.feed.getAuthorFeed"

logger = logging.getLogger(__name__)


class BskyRateLimitError(RuntimeError):
    pass


def poll_latest_posts(
    bot,
    handle: str,
    chat_ids: list[str],
    interval_seconds: int,
) -> None:
    last_seen_uri = None

    while True:
        try:
            posts = fetch_latest_posts(handle)
            if not posts:
                logger.debug("No posts found for bsky handle %s", handle)
            elif last_seen_uri is None:
                last_seen_uri = posts[0]["uri"]
                logger.info("Initialized bsky poller for %s at %s", handle, last_seen_uri)
            else:
                new_posts = []
                for post in posts:
                    if post["uri"] == last_seen_uri:
                        break
                    new_posts.append(post)

                if new_posts:
                    for post in reversed(new_posts):
                        forward_post(bot, chat_ids, post)
                        logger.info("Forwarded bsky post %s to %s", post["uri"], chat_ids)
                    last_seen_uri = new_posts[0]["uri"]
        except BskyRateLimitError as exc:
            logger.warning("Bsky rate limited for %s: %s", handle, exc)
        except Exception as exc:
            logger.error("Bsky polling failed for %s: %s", handle, exc)

        time.sleep(interval_seconds)


def fetch_latest_posts(handle: str, limit: int = 10) -> list[dict[str, Any]]:
    query = urlencode(
        {
            "actor": handle,
            "filter": "posts_no_replies",
            "limit": str(limit),
        }
    )
    url = f"{APPVIEW_BASE_URL}{AUTHOR_FEED_ENDPOINT}?{query}"
    response_data = fetch_json(url)

    posts = []
    for item in response_data.get("feed", []):
        if item.get("reason"):
            continue

        post = item.get("post") or {}
        record = post.get("record") or {}
        uri = post.get("uri")

        if not uri:
            continue

        if record.get("reply"):
            continue

        embed = post.get("embed")
        if not is_supported_embed(embed):
            logger.info("Skipped unsupported bsky post %s", uri)
            continue

        posts.append(
            {
                "uri": uri,
                "text": record.get("text", ""),
                "images": extract_image_urls(embed),
            }
        )

    return posts


def fetch_json(url: str) -> dict[str, Any]:
    try:
        with urlopen(url, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 429:
            raise BskyRateLimitError("HTTP 429 from bsky API") from exc
        raise RuntimeError(f"HTTP {exc.code} from bsky API") from exc
    except URLError as exc:
        raise RuntimeError(f"Network error calling bsky API: {exc.reason}") from exc


def extract_image_urls(embed: dict[str, Any] | None) -> list[str]:
    if not embed:
        return []

    embed_type = embed.get("$type", "")
    if embed_type.startswith("app.bsky.embed.images"):
        return [
            image["fullsize"]
            for image in embed.get("images", [])
            if image.get("fullsize")
        ]

    if embed_type.startswith("app.bsky.embed.recordWithMedia"):
        return extract_image_urls(embed.get("media"))

    return []


def is_supported_embed(embed: dict[str, Any] | None) -> bool:
    if not embed:
        return True

    embed_type = embed.get("$type", "")
    if embed_type.startswith("app.bsky.embed.images"):
        return True

    return False


def forward_post(bot, chat_ids: list[str], post: dict[str, Any]) -> None:
    text = html.unescape((post.get("text") or "").strip())
    images = post.get("images") or []

    for chat_id in chat_ids:
        if images:
            send_images(bot, chat_id, images, text)
        elif text:
            bot.send_message(chat_id, text)
        else:
            logger.info("Skipped empty bsky post %s for %s", post["uri"], chat_id)


def send_images(bot, chat_id: str, images: list[str], caption: str) -> None:
    if len(images) == 1:
        bot.send_photo(chat_id, images[0], caption=caption or None)
        return

    media = []
    for index, image_url in enumerate(images):
        if index == 0 and caption:
            media.append(types.InputMediaPhoto(image_url, caption=caption))
        else:
            media.append(types.InputMediaPhoto(image_url))

    bot.send_media_group(chat_id, media)
