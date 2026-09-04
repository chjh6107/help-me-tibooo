import json
from datetime import datetime
from pathlib import Path

from .models import (
    AlertDeliveryCheckpoint,
    CheckpointPosition,
    SourceCheckpoint,
    SourceName,
    WatcherState,
)


def load_state(path: Path) -> WatcherState | None:
    if not path.exists():
        return None

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("version") not in {1, 2, 3}:
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
            (
                SourceCheckpoint(
                    source=SourceName.LEGACY,
                    position=CheckpointPosition(id=legacy_latest_id),
                ),
            )
            if initialized and legacy_latest_id is not None
            else ()
        )
    else:
        source_checkpoints = _load_source_checkpoints(payload.get("source_checkpoints", []))
    alert_delivery = (
        _load_alert_delivery(payload.get("alert_delivery"))
        if payload["version"] == 3
        else None
    )

    return WatcherState(
        latest_id=latest_id,
        seen_ids=tuple(seen_ids),
        consecutive_failures=consecutive_failures,
        outage_notified=outage_notified,
        initialized=initialized,
        source_checkpoints=source_checkpoints,
        alert_delivery=alert_delivery,
    )


def save_state(path: Path, state: WatcherState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    payload = {
        "version": 3,
        "latest_id": state.latest_id,
        "seen_ids": list(state.seen_ids[-500:]),
        "consecutive_failures": state.consecutive_failures,
        "outage_notified": state.outage_notified,
        "initialized": state.initialized,
        "source_checkpoints": [
            {
                "source": checkpoint.source,
                "latest_id": checkpoint.position.id,
                "latest_created_at": (
                    checkpoint.position.created_at.isoformat()
                    if checkpoint.position.created_at is not None
                    else None
                ),
                "deferred_latest_id": (
                    checkpoint.deferred_position.id
                    if checkpoint.deferred_position is not None
                    else None
                ),
                "deferred_latest_created_at": (
                    checkpoint.deferred_position.created_at.isoformat()
                    if checkpoint.deferred_position is not None
                    and checkpoint.deferred_position.created_at is not None
                    else None
                ),
                "pending_ids": list(checkpoint.pending_ids),
            }
            for checkpoint in state.source_checkpoints
        ],
        "alert_delivery": (
            {
                "post_id": state.alert_delivery.post_id,
                "next_payload_index": state.alert_delivery.next_payload_index,
            }
            if state.alert_delivery is not None
            else None
        ),
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
        try:
            source_name = SourceName(source)
        except ValueError:
            raise ValueError("source_checkpoints의 형식이 잘못되었습니다") from None
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
                source=source_name,
                position=CheckpointPosition(id=latest_id, created_at=parsed_created_at),
                deferred_position=(
                    CheckpointPosition(
                        id=deferred_latest_id,
                        created_at=parsed_deferred_created_at,
                    )
                    if deferred_latest_id is not None
                    else None
                ),
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


def _load_alert_delivery(value: object) -> AlertDeliveryCheckpoint | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("alert_delivery의 형식이 잘못되었습니다")

    post_id = value.get("post_id")
    next_payload_index = value.get("next_payload_index")
    if not isinstance(post_id, str) or not post_id:
        raise ValueError("alert_delivery의 형식이 잘못되었습니다")
    if (
        isinstance(next_payload_index, bool)
        or not isinstance(next_payload_index, int)
        or next_payload_index < 0
    ):
        raise ValueError("alert_delivery의 형식이 잘못되었습니다")
    return AlertDeliveryCheckpoint(
        post_id=post_id,
        next_payload_index=next_payload_index,
    )
