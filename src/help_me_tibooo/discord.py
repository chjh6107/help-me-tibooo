from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from math import isfinite
from urllib.parse import urlsplit

import httpx

from help_me_tibooo.models import AlertCategory, Post, SourceBatch


ALERT_COLORS = {
    AlertCategory.RESET: 0x8B5CF6,
    AlertCategory.LIMITS: 0xF59E0B,
    AlertCategory.LAUNCH: 0x3B82F6,
    AlertCategory.PLANS: 0x22C55E,
    AlertCategory.INCIDENT: 0xEF4444,
}


@dataclass(frozen=True, slots=True)
class DiscordBotCredentials:
    token: str = field(repr=False)
    channel_id: str

    def __post_init__(self) -> None:
        if not self.token or self.token.isspace():
            raise ValueError("Discord bot token must not be empty")
        if not (
            self.channel_id.isascii()
            and self.channel_id.isdigit()
            and 1 <= len(self.channel_id) <= 20
        ):
            raise ValueError("Discord channel ID must be 1 to 20 ASCII digits")


def build_alert_payloads(
    post: Post,
    categories: tuple[AlertCategory, ...],
) -> tuple[dict[str, object], ...]:
    unique_categories = tuple(dict.fromkeys(categories))[: len(AlertCategory)]
    if not unique_categories:
        raise ValueError("at least one category is required")
    labels = " · ".join(category.value for category in unique_categories)
    safe_text = _replace_unpaired_surrogates(post.text)
    return tuple(
        {
            "embeds": [
                {
                    "title": f"티보햄 · {labels}",
                    "description": description,
                    "url": _canonical_post_url(post),
                    "color": ALERT_COLORS[unique_categories[0]],
                    "footer": {"text": "Tibo (@thsottiaux)"},
                }
            ],
            "allowed_mentions": {"parse": []},
        }
        for description in _split_utf16(safe_text, 4_096)
    )


def build_health_payload(
    failure_count: int,
    batches: tuple[SourceBatch, ...] = (),
    actions_url: str | None = None,
) -> dict[str, object]:
    bounded_failure_count = min(max(failure_count, 0), 999_999)
    return _build_monitor_payload(
        "티보햄 · 감시 장애",
        f"Tibo 감시가 {bounded_failure_count}회 연속 실패했습니다.",
        ALERT_COLORS[AlertCategory.INCIDENT], batches, actions_url,
    )


def _build_monitor_payload(
    title: str, description: str, color: int,
    batches: tuple[SourceBatch, ...], actions_url: str | None,
) -> dict[str, object]:
    description_parts = [description]
    if batches:
        description_parts.append(
            "\n".join(
                f"{batch.source}: {format_source_diagnostic(batch)}"
                for batch in batches[:2]
            )
        )
    if actions_url and len(actions_url) <= 300:
        description_parts.append(
            f"실행 로그: [GitHub Actions에서 열기]({actions_url})"
        )
    return {
        "embeds": [
            {
                "title": title,
                "description": "\n\n".join(description_parts),
                "color": color,
            }
        ],
        "allowed_mentions": {"parse": []},
    }


def format_source_diagnostic(batch: SourceBatch) -> str:
    if batch.error is None:
        return f"정상 응답 · 게시물 {len(batch.posts)}개"

    safe_error = "알 수 없는 오류"
    if (
        len(batch.error) == len("HTTP status 000")
        and batch.error.startswith("HTTP status ")
        and batch.error.removeprefix("HTTP status ").isascii()
        and batch.error.removeprefix("HTTP status ").isdigit()
    ):
        safe_error = f"HTTP {batch.error.removeprefix('HTTP status ')}"
    elif batch.error in {
        "response exceeds 2 MiB",
        "request timed out",
        "request failed",
        "invalid response",
    }:
        safe_error = batch.error
    return f"실패 · {safe_error}"


