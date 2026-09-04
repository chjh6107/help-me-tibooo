from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from help_me_tibooo.classifier import classify
from help_me_tibooo.models import (
    AlertCategory,
    Post,
    SourceBatch,
    SourceCheckpoint,
    WatcherState,
)


class WatcherRunError(RuntimeError):
    def __init__(self, state: WatcherState) -> None:
        super().__init__("alert delivery failed")
        self.state = state


def run_watcher(
    batches: tuple[SourceBatch, ...],
    state: WatcherState | None,
    send_alert: Callable[[Post, tuple[AlertCategory, ...]], None],
    send_health: Callable[[int], None],
) -> WatcherState:
    healthy_batches = tuple(batch for batch in batches if batch.error is None)
    if not healthy_batches:
        return _record_total_failure(state or WatcherState(), send_health)

    current_state = state or WatcherState()
    next_state = _clear_failure_state(current_state)
    was_initialized = current_state.initialized
    baseline_posts: list[Post] = []
    candidate_posts: dict[str, Post] = {}
    candidate_sources: dict[str, list[str]] = {}

    for batch in healthy_batches:
        checkpoint = _find_checkpoint(current_state, batch.source)
        if checkpoint is None and current_state.initialized and not current_state.source_checkpoints:
            checkpoint = SourceCheckpoint(source=batch.source, latest_id=current_state.latest_id)

        if checkpoint is None:
            source_checkpoint = _baseline_checkpoint(batch.source, batch.posts)
            next_state = _set_checkpoint(next_state, source_checkpoint)
            baseline_posts.extend(batch.posts)
            continue

        source_checkpoint = replace(checkpoint, source=batch.source)
        next_state = _set_checkpoint(next_state, source_checkpoint)
        for post in batch.posts:
            if not _post_is_after_checkpoint(post, source_checkpoint):
                continue
            candidate_posts.setdefault(post.id, post)
            candidate_sources.setdefault(post.id, []).append(batch.source)

    for post in _oldest_first(tuple(baseline_posts)):
        if post.id not in candidate_posts:
            next_state = (
                _remember_seen_only(next_state, post.id)
                if was_initialized
                else _remember(next_state, post.id)
            )

    for post in _oldest_first(tuple(candidate_posts.values())):
        if post.id not in next_state.seen_ids:
            categories = classify(post)
            if categories:
                try:
                    send_alert(post, categories)
                except Exception:
                    raise WatcherRunError(next_state) from None
        next_state = _remember(next_state, post.id)
        for source in candidate_sources[post.id]:
            checkpoint = _find_checkpoint(next_state, source)
            if checkpoint is not None:
                next_state = _set_checkpoint(
                    next_state,
                    _advance_checkpoint(checkpoint, post),
                )

    return next_state


def _record_total_failure(
    state: WatcherState,
    send_health: Callable[[int], None],
) -> WatcherState:
    next_state = replace(state, consecutive_failures=state.consecutive_failures + 1)
    if next_state.consecutive_failures < 3 or next_state.outage_notified:
        return next_state

    try:
        send_health(next_state.consecutive_failures)
    except Exception:
        return next_state
    return replace(next_state, outage_notified=True)


def _find_checkpoint(state: WatcherState, source: str) -> SourceCheckpoint | None:
    legacy: SourceCheckpoint | None = None
    for checkpoint in state.source_checkpoints:
        if checkpoint.source == source:
            return checkpoint
        if checkpoint.source == "*":
            legacy = checkpoint
    return legacy


def _set_checkpoint(state: WatcherState, checkpoint: SourceCheckpoint) -> WatcherState:
    checkpoints = list(state.source_checkpoints)
    for index, current in enumerate(checkpoints):
        if current.source == checkpoint.source:
            checkpoints[index] = checkpoint
            break
    else:
        checkpoints.append(checkpoint)
    return replace(state, initialized=True, source_checkpoints=tuple(checkpoints))


def _baseline_checkpoint(source: str, posts: tuple[Post, ...]) -> SourceCheckpoint:
    checkpoint = SourceCheckpoint(source=source)
    for post in _oldest_first(posts):
        checkpoint = _advance_checkpoint(checkpoint, post)
    return checkpoint


def _advance_checkpoint(checkpoint: SourceCheckpoint, post: Post) -> SourceCheckpoint:
    if not _post_is_after_checkpoint(post, checkpoint):
        return checkpoint
    return replace(
        checkpoint,
        latest_id=post.id,
        latest_created_at=_aware_datetime(post.created_at),
    )


def _post_is_after_checkpoint(post: Post, checkpoint: SourceCheckpoint) -> bool:
    if checkpoint.latest_id is None:
        return True
    if post.id == checkpoint.latest_id:
        return False
    if post.id.isdigit() and checkpoint.latest_id.isdigit():
        return int(post.id) > int(checkpoint.latest_id)

    post_created_at = _aware_datetime(post.created_at)
    checkpoint_created_at = _aware_datetime(checkpoint.latest_created_at)
    if post_created_at is not None and checkpoint_created_at is not None:
        return (post_created_at, post.id) > (checkpoint_created_at, checkpoint.latest_id)
    return post.id > checkpoint.latest_id


def _clear_failure_state(state: WatcherState) -> WatcherState:
    return replace(state, consecutive_failures=0, outage_notified=False)


def _oldest_first(posts: tuple[Post, ...]) -> tuple[Post, ...]:
    ordered = sorted(enumerate(posts), key=lambda item: _post_sort_key(item[1], item[0]))
    return tuple(post for _, post in ordered)


def _post_sort_key(post: Post, input_order: int) -> tuple[int, int, float, int]:
    try:
        return (0, int(post.id), 0.0, input_order)
    except ValueError:
        return (1, 0, _created_at_timestamp(post.created_at), input_order)


def _created_at_timestamp(created_at: datetime | None) -> float:
    aware = _aware_datetime(created_at)
    if aware is None:
        return float("inf")
    return aware.timestamp()


def _aware_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _remember(state: WatcherState, post_id: str) -> WatcherState:
    if post_id in state.seen_ids:
        return state
    return replace(state, latest_id=post_id, seen_ids=(*state.seen_ids, post_id))


def _remember_seen_only(state: WatcherState, post_id: str) -> WatcherState:
    if post_id in state.seen_ids:
        return state
    return replace(state, seen_ids=(*state.seen_ids, post_id))
