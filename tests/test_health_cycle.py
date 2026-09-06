from datetime import UTC, datetime, timedelta

import pytest

from help_me_tibooo.models import Post, SourceBatch, WatcherState
from help_me_tibooo.state import load_state, save_state
from help_me_tibooo.watcher import run_watcher


def test_outage_reminder_uses_elapsed_time_and_retries_failed_delivery(tmp_path):
    now = datetime(2026, 9, 7, tzinfo=UTC)
    sent = []
    failed = (SourceBatch("reset", error="request failed"),)
    state = WatcherState(consecutive_failures=2)
    state = run_watcher(failed, state, lambda *_: None, sent.append, now=now)
    assert sent == [3]
    assert state.last_outage_alert_at == now
    path = tmp_path / "state.json"
    save_state(path, state)
    state = load_state(path)
    state = run_watcher(failed, state, lambda *_: None, sent.append,
                        now=now + timedelta(hours=6, seconds=-1))
    assert sent == [3]

    def unavailable(_):
        raise RuntimeError("secret")

    state = run_watcher(failed, state, lambda *_: None, unavailable,
                        now=now + timedelta(hours=6))
    assert state.last_outage_alert_at == now
    state = run_watcher(failed, state, lambda *_: None, sent.append,
                        now=now + timedelta(hours=7))
    assert sent == [3, 6]
    assert state.last_outage_alert_at == now + timedelta(hours=7)


def test_recovery_retries_without_blocking_posts_and_sends_once(tmp_path):
    now = datetime(2026, 9, 7, tzinfo=UTC)
    post = Post("123", "quiet day", None, "https://x.com/thsottiaux/status/123", "reset")
    healthy = (SourceBatch("reset", posts=(post,)), SourceBatch("twiscan"))
    recovered = []

    def unavailable():
        raise RuntimeError("secret")

    state = run_watcher(healthy, WatcherState(outage_notified=True, consecutive_failures=3),
                        lambda *_: None, lambda _: None, send_recovery=unavailable, now=now)
    assert state.consecutive_failures == 0
    assert state.latest_id == "123"
    assert state.recovery_pending
    path = tmp_path / "state.json"
    save_state(path, state)
    state = run_watcher(healthy, load_state(path), lambda *_: None, lambda _: None,
                        send_recovery=lambda: recovered.append(True), now=now)
    state = run_watcher(healthy, state, lambda *_: None, lambda _: None,
                        send_recovery=lambda: recovered.append(True), now=now)
    assert recovered == [True]
    assert not state.recovery_pending
    assert state.last_outage_alert_at is None


def test_legacy_notified_outage_starts_six_hour_timer_without_immediate_duplicate(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"version":3,"outage_notified":true,"consecutive_failures":8}')
    now = datetime(2026, 9, 7, tzinfo=UTC)
    sent = []
    state = run_watcher((SourceBatch("reset"),), load_state(path), lambda *_: None,
                        sent.append, now=now)
    assert sent == []
    assert state.last_outage_alert_at == now
    state = run_watcher((SourceBatch("reset"),), state, lambda *_: None,
                        sent.append, now=now + timedelta(hours=6))
    assert sent == [10]


@pytest.mark.parametrize("value", ['"bad"', '"2026-09-07T00:00:00"', '123'])
def test_state_rejects_invalid_outage_timestamp(tmp_path, value):
    path = tmp_path / "state.json"
    path.write_text('{"version":3,"last_outage_alert_at":' + value + '}')
    with pytest.raises(ValueError):
        load_state(path)


def test_empty_response_does_not_send_stale_recovery_and_new_outage_is_counted():
    now = datetime(2026, 9, 7, tzinfo=UTC)
    recovered = []
    sent = []
    state = WatcherState(recovery_pending=True)
    for _ in range(3):
        state = run_watcher((SourceBatch("reset"),), state, lambda *_: None,
                            sent.append, send_recovery=lambda: recovered.append(True), now=now)
    assert recovered == []
    assert not state.recovery_pending
    assert sent == [3]


def test_initial_healthy_run_does_not_send_recovery():
    recovered = []
    post = Post("123", "quiet day", None, "https://x.com/thsottiaux/status/123", "reset")
    run_watcher((SourceBatch("reset", posts=(post,)),), None, lambda *_: None,
                lambda _: None, send_recovery=lambda: recovered.append(True))
    assert recovered == []


def test_failed_recovery_delivery_does_not_block_new_classified_post():
    post = Post("124", "Codex usage reset", None,
                "https://x.com/thsottiaux/status/124", "reset")
    sent = []

    def unavailable():
        raise RuntimeError("private bot error")

    state = run_watcher(
        (SourceBatch("reset", posts=(post,)),),
        WatcherState(latest_id="123", seen_ids=("123",), initialized=True,
                     outage_notified=True, consecutive_failures=3),
        lambda post, _: sent.append(post.id), lambda _: None,
        send_recovery=unavailable,
    )
    assert sent == ["124"]
    assert state.latest_id == "124"
    assert state.recovery_pending
