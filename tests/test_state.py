import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from help_me_tibooo.models import (
    AlertDeliveryCheckpoint,
    AlertCategory,
    CheckpointPosition,
    Post,
    SourceCheckpoint,
    SourceName,
    WatcherState,
)
from help_me_tibooo.state import load_state, save_state


def test_state_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "watcher.json"
    expected = WatcherState(
        latest_id="102",
        seen_ids=("100", "101", "102"),
        consecutive_failures=2,
        outage_notified=False,
        initialized=True,
        alert_delivery=AlertDeliveryCheckpoint(
            post=Post(
                id="103",
                text="Codex usage reset",
                created_at=datetime(2026, 9, 4, 12, tzinfo=UTC),
                url="https://x.com/thsottiaux/status/103",
                source=SourceName.RESET,
            ),
            categories=(AlertCategory.RESET,),
            sources=(SourceName.RESET,),
            next_payload_index=2,
        ),
    )

    save_state(path, expected)

    assert load_state(path) == expected


@pytest.mark.parametrize(
    "alert_delivery",
    (
        {},
        {"post_id": 103, "next_payload_index": 1},
        {"post_id": "103", "next_payload_index": -1},
        {"post_id": "103", "next_payload_index": True},
    ),
)
def test_version_three_rejects_invalid_alert_delivery(
    tmp_path: Path,
    alert_delivery: object,
) -> None:
    path = tmp_path / "watcher.json"
    path.write_text(
        '{"version": 3, "alert_delivery": '
        + json.dumps(alert_delivery)
        + "}",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="alert_delivery"):
        load_state(path)


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
        source_checkpoints=(
            SourceCheckpoint(
                source=SourceName.LEGACY,
                position=CheckpointPosition(id="102"),
            ),
        ),
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
            SourceCheckpoint(
                source=SourceName.RESET,
                position=CheckpointPosition(id="901"),
            ),
            SourceCheckpoint(source=SourceName.TWISCAN),
        ),
    )

    save_state(path, expected)

    assert load_state(path) == expected


def test_save_truncates_seen_ids_without_losing_source_checkpoint(tmp_path: Path) -> None:
    path = tmp_path / "watcher.json"
    expected_checkpoint = SourceCheckpoint(
        source=SourceName.RESET,
        position=CheckpointPosition(id="1000"),
    )

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
    assert state.source_checkpoints == (
        SourceCheckpoint(
            source=SourceName.LEGACY,
            position=CheckpointPosition(id="102"),
        ),
    )


def test_version_one_seen_only_state_uses_last_seen_id_for_migration(tmp_path: Path) -> None:
    path = tmp_path / "watcher.json"
    path.write_text(
        '{"version": 1, "seen_ids": ["101", "102"]}',
        encoding="utf-8",
    )

    state = load_state(path)

    assert state is not None
    assert state.source_checkpoints == (
        SourceCheckpoint(
            source=SourceName.LEGACY,
            position=CheckpointPosition(id="102"),
        ),
    )


def test_version_two_source_string_loads_as_source_enum(tmp_path: Path) -> None:
    path = tmp_path / "watcher.json"
    path.write_text(
        '{"version": 2, "initialized": true, "source_checkpoints": '
        '[{"source": "reset", "latest_id": "102"}]}',
        encoding="utf-8",
    )

    state = load_state(path)

    assert state is not None
    assert state.source_checkpoints[0].source is SourceName.RESET


def test_version_two_rejects_unknown_source_name(tmp_path: Path) -> None:
    path = tmp_path / "watcher.json"
    path.write_text(
        '{"version": 2, "initialized": true, "source_checkpoints": '
        '[{"source": "resset", "latest_id": "102"}]}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="source_checkpoints"):
        load_state(path)


def test_checkpoint_positions_round_trip_through_legacy_flat_json_fields(tmp_path: Path) -> None:
    path = tmp_path / "watcher.json"
    expected = WatcherState(
        initialized=True,
        source_checkpoints=(
            SourceCheckpoint(
                source=SourceName.RESET,
                position=CheckpointPosition(
                    id="101",
                    created_at=datetime(2026, 9, 4, 10, tzinfo=UTC),
                ),
                deferred_position=CheckpointPosition(
                    id="103",
                    created_at=datetime(2026, 9, 4, 12, tzinfo=UTC),
                ),
                pending_ids=("102",),
            ),
        ),
    )

    save_state(path, expected)

    assert load_state(path) == expected
    raw = path.read_text(encoding="utf-8")
    assert '"latest_id": "101"' in raw
    assert '"deferred_latest_id": "103"' in raw
    assert '"position"' not in raw
