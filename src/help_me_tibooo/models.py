from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class AlertCategory(StrEnum):
    RESET = "리셋"
    LIMITS = "한도"
    LAUNCH = "출시"
    PLANS = "요금제"
    INCIDENT = "장애"


@dataclass(frozen=True, slots=True)
class Post:
    id: str
    text: str
    created_at: datetime | None
    url: str
    source: str
    is_reply: bool = False
    is_repost: bool = False
    source_kind: str | None = None


@dataclass(frozen=True, slots=True)
class SourceBatch:
    source: str
    posts: tuple[Post, ...] = ()
    error: str | None = None


@dataclass(frozen=True, slots=True)
class WatcherState:
    latest_id: str | None = None
    seen_ids: tuple[str, ...] = ()
    consecutive_failures: int = 0
    outage_notified: bool = False
    initialized: bool = False
