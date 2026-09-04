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
        source_checkpoints = (
            (SourceCheckpoint(source="*", latest_id=latest_id),)
            if initialized and latest_id is not None
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
        if not isinstance(source, str) or not source or source in sources:
            raise ValueError("source_checkpoints의 형식이 잘못되었습니다")
        if latest_id is not None and not isinstance(latest_id, str):
            raise ValueError("source_checkpoints의 형식이 잘못되었습니다")
        if latest_created_at is not None:
            if not isinstance(latest_created_at, str):
                raise ValueError("source_checkpoints의 형식이 잘못되었습니다")
            try:
                parsed_created_at = datetime.fromisoformat(latest_created_at)
            except ValueError:
                raise ValueError("source_checkpoints의 형식이 잘못되었습니다") from None
            if parsed_created_at.tzinfo is None:
                raise ValueError("source_checkpoints의 형식이 잘못되었습니다")
        else:
            parsed_created_at = None
        sources.add(source)
        checkpoints.append(
            SourceCheckpoint(
                source=source,
                latest_id=latest_id,
                latest_created_at=parsed_created_at,
            )
        )
    return tuple(checkpoints)
