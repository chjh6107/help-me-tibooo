from datetime import datetime, timezone

import httpx
import pytest

from help_me_tibooo.models import ResetSourceKind, SourceName
from help_me_tibooo.sources import RESET_FEED_URL, fetch_all_sources, parse_reset_feed, parse_twiscan_html


def test_reset_feed_keeps_replies(load_json_fixture) -> None:
    posts = parse_reset_feed(load_json_fixture("codex_reset_feed.json"))

    assert [post.id for post in posts] == ["201", "202"]
    assert posts[1].is_reply is True
    assert posts[1].source_kind == "signal"
    assert posts[0].created_at == datetime(2026, 9, 4, tzinfo=timezone.utc)
    assert posts[0].source is SourceName.RESET
    assert posts[0].source_kind is ResetSourceKind.ANNOUNCEMENT


def test_twiscan_parser_marks_plain_repost(load_text_fixture) -> None:
    posts = parse_twiscan_html(load_text_fixture("twiscan_timeline.html"))

    assert [post.id for post in posts] == ["301", "302", "303"]
    assert posts[0].text == "We are launching GPT-6 Astra today."
    assert posts[2].is_repost is True


def test_fetch_all_sources_isolates_one_failure(load_text_fixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL(RESET_FEED_URL):
            raise httpx.ConnectError("reset feed unavailable", request=request)
        return httpx.Response(200, text=load_text_fixture("twiscan_timeline.html"))

    client = httpx.Client(transport=httpx.MockTransport(handler))

    batches = fetch_all_sources(client)

    assert batches[0].error == "request failed"
    assert batches[1].posts[0].id == "301"


def test_fetch_all_sources_does_not_expose_response_details() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="private response body", headers={"X-Secret": "private header"})

    client = httpx.Client(transport=httpx.MockTransport(handler))

    batches = fetch_all_sources(client)

    assert [batch.error for batch in batches] == ["HTTP status 500", "HTTP status 500"]


def test_fetch_all_sources_sends_required_request_settings() -> None:
    request_settings: list[tuple[str, dict[str, float]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_settings.append(
            (request.headers["User-Agent"], dict(request.extensions["timeout"]))
        )
        if request.url == httpx.URL(RESET_FEED_URL):
            return httpx.Response(200, json={"tweets": []})
        return httpx.Response(200, text='<html><body><div id="timeline"></div></body></html>')

    client = httpx.Client(transport=httpx.MockTransport(handler))

    batches = fetch_all_sources(client)

    assert [batch.posts for batch in batches] == [(), ()]
    assert request_settings == [
        (
            "help-me-tibooo/0.1",
            {"connect": 15.0, "read": 15.0, "write": 15.0, "pool": 15.0},
        ),
        (
            "help-me-tibooo/0.1",
            {"connect": 15.0, "read": 15.0, "write": 15.0, "pool": 15.0},
        ),
    ]


def test_fetch_all_sources_rejects_declared_oversized_responses() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Content-Length": str(2 * 1024 * 1024 + 1)})

    client = httpx.Client(transport=httpx.MockTransport(handler))

    batches = fetch_all_sources(client)

    assert [batch.error for batch in batches] == [
        "response exceeds 2 MiB",
        "response exceeds 2 MiB",
    ]


def test_fetch_all_sources_accepts_just_under_limit_responses() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL(RESET_FEED_URL):
            content = b'{"tweets": []}'
        else:
            content = b'<html><body><div id="timeline"></div></body></html>'
        return httpx.Response(200, content=content.ljust(2 * 1024 * 1024, b" "))

    client = httpx.Client(transport=httpx.MockTransport(handler))

    batches = fetch_all_sources(client)

    assert [batch.posts for batch in batches] == [(), ()]


def test_fetch_all_sources_rejects_chunked_oversized_responses() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1))

    client = httpx.Client(transport=httpx.MockTransport(handler))

    batches = fetch_all_sources(client)

    assert [batch.error for batch in batches] == [
        "response exceeds 2 MiB",
        "response exceeds 2 MiB",
    ]


def test_fetch_all_sources_sanitizes_transport_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(
            "https://private.example/?token=secret X-Private: secret body",
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))

    batches = fetch_all_sources(client)

    assert [batch.error for batch in batches] == ["request timed out", "request timed out"]


def test_fetch_all_sources_rejects_redirects() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(302, headers={"Location": "https://private.example"})
        )
    )

    batches = fetch_all_sources(client)

    assert [batch.error for batch in batches] == ["HTTP status 302", "HTTP status 302"]


@pytest.mark.parametrize(
    "payload",
    (
        [{"tweets": []}],
        {"tweets": [{"id": "broken"}]},
        {
            "tweets": [
                {
                    "id": "9" * 100,
                    "text": "Codex reset",
                    "at": "2026-09-04T00:00:00Z",
                    "url": "https://evil.example/oversized",
                }
            ]
        },
    ),
)
def test_reset_feed_rejects_unexpected_or_wholly_unusable_json(payload: object) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL(RESET_FEED_URL):
            return httpx.Response(200, json=payload)
        return httpx.Response(200, text='<html><body><div id="timeline"></div></body></html>')

    client = httpx.Client(transport=httpx.MockTransport(handler))

    batches = fetch_all_sources(client)

    assert batches[0].error == "invalid response"


@pytest.mark.parametrize(
    "html",
    (
        "<html><body>unrelated page</body></html>",
        '<html><body><div id="clamp-broken"></div></body></html>',
        '<html><body><div id="clamp-' + "9" * 100 + '-0">oversized</div></body></html>',
    ),
)
def test_twiscan_rejects_missing_timeline_or_wholly_unusable_records(html: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL(RESET_FEED_URL):
            return httpx.Response(200, json={"tweets": []})
        return httpx.Response(200, text=html)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    batches = fetch_all_sources(client)

    assert batches[1].error == "invalid response"


def test_explicit_empty_source_structures_are_healthy() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL(RESET_FEED_URL):
            return httpx.Response(200, json={"tweets": []})
        return httpx.Response(200, text='<html><body><div id="timeline"></div></body></html>')

    client = httpx.Client(transport=httpx.MockTransport(handler))

    batches = fetch_all_sources(client)

    assert [(batch.error, batch.posts) for batch in batches] == [(None, ()), (None, ())]


def test_repeated_malformed_responses_accumulate_total_failure_state() -> None:
    from help_me_tibooo.models import WatcherState
    from help_me_tibooo.watcher import run_watcher

    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, text="not a provider response")
        )
    )
    state = WatcherState(initialized=True)
    health_alerts: list[int] = []

    for _ in range(3):
        state = run_watcher(
            fetch_all_sources(client),
            state,
            lambda _post, _categories: None,
            health_alerts.append,
        )

    assert state.consecutive_failures == 3
    assert state.outage_notified is True
    assert health_alerts == [3]


def test_unknown_reset_source_kind_is_discarded() -> None:
    posts = parse_reset_feed(
        {
            "tweets": [
                {
                    "id": "205",
                    "text": "Codex availability changed.",
                    "at": "2026-09-04T00:00:00Z",
                    "url": "https://x.com/thsottiaux/status/205",
                    "kind": "announcemnet",
                }
            ]
        }
    )

    assert posts[0].source_kind is None
