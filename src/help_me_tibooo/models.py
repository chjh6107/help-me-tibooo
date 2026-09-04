from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class AlertCategory(StrEnum):
    RESET = "리셋"
    LIMITS = "한도"
    LAUNCH = "출시"
    PLANS = "요금제"
    INCIDENT = "장애"


class SourceName(StrEnum):
    RESET = "reset"
    TWISCAN = "twiscan"
    LEGACY = "*"


class ResetSourceKind(StrEnum):
    CANDIDATE = "candidate"
    BANKED = "banked"
    SIGNAL = "signal"
    LIMITS = "limits"
    ANNOUNCEMENT = "announcement"


@dataclass(frozen=True, slots=True)
class Post:
    id: str
    text: str
    created_at: datetime | None
    url: str
    source: SourceName
    is_reply: bool = False
    is_repost: bool = False
    source_kind: ResetSourceKind | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", SourceName(self.source))
        if self.source_kind is not None:
            object.__setattr__(self, "source_kind", ResetSourceKind(self.source_kind))


@dataclass(frozen=True, slots=True)
class SourceBatch:
    source: SourceName
    posts: tuple[Post, ...] = ()
    error: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", SourceName(self.source))


@dataclass(frozen=True, slots=True)
class CheckpointPosition:
    id: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True, init=False)
class SourceCheckpoint:
    source: SourceName
    position: CheckpointPosition = CheckpointPosition()
    deferred_position: CheckpointPosition | None = None
    pending_ids: tuple[str, ...] = ()

    def __init__(
        self,
        source: SourceName | str,
        position: CheckpointPosition | None = None,
        deferred_position: CheckpointPosition | None = None,
        pending_ids: tuple[str, ...] = (),
        *,
        latest_id: str | None = None,
        latest_created_at: datetime | None = None,
        deferred_latest_id: str | None = None,
        deferred_latest_created_at: datetime | None = None,
    ) -> None:
        if position is not None and (latest_id is not None or latest_created_at is not None):
            raise TypeError("position과 기존 위치 필드는 함께 지정할 수 없습니다")
        if deferred_position is not None and (
            deferred_latest_id is not None or deferred_latest_created_at is not None
        ):
            raise TypeError("deferred_position과 기존 위치 필드는 함께 지정할 수 없습니다")
        object.__setattr__(self, "source", SourceName(source))
        object.__setattr__(
            self,
            "position",
            position or CheckpointPosition(id=latest_id, created_at=latest_created_at),
        )
        object.__setattr__(
            self,
            "deferred_position",
            deferred_position
            or (
                CheckpointPosition(
                    id=deferred_latest_id,
                    created_at=deferred_latest_created_at,
                )
                if deferred_latest_id is not None or deferred_latest_created_at is not None
                else None
            ),
        )
        object.__setattr__(self, "pending_ids", pending_ids)

    @property
    def latest_id(self) -> str | None:
        return self.position.id

    @property
    def latest_created_at(self) -> datetime | None:
        return self.position.created_at

    @property
    def deferred_latest_id(self) -> str | None:
        return self.deferred_position.id if self.deferred_position is not None else None

    @property
    def deferred_latest_created_at(self) -> datetime | None:
        return self.deferred_position.created_at if self.deferred_position is not None else None


@dataclass(frozen=True, slots=True)
class WatcherState:
    latest_id: str | None = None
    seen_ids: tuple[str, ...] = ()
    consecutive_failures: int = 0
    outage_notified: bool = False
    initialized: bool = False
    source_checkpoints: tuple[SourceCheckpoint, ...] = ()
