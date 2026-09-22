import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from help_me_tibooo.diagnostics import (
    DiagnosticRun,
    canonical_post_key,
    evidence_hash,
)
from help_me_tibooo.models import Post, ResetSourceKind, SourceName, SourceSnapshot
from help_me_tibooo.sources import parse_tibo_html


START = datetime(2026, 9, 22, 1, 2, 3, tzinfo=UTC)


def make_post(
    post_id: str,
    text: str = "Codex usage reset",
    *,
    source: SourceName = SourceName.RESET,
    url: str | None = None,
) -> Post:
    return Post(
        id=post_id,
        text=text,
        created_at=START - timedelta(minutes=3),
        url=url or f"https://x.com/thsottiaux/status/{post_id}",
        source=source,
        source_kind=ResetSourceKind.CANDIDATE,
    )


def make_snapshot(
    endpoint: str,
    observed_at: datetime,
    posts: tuple[Post, ...],
    *,
    provider: str = "codex-reset.com",
    error: str | None = None,
    complete: bool = True,
    origin_time_bases: tuple[tuple[str, str], ...] = (),
) -> SourceSnapshot:
    return SourceSnapshot(
        source=posts[0].source if posts else SourceName.RESET,
        provider=provider,
        endpoint=endpoint,
        request_started_at=observed_at - timedelta(seconds=2),
        response_received_at=observed_at - timedelta(seconds=1),
        observed_at=observed_at if error is None else None,
        posts=posts,
        error=error,
        http_status=200 if error is None else 503,
        cache_headers=(("ETag", '"safe"'),),
        representation_hash="f" * 64 if error is None else None,
        complete=complete,
        origin_time_bases=origin_time_bases,
    )


