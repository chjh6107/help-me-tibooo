from pathlib import Path

from help_me_tibooo.models import WatcherState
from help_me_tibooo.state import load_state, save_state


def test_state_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "watcher.json"
    expected = WatcherState(
        latest_id="102",
        seen_ids=("100", "101", "102"),
        consecutive_failures=2,
        outage_notified=False,
        initialized=True,
    )

    save_state(path, expected)

    assert load_state(path) == expected


def test_missing_state_returns_none(tmp_path: Path) -> None:
    assert load_state(tmp_path / "missing.json") is None


def test_old_state_defaults_to_uninitialized(tmp_path: Path) -> None:
    path = tmp_path / "watcher.json"
    path.write_text(
        '{"version": 1, "latest_id": "102", "seen_ids": ["102"]}',
        encoding="utf-8",
    )

    assert load_state(path) == WatcherState(latest_id="102", seen_ids=("102",), initialized=False)
