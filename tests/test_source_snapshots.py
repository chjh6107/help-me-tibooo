from datetime import UTC, datetime, timedelta
from hashlib import sha256

import httpx

from help_me_tibooo.models import SourceName
from help_me_tibooo import sources


PUBLIC_RESETS_URL = "https://codex-resets.com/api/v1/resets"
RESET_FEED_URL = "https://codex-reset.com/api/feed"
TIBO_TIMELINE_URL = "https://codex-reset.com/tibo"


TIBO_HTML = '''<ul id="feed-list">
<li class="feed-item" data-kind="announcement"><a class="feed-time" href="https://x.com/thsottiaux/status/2100363668051603608">3h ago</a><p class="feed-text">Codex availability changed.</p></li>
</ul>'''


def public_response(post_id: str, *, more: bool = False, cursor: str | None = None) -> dict[str, object]:
    return {
        "data": [
            {
                "id": post_id,
                "reset_type": "regular",
                "announced_at": "2026-09-12T08:09:17Z",
                "text": "Hi. It is done.",
                "source": {
                    "type": "x_post",
                    "author": "thsottiaux",
                    "url": f"https://x.com/thsottiaux/status/{post_id}",
                },
            }
        ],
        "pagination": {"has_more": more, "next_cursor": cursor},
        "meta": {"api_version": "v1", "generated_at": "2026-09-22T00:00:00Z"},
    }


def test_snapshots_yield_immediately_with_endpoint_timestamps_and_safe_metadata(load_text_fixture) -> None:
    reset_content = load_text_fixture("codex_reset_feed.json").encode()
    requested_urls: list[str] = []
    start = datetime(2026, 9, 22, tzinfo=UTC)
    moments = iter(start + timedelta(seconds=offset) for offset in range(6))

    def clock() -> datetime:
        return next(moments)

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if request.url == httpx.URL(RESET_FEED_URL):
            return httpx.Response(
                200,
                content=reset_content,
                headers={
                    "Date": "Tue, 22 Sep 2026 00:00:01 GMT",
                    "ETag": '"feed-v1"',
                    "Retry-After": "12",
                    "X-Private": "must not escape",
                },
            )
        if request.url == httpx.URL(TIBO_TIMELINE_URL):
            return httpx.Response(200, text=TIBO_HTML)
        raise AssertionError(f"unexpected request: {request.url}")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        iterator = sources.fetch_source_snapshots(client, now=clock)
        first = next(iterator)

        assert first.endpoint == RESET_FEED_URL
        assert first.provider == "codex-reset.com"
        assert first.posts[0].id == "201"
        assert requested_urls == [RESET_FEED_URL]
        assert first.request_started_at == start
        assert first.response_received_at == start + timedelta(seconds=1)
        assert first.observed_at == start + timedelta(seconds=2)
        assert first.http_status == 200
        assert first.cache_headers == (
            ("Date", "Tue, 22 Sep 2026 00:00:01 GMT"),
            ("ETag", '"feed-v1"'),
            ("Retry-After", "12"),
        )
        assert first.representation_hash == sha256(reset_content).hexdigest()
        assert first.origin_time_bases == (("201", "x_source_field"), ("202", "x_source_field"))

        second = next(iterator)

        assert second.endpoint == TIBO_TIMELINE_URL
        assert second.provider == first.provider
        assert second.posts[0].id == "2100363668051603608"
        assert second.request_started_at == start + timedelta(seconds=3)
        assert second.response_received_at == start + timedelta(seconds=4)
        assert second.observed_at == start + timedelta(seconds=5)
        assert requested_urls == [RESET_FEED_URL, TIBO_TIMELINE_URL]
        assert second.origin_time_bases == (("2100363668051603608", "x_snowflake"),)
        iterator.close()


