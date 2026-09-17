import re
from urllib.parse import urlsplit
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

import httpx
from bs4 import BeautifulSoup

from help_me_tibooo.models import Post, ResetSourceKind, SourceBatch, SourceName


RESET_FEED_URL = "https://codex-reset.com/api/feed"
TWISCAN_TIMELINE_URL = "https://twiscan.com/en/x/thsottiaux"
PUBLIC_RESETS_URL = "https://codex-resets.com/api/v1/resets"
POST_ID_PATTERN = re.compile(r"^clamp-(\d{1,20})-(\d{1,20})$")
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
            and post_id.isascii()
            and post_id.isdigit()
            and 1 <= len(post_id) <= 20
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
        try:
            source_kind = ResetSourceKind(kind) if isinstance(kind, str) else None
        except ValueError:
            source_kind = None
        posts.append(
            Post(
                id=post_id,
                text=text,
                created_at=created_at,
                url=url,
                source=SourceName.RESET,
                is_reply=tweet.get("is_reply") is True,
                source_kind=source_kind,
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
                source=SourceName.TWISCAN,
                is_repost=repost_id != "0",
            )
        )

    return tuple(posts)


def fetch_all_sources(client: httpx.Client) -> tuple[SourceBatch, ...]:
    reset, twiscan = fetch_timeline_sources(client)
    latest = _fetch_source(
        client, SourceName.RESET, "https://codex-reset.com/tibo",
        lambda content: parse_tibo_html(content.decode()),
    )
    if latest.error is None:
        posts = {post.id: post for post in reset.posts}
        for post in latest.posts:
            posts.setdefault(post.id, post)
        reset = SourceBatch(SourceName.RESET, posts=tuple(posts.values()))
    else:
        reset = latest
    return (reset, twiscan, _fetch_public_resets(client))


def parse_tibo_html(html: str) -> tuple[Post, ...]:
    soup = BeautifulSoup(html, "html.parser")
    posts: dict[str, Post] = {}
    items = soup.select("#feed-list .feed-item")
    if not items:
        raise ValueError("missing Tibo timeline")
    for item in items:
        link = item.select_one("a.feed-time[href]")
        body = item.select_one(".feed-text")
        match = re.fullmatch(r"https://x\.com/thsottiaux/status/([0-9]{1,20})", link.get("href", "")) if link else None
        if match is None or body is None or not body.get_text(strip=True):
            raise ValueError("invalid Tibo post")
        post_id = match[1]
        text = body.get_text("\n", strip=True)
        try:
            kind = ResetSourceKind(item.get("data-kind"))
        except ValueError:
            kind = None
        posts[post_id] = Post(
            id=post_id, text=text,
            created_at=datetime.fromtimestamp(((int(post_id) >> 22) + 1288834974657) / 1000, UTC),
            url=link["href"], source=SourceName.RESET,
            is_reply=text.startswith("@"), source_kind=kind,
        )
    return tuple(posts.values())


def fetch_timeline_sources(client: httpx.Client) -> tuple[SourceBatch, ...]:
    return (
        _fetch_source(client, SourceName.RESET, RESET_FEED_URL, _decode_reset_feed),
        _fetch_source(client, SourceName.TWISCAN, TWISCAN_TIMELINE_URL, _decode_twiscan_timeline),
    )


def collection_status(batches: tuple[SourceBatch, ...]) -> str:
    timeline_ok = any(batch.error is None and batch.posts and batch.source in {SourceName.RESET, SourceName.TWISCAN} for batch in batches)
    resets_ok = any(batch.error is None and batch.source == SourceName.RESETS for batch in batches)
    if timeline_ok:
        return "수집 정상"
    if resets_ok:
        return "부분 장애 · 리셋 감시 정상 · 전체 소식 감시 불가"
    return "수집 실패"


def outage_signature(batches: tuple[SourceBatch, ...]) -> str | None:
    status = collection_status(batches)
    if status == "수집 정상":
        return None
    prefix = "partial" if status.startswith("부분 장애") else "total"
    failures = []
    for batch in sorted(batches, key=lambda batch: batch.source):
        if batch.error is None and (batch.posts or batch.source == SourceName.RESETS):
            continue
        error = batch.error or "empty response"
        if error not in {"request timed out", "request failed", "invalid response", "response exceeds 2 MiB", "empty response"} and re.fullmatch(r"HTTP status [0-9]{3}", error) is None:
            error = "unknown error"
        failures.append(f"{batch.source}:{error}")
    return prefix + "|" + "|".join(failures)


