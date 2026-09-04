import json
from datetime import UTC, datetime

import httpx
import pytest

import help_me_tibooo.discord as discord_module
from help_me_tibooo.discord import build_alert_payload, build_health_payload
from help_me_tibooo.models import AlertCategory
from help_me_tibooo.sources import parse_reset_feed


def test_alert_payload_disables_mentions_and_preserves_labels_and_url(make_post) -> None:
    post = make_post(text="@everyone reset landed")

    payload = build_alert_payload(
        post,
        (AlertCategory.RESET, AlertCategory.LIMITS),
    )

    assert payload["allowed_mentions"] == {"parse": []}
    assert payload["embeds"] == [
        {
            "title": "티보햄 · 리셋 · 한도",
            "description": post.text,
            "url": post.url,
            "color": 0x8B5CF6,
            "footer": {"text": "Tibo (@thsottiaux)"},
        }
    ]


def test_alert_payload_limits_embed_description_to_discord_maximum(make_post) -> None:
    post = make_post(text="a" * 4_200)

    payload = build_alert_payload(post, (AlertCategory.RESET,))
    embed = payload["embeds"][0]

    assert len(embed["description"]) == 4_096
    assert embed["url"] == post.url


def test_alert_payload_preserves_original_source_text_when_it_fits(make_post) -> None:
    original = "@everyone  리셋이 왔어요! 🚀\n둘째 줄도 그대로예요."
    post = make_post(text=original)

    payload = build_alert_payload(post, (AlertCategory.RESET,))

    assert payload["embeds"][0]["description"] == original


def test_alert_payload_bounds_hostile_id_and_url(make_post) -> None:
    post = make_post(
        id="9" * 10_000,
        url="https://evil.example/" + "x" * 10_000,
        text="중요한 원문",
    )

    payload = build_alert_payload(post, (AlertCategory.RESET,))

    embed = payload["embeds"][0]
    assert embed["url"] == "https://x.com/thsottiaux"
    assert "evil.example" not in json.dumps(payload)


def test_alert_payload_respects_discord_utf16_limit_at_emoji_boundary(make_post) -> None:
    post = make_post(text="🚀" * 2_000)

    payload = build_alert_payload(post, (AlertCategory.LAUNCH,))
    description = payload["embeds"][0]["description"]

    assert len(description.encode("utf-16-le")) // 2 <= 4_096
    assert payload["embeds"][0]["url"] == post.url


@pytest.mark.parametrize("escaped_surrogate", (r"\ud800", r"\udfff"))
def test_alert_payload_sanitizes_unpaired_surrogate_from_reset_json(
    escaped_surrogate: str,
) -> None:
    payload = json.loads(
        """
        {
          "tweets": [{
            "id": "123",
            "text": "before %s after 🚀",
            "at": "2026-09-04T00:00:00Z",
            "url": "https://x.com/thsottiaux/status/123"
          }]
        }
        """
        % escaped_surrogate
    )
    post = parse_reset_feed(payload)[0]

    alert = build_alert_payload(post, (AlertCategory.RESET,))
    description = alert["embeds"][0]["description"]

    assert "before � after 🚀" in description
    assert not any(0xD800 <= ord(character) <= 0xDFFF for character in description)
    assert len(description.encode("utf-16-le")) // 2 <= 4_096


def test_health_payload_names_consecutive_failure_count() -> None:
    payload = build_health_payload(3)

    assert payload["allowed_mentions"] == {"parse": []}
    assert payload["embeds"] == [
        {
            "title": "티보햄 · 감시 장애",
            "description": "Tibo 감시가 3회 연속 실패했습니다.",
            "color": 0xEF4444,
        }
    ]


