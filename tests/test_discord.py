from datetime import UTC, datetime

import httpx
import pytest

from help_me_tibooo.discord import (
    DiscordWebhook,
    build_alert_payload,
    build_health_payload,
)
from help_me_tibooo.models import AlertCategory


def test_alert_payload_disables_mentions_and_preserves_labels_and_url(make_post) -> None:
    post = make_post(text="@everyone reset landed")

    payload = build_alert_payload(
        post,
        (AlertCategory.RESET, AlertCategory.LIMITS),
    )

    assert payload["allowed_mentions"] == {"parse": []}
    assert "[리셋] · [한도]" in payload["content"]
    assert post.url in payload["content"]


def test_alert_payload_limits_content_to_discord_maximum(make_post) -> None:
    post = make_post(text="a" * 2_100)

    payload = build_alert_payload(post, (AlertCategory.RESET,))

    assert len(payload["content"]) == 2_000
    assert payload["content"].endswith(f"\n<{post.url}>")


def test_alert_payload_preserves_original_source_text_when_it_fits(make_post) -> None:
    original = "@everyone  리셋이 왔어요! 🚀\n둘째 줄도 그대로예요."
    post = make_post(text=original)

    payload = build_alert_payload(post, (AlertCategory.RESET,))

    assert original in payload["content"]


def test_alert_payload_bounds_hostile_id_and_url(make_post) -> None:
    post = make_post(
        id="9" * 10_000,
        url="https://evil.example/" + "x" * 10_000,
        text="중요한 원문",
    )

    payload = build_alert_payload(post, (AlertCategory.RESET,))

    assert len(payload["content"]) <= 2_000
    assert "evil.example" not in payload["content"]


def test_alert_payload_respects_discord_utf16_limit_at_emoji_boundary(make_post) -> None:
    post = make_post(text="🚀" * 2_000)

    payload = build_alert_payload(post, (AlertCategory.LAUNCH,))
    content = payload["content"]

    assert len(content.encode("utf-16-le")) // 2 <= 2_000
    assert content.endswith(f"\n<{post.url}>")


def test_health_payload_names_consecutive_failure_count() -> None:
    payload = build_health_payload(3)

    assert "3회 연속" in payload["content"]
    assert payload["allowed_mentions"] == {"parse": []}


def test_webhook_retries_server_error_then_succeeds() -> None:
    statuses = iter((500, 204))
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(next(statuses))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sleeps: list[float] = []
    webhook = DiscordWebhook("https://discord.example/webhook", client, sleeps.append)

    webhook.send({"content": "test", "allowed_mentions": {"parse": []}})

    assert len(calls) == 2
    assert sleeps == [1.0]


def test_webhook_retries_rate_limit_using_capped_retry_after() -> None:
    statuses = iter(
        (
            httpx.Response(429, headers={"Retry-After": "30"}),
            httpx.Response(204),
        )
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return next(statuses)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sleeps: list[float] = []
    webhook = DiscordWebhook("https://discord.example/webhook", client, sleeps.append)

    webhook.send({"content": "test", "allowed_mentions": {"parse": []}})

    assert sleeps == [10.0]


def test_webhook_uses_future_http_date_retry_after_with_injected_utc_clock() -> None:
    statuses = iter(
        (
            httpx.Response(429, headers={"Retry-After": "Fri, 04 Sep 2026 00:00:05 GMT"}),
            httpx.Response(204),
        )
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return next(statuses)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sleeps: list[float] = []
    webhook = DiscordWebhook(
        "https://discord.example/webhook",
        client,
        sleeps.append,
        lambda: datetime(2026, 9, 4, tzinfo=UTC),
    )

    webhook.send({"content": "test", "allowed_mentions": {"parse": []}})

    assert sleeps == [5.0]


def test_webhook_uses_backoff_for_nan_retry_after() -> None:
    statuses = iter(
        (
            httpx.Response(500, headers={"Retry-After": "NaN"}),
            httpx.Response(204),
        )
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return next(statuses)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sleeps: list[float] = []
    webhook = DiscordWebhook("https://discord.example/webhook", client, sleeps.append)

    webhook.send({"content": "test", "allowed_mentions": {"parse": []}})

    assert sleeps == [1.0]


def test_webhook_rejects_non_retryable_client_error_immediately() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(400, text="bad request")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sleeps: list[float] = []
    webhook = DiscordWebhook("https://discord.example/webhook", client, sleeps.append)

    with pytest.raises(RuntimeError, match="Discord webhook request failed: HTTP 400") as error:
        webhook.send({"content": "test", "allowed_mentions": {"parse": []}})

    assert len(calls) == 1
    assert sleeps == []
    assert "discord.example" not in str(error.value)


def test_webhook_stops_after_three_retryable_retries() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sleeps: list[float] = []
    webhook = DiscordWebhook("https://discord.example/webhook", client, sleeps.append)

    with pytest.raises(RuntimeError, match="Discord webhook request failed after 3 retries: HTTP 503") as error:
        webhook.send({"content": "test", "allowed_mentions": {"parse": []}})

    assert len(calls) == 4
    assert sleeps == [1.0, 2.0, 3.0]
    assert "discord.example" not in str(error.value)


def test_webhook_sanitizes_transport_error_details() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"connection failed for {request.url}", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    webhook = DiscordWebhook("https://discord.example/webhook", client, lambda _: None)

    with pytest.raises(RuntimeError, match="Discord webhook request failed: transport error") as error:
        webhook.send({"content": "test", "allowed_mentions": {"parse": []}})

    assert "discord.example" not in str(error.value)
    assert error.value.__suppress_context__
    assert error.value.__cause__ is None
