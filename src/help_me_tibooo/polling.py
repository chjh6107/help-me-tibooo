import math
import sys
import time
from collections.abc import Callable

from help_me_tibooo.watcher import WatcherRunError


def run_polling_session(
    collect: Callable[[], int],
    *,
    interval_seconds: float = 120,
    duration_seconds: float = 600,
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> int:
    if any(not math.isfinite(value) or value <= 0 for value in (interval_seconds, duration_seconds)):
        raise ValueError("수집 간격과 세션 길이는 유한한 양수여야 합니다")
    clock = clock or time.monotonic
    sleep = sleep or time.sleep
    started_at = clock()
    deadline = started_at + duration_seconds
    next_tick = started_at
    failed = False

    while next_tick < deadline:
        delay = next_tick - clock()
        if delay > 0:
            sleep(delay)
        if clock() >= deadline:
            break
        print(f"반복 감시: 세션 시작 후 {clock() - started_at:.0f}초", flush=True)
        try:
            failed = collect() != 0 or failed
        except WatcherRunError as error:
            print(f"감시 실행 실패: {error}", file=sys.stderr, flush=True)
            failed = True
        next_tick = started_at + (math.floor((clock() - started_at) / interval_seconds) + 1) * interval_seconds

    return 1 if failed else 0
