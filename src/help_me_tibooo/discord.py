from collections.abc import Callable

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
    ) -> None:
        self._webhook_url = webhook_url
        self._client = client
        self._sleep = sleep

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

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after is None:
            return float(attempt)

        try:
            return min(max(float(retry_after), 0.0), 10.0)
        except ValueError:
            return float(attempt)
