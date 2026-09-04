from datetime import UTC, datetime

import pytest

from help_me_tibooo.models import Post, SourceBatch, WatcherState
from help_me_tibooo.watcher import WatcherRunError, run_watcher


def important_post(post_id: str, **changes: object) -> Post:
    fields: dict[str, object] = {
        "id": post_id,
        "text": "Your Codex usage reset will land soon.",
        "created_at": None,
        "url": f"https://x.com/thsottiaux/status/{post_id}",
        "source": "test",
        "source_kind": "candidate",
    }
    fields.update(changes)
    return Post(**fields)


def no_alert(*_args: object) -> None:
    raise AssertionError("알림을 보내면 안 됩니다")


def test_first_run_baselines_without_alerting() -> None:
    alerts: list[str] = []
    batches = (SourceBatch("reset", posts=(important_post("401"),)),)

    state = run_watcher(batches, None, lambda post, _: alerts.append(post.id), lambda _: None)

    assert alerts == []
    assert state.latest_id == "401"
    assert state.seen_ids == ("401",)
    assert state.initialized is True


def test_cross_source_duplicate_sends_once() -> None:
    alerts: list[str] = []
    duplicate = important_post("402")
    batches = (
        SourceBatch("reset", posts=(duplicate,)),
        SourceBatch("twiscan", posts=(duplicate,)),
    )

    state = run_watcher(
        batches,
        WatcherState(latest_id="401", seen_ids=("401",), initialized=True),
        lambda post, _: alerts.append(post.id),
        lambda _: None,
    )

    assert alerts == ["402"]
    assert state.seen_ids == ("401", "402")


def test_sends_new_posts_oldest_first_when_sources_return_newest_first() -> None:
    alerts: list[str] = []
    batches = (SourceBatch("reset", posts=(important_post("404"), important_post("403"))),)

    run_watcher(
        batches,
        WatcherState(latest_id="402", seen_ids=("402",), initialized=True),
        lambda post, _: alerts.append(post.id),
        lambda _: None,
    )

    assert alerts == ["403", "404"]


def test_non_numeric_ids_fall_back_to_created_at_then_input_order() -> None:
    alerts: list[str] = []
    batches = (
        SourceBatch(
            "twiscan",
            posts=(
                important_post("later", created_at=datetime(2026, 9, 4, 11, tzinfo=UTC)),
                important_post("first", created_at=datetime(2026, 9, 4, 10, tzinfo=UTC)),
                important_post("second", created_at=datetime(2026, 9, 4, 10, tzinfo=UTC)),
            ),
        ),
    )

    run_watcher(
        batches,
        WatcherState(initialized=True),
        lambda post, _: alerts.append(post.id),
        lambda _: None,
    )

    assert alerts == ["first", "second", "later"]


def test_marks_reposts_and_irrelevant_posts_seen_without_alerting() -> None:
    alerts: list[str] = []
    batches = (
        SourceBatch(
            "twiscan",
            posts=(
                important_post("405", is_repost=True),
                important_post("406", text="I enjoyed a quiet walk today.", source_kind=None),
            ),
        ),
    )

    state = run_watcher(
        batches,
        WatcherState(latest_id="404", seen_ids=("404",), initialized=True),
        lambda post, _: alerts.append(post.id),
        lambda _: None,
    )

    assert alerts == []
    assert state.seen_ids == ("404", "405", "406")
    assert state.latest_id == "406"


def test_failed_alert_is_retried_and_later_posts_are_not_sent() -> None:
    attempts: list[str] = []
    batches = (
        SourceBatch(
            "reset",
            posts=(important_post("501"), important_post("502"), important_post("503")),
        ),
    )

    def fail_on_second(post: Post, _categories: object) -> None:
        attempts.append(post.id)
        if post.id == "502":
            raise RuntimeError("webhook unavailable")

    with pytest.raises(WatcherRunError, match="alert delivery failed") as error:
        run_watcher(batches, WatcherState(initialized=True), fail_on_second, lambda _: None)

    retried: list[str] = []
    state = run_watcher(
        batches,
        error.value.state,
        lambda post, _: retried.append(post.id),
        lambda _: None,
    )

    assert attempts == ["501", "502"]
    assert retried == ["502", "503"]
    assert state.seen_ids == ("501", "502", "503")


def test_failed_alert_carries_state_after_earlier_success() -> None:
    attempts: list[str] = []
    batches = (
        SourceBatch(
            "reset",
            posts=(important_post("702"), important_post("701")),
        ),
    )

    def fail_on_second(post: Post, _categories: object) -> None:
        attempts.append(post.id)
        if post.id == "702":
            raise RuntimeError("webhook unavailable")

    with pytest.raises(WatcherRunError, match="alert delivery failed") as error:
        run_watcher(
            batches,
            WatcherState(latest_id="700", seen_ids=("700",), initialized=True),
            fail_on_second,
            lambda _: None,
        )

    assert attempts == ["701", "702"]
    assert str(error.value) == "alert delivery failed"
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__ is True
    assert error.value.state == WatcherState(
        latest_id="701",
        seen_ids=("700", "701"),
        initialized=True,
    )


def test_failed_first_run_baselines_historical_posts_after_recovery() -> None:
    alerts: list[str] = []
    failed = (SourceBatch("reset", error="down"), SourceBatch("twiscan", error="down"))
    historical = (SourceBatch("reset", posts=(important_post("800"),)),)

    failed_state = run_watcher(failed, None, no_alert, lambda _: None)
    state = run_watcher(
        historical,
        failed_state,
        lambda post, _: alerts.append(post.id),
        lambda _: None,
    )

    assert failed_state.initialized is False
    assert alerts == []
    assert state == WatcherState(latest_id="800", seen_ids=("800",), initialized=True)


def test_one_healthy_source_clears_failure_state_and_processes_posts() -> None:
    alerts: list[str] = []
    batches = (
        SourceBatch("reset", error="down"),
        SourceBatch("twiscan", posts=(important_post("601"),)),
    )

    state = run_watcher(
        batches,
        WatcherState(consecutive_failures=2, outage_notified=True, initialized=True),
        lambda post, _: alerts.append(post.id),
        lambda _: None,
    )

    assert alerts == ["601"]
    assert state.consecutive_failures == 0
    assert state.outage_notified is False


def test_health_alert_fires_once_on_third_consecutive_failure() -> None:
    health_alerts: list[int] = []
    state = WatcherState()
    failed = (SourceBatch("reset", error="down"), SourceBatch("twiscan", error="down"))

    state = run_watcher(failed, state, no_alert, health_alerts.append)
    state = run_watcher(failed, state, no_alert, health_alerts.append)
    state = run_watcher(failed, state, no_alert, health_alerts.append)
    state = run_watcher(failed, state, no_alert, health_alerts.append)

    assert health_alerts == [3]
    assert state.consecutive_failures == 4
    assert state.outage_notified is True


def test_failed_health_alert_is_retried_on_the_next_total_failure() -> None:
    health_alerts: list[int] = []
    failed = (SourceBatch("reset", error="down"), SourceBatch("twiscan", error="down"))

    def fail_health(failures: int) -> None:
        raise RuntimeError(str(failures))

    state = WatcherState(consecutive_failures=2)
    state = run_watcher(
        failed,
        state,
        no_alert,
        fail_health,
    )
    state = run_watcher(failed, state, no_alert, health_alerts.append)

    assert health_alerts == [4]
    assert state.consecutive_failures == 4
    assert state.outage_notified is True
