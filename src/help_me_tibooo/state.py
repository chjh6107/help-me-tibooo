import json
from datetime import datetime
from pathlib import Path

from .models import SourceCheckpoint, WatcherState


def load_state(path: Path) -> WatcherState | None:
    if not path.exists():
        return None

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("version") not in {1, 2}:
        raise ValueError("지원하지 않는 상태 버전입니다")

    latest_id = payload.get("latest_id")
    seen_ids = payload.get("seen_ids", [])
    consecutive_failures = payload.get("consecutive_failures", 0)
    outage_notified = payload.get("outage_notified", False)
    if latest_id is not None and not isinstance(latest_id, str):
        raise ValueError("latest_id의 형식이 잘못되었습니다")
    if not isinstance(seen_ids, list) or not all(isinstance(item, str) for item in seen_ids):
        raise ValueError("seen_ids의 형식이 잘못되었습니다")
    if isinstance(consecutive_failures, bool) or not isinstance(consecutive_failures, int):
        raise ValueError("consecutive_failures의 형식이 잘못되었습니다")
    if not isinstance(outage_notified, bool):
        raise ValueError("outage_notified의 형식이 잘못되었습니다")
    if "initialized" in payload:
        initialized = payload["initialized"]
        if not isinstance(initialized, bool):
            raise ValueError("initialized의 형식이 잘못되었습니다")
    else:
        initialized = bool(latest_id) or bool(seen_ids)

    if payload["version"] == 1:
        legacy_latest_id = (
            latest_id if latest_id is not None else (seen_ids[-1] if seen_ids else None)
        )
        source_checkpoints = (
            (SourceCheckpoint(source="*", latest_id=legacy_latest_id),)
            if initialized and legacy_latest_id is not None
            else ()
        )
    else:
        source_checkpoints = _load_source_checkpoints(payload.get("source_checkpoints", []))

    return WatcherState(
        latest_id=latest_id,
        seen_ids=tuple(seen_ids),
        consecutive_failures=consecutive_failures,
        outage_notified=outage_notified,
        initialized=initialized,
        source_checkpoints=source_checkpoints,
    )


def save_state(path: Path, state: WatcherState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    payload = {
        "version": 2,
        "latest_id": state.latest_id,
        "seen_ids": list(state.seen_ids[-500:]),
        "consecutive_failures": state.consecutive_failures,
        "outage_notified": state.outage_notified,
        "initialized": state.initialized,
        "source_checkpoints": [
            {
                "source": checkpoint.source,
                "latest_id": checkpoint.latest_id,
                "latest_created_at": (
                    checkpoint.latest_created_at.isoformat()
                    if checkpoint.latest_created_at is not None
                    else None
                ),
                "deferred_latest_id": checkpoint.deferred_latest_id,
                "deferred_latest_created_at": (
                    checkpoint.deferred_latest_created_at.isoformat()
                    if checkpoint.deferred_latest_created_at is not None
                    else None
                ),
                "pending_ids": list(checkpoint.pending_ids),
            }
            for checkpoint in state.source_checkpoints
        ],
    }
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _load_source_checkpoints(payload: object) -> tuple[SourceCheckpoint, ...]:
    if not isinstance(payload, list):
        raise ValueError("source_checkpoints의 형식이 잘못되었습니다")

    checkpoints: list[SourceCheckpoint] = []
    sources: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("source_checkpoints의 형식이 잘못되었습니다")
        source = item.get("source")
        latest_id = item.get("latest_id")
        latest_created_at = item.get("latest_created_at")
        deferred_latest_id = item.get("deferred_latest_id")
        deferred_latest_created_at = item.get("deferred_latest_created_at")
        pending_ids = item.get("pending_ids", [])
        if not isinstance(source, str) or not source or source in sources:
            raise ValueError("source_checkpoints의 형식이 잘못되었습니다")
        if latest_id is not None and not isinstance(latest_id, str):
            raise ValueError("source_checkpoints의 형식이 잘못되었습니다")
        if deferred_latest_id is not None and not isinstance(deferred_latest_id, str):
            raise ValueError("source_checkpoints의 형식이 잘못되었습니다")
        if not isinstance(pending_ids, list) or not all(
            isinstance(post_id, str) for post_id in pending_ids
        ):
            raise ValueError("source_checkpoints의 형식이 잘못되었습니다")
        parsed_created_at = _load_checkpoint_datetime(latest_created_at)
        parsed_deferred_created_at = _load_checkpoint_datetime(deferred_latest_created_at)
        sources.add(source)
        checkpoints.append(
            SourceCheckpoint(
                source=source,
                latest_id=latest_id,
                latest_created_at=parsed_created_at,
                deferred_latest_id=deferred_latest_id,
                deferred_latest_created_at=parsed_deferred_created_at,
                pending_ids=tuple(pending_ids),
            )
        )
    return tuple(checkpoints)


def _load_checkpoint_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("source_checkpoints의 형식이 잘못되었습니다")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("source_checkpoints의 형식이 잘못되었습니다") from None
    if parsed.tzinfo is None:
        raise ValueError("source_checkpoints의 형식이 잘못되었습니다")
    return parsed