def read_json_lines(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_records_distinct_endpoint_membership_and_deduplicates_canonical_x_id(
    tmp_path: Path,
) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    index_path = tmp_path / "observations.json"
    post = make_post("2100000000000000001")
    confirmed = make_post(
        post.id,
        source=SourceName.RESETS,
        url=post.url,
    )

    with DiagnosticRun(metrics_path, index_path, now=lambda: START) as run:
        run.record_snapshot(
            make_snapshot(
                "https://codex-reset.com/api/feed",
                START,
                (post,),
                origin_time_bases=((post.id, "x_source_field"),),
            )
        )
        run.record_snapshot(
            make_snapshot(
                "https://codex-resets.com/api/v1/resets",
                START + timedelta(seconds=10),
                (confirmed,),
                provider="codex-resets.com",
                origin_time_bases=((post.id, "provider_observed"),),
            )
        )
        run.finish("수집 정상")

    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert index["version"] == 2
    assert index["measurement_epoch"] == START.isoformat()
    assert list(index["events"]) == [f"x:{post.id}"]
    event = index["events"][f"x:{post.id}"]
    assert set(event["endpoints"]) == {
        "https://codex-reset.com/api/feed",
        "https://codex-resets.com/api/v1/resets",
    }
    assert event["first_observed_at"] == START.isoformat()
    assert event["last_observed_at"] == (START + timedelta(seconds=10)).isoformat()
    assert event["provider_visible_at"] is None
    assert set(event["origin_time_bases"]) == {
        "x_source_field",
        "provider_observed",
    }
    assert index["endpoint_memberships"]["https://codex-reset.com/api/feed"][
        "canonical_ids"
    ] == [f"x:{post.id}"]

    serialized = metrics_path.read_text(encoding="utf-8") + index_path.read_text(
        encoding="utf-8"
    )
    assert post.text not in serialized
    assert "secret" not in serialized


def test_evidence_hash_ignores_relative_time_html_and_observation_timestamps() -> None:
    earlier = parse_tibo_html(
        '<ul id="feed-list"><li class="feed-item" data-kind="announcement">'
        '<a class="feed-time" href="https://x.com/thsottiaux/status/2100363668051603608">3h ago</a>'
        '<p class="feed-text">Codex availability changed.</p></li></ul>'
    )[0]
    later = parse_tibo_html(
        '<ul id="feed-list"><li class="feed-item" data-kind="announcement">'
        '<a class="feed-time" href="https://x.com/thsottiaux/status/2100363668051603608">4h ago</a>'
        '<p class="feed-text">Codex availability changed.</p></li></ul>'
    )[0]

    assert evidence_hash(earlier) == evidence_hash(later)


def test_history_keeps_earliest_event_and_version_times_for_a_b_a(
    tmp_path: Path,
) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    index_path = tmp_path / "observations.json"
    post_a = make_post("2100000000000000002", "Codex A")
    post_b = make_post(post_a.id, "Codex A with confirmed details")

    with DiagnosticRun(metrics_path, index_path, now=lambda: START) as run:
        for offset, post in ((0, post_a), (10, post_b), (20, post_a)):
            run.record_snapshot(
                make_snapshot(
                    "https://codex-reset.com/api/feed",
                    START + timedelta(seconds=offset),
                    (post,),
                    origin_time_bases=((post.id, "x_source_field"),),
                )
            )
        run.finish("수집 정상")

    event = json.loads(index_path.read_text(encoding="utf-8"))["events"][
        f"x:{post_a.id}"
    ]
    assert event["first_observed_at"] == START.isoformat()
    assert event["last_observed_at"] == (START + timedelta(seconds=20)).isoformat()
    assert event["versions"][evidence_hash(post_a)] == {
        "first_observed_at": START.isoformat(),
        "last_observed_at": (START + timedelta(seconds=20)).isoformat(),
    }
    assert event["versions"][evidence_hash(post_b)] == {
        "first_observed_at": (START + timedelta(seconds=10)).isoformat(),
        "last_observed_at": (START + timedelta(seconds=10)).isoformat(),
    }


def test_overlap_uses_full_previous_successful_membership_and_failure_does_not_replace_it(
    tmp_path: Path,
) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    index_path = tmp_path / "observations.json"
    endpoint = "https://codex-reset.com/api/feed"
    a = make_post("2100000000000000010")
    b = make_post("2100000000000000011")
    c = make_post("2100000000000000012")

    with DiagnosticRun(metrics_path, index_path, now=lambda: START) as run:
        run.record_snapshot(make_snapshot(endpoint, START, (a, b)))
        run.record_snapshot(
            make_snapshot(endpoint, START + timedelta(seconds=10), (b, c))
        )
        run.record_snapshot(
            make_snapshot(
                endpoint,
                START + timedelta(seconds=20),
                (),
                error="private upstream body",
            )
        )
        run.record_snapshot(
            make_snapshot(endpoint, START + timedelta(seconds=30), (a,))
        )
        run.finish("부분 장애")

    fetched = [
        event
        for event in read_json_lines(metrics_path)
        if event["event"] == "source_fetched"
    ]
    assert [event["membership_overlap"] for event in fetched] == [
        "unknown",
        "overlap",
        "unknown",
        "none",
    ]
    assert fetched[1]["membership_overlap_count"] == 1
    assert fetched[2]["outcome"] == "failed"
    assert "private upstream body" not in metrics_path.read_text(encoding="utf-8")

    membership = json.loads(index_path.read_text(encoding="utf-8"))[
        "endpoint_memberships"
    ][endpoint]
    assert membership["canonical_ids"] == [f"x:{a.id}"]
    assert membership["last_successful_at"] == (
        START + timedelta(seconds=30)
    ).isoformat()


def test_empty_snapshot_preserves_previous_membership_for_recovery_overlap(
    tmp_path: Path,
) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    index_path = tmp_path / "observations.json"
    endpoint = "https://codex-reset.com/api/feed"
    a = make_post("2100000000000000050")
    b = make_post("2100000000000000051")
    c = make_post("2100000000000000052")

    with DiagnosticRun(metrics_path, index_path, now=lambda: START) as run:
        run.record_snapshot(make_snapshot(endpoint, START, (a, b)))
        run.record_snapshot(
            make_snapshot(endpoint, START + timedelta(seconds=10), ())
        )
        run.record_snapshot(
            make_snapshot(endpoint, START + timedelta(seconds=20), (b, c))
        )
        run.finish("수집 정상")

    fetched = [
        event
        for event in read_json_lines(metrics_path)
        if event["event"] == "source_fetched"
    ]
    assert [event["outcome"] for event in fetched] == ["success", "empty", "success"]
    assert [event["membership_overlap"] for event in fetched] == [
        "unknown",
        "unknown",
        "overlap",
    ]
    assert fetched[2]["membership_overlap_count"] == 1
    membership = json.loads(index_path.read_text(encoding="utf-8"))[
        "endpoint_memberships"
    ][endpoint]
    assert membership == {
        "canonical_ids": [f"x:{b.id}", f"x:{c.id}"],
        "last_successful_at": (START + timedelta(seconds=20)).isoformat(),
    }


def test_empty_final_page_commits_nonempty_accumulated_membership(
    tmp_path: Path,
) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    index_path = tmp_path / "observations.json"
    endpoint = "https://codex-resets.com/api/v1/resets"
    post = make_post(
        "2100000000000000053",
        source=SourceName.RESETS,
    )

    with DiagnosticRun(metrics_path, index_path, now=lambda: START) as run:
        run.record_snapshot(
            make_snapshot(endpoint, START, (post,), complete=False)
        )
        run.record_snapshot(
            make_snapshot(endpoint, START + timedelta(seconds=10), (), complete=True)
        )
        run.finish("수집 정상")

    membership = json.loads(index_path.read_text(encoding="utf-8"))[
        "endpoint_memberships"
    ][endpoint]
    assert membership == {
        "canonical_ids": [f"x:{post.id}"],
        "last_successful_at": (START + timedelta(seconds=10)).isoformat(),
    }


def test_metrics_include_run_snapshot_observation_classification_and_finish_events(
    tmp_path: Path,
) -> None:
    post = make_post("2100000000000000020")
    metrics_path = tmp_path / "metrics.jsonl"

    with DiagnosticRun(
        metrics_path,
        tmp_path / "observations.json",
        now=lambda: START,
    ) as run:
        run.record_snapshot(
            make_snapshot(
                "https://codex-reset.com/api/feed",
                START,
                (post,),
                origin_time_bases=((post.id, "x_source_field"),),
            )
        )
        run.finish("수집 정상")

    events = read_json_lines(metrics_path)
    assert [event["event"] for event in events] == [
        "run_started",
        "source_fetched",
        "post_observed",
        "classified",
        "run_finished",
    ]
    assert len({event["run_id"] for event in events}) == 1
    post_event = events[2]
    assert post_event["canonical_id"] == f"x:{post.id}"
    assert post_event["evidence_hash"] == evidence_hash(post)
    assert post_event["origin_time_basis"] == "x_source_field"
    assert post_event["provider_visible_at"] is None
    assert post_event["origin_latency_seconds"] == 180.0
    assert post_event["origin_latency_valid"] is True
    assert events[3]["categories"] == ["리셋"]


def test_negative_latency_is_marked_invalid_instead_of_clamped(tmp_path: Path) -> None:
    post = Post(
        id="2100000000000000030",
        text="Codex update",
        created_at=START + timedelta(minutes=1),
        url="https://x.com/thsottiaux/status/2100000000000000030",
        source=SourceName.RESET,
    )
    metrics_path = tmp_path / "metrics.jsonl"

    with DiagnosticRun(
        metrics_path,
        tmp_path / "observations.json",
        now=lambda: START,
    ) as run:
        run.record_snapshot(
            make_snapshot(
                "https://codex-reset.com/api/feed",
                START,
                (post,),
                origin_time_bases=((post.id, "x_source_field"),),
            )
        )
        run.finish("수집 정상")

    observed = next(
        event
        for event in read_json_lines(metrics_path)
        if event["event"] == "post_observed"
    )
    assert observed["origin_latency_seconds"] == -60.0
    assert observed["origin_latency_valid"] is False


def test_later_known_origin_fills_unknown_without_changing_first_observation(
    tmp_path: Path,
) -> None:
    post_id = "2100000000000000060"
    unknown = Post(
        id=post_id,
        text="Codex update",
        created_at=None,
        url=f"https://x.com/thsottiaux/status/{post_id}",
        source=SourceName.TWISCAN,
    )
    known_origin = START - timedelta(minutes=15)
    known = Post(
        id=post_id,
        text="Codex update",
        created_at=known_origin,
        url=unknown.url,
        source=SourceName.RESET,
    )
    metrics_path = tmp_path / "metrics.jsonl"
    index_path = tmp_path / "observations.json"

    with DiagnosticRun(metrics_path, index_path, now=lambda: START) as run:
        run.record_snapshot(
            make_snapshot(
                "https://twiscan.com/en/x/thsottiaux",
                START,
                (unknown,),
                provider="twiscan.com",
                origin_time_bases=((post_id, "unknown"),),
            )
        )
        run.record_snapshot(
            make_snapshot(
                "https://codex-reset.com/api/feed",
                START + timedelta(seconds=10),
                (known,),
                origin_time_bases=((post_id, "x_source_field"),),
            )
        )
        run.record_snapshot(
            make_snapshot(
                "https://twiscan.com/en/x/thsottiaux",
                START + timedelta(seconds=20),
                (unknown,),
                provider="twiscan.com",
                origin_time_bases=((post_id, "unknown"),),
            )
        )
        run.finish("수집 정상")

    event = json.loads(index_path.read_text(encoding="utf-8"))["events"][f"x:{post_id}"]
    assert event["origin_at"] == known_origin.isoformat()
    assert event["first_observed_at"] == START.isoformat()
    assert event["last_observed_at"] == (START + timedelta(seconds=20)).isoformat()
    assert event["versions"][evidence_hash(unknown)]["first_observed_at"] == (
        START.isoformat()
    )
    assert event["versions"][evidence_hash(known)]["first_observed_at"] == (
        START + timedelta(seconds=10)
    ).isoformat()


def test_malformed_index_fails_without_replacing_measurement_history(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "observations.json"
    index_path.write_text('{"version": 1, "measurement_epoch":', encoding="utf-8")

    with pytest.raises(ValueError, match="진단 인덱스"):
        with DiagnosticRun(tmp_path / "metrics.jsonl", index_path, now=lambda: START):
            pass

    assert index_path.read_text(encoding="utf-8") == (
        '{"version": 1, "measurement_epoch":'
    )


def test_semantically_malformed_index_fails_before_appending_metrics(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "observations.json"
    index_path.write_text(
        json.dumps(
            {
                "version": 1,
                "measurement_epoch": START.isoformat(),
                "events": {"x:1": []},
                "endpoint_memberships": {},
            }
        ),
        encoding="utf-8",
    )
    metrics_path = tmp_path / "metrics.jsonl"

    with pytest.raises(ValueError, match="진단 인덱스"):
        with DiagnosticRun(metrics_path, index_path, now=lambda: START):
            pass

    assert not metrics_path.exists()


@pytest.mark.parametrize(
    ("object_path", "unsafe_key"),
    (
        ((), "body"),
        (("events", "x:2100000000000000042"), "credentials"),
        (
            (
                "events",
                "x:2100000000000000042",
                "endpoints",
                "https://codex-reset.com/api/feed",
            ),
            "raw_response",
        ),
        (
            (
                "events",
                "x:2100000000000000042",
                "versions",
                evidence_hash(make_post("2100000000000000042")),
            ),
            "text",
        ),
        (
            (
                "endpoint_memberships",
                "https://codex-reset.com/api/feed",
            ),
            "token",
        ),
    ),
    ids=("top", "event", "endpoint", "version", "membership"),
)
@pytest.mark.parametrize("index_version", (1, 2))
def test_index_rejects_unknown_fields_before_metrics_append_or_reserialization(
    tmp_path: Path,
    object_path: tuple[str, ...],
    unsafe_key: str,
    index_version: int,
) -> None:
    metrics_path = tmp_path / "metrics.jsonl"
    index_path = tmp_path / "observations.json"
    post = make_post("2100000000000000042")
    with DiagnosticRun(metrics_path, index_path, now=lambda: START) as run:
        run.record_snapshot(
            make_snapshot(
                "https://codex-reset.com/api/feed",
                START,
                (post,),
                origin_time_bases=((post.id, "x_source_field"),),
            )
        )
        run.finish("수집 정상")

    payload = json.loads(index_path.read_text(encoding="utf-8"))
    payload["version"] = index_version
    if index_version == 1:
        for event in payload["events"].values():
            del event["origin_time_basis"]
    target = payload
    for key in object_path:
        target = target[key]
    assert isinstance(target, dict)
    target[unsafe_key] = "private-body-or-credential"
    index_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    malformed_index = index_path.read_bytes()
    existing_metrics = metrics_path.read_bytes()

    with pytest.raises(ValueError, match="진단 인덱스"):
        with DiagnosticRun(
            metrics_path,
            index_path,
            now=lambda: START + timedelta(minutes=1),
        ):
            pass

    assert metrics_path.read_bytes() == existing_metrics
    assert index_path.read_bytes() == malformed_index


def test_canonical_key_uses_provider_for_non_x_and_rejects_mismatched_x_url() -> None:
    opaque = make_post(
        "observed-safe_1",
        source=SourceName.RESETS,
        url="https://codex-resets.com/",
    )
    assert canonical_post_key(opaque, "codex-resets.com") == (
        "provider:codex-resets.com:observed-safe_1"
    )

    mismatched = make_post(
        "2100000000000000040",
        url="https://x.com/thsottiaux/status/2100000000000000041",
    )
    with pytest.raises(ValueError, match="X 게시물 URL"):
        canonical_post_key(mismatched, "codex-reset.com")


@pytest.mark.parametrize(
    ("first_basis", "next_basis", "upgrade"),
    (
        ("provider_observed", "x_source_field", True),
        ("provider_observed", "x_snowflake", True),
        ("x_snowflake", "x_source_field", True),
        ("unknown", "provider_observed", True),
        ("x_source_field", "provider_observed", False),
        ("x_source_field", "x_snowflake", False),
        ("x_source_field", "x_source_field", False),
    ),
)
def test_origin_selection_persists_quality_across_runs(
    tmp_path: Path,
    first_basis: str,
    next_basis: str,
    upgrade: bool,
) -> None:
    metrics = tmp_path / "metrics.jsonl"
    index_path = tmp_path / "observations.json"
    initial = replace(
        make_post("2100000000000000070", source=SourceName.RESETS),
        created_at=START - timedelta(minutes=1),
    )
    newer = replace(
        initial,
        source=SourceName.RESET,
        created_at=START - timedelta(minutes=10),
    )
    endpoint = "https://codex-resets.com/api/v1/resets"
    with DiagnosticRun(metrics, index_path, now=lambda: START) as run:
        run.record_snapshot(make_snapshot(
            endpoint, START, (initial,), provider="codex-resets.com",
            origin_time_bases=((initial.id, first_basis),),
        ))
        run.finish("수집 정상")
    before = json.loads(index_path.read_text())
    with DiagnosticRun(metrics, index_path, now=lambda: START + timedelta(seconds=10)) as run:
        run.record_snapshot(make_snapshot(
            "https://codex-reset.com/api/feed", START + timedelta(seconds=10), (newer,),
            origin_time_bases=((newer.id, next_basis),),
        ))
        run.finish("수집 정상")
    after = json.loads(index_path.read_text())
    event = after["events"][f"x:{initial.id}"]
    assert event["origin_at"] == (newer if upgrade else initial).created_at.isoformat()
    assert event["origin_time_basis"] == (next_basis if upgrade else first_basis)
    assert event["first_observed_at"] == START.isoformat()
    original_version = before["events"][f"x:{initial.id}"]["versions"][
        evidence_hash(initial)
    ]
    assert event["versions"][evidence_hash(initial)] == original_version
    assert after["measurement_epoch"] == before["measurement_epoch"]
    observed = [row for row in read_json_lines(metrics) if row["event"] == "post_observed"]
    assert observed[0]["origin_at"] == initial.created_at.isoformat()
    assert observed[0]["origin_time_basis"] == first_basis
    assert observed[1]["origin_at"] == newer.created_at.isoformat()
    assert observed[1]["origin_time_basis"] == next_basis


def test_legacy_index_retains_history_without_guessing_selected_origin_basis(
    tmp_path: Path,
) -> None:
    metrics = tmp_path / "metrics.jsonl"
    index_path = tmp_path / "observations.json"
    post = make_post("2100000000000000071")
    endpoint = "https://codex-reset.com/api/feed"
    with DiagnosticRun(metrics, index_path, now=lambda: START) as run:
        run.record_snapshot(make_snapshot(endpoint, START, (post,)))
        run.finish("수집 정상")
    legacy = json.loads(index_path.read_text())
    legacy["version"] = 1
    old_event = legacy["events"][f"x:{post.id}"]
    old_event.pop("origin_time_basis", None)
    old_event["origin_time_bases"] = ["provider_observed", "x_source_field"]
    index_path.write_text(json.dumps(legacy))
    with DiagnosticRun(metrics, index_path, now=lambda: START + timedelta(seconds=10)) as run:
        run.record_snapshot(make_snapshot(endpoint, START + timedelta(seconds=10), ()))
        run.finish("부분 장애")
    migrated = json.loads(index_path.read_text())
    assert migrated["version"] == 2
    assert migrated["measurement_epoch"] == legacy["measurement_epoch"]
    assert migrated["endpoint_memberships"] == legacy["endpoint_memberships"]
    event = migrated["events"][f"x:{post.id}"]
    assert event == {**old_event, "origin_time_basis": "unknown"}
    corrected = replace(post, created_at=START - timedelta(minutes=20))
    with DiagnosticRun(metrics, index_path, now=lambda: START + timedelta(seconds=20)) as run:
        run.record_snapshot(make_snapshot(
            endpoint, START + timedelta(seconds=20), (corrected,),
            origin_time_bases=((post.id, "x_source_field"),),
        ))
        run.finish("수집 정상")
    event = json.loads(index_path.read_text())["events"][f"x:{post.id}"]
    assert event["origin_at"] == corrected.created_at.isoformat()
    assert event["origin_time_basis"] == "x_source_field"
    assert event["first_observed_at"] == old_event["first_observed_at"]


@pytest.mark.parametrize("basis", [None, [], "unrecognized"])
def test_index_rejects_invalid_selected_origin_basis_before_writing(
    tmp_path: Path, basis: object,
) -> None:
    metrics = tmp_path / "metrics.jsonl"
    index_path = tmp_path / "observations.json"
    post = make_post("2100000000000000072")
    with DiagnosticRun(metrics, index_path, now=lambda: START) as run:
        run.record_snapshot(make_snapshot("https://codex-reset.com/api/feed", START, (post,)))
        run.finish("수집 정상")
    payload = json.loads(index_path.read_text())
    payload["version"] = 2
    payload["events"][f"x:{post.id}"]["origin_time_basis"] = basis
    index_path.write_text(json.dumps(payload))
    before_index, before_metrics = index_path.read_bytes(), metrics.read_bytes()
    with pytest.raises(ValueError, match="진단 인덱스"):
        with DiagnosticRun(metrics, index_path, now=lambda: START):
            pass
    assert index_path.read_bytes() == before_index
    assert metrics.read_bytes() == before_metrics
