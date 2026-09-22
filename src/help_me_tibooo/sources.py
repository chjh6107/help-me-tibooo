import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

from help_me_tibooo.models import Post, ResetSourceKind, SourceBatch, SourceName, SourceSnapshot


RESET_FEED_URL = "https://codex-reset.com/api/feed"
TIBO_TIMELINE_URL = "https://codex-reset.com/tibo"
TWISCAN_TIMELINE_URL = "https://twiscan.com/en/x/thsottiaux"
PUBLIC_RESETS_URL = "https://codex-resets.com/api/v1/resets"
POST_ID_PATTERN = re.compile(r"^clamp-(\d{1,20})-(\d{1,20})$")
RESPONSE_LIMIT_BYTES = 2 * 1024 * 1024
CACHE_RESPONSE_HEADERS = (
    "Date",
    "Age",
    "Cache-Control",
    "ETag",
    "Last-Modified",
    "Retry-After",
)


@dataclass(frozen=True, slots=True)
class _ParsedResponse:
    posts: tuple[Post, ...]
    origin_time_bases: tuple[tuple[str, str], ...] = ()
    next_cursor: str | None = None


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
            id=post_id,
            text=text,
            created_at=datetime.fromtimestamp(((int(post_id) >> 22) + 1288834974657) / 1000, UTC),
            url=link["href"],
            source=SourceName.RESET,
            is_reply=text.startswith("@"),
            source_kind=kind,
        )
    return tuple(posts.values())


def fetch_source_snapshots(
    client: httpx.Client,
    *,
    now: Callable[[], datetime] | None = None,
) -> Iterator[SourceSnapshot]:
    clock = now or _utc_now
    snapshot, _ = _fetch_snapshot(
        client,
        source=SourceName.RESET,
        provider="codex-reset.com",
        endpoint=RESET_FEED_URL,
        request_url=RESET_FEED_URL,
        parser=_decode_reset_snapshot,
        now=clock,
    )
    yield snapshot

    snapshot, _ = _fetch_snapshot(
        client,
        source=SourceName.RESET,
        provider="codex-reset.com",
        endpoint=TIBO_TIMELINE_URL,
        request_url=TIBO_TIMELINE_URL,
        parser=_decode_tibo_snapshot,
        now=clock,
    )
    yield snapshot

    snapshot, _ = _fetch_snapshot(
        client,
        source=SourceName.TWISCAN,
        provider="twiscan.com",
        endpoint=TWISCAN_TIMELINE_URL,
        request_url=TWISCAN_TIMELINE_URL,
        parser=_decode_twiscan_snapshot,
        now=clock,
    )
    yield snapshot

    yield from _fetch_public_reset_snapshots(client, now=clock)


def batches_from_snapshots(snapshots: tuple[SourceSnapshot, ...]) -> tuple[SourceBatch, ...]:
    reset_snapshots = tuple(snapshot for snapshot in snapshots if snapshot.source == SourceName.RESET)
    successful_reset_snapshots = tuple(snapshot for snapshot in reset_snapshots if snapshot.error is None)
    if successful_reset_snapshots:
        posts: dict[str, Post] = {}
        for endpoint in (RESET_FEED_URL, TIBO_TIMELINE_URL):
            for snapshot in successful_reset_snapshots:
                if snapshot.endpoint != endpoint:
                    continue
                for post in snapshot.posts:
                    posts.setdefault(post.id, post)
        reset = SourceBatch(SourceName.RESET, tuple(posts.values()))
    else:
        reset = SourceBatch(
            SourceName.RESET,
            error=reset_snapshots[-1].error if reset_snapshots else "invalid response",
        )

    twiscan_snapshot = next(
        (snapshot for snapshot in snapshots if snapshot.source == SourceName.TWISCAN),
        None,
    )
    twiscan = _batch_from_snapshot(twiscan_snapshot, SourceName.TWISCAN)

    public_snapshots = tuple(snapshot for snapshot in snapshots if snapshot.source == SourceName.RESETS)
    failed_public = next((snapshot for snapshot in reversed(public_snapshots) if snapshot.error is not None), None)
    if failed_public is not None:
        public = SourceBatch(SourceName.RESETS, error=failed_public.error)
    elif not public_snapshots or not public_snapshots[-1].complete:
        public = SourceBatch(SourceName.RESETS, error="invalid response")
    else:
        public_posts: dict[str, Post] = {}
        for snapshot in public_snapshots:
            for post in snapshot.posts:
                public_posts[post.id] = post
        if public_posts:
            public = SourceBatch(SourceName.RESETS, tuple(public_posts.values()))
        else:
            public = SourceBatch(SourceName.RESETS, error="invalid response")

    return (reset, twiscan, public)


