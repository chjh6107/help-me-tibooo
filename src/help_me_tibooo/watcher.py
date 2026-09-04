from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from help_me_tibooo.classifier import classify
from help_me_tibooo.models import (
    AlertDeliveryCheckpoint,
    AlertCategory,
    CheckpointPosition,
    Post,
    SourceBatch,
    SourceCheckpoint,
    SourceName,
    WatcherState,
)


class WatcherRunError(RuntimeError):
    def __init__(self, state: WatcherState) -> None:
        super().__init__("alert delivery failed")
        self.state = state


class AlertDeliveryInterrupted(RuntimeError):
    def __init__(self, next_payload_index: int) -> None:
        super().__init__("alert delivery interrupted")
        self.next_payload_index = next_payload_index


def run_watcher(
    batches: tuple[SourceBatch, ...],
    state: WatcherState | None,
    send_alert: Callable[[Post, tuple[AlertCategory, ...]], None],
    send_health: Callable[[int], None],
) -> WatcherState:
    current_state = _resume_pending_alert(
        state or WatcherState(),
        send_alert,
    )
    usable_batches = tuple(batch for batch in batches if batch.error is None and batch.posts)
    if not usable_batches:
        return _record_total_failure(current_state, send_health)

    next_state = _clear_failure_state(current_state)
    was_initialized = current_state.initialized
    baseline_posts: list[Post] = []
    candidate_posts: dict[str, Post] = {}
    candidate_sources: dict[str, list[SourceName]] = {}
    new_source_batches: list[SourceBatch] = []

    for batch in usable_batches:
        checkpoint = _find_checkpoint(current_state, batch.source)
        if checkpoint is None and current_state.initialized and not current_state.source_checkpoints:
            checkpoint = SourceCheckpoint(
                source=batch.source,
                position=CheckpointPosition(id=current_state.latest_id),
            )

        if checkpoint is None:
            new_source_batches.append(batch)
            continue

        source_checkpoint = replace(checkpoint, source=batch.source)
        next_state = _set_checkpoint(next_state, source_checkpoint)
        for post in batch.posts:
            if not _post_is_eligible(post, source_checkpoint):
                continue
            candidate_posts.setdefault(post.id, post)
            candidate_sources.setdefault(post.id, []).append(batch.source)

    for batch in new_source_batches:
        safe_checkpoint = SourceCheckpoint(source=batch.source)
        overlap_found = False
        pending_ids: list[str] = []
        for post in _oldest_first(batch.posts):
            baseline_posts.append(post)
            if post.id in candidate_posts:
                overlap_found = True
                pending_ids.append(post.id)
                candidate_sources[post.id].append(batch.source)
            elif not overlap_found:
                safe_checkpoint = _advance_checkpoint(safe_checkpoint, post)
        full_checkpoint = _baseline_checkpoint(batch.source, batch.posts)
        if pending_ids:
            safe_checkpoint = replace(
                safe_checkpoint,
                deferred_position=full_checkpoint.position,
                pending_ids=tuple(pending_ids),
            )
        else:
            safe_checkpoint = full_checkpoint
        next_state = _set_checkpoint(next_state, safe_checkpoint)

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
                tracking_sources = set(candidate_sources[post.id])
                tracking_sources.update(
                    checkpoint.source
                    for checkpoint in next_state.source_checkpoints
                    if post.id in checkpoint.pending_ids
                )
                try:
                    send_alert(post, categories)
                except AlertDeliveryInterrupted as error:
                    next_state = replace(
                        next_state,
                        alert_delivery=_delivery_checkpoint(
                            post,
                            categories,
                            tracking_sources,
                            error.next_payload_index,
                        ),
                    )
                    raise WatcherRunError(next_state) from None
                except Exception:
                    next_state = replace(
                        next_state,
                        alert_delivery=_delivery_checkpoint(
                            post,
                            categories,
                            tracking_sources,
                            0,
                        ),
                    )
                    raise WatcherRunError(next_state) from None
        next_state = _remember(next_state, post.id)
        tracking_sources = set(candidate_sources[post.id])
        tracking_sources.update(
            checkpoint.source
            for checkpoint in next_state.source_checkpoints
            if post.id in checkpoint.pending_ids
        )
        for source in tracking_sources:
            checkpoint = _find_checkpoint(next_state, source)
            if checkpoint is not None:
                next_state = _set_checkpoint(
                    next_state,
                    _complete_checkpoint_post(checkpoint, post),
                )

    return next_state


