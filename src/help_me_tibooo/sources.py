import re
from collections.abc import Callable, Mapping
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from help_me_tibooo.models import Post, SourceBatch


RESET_FEED_URL = "https://codex-reset.com/api/feed"
TWISCAN_TIMELINE_URL = "https://twiscan.com/en/x/thsottiaux"
POST_ID_PATTERN = re.compile(r"^clamp-(\d+)-(\d+)$")
RESPONSE_LIMIT_BYTES = 2 * 1024 * 1024


def parse_reset_feed(payload: object) -> tuple[Post, ...]:
    if not isinstance(payload, Mapping):
        return ()

    tweets = payload.get("tweets")
    if not isinstance(tweets, list):
        return ()

    posts: list[Post] = []
    for tweet in tweets:
        if not isinstance(tweet, Mapping):
            continue

        post_id = tweet.get("id")
        text = tweet.get("text")
        posted_at = tweet.get("at")
        url = tweet.get("url")
        if not (
            isinstance(post_id, str)
            and post_id.isdigit()
            and isinstance(text, str)
            and text
            and isinstance(posted_at, str)
            and isinstance(url, str)
            and url
        ):
            continue

        try:
            created_at = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if created_at.tzinfo is None:
            continue

        kind = tweet.get("kind")
        posts.append(
            Post(
                id=post_id,
                text=text,
                created_at=created_at,
                url=url,
                source="reset",
                is_reply=tweet.get("is_reply") is True,
                source_kind=kind if isinstance(kind, str) else None,
            )
        )

    return tuple(posts)


def parse_twiscan_html(html: str) -> tuple[Post, ...]:
    soup = BeautifulSoup(html, "html.parser")
    posts: list[Post] = []
    for element in soup.select("div[id^='clamp-']"):
        match = POST_ID_PATTERN.fullmatch(element.get("id", ""))
        if match is None:
            continue

        post_id, repost_id = match.groups()
        text = element.get_text(" ", strip=True)
        if not text:
            continue
        posts.append(
            Post(
                id=post_id,
                text=text,
                created_at=None,
                url=f"https://x.com/thsottiaux/status/{post_id}",
                source="twiscan",
                is_repost=repost_id != "0",
            )
        )

    return tuple(posts)


def fetch_all_sources(client: httpx.Client) -> tuple[SourceBatch, ...]:
    return (
        _fetch_source(client, "reset", RESET_FEED_URL, _decode_reset_feed),
        _fetch_source(client, "twiscan", TWISCAN_TIMELINE_URL, _decode_twiscan_timeline),
    )


def _fetch_source(
    client: httpx.Client,
    source: str,
    url: str,
    parser: Callable[[bytes], tuple[Post, ...]],
) -> SourceBatch:
    try:
        with client.stream(
            "GET",
            url,
            headers={"User-Agent": "help-me-tibooo/0.1"},
            timeout=15.0,
        ) as response:
            if response.status_code >= 400:
                return SourceBatch(source=source, error=f"HTTP status {response.status_code}")
            content_length = response.headers.get("Content-Length")
            if content_length is not None and content_length.isdigit() and int(content_length) > RESPONSE_LIMIT_BYTES:
                return SourceBatch(source=source, error="response exceeds 2 MiB")

            content = bytearray()
            for chunk in response.iter_bytes():
                if len(content) + len(chunk) > RESPONSE_LIMIT_BYTES:
                    return SourceBatch(source=source, error="response exceeds 2 MiB")
                content.extend(chunk)
        return SourceBatch(source=source, posts=parser(bytes(content)))
    except httpx.TimeoutException:
        return SourceBatch(source=source, error="request timed out")
    except httpx.HTTPError:
        return SourceBatch(source=source, error="request failed")
    except (UnicodeDecodeError, ValueError):
        return SourceBatch(source=source, error="invalid response")


def _decode_reset_feed(content: bytes) -> tuple[Post, ...]:
    return parse_reset_feed(httpx.Response(200, content=content).json())


def _decode_twiscan_timeline(content: bytes) -> tuple[Post, ...]:
    return parse_twiscan_html(content.decode())
