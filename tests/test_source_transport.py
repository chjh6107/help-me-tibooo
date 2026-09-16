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
