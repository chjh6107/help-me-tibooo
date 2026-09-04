from datetime import datetime, timezone

import httpx

from help_me_tibooo.sources import RESET_FEED_URL, fetch_all_sources, parse_reset_feed, parse_twiscan_html


def test_reset_feed_keeps_replies(load_json_fixture) -> None:
    posts = parse_reset_feed(load_json_fixture("codex_reset_feed.json"))

    assert [post.id for post in posts] == ["201", "202"]
    assert posts[1].is_reply is True
    assert posts[1].source_kind == "signal"
    assert posts[0].created_at == datetime(2026, 9, 4, tzinfo=timezone.utc)


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

    assert batches[0].error == "reset feed unavailable"
    assert batches[1].posts[0].id == "301"


def test_fetch_all_sources_does_not_expose_response_details() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="private response body", headers={"X-Secret": "private header"})

    client = httpx.Client(transport=httpx.MockTransport(handler))

    batches = fetch_all_sources(client)

    assert [batch.error for batch in batches] == ["HTTP status 500", "HTTP status 500"]