def test_json_snapshot_survives_html_parse_failure_in_legacy_batch(load_text_fixture) -> None:
    reset_content = load_text_fixture("codex_reset_feed.json").encode()
    start = datetime(2026, 9, 22, tzinfo=UTC)
    moments = iter(start + timedelta(seconds=offset) for offset in range(9))

    def clock() -> datetime:
        return next(moments)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL(RESET_FEED_URL):
            return httpx.Response(200, content=reset_content)
        if request.url == httpx.URL(TIBO_TIMELINE_URL):
            return httpx.Response(200, text="not a Tibo timeline")
        return httpx.Response(503)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        snapshots = tuple(sources.fetch_source_snapshots(client, now=clock))

    reset_snapshots = tuple(snapshot for snapshot in snapshots if snapshot.source == SourceName.RESET)
    assert len(reset_snapshots) == 2
    assert reset_snapshots[0].error is None
    assert reset_snapshots[1].error == "invalid response"
    assert reset_snapshots[1].response_received_at == start + timedelta(seconds=4)
    assert reset_snapshots[1].observed_at is None
    assert reset_snapshots[1].representation_hash == sha256(b"not a Tibo timeline").hexdigest()

    reset = sources.batches_from_snapshots(snapshots)[0]
    assert reset.error is None
    assert [post.id for post in reset.posts] == ["201", "202"]


def test_reset_page_failure_retains_prior_snapshot_but_adapter_discards_partial_posts() -> None:
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if request.url.host != "codex-resets.com":
            return httpx.Response(503)
        if "cursor" not in request.url.params:
            return httpx.Response(200, json=public_response("2098685367058612394", more=True, cursor="page2"))
        return httpx.Response(503)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        snapshots = tuple(sources.fetch_source_snapshots(client))

    resets = tuple(snapshot for snapshot in snapshots if snapshot.source == SourceName.RESETS)
    assert len(resets) == 2
    assert resets[0].endpoint == PUBLIC_RESETS_URL
    assert resets[0].page == 1
    assert resets[0].complete is False
    assert resets[0].error is None
    assert [post.id for post in resets[0].posts] == ["2098685367058612394"]
    assert resets[1].endpoint == PUBLIC_RESETS_URL
    assert resets[1].page == 2
    assert resets[1].complete is False
    assert resets[1].error == "HTTP status 503"
    assert requested_urls[-2:] == [
        "https://codex-resets.com/api/v1/resets?limit=100",
        "https://codex-resets.com/api/v1/resets?limit=100&cursor=page2",
    ]

    public = sources.batches_from_snapshots(snapshots)[2]
    assert public.error == "HTTP status 503"
    assert public.posts == ()


def test_reset_snapshot_is_complete_only_on_successful_final_page() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host != "codex-resets.com":
            return httpx.Response(503)
        if "cursor" not in request.url.params:
            return httpx.Response(200, json=public_response("2098685367058612394", more=True, cursor="page2"))
        return httpx.Response(200, json=public_response("2098685367058612393"))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        snapshots = tuple(sources.fetch_source_snapshots(client))

    resets = tuple(snapshot for snapshot in snapshots if snapshot.source == SourceName.RESETS)
    assert [(snapshot.page, snapshot.complete, snapshot.error) for snapshot in resets] == [
        (1, False, None),
        (2, True, None),
    ]
    assert [[post.id for post in snapshot.posts] for snapshot in resets] == [
        ["2098685367058612394"],
        ["2098685367058612393"],
    ]

    public = sources.batches_from_snapshots(snapshots)[2]
    assert public.error is None
    assert [post.id for post in public.posts] == ["2098685367058612394", "2098685367058612393"]


def test_public_observed_record_keeps_provider_origin_basis() -> None:
    record = public_response("2098685367058612394")
    item = record["data"][0]
    assert isinstance(item, dict)
    item["id"] = "observed-2098685367058612394"
    item["source"] = {
        "type": "observed",
        "url": "https://x.com/thsottiaux/status/2098685367058612394",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "codex-resets.com":
            return httpx.Response(200, json=record)
        return httpx.Response(503)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        snapshots = tuple(sources.fetch_source_snapshots(client))

    public = next(snapshot for snapshot in snapshots if snapshot.source == SourceName.RESETS)
    assert public.posts[0].id == "2098685367058612394"
    assert public.origin_time_bases == (("2098685367058612394", "provider_observed"),)