def test_bot_posts_to_channel_with_authorization_and_retries_server_error() -> None:
    statuses = iter((500, 200))
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(next(statuses))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sleeps: list[float] = []
    bot = discord_module.DiscordBot("secret.bot.token", "123456789", client, sleeps.append)

    bot.send({"content": "test", "allowed_mentions": {"parse": []}})

    assert len(calls) == 2
    assert calls[0].url == httpx.URL(
        "https://discord.com/api/v10/channels/123456789/messages"
    )
    assert calls[0].headers["Authorization"] == "Bot secret.bot.token"
    assert json.loads(calls[0].content) == {
        "content": "test",
        "allowed_mentions": {"parse": []},
    }
    assert sleeps == [1.0]


def test_bot_retries_rate_limit_using_capped_retry_after() -> None:
    statuses = iter(
        (
            httpx.Response(429, headers={"Retry-After": "30"}),
            httpx.Response(200),
        )
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return next(statuses)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sleeps: list[float] = []
    bot = discord_module.DiscordBot("secret.bot.token", "123", client, sleeps.append)

    bot.send({"content": "test", "allowed_mentions": {"parse": []}})

    assert sleeps == [10.0]


def test_bot_uses_future_http_date_retry_after_with_injected_utc_clock() -> None:
    statuses = iter(
        (
            httpx.Response(429, headers={"Retry-After": "Fri, 04 Sep 2026 00:00:05 GMT"}),
            httpx.Response(200),
        )
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return next(statuses)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sleeps: list[float] = []
    bot = discord_module.DiscordBot(
        "secret.bot.token",
        "123",
        client,
        sleeps.append,
        lambda: datetime(2026, 9, 4, tzinfo=UTC),
    )

    bot.send({"content": "test", "allowed_mentions": {"parse": []}})

    assert sleeps == [5.0]


def test_bot_uses_backoff_for_nan_retry_after() -> None:
    statuses = iter(
        (
            httpx.Response(500, headers={"Retry-After": "NaN"}),
            httpx.Response(200),
        )
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return next(statuses)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sleeps: list[float] = []
    bot = discord_module.DiscordBot("secret.bot.token", "123", client, sleeps.append)

    bot.send({"content": "test", "allowed_mentions": {"parse": []}})

    assert sleeps == [1.0]


def test_bot_rejects_non_retryable_client_error_immediately() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(400, text="bad request")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sleeps: list[float] = []
    bot = discord_module.DiscordBot("secret.bot.token", "123", client, sleeps.append)

    with pytest.raises(RuntimeError, match="Discord bot request failed: HTTP 400") as error:
        bot.send({"content": "test", "allowed_mentions": {"parse": []}})

    assert len(calls) == 1
    assert sleeps == []
    assert "secret.bot.token" not in str(error.value)
    assert "bad request" not in str(error.value)


def test_bot_stops_after_three_retryable_retries() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sleeps: list[float] = []
    bot = discord_module.DiscordBot("secret.bot.token", "123", client, sleeps.append)

    with pytest.raises(RuntimeError, match="Discord bot request failed after 3 retries: HTTP 503") as error:
        bot.send({"content": "test", "allowed_mentions": {"parse": []}})

    assert len(calls) == 4
    assert sleeps == [1.0, 2.0, 3.0]
    assert "secret.bot.token" not in str(error.value)


def test_bot_sanitizes_transport_error_details() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"connection failed for {request.url}", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    bot = discord_module.DiscordBot("secret.bot.token", "123", client, lambda _: None)

    with pytest.raises(RuntimeError, match="Discord bot request failed: transport error") as error:
        bot.send({"content": "test", "allowed_mentions": {"parse": []}})

    assert "secret.bot.token" not in str(error.value)
    assert error.value.__suppress_context__
    assert error.value.__cause__ is None


@pytest.mark.parametrize("channel_id", ("", "abc", "123/456", "9" * 21))
def test_bot_rejects_invalid_channel_id(channel_id: str) -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200)))

    with pytest.raises(ValueError, match="Discord channel ID"):
        discord_module.DiscordBot("secret.bot.token", channel_id, client, lambda _: None)
