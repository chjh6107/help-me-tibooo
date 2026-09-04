from pathlib import Path

from help_me_tibooo.models import SourceCheckpoint, WatcherState
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


def test_legacy_state_with_checkpoint_is_initialized(tmp_path: Path) -> None:
    path = tmp_path / "watcher.json"
    path.write_text(
        '{"version": 1, "latest_id": "102", "seen_ids": ["102"]}',
        encoding="utf-8",
    )

    assert load_state(path) == WatcherState(
        latest_id="102",
        seen_ids=("102",),
        initialized=True,
        source_checkpoints=(SourceCheckpoint(source="*", latest_id="102"),),
    )


def test_legacy_failure_state_without_checkpoint_is_uninitialized(tmp_path: Path) -> None:
    path = tmp_path / "watcher.json"
    path.write_text(
        '{"version": 1, "consecutive_failures": 2, "outage_notified": false}',
        encoding="utf-8",
    )

    assert load_state(path) == WatcherState(consecutive_failures=2, initialized=False)


def test_explicit_uninitialized_state_is_preserved(tmp_path: Path) -> None:
    path = tmp_path / "watcher.json"
    path.write_text(
        '{"version": 1, "latest_id": "102", "seen_ids": ["102"], "initialized": false}',
        encoding="utf-8",
    )

    assert load_state(path) == WatcherState(latest_id="102", seen_ids=("102",), initialized=False)


def test_state_round_trip_preserves_per_source_checkpoints(tmp_path: Path) -> None:
    path = tmp_path / "watcher.json"
    expected = WatcherState(
        latest_id="901",
        seen_ids=("900", "901"),
        initialized=True,
        source_checkpoints=(
            SourceCheckpoint(source="reset", latest_id="901"),
            SourceCheckpoint(source="twiscan", latest_id=None),
        ),
    )

    save_state(path, expected)

    assert load_state(path) == expected


def test_save_truncates_seen_ids_without_losing_source_checkpoint(tmp_path: Path) -> None:
    path = tmp_path / "watcher.json"
    expected_checkpoint = SourceCheckpoint(source="reset", latest_id="1000")

    save_state(
        path,
        WatcherState(
            latest_id="1000",
            seen_ids=tuple(str(post_id) for post_id in range(1, 1001)),
            initialized=True,
            source_checkpoints=(expected_checkpoint,),
        ),
    )

    loaded = load_state(path)
    assert loaded is not None
    assert len(loaded.seen_ids) == 500
    assert loaded.seen_ids[0] == "501"
    assert loaded.source_checkpoints == (expected_checkpoint,)


def test_version_one_state_migrates_to_a_legacy_global_checkpoint(tmp_path: Path) -> None:
    path = tmp_path / "watcher.json"
    path.write_text(
        '{"version": 1, "latest_id": "102", "seen_ids": ["101", "102"]}',
        encoding="utf-8",
    )

    state = load_state(path)

    assert state is not None
    assert state.source_checkpoints == (SourceCheckpoint(source="*", latest_id="102"),)


def test_version_one_seen_only_state_uses_last_seen_id_for_migration(tmp_path: Path) -> None:
    path = tmp_path / "watcher.json"
    path.write_text(
        '{"version": 1, "seen_ids": ["101", "102"]}',
        encoding="utf-8",
    )

    state = load_state(path)

    assert state is not None
    assert state.source_checkpoints == (SourceCheckpoint(source="*", latest_id="102"),)