def _fetch_public_resets(client: httpx.Client) -> SourceBatch:
    posts: dict[str, Post] = {}
    cursor: str | None = None
    seen_cursors: set[str] = set()
    for _ in range(10):
        next_cursor: str | None = None

        def decode(content: bytes) -> tuple[Post, ...]:
            nonlocal next_cursor
            payload = httpx.Response(200, content=content).json()
            if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), list):
                raise ValueError("invalid resets")
            pagination = payload.get("pagination")
            if not isinstance(pagination, Mapping) or not isinstance(pagination.get("has_more"), bool):
                raise ValueError("invalid pagination")
            if pagination["has_more"]:
                value = pagination.get("next_cursor")
                if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,1024}", value):
                    raise ValueError("invalid cursor")
                next_cursor = value
            result = []
            for item in payload["data"]:
                if not isinstance(item, Mapping) or item.get("reset_type") not in ("regular", "banked"):
                    raise ValueError("invalid reset")
                source = item.get("source")
                post_id, text, at = item.get("id"), item.get("text"), item.get("announced_at")
                if not isinstance(source, Mapping) or source.get("type") not in ("x_post", "observed"):
                    raise ValueError("invalid source")
                if not isinstance(post_id, str) or not re.fullmatch(r"(?:[0-9]{1,20}|observed-[A-Za-z0-9_-]{1,55})", post_id) or not isinstance(text, str) or not text or not isinstance(at, str):
                    raise ValueError("invalid reset")
                created_at = datetime.fromisoformat(at.replace("Z", "+00:00"))
                if created_at.tzinfo is None:
                    raise ValueError("invalid date")
                url = source.get("url")
                if isinstance(url, str):
                    parsed = urlsplit(url)
                    match = re.fullmatch(r"/thsottiaux/status/([0-9]{1,20})", parsed.path)
                    if parsed.scheme != "https" or parsed.hostname != "x.com" or not match or parsed.query or parsed.fragment:
                        raise ValueError("invalid source URL")
                    if source["type"] == "x_post" and (source.get("author") != "thsottiaux" or match[1] != post_id):
                        raise ValueError("invalid author")
                    post_id = match[1]
                elif source["type"] == "observed":
                    if not post_id.startswith("observed-"):
                        raise ValueError("invalid observed ID")
                    url = "https://codex-resets.com/"
                else:
                    raise ValueError("missing source URL")
                result.append(Post(post_id, text, created_at, url, SourceName.RESETS,
                                   source_kind=ResetSourceKind.BANKED if item["reset_type"] == "banked" else ResetSourceKind.ANNOUNCEMENT))
            return tuple(result)

        url = str(httpx.URL(PUBLIC_RESETS_URL, params={"limit": "100", **({"cursor": cursor} if cursor else {})}))
        batch = _fetch_source(client, SourceName.RESETS, url, decode)
        if batch.error:
            return batch
        posts.update((post.id, post) for post in batch.posts)
        if next_cursor is None:
            if not posts:
                return SourceBatch(SourceName.RESETS, error="invalid response")
            return SourceBatch(SourceName.RESETS, tuple(posts.values()))
        if next_cursor in seen_cursors:
            return SourceBatch(SourceName.RESETS, error="invalid response")
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    return SourceBatch(SourceName.RESETS, error="invalid response")


def _fetch_source(
    client: httpx.Client,
    source: SourceName,
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
            if not 200 <= response.status_code < 300:
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
    payload = httpx.Response(200, content=content).json()
    if not isinstance(payload, Mapping):
        raise ValueError("invalid reset feed")
    tweets = payload.get("tweets")
    if not isinstance(tweets, list):
        raise ValueError("invalid reset feed")
    posts = parse_reset_feed(payload)
    if tweets and not posts:
        raise ValueError("invalid reset feed")
    return posts


def _decode_twiscan_timeline(content: bytes) -> tuple[Post, ...]:
    html = content.decode()
    soup = BeautifulSoup(html, "html.parser")
    candidates = soup.select("div[id^='clamp-']")
    posts = parse_twiscan_html(html)
    if candidates:
        if not posts:
            raise ValueError("invalid TwiScan timeline")
        return posts
    if soup.select_one("#timeline") is not None:
        return ()
    raise ValueError("invalid TwiScan timeline")
