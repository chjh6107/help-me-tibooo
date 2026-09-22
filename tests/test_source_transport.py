from types import SimpleNamespace

import httpx
from curl_cffi.requests.exceptions import Timeout

from help_me_tibooo.sources import fetch_timeline_sources


def test_source_transport_preserves_parsing_and_closes_streams(monkeypatch, load_text_fixture):
    from help_me_tibooo.source_transport import SourceTransport

    closed = []
    bodies = [b'{"tweets": []}', load_text_fixture("twiscan_timeline.html").encode()]

    def request(self, method, url, **kwargs):
        body = bodies.pop(0)
        return SimpleNamespace(
            status_code=200,
            headers={"content-encoding": "gzip"},
            iter_content=lambda: iter([body]),
            close=lambda: closed.append(url),
        )

    monkeypatch.setattr("curl_cffi.requests.Session.request", request)
    with httpx.Client(transport=SourceTransport()) as client:
        batches = fetch_timeline_sources(client)

    assert batches[0].error is None
    assert batches[1].posts[0].id == "301"
    assert len(closed) == 2


def test_source_transport_maps_timeouts_and_preserves_other_source(monkeypatch, load_text_fixture):
    from help_me_tibooo.source_transport import SourceTransport

    def request(self, method, url, **kwargs):
        if "codex-reset.com" in url:
            raise Timeout("private connection detail")
        return SimpleNamespace(
            status_code=200,
            headers={},
            iter_content=lambda: iter([load_text_fixture("twiscan_timeline.html").encode()]),
            close=lambda: None,
        )

    monkeypatch.setattr("curl_cffi.requests.Session.request", request)
    with httpx.Client(transport=SourceTransport()) as client:
        batches = fetch_timeline_sources(client)

    assert batches[0].error == "request timed out"
    assert batches[1].posts[0].id == "301"


def test_source_transport_keeps_response_size_limit(monkeypatch):
    from help_me_tibooo.source_transport import SourceTransport

    closed = []
    monkeypatch.setattr(
        "curl_cffi.requests.Session.request",
        lambda *args, **kwargs: SimpleNamespace(
            status_code=200,
            headers={},
            iter_content=lambda: iter([b"x" * (2 * 1024 * 1024 + 1)]),
            close=lambda: closed.append(True),
        ),
    )
    with httpx.Client(transport=SourceTransport()) as client:
        batches = fetch_timeline_sources(client)

    assert [batch.error for batch in batches] == ["response exceeds 2 MiB"] * 2
    assert len(closed) == 2


def test_source_transport_forwards_only_public_cache_request_headers(monkeypatch):
    from help_me_tibooo.source_transport import SourceTransport

    forwarded = []

    def request(self, method, url, **kwargs):
        forwarded.append(kwargs["headers"])
        return SimpleNamespace(
            status_code=200,
            headers={
                "Date": "Tue, 22 Sep 2026 00:00:01 GMT",
                "ETag": '"v1"',
                "X-Source-Metadata": "retained",
            },
            iter_content=lambda: iter([b"ok"]),
            close=lambda: None,
        )

    monkeypatch.setattr("curl_cffi.requests.Session.request", request)
    with httpx.Client(transport=SourceTransport()) as client:
        response = client.get(
            "https://public.example/feed",
            headers={
                "User-Agent": "help-me-tibooo/0.1",
                "Accept": "application/json",
                "If-None-Match": '"cached"',
                "If-Modified-Since": "Mon, 21 Sep 2026 00:00:00 GMT",
                "Authorization": "Bearer secret",
                "Cookie": "session=secret",
                "Host": "private.example",
            },
        )

    assert forwarded == [
        {
            "user-agent": "help-me-tibooo/0.1",
            "accept": "application/json",
            "if-none-match": '"cached"',
            "if-modified-since": "Mon, 21 Sep 2026 00:00:00 GMT",
        }
    ]
    assert response.headers["Date"] == "Tue, 22 Sep 2026 00:00:01 GMT"
    assert response.headers["ETag"] == '"v1"'
    assert response.headers["X-Source-Metadata"] == "retained"
