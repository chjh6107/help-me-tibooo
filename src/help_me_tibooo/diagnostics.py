import hashlib
import json
import os
import re
import sys
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Self
from urllib.parse import urlsplit

from help_me_tibooo.classifier import classify
from help_me_tibooo.models import AlertCategory, Post, SourceSnapshot
from help_me_tibooo.runtime import exclusive_state


INDEX_VERSION = 1
X_POST_PATH = re.compile(r"/[A-Za-z0-9_]{1,15}/status/([0-9]{1,20})")
SAFE_COMPONENT = re.compile(r"[A-Za-z0-9._-]{1,200}")
SAFE_CACHE_HEADERS = {
    "age",
    "cache-control",
    "date",
    "etag",
    "last-modified",
    "retry-after",
}


class DiagnosticIndexError(ValueError):
    pass


def canonical_post_key(post: Post, provider: str) -> str:
    parsed = urlsplit(post.url)
    if parsed.hostname == "x.com":
        match = X_POST_PATH.fullmatch(parsed.path)
        if (
            parsed.scheme != "https"
            or match is None
            or parsed.query
            or parsed.fragment
            or match[1] != post.id
        ):
            raise ValueError("X 게시물 URL과 ID가 일치하지 않습니다")
        return f"x:{post.id}"

    if not SAFE_COMPONENT.fullmatch(provider) or not SAFE_COMPONENT.fullmatch(post.id):
        raise ValueError("제공자 게시물 식별자가 잘못되었습니다")
    return f"provider:{provider}:{post.id}"


