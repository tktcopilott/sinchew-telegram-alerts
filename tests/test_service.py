from datetime import datetime, timedelta, timezone
import unittest

from article_alerts.domain import DeliveryError, MonitorState, SourceError, StateError
from article_alerts.service import Monitor
from tests.helpers import FakeNotifier, FakeSource, MemoryStore, article


NOW = datetime(2026, 10, 24, 10, tzinfo=timezone.utc)


class MonitorTests(unittest.TestCase):
    def make(self, source=None, store=None, notifier=None, **kwargs):
        source = source or FakeSource()
        store = store or MemoryStore(MonitorState("source-1", NOW.isoformat(), {"post:1", "post:2"},
                         last_heartbeat_at=NOW.isoformat(), last_success_at=NOW.isoformat()))
        notifier = notifier or FakeNotifier()
        return Monitor(source, store, notifier, clock=lambda: NOW, **kwargs), store, notifier

    def test_initialize_baselines_without_old_article_alerts(self):
        monitor, store, notifier = self.make(store=MemoryStore())
        monitor.initialize()
        self.assertEqual(store.state.seen, {"post:1", "post:2"})
        self.assertEqual(len(notifier.messages), 1)
        self.assertIn("ready", notifier.messages[0])

    def test_reinitialize_never_erases_history(self):
        monitor, store, notifier = self.make()
        with self.assertRaises(StateError):
            monitor.initialize()
        self.assertEqual(store.saves, 0)

    def test_no_state_requires_explicit_initialize(self):
        monitor, store, notifier = self.make(store=MemoryStore())
        with self.assertRaises(StateError):
            monitor.check()
        self.assertEqual(notifier.messages, [])

    def test_oldest_new_article_delivered_first_and_deduplicated_next_run(self):
        monitor, store, notifier = self.make(source=FakeSource([article(4), article(3), article(2)]))
        result = monitor.check()
        self.assertEqual(result.delivered, 2)
        self.assertIn("新闻 3", notifier.messages[0])
        self.assertIn("新闻 4", notifier.messages[1])
        self.assertEqual(monitor.check().delivered, 0)
        self.assertEqual(len(notifier.messages), 2)

    def test_partial_failure_keeps_only_unsent_items_queued(self):
        monitor, store, notifier = self.make(source=FakeSource([article(4), article(3), article(2)]),
                                           notifier=FakeNotifier(fail_on=1))
        with self.assertRaises(DeliveryError):
            monitor.check()
        self.assertIn("post:3", store.state.seen)
        self.assertEqual([a.id for a in store.state.pending], ["post:4"])
        replacement = FakeNotifier()
        resumed, _, _ = self.make(source=monitor.source, store=store, notifier=replacement)
        self.assertEqual(resumed.check().delivered, 1)
        self.assertIn("新闻 4", replacement.messages[0])

    def test_queue_is_durable_before_first_delivery(self):
        monitor, store, notifier = self.make(source=FakeSource([article(3), article(2)]),
                                           notifier=FakeNotifier(fail_on=0))
        with self.assertRaises(DeliveryError):
            monitor.check()
        self.assertEqual([a.id for a in store.state.pending], ["post:3"])
        self.assertNotIn("post:3", store.state.seen)

    def test_pending_delivery_survives_source_outage(self):
        monitor, store, notifier = self.make()
        store.state.pending = [article(3)]
        monitor.source.error = SourceError("blocked")
        with self.assertRaises(SourceError):
            monitor.check()
        self.assertIn("post:3", store.state.seen)
        self.assertEqual(store.state.pending, [])

    def test_delivery_cap_retains_backlog_for_next_run(self):
        monitor, store, notifier = self.make(source=FakeSource([article(5), article(4), article(3), article(2)]),
                                           max_deliveries=1)
        self.assertEqual(monitor.check().pending, 2)
        self.assertEqual(monitor.check().pending, 1)
        self.assertEqual(monitor.check().pending, 0)
        self.assertEqual(len(notifier.messages), 3)

    def test_source_change_never_uses_another_tags_history(self):
        monitor, store, notifier = self.make()
        store.state.source_id = "another-source"
        with self.assertRaises(StateError):
            monitor.check()

    def test_daily_heartbeat_and_no_unchanged_poll_commits(self):
        monitor, store, notifier = self.make()
        monitor.check()
        self.assertEqual(store.saves, 0)
        monitor.clock = lambda: NOW + timedelta(days=1)
        monitor.check()
        self.assertEqual(len(notifier.messages), 1)
        self.assertIn("healthy", notifier.messages[0])

    def test_error_alert_is_throttled_and_recovery_is_reported(self):
        monitor, store, notifier = self.make()
        monitor.check()
        monitor.report_failure(SourceError("blocked"))
        monitor.report_failure(SourceError("blocked"))
        self.assertEqual(len(notifier.messages), 1)
        monitor.check()
        self.assertIn("recovered", notifier.messages[-1])

    def test_corrupt_state_is_rejected(self):
        with self.assertRaises(StateError):
            MonitorState.decode(b'{"version":1,"source_id":"source-1"}')

    def test_state_roundtrip_including_pending_queue(self):
        monitor, store, notifier = self.make()
        store.state.pending = [article(3)]
        decoded = MonitorState.decode(store.state.encode())
        self.assertEqual(decoded.pending, [article(3)])
        self.assertEqual(decoded.seen, store.state.seen)

    def test_checkpoint_failure_stops_before_next_message(self):
        class FailingStore(MemoryStore):
            def save(self, state):
                if self.saves == 1:
                    raise StateError("checkpoint failed")
                super().save(state)
        monitor, store, notifier = self.make(source=FakeSource([article(4), article(3), article(2)]))
        monitor.store = FailingStore(store.state)
        with self.assertRaises(StateError):
            monitor.check()
        self.assertEqual(len(notifier.messages), 1)
        self.assertEqual([a.id for a in monitor.store.state.pending], ["post:3", "post:4"])
