"""Domain objects and narrow contracts; independent of HTTP, GitHub and Telegram."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Protocol


class AlertError(Exception):
    """Expected operational error whose message is safe to log."""


class SourceError(AlertError):
    pass


class StateError(AlertError):
    pass


class DeliveryError(AlertError):
    pass


class ConfigurationError(AlertError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Article:
    id: str
    title: str
    url: str


@dataclass
class MonitorState:
    source_id: str
    initialized_at: str
    seen: set[str] = field(default_factory=set)
    pending: list[Article] = field(default_factory=list)
    last_success_at: str | None = None
    last_heartbeat_at: str | None = None
    last_error_alert_at: str | None = None
    consecutive_failures: int = 0

    def encode(self) -> bytes:
        return (json.dumps({
            "version": 1,
            "source_id": self.source_id,
            "initialized_at": self.initialized_at,
            "seen": sorted(self.seen),
            "pending": [asdict(article) for article in self.pending],
            "last_success_at": self.last_success_at,
            "last_heartbeat_at": self.last_heartbeat_at,
            "last_error_alert_at": self.last_error_alert_at,
            "consecutive_failures": self.consecutive_failures,
        }, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    @classmethod
    def decode(cls, raw: bytes) -> MonitorState:
        try:
            value = json.loads(raw)
            if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1:
                raise ValueError("unsupported schema")
            for name in ("source_id", "initialized_at"):
                if not isinstance(value.get(name), str) or not value[name]:
                    raise ValueError("missing identity")
            if not isinstance(value.get("seen"), list) or not all(
                isinstance(item, str) and item for item in value["seen"]
            ):
                raise ValueError("invalid seen IDs")
            if not isinstance(value.get("pending"), list):
                raise ValueError("invalid pending queue")
            pending = []
            for item in value["pending"]:
                if not isinstance(item, dict) or set(item) != {"id", "title", "url"}:
                    raise ValueError("invalid queued article")
                if not all(isinstance(v, str) and v for v in item.values()):
                    raise ValueError("invalid queued article values")
                pending.append(Article(**item))
            ids = [a.id for a in pending]
            if len(ids) != len(set(ids)) or set(ids) & set(value["seen"]):
                raise ValueError("inconsistent queue")
            for name in ("initialized_at", "last_success_at", "last_heartbeat_at", "last_error_alert_at"):
                timestamp = value.get(name)
                if timestamp is not None:
                    if not isinstance(timestamp, str) or datetime.fromisoformat(timestamp).tzinfo is None:
                        raise ValueError("invalid timestamp")
            failures = value.get("consecutive_failures", 0)
            if type(failures) is not int or failures < 0:
                raise ValueError("invalid failure count")
            return cls(
                source_id=value["source_id"], initialized_at=value["initialized_at"],
                seen=set(value["seen"]), pending=pending,
                last_success_at=value.get("last_success_at"),
                last_heartbeat_at=value.get("last_heartbeat_at"),
                last_error_alert_at=value.get("last_error_alert_at"),
                consecutive_failures=failures,
            )
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise StateError("State is invalid or incompatible; restore it instead of resetting it.") from None


class ArticleSource(Protocol):
    @property
    def identity(self) -> str: ...

    def baseline(self) -> list[Article]: ...

    def discover(self, known_ids: set[str]) -> list[Article]: ...


class StateStore(Protocol):
    def load(self) -> MonitorState | None: ...

    def save(self, state: MonitorState) -> None: ...


class Notifier(Protocol):
    def send(self, text: str) -> None: ...
