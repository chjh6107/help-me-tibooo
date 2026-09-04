from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from math import isfinite

import httpx

from help_me_tibooo.models import AlertCategory, Post


def build_alert_payload(
    post: Post,
    categories: tuple[AlertCategory, ...],
) -> dict[str, object]:
    labels = " · ".join(f"[{category.value}]" for category in categories)
    prefix = f"**{labels} Tibo 알림**\n"
    suffix = f"\n<{post.url}>"
    body = post.text[: 2_000 - len(prefix) - len(suffix)]
    return {
        "content": f"{prefix}{body}{suffix}",
        "allowed_mentions": {"parse": []},
    }


def build_health_payload(failure_count: int) -> dict[str, object]:
    return {
        "content": f"Tibo 감시가 {failure_count}회 연속 실패했습니다.",
        "allowed_mentions": {"parse": []},
    }


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