def fetch_all_sources(client: httpx.Client) -> tuple[SourceBatch, ...]:
    return batches_from_snapshots(tuple(fetch_source_snapshots(client)))


def fetch_timeline_sources(client: httpx.Client) -> tuple[SourceBatch, ...]:
    clock = _utc_now
    reset, _ = _fetch_snapshot(
        client,
        source=SourceName.RESET,
        provider="codex-reset.com",
        endpoint=RESET_FEED_URL,
        request_url=RESET_FEED_URL,
        parser=_decode_reset_snapshot,
        now=clock,
    )
    twiscan, _ = _fetch_snapshot(
        client,
        source=SourceName.TWISCAN,
        provider="twiscan.com",
        endpoint=TWISCAN_TIMELINE_URL,
        request_url=TWISCAN_TIMELINE_URL,
        parser=_decode_twiscan_snapshot,
        now=clock,
    )
    return (
        _batch_from_snapshot(reset, SourceName.RESET),
        _batch_from_snapshot(twiscan, SourceName.TWISCAN),
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


def _fetch_public_reset_snapshots(
    client: httpx.Client,
    *,
    now: Callable[[], datetime],
) -> Iterator[SourceSnapshot]:
    cursor: str | None = None
    seen_cursors: set[str] = set()
    post_count = 0
    for page in range(1, 11):
        request_url = str(
            httpx.URL(
                PUBLIC_RESETS_URL,
                params={"limit": "100", **({"cursor": cursor} if cursor else {})},
            )
        )
        snapshot, next_cursor = _fetch_snapshot(
            client,
            source=SourceName.RESETS,
            provider="codex-resets.com",
            endpoint=PUBLIC_RESETS_URL,
            request_url=request_url,
            parser=_decode_public_reset_snapshot,
            now=now,
            page=page,
            complete=False,
        )
        if snapshot.error is not None:
            yield snapshot
            return

        post_count += len(snapshot.posts)
        if next_cursor is None:
            if post_count == 0:
                yield replace(snapshot, error="invalid response")
            else:
                yield replace(snapshot, complete=True)
            return
        if next_cursor in seen_cursors or page == 10:
            yield replace(snapshot, error="invalid response")
            return

        yield snapshot
        seen_cursors.add(next_cursor)
        cursor = next_cursor


def _fetch_snapshot(
    client: httpx.Client,
    *,
    source: SourceName,
    provider: str,
    endpoint: str,
    request_url: str,
    parser: Callable[[bytes], _ParsedResponse],
    now: Callable[[], datetime],
    page: int = 1,
    complete: bool = True,
) -> tuple[SourceSnapshot, str | None]:
    request_started_at = now()
    http_status: int | None = None
    cache_headers: tuple[tuple[str, str], ...] = ()
    try:
        with client.stream(
            "GET",
            request_url,
            headers={"User-Agent": "help-me-tibooo/0.1"},
            timeout=15.0,
        ) as response:
            http_status = response.status_code
            cache_headers = _safe_cache_headers(response.headers)
            if not 200 <= response.status_code < 300:
                return (
                    SourceSnapshot(
                        source=source,
                        provider=provider,
                        endpoint=endpoint,
                        request_started_at=request_started_at,
                        response_received_at=None,
                        observed_at=None,
                        error=f"HTTP status {response.status_code}",
                        http_status=http_status,
                        cache_headers=cache_headers,
                        page=page,
                        complete=False,
                    ),
                    None,
                )
            content_length = response.headers.get("Content-Length")
            if content_length is not None and content_length.isdigit() and int(content_length) > RESPONSE_LIMIT_BYTES:
                return (
                    SourceSnapshot(
                        source=source,
                        provider=provider,
                        endpoint=endpoint,
                        request_started_at=request_started_at,
                        response_received_at=None,
                        observed_at=None,
                        error="response exceeds 2 MiB",
                        http_status=http_status,
                        cache_headers=cache_headers,
                        page=page,
                        complete=False,
                    ),
                    None,
                )

            content = bytearray()
            for chunk in response.iter_bytes():
                if len(content) + len(chunk) > RESPONSE_LIMIT_BYTES:
                    return (
                        SourceSnapshot(
                            source=source,
                            provider=provider,
                            endpoint=endpoint,
                            request_started_at=request_started_at,
                            response_received_at=None,
                            observed_at=None,
                            error="response exceeds 2 MiB",
                            http_status=http_status,
                            cache_headers=cache_headers,
                            page=page,
                            complete=False,
                        ),
                        None,
                    )
                content.extend(chunk)
            response_received_at = now()

        representation = bytes(content)
        representation_hash = sha256(representation).hexdigest()
        try:
            parsed = parser(representation)
        except (UnicodeDecodeError, ValueError):
            return (
                SourceSnapshot(
                    source=source,
                    provider=provider,
                    endpoint=endpoint,
                    request_started_at=request_started_at,
                    response_received_at=response_received_at,
                    observed_at=None,
                    error="invalid response",
                    http_status=http_status,
                    cache_headers=cache_headers,
                    representation_hash=representation_hash,
                    page=page,
                    complete=False,
                ),
                None,
            )
        observed_at = now()
        return (
            SourceSnapshot(
                source=source,
                provider=provider,
                endpoint=endpoint,
                request_started_at=request_started_at,
                response_received_at=response_received_at,
                observed_at=observed_at,
                posts=parsed.posts,
                http_status=http_status,
                cache_headers=cache_headers,
                representation_hash=representation_hash,
                page=page,
                complete=complete,
                origin_time_bases=parsed.origin_time_bases,
            ),
            parsed.next_cursor,
        )
    except httpx.TimeoutException:
        error = "request timed out"
    except httpx.HTTPError:
        error = "request failed"

    return (
        SourceSnapshot(
            source=source,
            provider=provider,
            endpoint=endpoint,
            request_started_at=request_started_at,
            response_received_at=None,
            observed_at=None,
            error=error,
            http_status=http_status,
            cache_headers=cache_headers,
            page=page,
            complete=False,
        ),
        None,
    )


def _decode_reset_snapshot(content: bytes) -> _ParsedResponse:
    posts = _decode_reset_feed(content)
    return _ParsedResponse(posts, tuple((post.id, "x_source_field") for post in posts))


def _decode_tibo_snapshot(content: bytes) -> _ParsedResponse:
    posts = parse_tibo_html(content.decode())
    return _ParsedResponse(posts, tuple((post.id, "x_snowflake") for post in posts))


def _decode_twiscan_snapshot(content: bytes) -> _ParsedResponse:
    posts = _decode_twiscan_timeline(content)
    return _ParsedResponse(posts, tuple((post.id, "unknown") for post in posts))


def _decode_public_reset_snapshot(content: bytes) -> _ParsedResponse:
    payload = httpx.Response(200, content=content).json()
    if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), list):
        raise ValueError("invalid resets")
    pagination = payload.get("pagination")
    if not isinstance(pagination, Mapping) or not isinstance(pagination.get("has_more"), bool):
        raise ValueError("invalid pagination")

    next_cursor: str | None = None
    if pagination["has_more"]:
        value = pagination.get("next_cursor")
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,1024}", value):
            raise ValueError("invalid cursor")
        next_cursor = value

    posts: list[Post] = []
    origin_time_bases: list[tuple[str, str]] = []
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
        source_type = source["type"]
        url = source.get("url")
        if isinstance(url, str):
            parsed = urlsplit(url)
            match = re.fullmatch(r"/thsottiaux/status/([0-9]{1,20})", parsed.path)
            if parsed.scheme != "https" or parsed.hostname != "x.com" or not match or parsed.query or parsed.fragment:
                raise ValueError("invalid source URL")
            if source_type == "x_post" and (source.get("author") != "thsottiaux" or match[1] != post_id):
                raise ValueError("invalid author")
            post_id = match[1]
        elif source_type == "observed":
            if not post_id.startswith("observed-"):
                raise ValueError("invalid observed ID")
            url = "https://codex-resets.com/"
        else:
            raise ValueError("missing source URL")
        posts.append(
            Post(
                post_id,
                text,
                created_at,
                url,
                SourceName.RESETS,
                source_kind=ResetSourceKind.BANKED if item["reset_type"] == "banked" else ResetSourceKind.ANNOUNCEMENT,
            )
        )
        origin_time_bases.append(
            (post_id, "x_source_field" if source_type == "x_post" else "provider_observed")
        )
    return _ParsedResponse(tuple(posts), tuple(origin_time_bases), next_cursor)


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


def _batch_from_snapshot(snapshot: SourceSnapshot | None, source: SourceName) -> SourceBatch:
    if snapshot is None:
        return SourceBatch(source, error="invalid response")
    return SourceBatch(source, snapshot.posts, snapshot.error)


def _safe_cache_headers(headers: httpx.Headers) -> tuple[tuple[str, str], ...]:
    return tuple((name, headers[name]) for name in CACHE_RESPONSE_HEADERS if name in headers)


def _utc_now() -> datetime:
    return datetime.now(UTC)
