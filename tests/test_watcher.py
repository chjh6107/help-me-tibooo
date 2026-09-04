from datetime import UTC, datetime

import pytest

from help_me_tibooo.models import Post, SourceBatch, SourceCheckpoint, SourceName, WatcherState
from help_me_tibooo.watcher import WatcherRunError, run_watcher


def important_post(post_id: str, **changes: object) -> Post:
    fields: dict[str, object] = {
        "id": post_id,
        "text": "Your Codex usage reset will land soon.",
        "created_at": None,
        "url": f"https://x.com/thsottiaux/status/{post_id}",
        "source": SourceName.RESET,
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
        source_checkpoints=(SourceCheckpoint(source="reset", latest_id="701"),),
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
    assert state == WatcherState(
        latest_id="800",
        seen_ids=("800",),
        initialized=True,
        source_checkpoints=(SourceCheckpoint(source="reset", latest_id="800"),),
    )


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


def test_partial_first_run_baselines_only_the_healthy_source(tmp_path) -> None:
    from help_me_tibooo.state import load_state, save_state

    first_alerts: list[str] = []
    first_state = run_watcher(
        (
            SourceBatch("reset", posts=(important_post("100"),)),
            SourceBatch("twiscan", error="down"),
        ),
        None,
        lambda post, _: first_alerts.append(post.id),
        lambda _: None,
    )

    assert first_alerts == []
    assert first_state.source_checkpoints == (
        SourceCheckpoint(source="reset", latest_id="100"),
    )
    state_path = tmp_path / "watcher.json"
    save_state(state_path, first_state)
    first_state = load_state(state_path)
    assert first_state is not None

    recovered_alerts: list[str] = []
    recovered_state = run_watcher(
        (
            SourceBatch(
                "reset",
                posts=(important_post("101"), important_post("100")),
            ),
            SourceBatch(
                "twiscan",
                posts=(important_post("101"), important_post("50"), important_post("49")),
            ),
        ),
        first_state,
        lambda post, _: recovered_alerts.append(post.id),
        lambda _: None,
    )

    assert recovered_alerts == ["101"]
    assert recovered_state.source_checkpoints == (
        SourceCheckpoint(source="reset", latest_id="101"),
        SourceCheckpoint(source="twiscan", latest_id="101"),
    )


def test_source_checkpoint_prevents_resend_after_seen_ids_are_truncated(tmp_path) -> None:
    from help_me_tibooo.state import load_state, save_state

    path = tmp_path / "watcher.json"
    save_state(
        path,
        WatcherState(
            latest_id="1000",
            seen_ids=tuple(str(post_id) for post_id in range(1, 1001)),
            initialized=True,
            source_checkpoints=(SourceCheckpoint(source="reset", latest_id="1000"),),
        ),
    )
    state = load_state(path)
    assert state is not None

    alerts: list[str] = []
    next_state = run_watcher(
        (
            SourceBatch(
                "reset",
                posts=(important_post("1001"), important_post("1")),
            ),
        ),
        state,
        lambda post, _: alerts.append(post.id),
        lambda _: None,
    )

    assert "1" not in state.seen_ids
    assert alerts == ["1001"]
    assert next_state.source_checkpoints == (
        SourceCheckpoint(source="reset", latest_id="1001"),
    )


def test_cross_source_duplicate_advances_each_source_checkpoint() -> None:
    duplicate = important_post("402")

    state = run_watcher(
        (
            SourceBatch("reset", posts=(duplicate,)),
            SourceBatch("twiscan", posts=(duplicate,)),
        ),
        WatcherState(
            latest_id="401",
            seen_ids=("401",),
            initialized=True,
            source_checkpoints=(
                SourceCheckpoint(source="reset", latest_id="401"),
                SourceCheckpoint(source="twiscan", latest_id="401"),
            ),
        ),
        lambda _post, _categories: None,
        lambda _: None,
    )

    assert state.source_checkpoints == (
        SourceCheckpoint(source="reset", latest_id="402"),
        SourceCheckpoint(source="twiscan", latest_id="402"),
    )


def test_fallback_checkpoint_uses_created_at_for_eligibility() -> None:
    alerts: list[str] = []
    state = run_watcher(
        (
            SourceBatch(
                "twiscan",
                posts=(
                    important_post(
                        "newer",
                        created_at=datetime(2026, 9, 4, 11, tzinfo=UTC),
                    ),
                    important_post(
                        "older",
                        created_at=datetime(2026, 9, 4, 9, tzinfo=UTC),
                    ),
                ),
            ),
        ),
        WatcherState(
            initialized=True,
            source_checkpoints=(
                SourceCheckpoint(
                    source="twiscan",
                    latest_id="current",
                    latest_created_at=datetime(2026, 9, 4, 10, tzinfo=UTC),
                ),
            ),
        ),
        lambda post, _: alerts.append(post.id),
        lambda _: None,
    )

    assert alerts == ["newer"]
    assert state.source_checkpoints == (
        SourceCheckpoint(
            source="twiscan",
            latest_id="newer",
            latest_created_at=datetime(2026, 9, 4, 11, tzinfo=UTC),
        ),
    )


def test_failed_overlap_from_recovered_source_is_retried_when_original_source_is_down() -> None:
    initial_state = WatcherState(
        latest_id="100",
        seen_ids=("100",),
        initialized=True,
        source_checkpoints=(SourceCheckpoint(source="reset", latest_id="100"),),
    )
    overlapping_batches = (
        SourceBatch("reset", posts=(important_post("101"),)),
        SourceBatch(
            "twiscan",
            posts=(important_post("102"), important_post("101"), important_post("50")),
        ),
    )

    def fail_delivery(_post: Post, _categories: object) -> None:
        raise RuntimeError("down")

    with pytest.raises(WatcherRunError) as error:
        run_watcher(
            overlapping_batches,
            initial_state,
            fail_delivery,
            lambda _: None,
        )

    assert error.value.state.source_checkpoints == (
        SourceCheckpoint(source="reset", latest_id="100"),
        SourceCheckpoint(
            source="twiscan",
            latest_id="50",
            deferred_latest_id="102",
            pending_ids=("101",),
        ),
    )
    retried: list[str] = []
    recovered_state = run_watcher(
        (
            SourceBatch("reset", error="down"),
            SourceBatch(
                "twiscan",
                posts=(important_post("102"), important_post("101"), important_post("50")),
            ),
        ),
        error.value.state,
        lambda post, _: retried.append(post.id),
        lambda _: None,
    )

    assert retried == ["101"]
    assert recovered_state.source_checkpoints[-1] == SourceCheckpoint(
        source="twiscan",
        latest_id="102",
    )


def test_recovery_baseline_stays_suppressed_after_failed_overlap_and_seen_truncation(
    tmp_path,
) -> None:
    from help_me_tibooo.state import load_state, save_state

    history = tuple(important_post(str(post_id)) for post_id in range(702, 101, -1))
    initial_state = WatcherState(
        latest_id="100",
        seen_ids=("100",),
        initialized=True,
        source_checkpoints=(SourceCheckpoint(source="reset", latest_id="100"),),
    )

    def fail_delivery(_post: Post, _categories: object) -> None:
        raise RuntimeError("down")

    with pytest.raises(WatcherRunError) as error:
        run_watcher(
            (
                SourceBatch("reset", posts=(important_post("101"),)),
                SourceBatch(
                    "twiscan",
                    posts=(*history, important_post("101"), important_post("50")),
                ),
            ),
            initial_state,
            fail_delivery,
            lambda _: None,
        )

    state_path = tmp_path / "watcher.json"
    save_state(state_path, error.value.state)
    persisted = load_state(state_path)
    assert persisted is not None
    assert len(persisted.seen_ids) == 500

    retried: list[str] = []
    recovered_state = run_watcher(
        (
            SourceBatch("reset", error="down"),
            SourceBatch(
                "twiscan",
                posts=(*history, important_post("101"), important_post("50")),
            ),
        ),
        persisted,
        lambda post, _: retried.append(post.id),
        lambda _: None,
    )

    assert retried == ["101"]
    assert recovered_state.source_checkpoints[-1].latest_id == "702"


def test_first_empty_result_does_not_initialize_or_backfill_later_history() -> None:
    empty_state = run_watcher(
        (SourceBatch("reset"), SourceBatch("twiscan")),
        None,
        no_alert,
        lambda _: None,
    )
    alerts: list[str] = []

    baseline_state = run_watcher(
        (
            SourceBatch("reset", posts=(important_post("800"),)),
            SourceBatch("twiscan"),
        ),
        empty_state,
        lambda post, _: alerts.append(post.id),
        lambda _: None,
    )

    assert empty_state.initialized is False
    assert empty_state.consecutive_failures == 1
    assert alerts == []
    assert baseline_state.consecutive_failures == 0
    assert baseline_state.source_checkpoints == (
        SourceCheckpoint(source="reset", latest_id="800"),
    )


def test_three_all_empty_runs_send_one_health_alert() -> None:
    state = WatcherState()
    health_alerts: list[int] = []
    empty = (SourceBatch("reset"), SourceBatch("twiscan"))

    for _ in range(4):
        state = run_watcher(empty, state, no_alert, health_alerts.append)

    assert health_alerts == [3]
    assert state.consecutive_failures == 4
    assert state.outage_notified is True
    assert state.initialized is False


def test_empty_source_remains_uninitialized_while_nonempty_source_progresses() -> None:
    first_state = run_watcher(
        (
            SourceBatch("reset", posts=(important_post("100"),)),
            SourceBatch("twiscan"),
        ),
        None,
        no_alert,
        lambda _: None,
    )
    alerts: list[str] = []

    recovered_state = run_watcher(
        (
            SourceBatch("reset", posts=(important_post("101"), important_post("100"))),
            SourceBatch("twiscan", posts=(important_post("50"), important_post("49"))),
        ),
        first_state,
        lambda post, _: alerts.append(post.id),
        lambda _: None,
    )

    assert first_state.source_checkpoints == (
        SourceCheckpoint(source="reset", latest_id="100"),
    )
    assert alerts == ["101"]
    assert recovered_state.source_checkpoints == (
        SourceCheckpoint(source="reset", latest_id="101"),
        SourceCheckpoint(source="twiscan", latest_id="50"),
    )
