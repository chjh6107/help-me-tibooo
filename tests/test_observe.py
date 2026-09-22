import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from help_me_tibooo.__main__ import main
from help_me_tibooo.models import Post, SourceName, SourceSnapshot


START = datetime(2026, 9, 22, 2, 0, tzinfo=UTC)


def make_post(post_id: str = "2100000000000000100") -> Post:
    return Post(
        id=post_id,
        text="Codex usage reset",
        created_at=START - timedelta(minutes=2),
        url=f"https://x.com/thsottiaux/status/{post_id}",
        source=SourceName.RESET,
        source_kind="candidate",
    )


def make_snapshot(observed_at: datetime = START) -> SourceSnapshot:
    post = make_post()
    return SourceSnapshot(
        source=SourceName.RESET,
        provider="codex-reset.com",
        endpoint="https://codex-reset.com/api/feed",
        request_started_at=observed_at - timedelta(seconds=2),
        response_received_at=observed_at - timedelta(seconds=1),
        observed_at=observed_at,
        posts=(post,),
        http_status=200,
        representation_hash="a" * 64,
        origin_time_bases=((post.id, "x_source_field"),),
    )


def reject_call(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("호출하면 안 됩니다")


def test_observe_needs_no_credentials_discord_watcher_or_operational_state(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    shadow_dir = tmp_path / "shadow"
    production_path = tmp_path / "watcher.json"
    production_bytes = (
        b'{"version":4,"alert_delivery":{"post":{"id":"pending-secret"}}}'
    )
    production_path.write_bytes(production_bytes)
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DISCORD_CHANNEL_ID", raising=False)
    monkeypatch.setattr(
        "help_me_tibooo.__main__.fetch_source_snapshots",
        lambda _client: iter((make_snapshot(),)),
    )
    monkeypatch.setattr("help_me_tibooo.__main__.DiscordBot", reject_call)
    monkeypatch.setattr("help_me_tibooo.__main__.run_watcher", reject_call)
    monkeypatch.setattr("help_me_tibooo.__main__.load_state", reject_call)
    monkeypatch.setattr("help_me_tibooo.__main__.save_state", reject_call)

    assert main(
        [
            "observe",
            "--shadow-dir",
            str(shadow_dir),
            "--production-state-path",
            str(production_path),
        ]
    ) == 0

    assert production_path.read_bytes() == production_bytes
    assert (shadow_dir / "metrics.jsonl").is_file()
    assert (shadow_dir / "observations.json").is_file()
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.splitlines() == [
        "reset: 정상 응답 · 게시물 1개",
        "twiscan: 실패 · invalid response",
        "resets: 실패 · invalid response",
    ]
    serialized = (shadow_dir / "metrics.jsonl").read_text(encoding="utf-8")
    assert "Codex usage reset" not in serialized
    assert "pending-secret" not in serialized


@pytest.mark.parametrize("alias_kind", ("symlink", "hardlink"))
def test_observe_rejects_output_alias_to_production_before_network(
    monkeypatch,
    tmp_path: Path,
    alias_kind: str,
) -> None:
    production_path = tmp_path / "watcher.json"
    production_path.write_text('{"version": 4}', encoding="utf-8")
    shadow_dir = tmp_path / "shadow"
    shadow_dir.mkdir()
    output_path = shadow_dir / (
        "metrics.jsonl" if alias_kind == "symlink" else "observations.json"
    )
    if alias_kind == "symlink":
        output_path.symlink_to(production_path)
    else:
        os.link(production_path, output_path)
    requests = 0

    def count_fetch(_client: object) -> tuple[SourceSnapshot, ...]:
        nonlocal requests
        requests += 1
        return (make_snapshot(),)

    monkeypatch.setattr(
        "help_me_tibooo.__main__.fetch_source_snapshots",
        count_fetch,
    )

    assert main(
        [
            "observe",
            "--shadow-dir",
            str(shadow_dir),
            "--production-state-path",
            str(production_path),
        ]
    ) == 1
    assert requests == 0
    assert production_path.read_text(encoding="utf-8") == '{"version": 4}'


def test_repeated_observe_keeps_first_observation_and_epoch(
    monkeypatch,
    tmp_path: Path,
) -> None:
    shadow_dir = tmp_path / "shadow"
    snapshots = iter(
        (
            (make_snapshot(START),),
            (make_snapshot(START + timedelta(minutes=5)),),
        )
    )
    monkeypatch.setattr(
        "help_me_tibooo.__main__.fetch_source_snapshots",
        lambda _client: iter(next(snapshots)),
    )

    assert main(["observe", "--shadow-dir", str(shadow_dir)]) == 0
    first_index = json.loads(
        (shadow_dir / "observations.json").read_text(encoding="utf-8")
    )
    assert main(["observe", "--shadow-dir", str(shadow_dir)]) == 0
    second_index = json.loads(
        (shadow_dir / "observations.json").read_text(encoding="utf-8")
    )

    event = second_index["events"][f"x:{make_post().id}"]
    assert second_index["measurement_epoch"] == first_index["measurement_epoch"]
    assert event["first_observed_at"] == START.isoformat()
    assert event["last_observed_at"] == (START + timedelta(minutes=5)).isoformat()


def test_observe_resolves_index_symlink_once_and_keeps_lock_identity(
    monkeypatch,
    tmp_path: Path,
) -> None:
    shadow_dir = tmp_path / "shadow"
    shadow_dir.mkdir()
    index_target = shadow_dir / "actual-index.json"
    index_alias = shadow_dir / "observations.json"
    index_alias.symlink_to(index_target)
    snapshots = iter(
        (
            (make_snapshot(START),),
            (make_snapshot(START + timedelta(minutes=5)),),
        )
    )
    monkeypatch.setattr(
        "help_me_tibooo.__main__.fetch_source_snapshots",
        lambda _client: iter(next(snapshots)),
    )

    assert main(["observe", "--shadow-dir", str(shadow_dir)]) == 0
    assert main(["observe", "--shadow-dir", str(shadow_dir)]) == 0

    assert index_alias.is_symlink()
    assert index_target.is_file()
    assert (shadow_dir / "actual-index.json.lock").is_file()
    assert not (shadow_dir / "observations.json.lock").exists()
    event = json.loads(index_target.read_text(encoding="utf-8"))["events"][
        f"x:{make_post().id}"
    ]
    assert event["first_observed_at"] == START.isoformat()
    assert event["last_observed_at"] == (START + timedelta(minutes=5)).isoformat()


def test_observe_returns_smoke_collection_failure_status(monkeypatch, tmp_path: Path) -> None:
    failed = SourceSnapshot(
        source=SourceName.RESET,
        provider="codex-reset.com",
        endpoint="https://codex-reset.com/api/feed",
        request_started_at=START,
        response_received_at=START,
        observed_at=None,
        error="request failed",
    )
    monkeypatch.setattr(
        "help_me_tibooo.__main__.fetch_source_snapshots",
        lambda _client: iter((failed,)),
    )

    assert main(["observe", "--shadow-dir", str(tmp_path / "shadow")]) == 1


def test_observe_reports_malformed_index_before_collection(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    shadow_dir = tmp_path / "shadow"
    shadow_dir.mkdir()
    (shadow_dir / "observations.json").write_text("not-json", encoding="utf-8")
    collections = 0

    def count_collection(_client: object) -> tuple[SourceSnapshot, ...]:
        nonlocal collections
        collections += 1
        return (make_snapshot(),)

    monkeypatch.setattr(
        "help_me_tibooo.__main__.fetch_source_snapshots",
        count_collection,
    )

    assert main(["observe", "--shadow-dir", str(shadow_dir)]) == 1
    assert collections == 0
    assert capsys.readouterr().err == (
        "관측 실행 실패: 진단 인덱스의 형식이 잘못되었습니다\n"
    )