def evidence_hash(post: Post) -> str:
    evidence = {
        "id": post.id,
        "is_reply": post.is_reply,
        "is_repost": post.is_repost,
        "source": post.source.value,
        "source_kind": post.source_kind.value if post.source_kind is not None else None,
        "text": post.text,
        "url": post.url,
    }
    serialized = json.dumps(
        evidence,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(serialized).hexdigest()


class DiagnosticRun:
    def __init__(
        self,
        metrics_path: Path,
        index_path: Path,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.metrics_path = metrics_path
        self.index_path = index_path
        self._now = now or (lambda: datetime.now(UTC))
        self.run_id = uuid.uuid4().hex
        self._lock: Any = None
        self._index: dict[str, Any] | None = None
        self._finished = False
        self._partial_memberships: dict[str, set[str]] = {}

    def __enter__(self) -> Self:
        self._lock = exclusive_state(self.index_path)
        self._lock.__enter__()
        try:
            started_at = _utc(self._now())
            self._index = self._load_or_create_index(started_at)
            self._append(
                {
                    "event": "run_started",
                    "started_at": started_at.isoformat(),
                }
            )
        except BaseException:
            self._lock.__exit__(*sys.exc_info())
            self._lock = None
            raise
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        try:
            if not self._finished:
                self._append(
                    {
                        "event": "run_finished",
                        "finished_at": _utc(self._now()).isoformat(),
                        "status": "failed" if exception_type is not None else "unknown",
                    }
                )
        finally:
            if self._lock is not None:
                self._lock.__exit__(exception_type, exception, traceback)
                self._lock = None
        return False

    def record_snapshot(self, snapshot: SourceSnapshot) -> None:
        index = self._require_index()
        observed_ids = [canonical_post_key(post, snapshot.provider) for post in snapshot.posts]
        membership = set(observed_ids)
        previous = index["endpoint_memberships"].get(snapshot.endpoint)
        overlap = "unknown"
        overlap_count: int | None = None

        if snapshot.error is not None:
            self._partial_memberships.pop(snapshot.endpoint, None)
        elif not snapshot.complete:
            self._partial_memberships.setdefault(snapshot.endpoint, set()).update(membership)
        else:
            membership.update(self._partial_memberships.pop(snapshot.endpoint, set()))
            if previous is not None:
                intersection = membership.intersection(previous["canonical_ids"])
                overlap = "overlap" if intersection else "none"
                overlap_count = len(intersection)

        self._append(
            {
                "event": "source_fetched",
                "source": snapshot.source.value,
                "provider": snapshot.provider,
                "endpoint": snapshot.endpoint,
                "page": snapshot.page,
                "complete": snapshot.complete,
                "request_started_at": _iso(snapshot.request_started_at),
                "response_received_at": _iso(snapshot.response_received_at),
                "observed_at": _iso(snapshot.observed_at),
                "http_status": snapshot.http_status,
                "cache_headers": _safe_cache_headers(snapshot.cache_headers),
                "representation_hash": snapshot.representation_hash,
                "outcome": _snapshot_outcome(snapshot),
                "count": len(observed_ids),
                "head": observed_ids[0] if observed_ids else None,
                "tail": observed_ids[-1] if observed_ids else None,
                "membership_overlap": overlap,
                "membership_overlap_count": overlap_count,
            }
        )

        origin_time_bases = dict(snapshot.origin_time_bases)
        for post, canonical_id in zip(snapshot.posts, observed_ids, strict=True):
            if snapshot.observed_at is None:
                continue
            observed_at = _utc(snapshot.observed_at)
            post_hash = evidence_hash(post)
            origin_basis = origin_time_bases.get(post.id, "unknown")
            self._record_observation(
                snapshot,
                post,
                canonical_id,
                post_hash,
                origin_basis,
                observed_at,
            )
            categories = classify(post)
            self._append(
                {
                    "event": "classified",
                    "canonical_id": canonical_id,
                    "evidence_hash": post_hash,
                    "categories": [category.value for category in categories],
                    "classified_at": observed_at.isoformat(),
                }
            )

        if snapshot.error is None and snapshot.complete and snapshot.observed_at is not None:
            index["endpoint_memberships"][snapshot.endpoint] = {
                "canonical_ids": sorted(membership),
                "last_successful_at": _iso(snapshot.observed_at),
            }
        self._save_index()

    def record_alert(
        self,
        post: Post,
        outcome: str,
        categories: tuple[AlertCategory, ...],
    ) -> None:
        self.record_delivery(
            "post",
            canonical_post_key(post, _post_provider(post)),
            outcome,
            categories,
            post_hash=evidence_hash(post),
        )

    def record_delivery(
        self,
        notification_kind: str,
        identifier: str,
        outcome: str,
        categories: tuple[AlertCategory, ...] = (),
        *,
        post_hash: str | None = None,
    ) -> None:
        if outcome not in {"attempted", "succeeded", "failed"}:
            raise ValueError("알림 결과가 잘못되었습니다")
        if not SAFE_COMPONENT.fullmatch(notification_kind) or not SAFE_COMPONENT.fullmatch(
            identifier.replace(":", "-")
        ):
            raise ValueError("알림 식별자가 잘못되었습니다")
        self._append(
            {
                "event": "alert_delivery",
                "notification_kind": notification_kind,
                "canonical_id": identifier,
                "evidence_hash": post_hash,
                "categories": [category.value for category in categories],
                "outcome": outcome,
                "recorded_at": _utc(self._now()).isoformat(),
            }
        )

    def finish(self, status: str) -> None:
        if self._finished:
            return
        self._append(
            {
                "event": "run_finished",
                "finished_at": _utc(self._now()).isoformat(),
                "status": status,
            }
        )
        self._finished = True

    def _record_observation(
        self,
        snapshot: SourceSnapshot,
        post: Post,
        canonical_id: str,
        post_hash: str,
        origin_basis: str,
        observed_at: datetime,
    ) -> None:
        index = self._require_index()
        observed = observed_at.isoformat()
        event = index["events"].setdefault(
            canonical_id,
            {
                "first_observed_at": observed,
                "last_observed_at": observed,
                "origin_at": _iso(post.created_at),
                "origin_time_bases": [],
                "provider_visible_at": None,
                "endpoints": {},
                "versions": {},
            },
        )
        event["last_observed_at"] = observed
        if origin_basis not in event["origin_time_bases"]:
            event["origin_time_bases"].append(origin_basis)
            event["origin_time_bases"].sort()

        endpoint = event["endpoints"].setdefault(
            snapshot.endpoint,
            {
                "provider": snapshot.provider,
                "first_observed_at": observed,
                "last_observed_at": observed,
            },
        )
        endpoint["last_observed_at"] = observed
        version = event["versions"].setdefault(
            post_hash,
            {
                "first_observed_at": observed,
                "last_observed_at": observed,
            },
        )
        version["last_observed_at"] = observed

        latency = None
        latency_valid = None
        if post.created_at is not None:
            latency = (observed_at - _utc(post.created_at)).total_seconds()
            latency_valid = latency >= 0
        self._append(
            {
                "event": "post_observed",
                "canonical_id": canonical_id,
                "evidence_hash": post_hash,
                "source": snapshot.source.value,
                "provider": snapshot.provider,
                "endpoint": snapshot.endpoint,
                "observed_at": observed,
                "origin_at": _iso(post.created_at),
                "origin_time_basis": origin_basis,
                "provider_visible_at": None,
                "origin_latency_seconds": latency,
                "origin_latency_valid": latency_valid,
            }
        )

    def _load_or_create_index(self, started_at: datetime) -> dict[str, Any]:
        try:
            serialized = self.index_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {
                "version": INDEX_VERSION,
                "measurement_epoch": started_at.isoformat(),
                "events": {},
                "endpoint_memberships": {},
            }
        except OSError as error:
            raise DiagnosticIndexError("진단 인덱스를 읽을 수 없습니다") from error

        try:
            index = json.loads(serialized)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise DiagnosticIndexError("진단 인덱스의 형식이 잘못되었습니다") from error
        if not _valid_index(index):
            raise DiagnosticIndexError("진단 인덱스의 형식이 잘못되었습니다")
        return index

    def _save_index(self) -> None:
        index = self._require_index()
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.index_path.with_suffix(".tmp")
        serialized = json.dumps(
            index,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        descriptor = os.open(
            temporary_path,
            os.O_CREAT | os.O_TRUNC | os.O_WRONLY | os.O_NOFOLLOW,
            0o600,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                descriptor = -1
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        temporary_path.replace(self.index_path)

    def _append(self, event: dict[str, Any]) -> None:
        self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"run_id": self.run_id, **event}
        with self.metrics_path.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n"
            )
            stream.flush()

    def _require_index(self) -> dict[str, Any]:
        if self._index is None:
            raise RuntimeError("진단 실행이 시작되지 않았습니다")
        return self._index


def _valid_index(index: object) -> bool:
    if not isinstance(index, dict):
        return False
    if index.get("version") != INDEX_VERSION:
        return False
    if not _valid_timestamp(index.get("measurement_epoch")):
        return False
    events = index.get("events")
    if not isinstance(events, dict):
        return False
    if not all(
        isinstance(canonical_id, str) and _valid_event(event)
        for canonical_id, event in events.items()
    ):
        return False
    memberships = index.get("endpoint_memberships")
    if not isinstance(memberships, dict):
        return False
    if not all(
        isinstance(endpoint, str) and _valid_membership(membership)
        for endpoint, membership in memberships.items()
    ):
        return False
    return True


def _valid_event(event: object) -> bool:
    if not isinstance(event, dict):
        return False
    if not _valid_timestamp(event.get("first_observed_at")) or not _valid_timestamp(
        event.get("last_observed_at")
    ):
        return False
    origin_at = event.get("origin_at")
    if origin_at is not None and not _valid_timestamp(origin_at):
        return False
    if event.get("provider_visible_at") is not None:
        return False
    origin_time_bases = event.get("origin_time_bases")
    if not isinstance(origin_time_bases, list) or not all(
        isinstance(basis, str) for basis in origin_time_bases
    ):
        return False
    endpoints = event.get("endpoints")
    if not isinstance(endpoints, dict) or not all(
        isinstance(endpoint, str)
        and isinstance(observation, dict)
        and isinstance(observation.get("provider"), str)
        and _valid_timestamp(observation.get("first_observed_at"))
        and _valid_timestamp(observation.get("last_observed_at"))
        for endpoint, observation in endpoints.items()
    ):
        return False
    versions = event.get("versions")
    return isinstance(versions, dict) and all(
        isinstance(post_hash, str)
        and re.fullmatch(r"[0-9a-f]{64}", post_hash) is not None
        and isinstance(version, dict)
        and _valid_timestamp(version.get("first_observed_at"))
        and _valid_timestamp(version.get("last_observed_at"))
        for post_hash, version in versions.items()
    )


def _valid_membership(membership: object) -> bool:
    if not isinstance(membership, dict):
        return False
    canonical_ids = membership.get("canonical_ids")
    return (
        isinstance(canonical_ids, list)
        and all(isinstance(canonical_id, str) for canonical_id in canonical_ids)
        and _valid_timestamp(membership.get("last_successful_at"))
    )


def _valid_timestamp(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _post_provider(post: Post) -> str:
    return {
        "reset": "codex-reset.com",
        "twiscan": "twiscan.com",
        "resets": "codex-resets.com",
    }.get(post.source.value, "watcher")


def _snapshot_outcome(snapshot: SourceSnapshot) -> str:
    if snapshot.error is not None:
        return "failed"
    if not snapshot.complete:
        return "pagination_partial"
    if not snapshot.posts:
        return "empty"
    return "success"


def _safe_cache_headers(headers: tuple[tuple[str, str], ...]) -> dict[str, str]:
    return {
        name: value[:1000]
        for name, value in headers
        if name.lower() in SAFE_CACHE_HEADERS
        and "\n" not in value
        and "\r" not in value
    }


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("진단 시각에는 시간대가 필요합니다")
    return value.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    return _utc(value).isoformat() if value is not None else None
