from pathlib import Path

import pytest

from help_me_tibooo.__main__ import main
from help_me_tibooo.models import Post, SourceBatch, SourceName, WatcherState
from help_me_tibooo.state import load_state, save_state


class Clock:
    def __init__(self) -> None:
        self.seconds = 0.0

    def now(self) -> float:
        return self.seconds

    def sleep(self, seconds: float) -> None:
        self.seconds += seconds


def run_session(callback, clock, *, duration=360, interval=120):
    from help_me_tibooo.polling import run_polling_session

    return run_polling_session(
        callback, interval_seconds=interval, duration_seconds=duration,
        clock=clock.now, sleep=clock.sleep,
    )


def test_collects_every_two_minutes_without_waiting_for_another_schedule() -> None:
    clock = Clock()
    starts = []

    def collect():
        starts.append(clock.seconds)
        clock.seconds += 7
        return 0

    assert run_session(collect, clock) == 0
    assert starts == [0, 120, 240]
    assert clock.seconds == 247


def test_slow_collection_skips_missed_ticks_without_a_catchup_burst() -> None:
    clock = Clock()
    starts = []

    def collect():
        starts.append(clock.seconds)
        clock.seconds += 130
        return 0

    assert run_session(collect, clock, duration=480) == 0
    assert starts == [0, 240]


def test_collection_failure_does_not_stop_next_poll() -> None:
    clock = Clock()
    starts = []

    def collect():
        starts.append(clock.seconds)
        return 1 if len(starts) == 1 else 0

    assert run_session(collect, clock) == 1
    assert starts == [0, 120, 240]


@pytest.mark.parametrize('interval,duration', [(0, 360), (-1, 360), (120, 0), (float('nan'), 360), (120, float('inf'))])
def test_invalid_timing_is_rejected_before_collection(interval, duration) -> None:
    def reject_collection():
        raise AssertionError('invalid timing must not collect')

    with pytest.raises(ValueError):
        run_session(reject_collection, Clock(), interval=interval, duration=duration)


def test_unexpected_storage_error_aborts_session() -> None:
    def broken_storage():
        raise OSError('storage unavailable')

    with pytest.raises(OSError):
        run_session(broken_storage, Clock())


def test_loop_retries_delivery_from_saved_state_without_duplicate(monkeypatch, tmp_path: Path) -> None:
    clock = Clock()
    state_path = tmp_path / 'watcher.json'
    save_state(state_path, WatcherState(latest_id='500', seen_ids=('500',), initialized=True))
    post = Post(id='501', text='Codex usage reset', created_at=None,
                url='https://x.com/thsottiaux/status/501', source=SourceName.RESET)
    monkeypatch.setenv('DISCORD_BOT_TOKEN', 'test-token')
    monkeypatch.setenv('DISCORD_CHANNEL_ID', '123')
    monkeypatch.setattr('help_me_tibooo.polling.time.monotonic', clock.now)
    monkeypatch.setattr('help_me_tibooo.polling.time.sleep', clock.sleep)
    monkeypatch.setattr('help_me_tibooo.__main__.fetch_all_sources', lambda _client: (SourceBatch(SourceName.RESET, posts=(post,)),))
    attempts = []
    delivered = []

    def send(_bot, payload):
        attempts.append(clock.seconds)
        if len(attempts) == 1:
            raise RuntimeError('temporary Discord failure')
        delivered.append(payload)

    monkeypatch.setattr('help_me_tibooo.__main__.DiscordBot.send', send)
    assert main(['watch-loop', '--state-path', str(state_path), '--duration-seconds', '360']) == 1
    assert attempts == [0, 120]
    assert len(delivered) == 1
    saved = load_state(state_path)
    assert saved.alert_delivery is None
    assert '501' in saved.seen_ids
    assert main(['watch-loop', '--state-path', str(state_path), '--duration-seconds', '360']) == 0
    assert attempts == [0, 120]
    assert len(delivered) == 1


def test_loop_does_not_bootstrap_missing_production_state(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv('DISCORD_BOT_TOKEN', 'test-token')
    monkeypatch.setenv('DISCORD_CHANNEL_ID', '123')
    state_path = tmp_path / 'missing.json'
    assert main(['watch-loop', '--state-path', str(state_path)]) == 2
    assert not state_path.exists()