def build_recovery_payload(
    batches: tuple[SourceBatch, ...], actions_url: str | None = None,
) -> dict[str, object]:
    return _build_monitor_payload(
        "티보햄 · 감시 복구",
        "일부 소스에서 게시물 수집이 재개되어 Tibo 감시가 복구되었습니다.",
        0x22C55E, batches, actions_url,
    )


def _canonical_post_url(post: Post) -> str:
    if post.id.isascii() and post.id.isdigit() and 1 <= len(post.id) <= 20:
        return f"https://x.com/thsottiaux/status/{post.id}"

    try:
        parsed = urlsplit(post.url)
        path_parts = parsed.path.rstrip("/").split("/")
        url_id = path_parts[-1]
        is_tibo_status = path_parts[-3:-1] == ["thsottiaux", "status"]
        is_trusted_host = parsed.scheme == "https" and parsed.hostname in {"x.com", "www.x.com"}
        if (
            is_trusted_host
            and is_tibo_status
            and url_id.isascii()
            and url_id.isdigit()
            and 1 <= len(url_id) <= 20
        ):
            return f"https://x.com/thsottiaux/status/{url_id}"
    except (ValueError, IndexError):
        pass
    return "https://x.com/thsottiaux"


def _utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _replace_unpaired_surrogates(value: str) -> str:
    return "".join(
        "\N{REPLACEMENT CHARACTER}" if 0xD800 <= ord(character) <= 0xDFFF else character
        for character in value
    )


def _split_utf16(value: str, maximum: int) -> tuple[str, ...]:
    if maximum <= 0:
        raise ValueError("maximum must be positive")
    if not value:
        return ("",)

    chunks: list[str] = []
    remaining = value
    while remaining:
        boundary = _utf16_prefix_length(remaining, maximum)
        chunks.append(remaining[:boundary])
        remaining = remaining[boundary:]
    return tuple(chunks)


def _utf16_prefix_length(value: str, maximum: int) -> int:
    if _utf16_length(value) <= maximum:
        return len(value)

    low = 0
    high = min(len(value), maximum)
    while low < high:
        middle = (low + high + 1) // 2
        if _utf16_length(value[:middle]) <= maximum:
            low = middle
        else:
            high = middle - 1
    return low


class DiscordBot:
    def __init__(
        self,
        credentials: DiscordBotCredentials,
        client: httpx.Client,
        sleep: Callable[[float], None],
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._token = credentials.token
        self._message_url = (
            f"https://discord.com/api/v10/channels/{credentials.channel_id}/messages"
        )
        self._client = client
        self._sleep = sleep
        self._now = now or (lambda: datetime.now(UTC))

    def send(self, payload: dict[str, object]) -> None:
        for attempt in range(1, 5):
            try:
                response = self._client.post(
                    self._message_url,
                    headers={"Authorization": f"Bot {self._token}"},
                    json=payload,
                )
            except httpx.HTTPError:
                raise RuntimeError("Discord bot request failed: transport error") from None

            if 200 <= response.status_code < 300:
                return

            if response.status_code != 429 and response.status_code < 500:
                raise RuntimeError(
                    f"Discord bot request failed: HTTP {response.status_code}"
                )

            if attempt == 4:
                raise RuntimeError(
                    "Discord bot request failed after 3 retries: "
                    f"HTTP {response.status_code}"
                )

            self._sleep(self._retry_delay(response, attempt))

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after is None:
            return float(attempt)

        try:
            delay = float(retry_after)
        except ValueError:
            return self._retry_date_delay(retry_after, attempt)

        if not isfinite(delay) or delay < 0:
            return float(attempt)
        return min(delay, 10.0)

    def _retry_date_delay(self, retry_after: str, attempt: int) -> float:
        try:
            retry_at = parsedate_to_datetime(retry_after)
            if retry_at.tzinfo is None:
                return float(attempt)
            delay = (retry_at.astimezone(UTC) - self._now().astimezone(UTC)).total_seconds()
        except (IndexError, OverflowError, TypeError, ValueError):
            return float(attempt)

        if not isfinite(delay) or delay < 0:
            return float(attempt)
        return min(delay, 10.0)
