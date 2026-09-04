from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from help_me_tibooo.classifier import classify
from help_me_tibooo.models import AlertCategory, Post, SourceBatch, WatcherState


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

    posts = _deduplicate_posts(healthy_batches)
    if state is None or not state.initialized:
        return _baseline(posts)

    next_state = _clear_failure_state(state)
    for post in _unseen_posts_oldest_first(posts, state.seen_ids):
        categories = classify(post)
        if categories:
            try:
                send_alert(post, categories)
            except Exception:
                raise WatcherRunError(next_state) from None
        next_state = _remember(next_state, post.id)
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


def _deduplicate_posts(batches: tuple[SourceBatch, ...]) -> tuple[Post, ...]:
    posts_by_id: dict[str, Post] = {}
    for batch in batches:
        for post in batch.posts:
            posts_by_id.setdefault(post.id, post)
    return tuple(posts_by_id.values())


def _baseline(posts: tuple[Post, ...]) -> WatcherState:
    state = WatcherState(initialized=True)
    for post in _oldest_first(posts):
        state = _remember(state, post.id)
    return state


def _clear_failure_state(state: WatcherState) -> WatcherState:
    return replace(state, consecutive_failures=0, outage_notified=False)


def _unseen_posts_oldest_first(posts: tuple[Post, ...], seen_ids: tuple[str, ...]) -> tuple[Post, ...]:
    seen = set(seen_ids)
    return tuple(post for post in _oldest_first(posts) if post.id not in seen)


def _oldest_first(posts: tuple[Post, ...]) -> tuple[Post, ...]:
    ordered = sorted(enumerate(posts), key=lambda item: _post_sort_key(item[1], item[0]))
    return tuple(post for _, post in ordered)


def _post_sort_key(post: Post, input_order: int) -> tuple[int, int, float, int]:
    try:
        return (0, int(post.id), 0.0, input_order)
    except ValueError:
        return (1, 0, _created_at_timestamp(post.created_at), input_order)


def _created_at_timestamp(created_at: datetime | None) -> float:
    if created_at is None:
        return float("inf")
    if created_at.tzinfo is None:
        return created_at.replace(tzinfo=UTC).timestamp()
    return created_at.timestamp()


def _remember(state: WatcherState, post_id: str) -> WatcherState:
    if post_id in state.seen_ids:
        return replace(state, latest_id=post_id)
    return replace(state, latest_id=post_id, seen_ids=(*state.seen_ids, post_id))
