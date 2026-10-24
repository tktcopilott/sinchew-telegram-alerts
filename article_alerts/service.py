"""Use cases depend on ports, not on Sin Chew, Telegram or GitHub implementations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from .domain import (AlertError, ArticleSource, MonitorState, Notifier,
                     StateError, StateStore, utc_now)


@dataclass(frozen=True)
class CheckResult:
    status: str
    discovered: int = 0
    delivered: int = 0
    pending: int = 0


class Monitor:
    def __init__(self, source: ArticleSource, store: StateStore, notifier: Notifier,
                 *, label: str = "Sin Chew · 诈骗", max_deliveries: int = 50,
                 heartbeat_hours: int = 24, clock: Callable[[], datetime] = utc_now):
        self.source, self.store, self.notifier = source, store, notifier
        self.label, self.max_deliveries = label, max_deliveries
        self.heartbeat_hours, self.clock = heartbeat_hours, clock
        self.state: MonitorState | None = None

    def initialize(self) -> CheckResult:
        if self.store.load() is not None:
            raise StateError("Already initialized. Use check; initialization never resets existing history.")
        articles = self.source.baseline()
        if not articles:
            raise StateError("Refusing to initialize an empty article baseline.")
        now = self.clock().isoformat()
        self.state = MonitorState(self.source.identity, now, {a.id for a in articles},
                                  last_success_at=now, last_heartbeat_at=now)
        self.store.save(self.state)
        self.notifier.send(f"Article alerts ready: {self.label}\n"
                           f"Recorded {len(self.state.seen)} existing articles without sending old news.\n"
                           "Enable MONITOR_ENABLED=true in GitHub repository variables to start scheduled checks.")
        return CheckResult("initialized")

    def _load(self) -> MonitorState:
        state = self.store.load()
        if state is None:
            raise StateError("No saved state. Run initialize manually before enabling scheduled checks.")
        if state.source_id != self.source.identity:
            raise StateError("Source configuration differs from saved state. Use a separate state branch for another tag.")
        self.state = state
        return state

    def _drain(self, state: MonitorState, limit: int) -> int:
        delivered = 0
        while state.pending and delivered < limit:
            article = state.pending[0]
            # Stay below Telegram's 4096 UTF-16-code-unit limit, even with emoji.
            title = article.title[:900]
            if len(article.url) > 1500:
                raise AlertError("Article URL is too long; inspect the queued article before retrying.")
            self.notifier.send(f"{self.label}\n{title}\n{article.url}")
            state.seen.add(article.id)
            state.pending.pop(0)
            # Checkpoint after EACH acknowledged message, never after the whole batch.
            self.store.save(state)
            delivered += 1
        return delivered

    def check(self) -> CheckResult:
        state = self._load()
        delivered = self._drain(state, self.max_deliveries)
        if state.pending:
            return CheckResult("draining-backlog", delivered=delivered, pending=len(state.pending))
        articles = self.source.discover(state.seen)
        fresh = [a for a in articles if a.id not in state.seen]
        if fresh:
            # Source order is newest-first. Persist the queue before sending anything.
            state.pending = list(reversed(fresh))
            self.store.save(state)
            delivered += self._drain(state, self.max_deliveries - delivered)
        now = self.clock()
        previous_failures = state.consecutive_failures
        state.consecutive_failures = 0
        heartbeat_due = self.heartbeat_hours > 0 and (
            state.last_heartbeat_at is None or
            now - datetime.fromisoformat(state.last_heartbeat_at) >= timedelta(hours=self.heartbeat_hours)
        )
        if previous_failures:
            self.notifier.send(f"Article alerts recovered: {self.label}\nThe source check succeeded again.")
        if heartbeat_due:
            self.notifier.send(f"Article alerts healthy: {self.label}\n"
                               f"Latest source check succeeded. Queued articles: {len(state.pending)}.\n"
                               "Checks follow GitHub's schedule and may be delayed.")
            state.last_heartbeat_at = now.isoformat()
        # Avoid writing a commit for every empty five-minute poll.
        checkpoint_due = state.last_success_at is None or (
            now - datetime.fromisoformat(state.last_success_at) >= timedelta(hours=6)
        )
        if fresh or delivered or previous_failures or heartbeat_due or checkpoint_due:
            state.last_success_at = now.isoformat()
            self.store.save(state)
        return CheckResult("healthy", len(fresh), delivered, len(state.pending))

    def report_failure(self, error: AlertError) -> None:
        """Best effort alert, at most once daily when the state backend is healthy."""
        state = self.state
        if state is None:
            return  # Missing/corrupt initialization uses the GitHub failed-run notification.
        now = self.clock()
        if isinstance(error, StateError):
            # Never attempt to repair or overwrite state after a failed checkpoint.
            self.notifier.send(f"Article alerts need attention: {self.label}\n"
                               "A state checkpoint failed. Open the failed GitHub Actions run.")
            return
        state.consecutive_failures += 1
        due = state.last_error_alert_at is None or (
            now - datetime.fromisoformat(state.last_error_alert_at) >= timedelta(hours=24)
        )
        if due:
            self.notifier.send(f"Article alerts need attention: {self.label}\n{error}\n"
                               "Queued articles are retained. Open the failed GitHub Actions run.")
            state.last_error_alert_at = now.isoformat()
        self.store.save(state)
