from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from math import isfinite
from urllib.parse import urlsplit

import httpx

from help_me_tibooo.models import AlertCategory, Post


def build_alert_payload(
    post: Post,
    categories: tuple[AlertCategory, ...],
) -> dict[str, object]:
    unique_categories = tuple(dict.fromkeys(categories))[: len(AlertCategory)]
    labels = " · ".join(f"[{category.value}]" for category in unique_categories)
    prefix = f"**{labels} Tibo 알림**\n"
    suffix = f"\n<{_canonical_post_url(post)}>"
    body = _truncate_utf16(post.text, 2_000 - _utf16_length(prefix) - _utf16_length(suffix))
    return {
        "content": f"{prefix}{body}{suffix}",
        "allowed_mentions": {"parse": []},
    }


def build_health_payload(failure_count: int) -> dict[str, object]:
    bounded_failure_count = min(max(failure_count, 0), 999_999)
    return {
        "content": f"Tibo 감시가 {bounded_failure_count}회 연속 실패했습니다.",
        "allowed_mentions": {"parse": []},
    }


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


def _truncate_utf16(value: str, maximum: int) -> str:
    if maximum <= 0:
        return ""
    if _utf16_length(value) <= maximum:
        return value

    low = 0
    high = min(len(value), maximum)
    while low < high:
        middle = (low + high + 1) // 2
        if _utf16_length(value[:middle]) <= maximum:
            low = middle
        else:
            high = middle - 1
    return value[:low]


class DiscordWebhook:
    def __init__(
        self,
        webhook_url: str,
        client: httpx.Client,
        sleep: Callable[[float], None],
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._webhook_url = webhook_url
        self._client = client
        self._sleep = sleep
        self._now = now or (lambda: datetime.now(UTC))

    def send(self, payload: dict[str, object]) -> None:
        for attempt in range(1, 5):
            try:
                response = self._client.post(self._webhook_url, json=payload)
            except httpx.HTTPError:
                raise RuntimeError("Discord webhook request failed: transport error") from None

            if 200 <= response.status_code < 300:
                return

            if response.status_code != 429 and response.status_code < 500:
                raise RuntimeError(
                    f"Discord webhook request failed: HTTP {response.status_code}"
                )

            if attempt == 4:
                raise RuntimeError(
                    "Discord webhook request failed after 3 retries: "
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