def _resume_pending_alert(
    state: WatcherState,
    send_alert: Callable[[Post, tuple[AlertCategory, ...]], None],
) -> WatcherState:
    checkpoint = state.alert_delivery
    if checkpoint is None:
        return state

    try:
        send_alert(checkpoint.post, checkpoint.categories)
    except AlertDeliveryInterrupted as error:
        raise WatcherRunError(
            replace(
                state,
                alert_delivery=replace(
                    checkpoint,
                    next_payload_index=error.next_payload_index,
                ),
            )
        ) from None
    except Exception:
        raise WatcherRunError(state) from None

    next_state = _remember(replace(state, alert_delivery=None), checkpoint.post_id)
    for source in checkpoint.sources:
        source_checkpoint = _find_checkpoint(next_state, source)
        if source_checkpoint is not None:
            next_state = _set_checkpoint(
                next_state,
                _complete_checkpoint_post(source_checkpoint, checkpoint.post),
            )
    return next_state


def _delivery_checkpoint(
    post: Post,
    categories: tuple[AlertCategory, ...],
    sources: set[SourceName],
    next_payload_index: int,
) -> AlertDeliveryCheckpoint:
    return AlertDeliveryCheckpoint(
        post=post,
        categories=categories,
        sources=tuple(sorted(sources)),
        next_payload_index=next_payload_index,
    )


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


def _find_checkpoint(state: WatcherState, source: SourceName) -> SourceCheckpoint | None:
    legacy: SourceCheckpoint | None = None
    for checkpoint in state.source_checkpoints:
        if checkpoint.source == source:
            return checkpoint
        if checkpoint.source == SourceName.LEGACY:
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


def _baseline_checkpoint(source: SourceName, posts: tuple[Post, ...]) -> SourceCheckpoint:
    checkpoint = SourceCheckpoint(source=source)
    for post in _oldest_first(posts):
        checkpoint = _advance_checkpoint(checkpoint, post)
    return checkpoint


def _advance_checkpoint(checkpoint: SourceCheckpoint, post: Post) -> SourceCheckpoint:
    position = _advance_position(checkpoint.position, post)
    if position is checkpoint.position:
        return checkpoint
    return replace(checkpoint, position=position)


def _complete_checkpoint_post(checkpoint: SourceCheckpoint, post: Post) -> SourceCheckpoint:
    pending_ids = tuple(post_id for post_id in checkpoint.pending_ids if post_id != post.id)
    updated = replace(checkpoint, pending_ids=pending_ids)
    if checkpoint.pending_ids and not pending_ids:
        updated = replace(
            updated,
            position=checkpoint.deferred_position or checkpoint.position,
            deferred_position=None,
        )
    if updated.pending_ids:
        deferred_position = updated.deferred_position or updated.position
        advanced = _advance_position(deferred_position, post)
        return replace(
            updated,
            deferred_position=advanced,
        )
    return _advance_checkpoint(updated, post)


def _post_is_eligible(post: Post, checkpoint: SourceCheckpoint) -> bool:
    if post.id in checkpoint.pending_ids:
        return True
    if checkpoint.deferred_position is not None:
        return _post_is_after_position(post, checkpoint.deferred_position)
    return _post_is_after_position(post, checkpoint.position)


def _advance_position(position: CheckpointPosition, post: Post) -> CheckpointPosition:
    if not _post_is_after_position(post, position):
        return position
    return CheckpointPosition(id=post.id, created_at=_aware_datetime(post.created_at))


def _post_is_after_position(post: Post, position: CheckpointPosition) -> bool:
    if position.id is None:
        return True
    if post.id == position.id:
        return False
    if post.id.isdigit() and position.id.isdigit():
        return int(post.id) > int(position.id)

    post_created_at = _aware_datetime(post.created_at)
    checkpoint_created_at = _aware_datetime(position.created_at)
    if post_created_at is not None and checkpoint_created_at is not None:
        return (post_created_at, post.id) > (checkpoint_created_at, position.id)
    return post.id > position.id


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
