import json
from pathlib import Path

from .models import WatcherState


def load_state(path: Path) -> WatcherState | None:
    if not path.exists():
        return None

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("지원하지 않는 상태 버전입니다")

    latest_id = payload.get("latest_id")
    seen_ids = payload.get("seen_ids", [])
    consecutive_failures = payload.get("consecutive_failures", 0)
    outage_notified = payload.get("outage_notified", False)
    initialized = payload.get("initialized", False)
    if latest_id is not None and not isinstance(latest_id, str):
        raise ValueError("latest_id의 형식이 잘못되었습니다")
    if not isinstance(seen_ids, list) or not all(isinstance(item, str) for item in seen_ids):
        raise ValueError("seen_ids의 형식이 잘못되었습니다")
    if isinstance(consecutive_failures, bool) or not isinstance(consecutive_failures, int):
        raise ValueError("consecutive_failures의 형식이 잘못되었습니다")
    if not isinstance(outage_notified, bool):
        raise ValueError("outage_notified의 형식이 잘못되었습니다")
    if not isinstance(initialized, bool):
        raise ValueError("initialized의 형식이 잘못되었습니다")

    return WatcherState(
        latest_id=latest_id,
        seen_ids=tuple(seen_ids),
        consecutive_failures=consecutive_failures,
        outage_notified=outage_notified,
        initialized=initialized,
    )


def save_state(path: Path, state: WatcherState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    payload = {
        "version": 1,
        "latest_id": state.latest_id,
        "seen_ids": list(state.seen_ids[-500:]),
        "consecutive_failures": state.consecutive_failures,
        "outage_notified": state.outage_notified,
        "initialized": state.initialized,
    }
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
