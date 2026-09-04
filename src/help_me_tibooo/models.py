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


@dataclass(frozen=True, slots=True)
class SourceCheckpoint:
    source: SourceName
    position: CheckpointPosition = CheckpointPosition()
    deferred_position: CheckpointPosition | None = None
    pending_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AlertDeliveryCheckpoint:
    post: Post
    categories: tuple[AlertCategory, ...]
    sources: tuple[SourceName, ...]
    next_payload_index: int

    @property
    def post_id(self) -> str:
        return self.post.id


@dataclass(frozen=True, slots=True)
class WatcherState:
    latest_id: str | None = None
    seen_ids: tuple[str, ...] = ()
    consecutive_failures: int = 0
    outage_notified: bool = False
    initialized: bool = False
    source_checkpoints: tuple[SourceCheckpoint, ...] = ()
    alert_delivery: AlertDeliveryCheckpoint | None = None
