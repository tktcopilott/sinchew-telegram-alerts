"""Full source → GitHub state → Telegram flow with provider APIs simulated in memory."""

import base64
from datetime import datetime, timezone
import json
import unittest
from urllib.parse import parse_qs, urlsplit

from article_alerts.domain import DeliveryError, MonitorState, SourceError
from article_alerts.http import HttpError, RetryingHttpClient
from article_alerts.service import Monitor
from article_alerts.source import SinChewTagSource
from article_alerts.state import GitHubStateStore
from article_alerts.telegram import TelegramNotifier
from tests.helpers import article, response


class ProviderSimulation:
    def __init__(self):
        self.pages = [[2], [1]]
        self.branch_exists = False
        self.saved = None
        self.sha = 0
        self.messages = []
        self.telegram_fails = False
        self.source_blocked = False

    def request(self, method, url, *, headers=None, body=None):
        parsed = urlsplit(url)
        payload = json.loads(body) if body else None
        if parsed.hostname == "www.sinchew.com.my":
            if self.source_blocked:
                raise HttpError(403)
            number = int(parse_qs(parsed.query)["page"][0])
            ids = self.pages[number - 1] if number <= len(self.pages) else []
            return response([{"title": article(n).title, "url": article(n).url} for n in ids])
        if parsed.hostname == "api.telegram.org":
            if self.telegram_fails:
                raise HttpError(503)
            self.messages.append(payload["text"])
            return response({"ok": True, "result": {"message_id": len(self.messages)}})
        if parsed.hostname == "api.github.com":
            if "/contents/" in parsed.path:
                if method == "GET":
                    if self.saved is None:
                        raise HttpError(404)
                    return response({"encoding": "base64", "sha": str(self.sha),
                                     "content": base64.b64encode(self.saved).decode()})
                if payload.get("sha") != (str(self.sha) if self.saved else None):
                    raise HttpError(409)
                self.saved = base64.b64decode(payload["content"])
                self.sha += 1
                return response({"content": {"sha": str(self.sha)}})
            if "/git/ref/heads/main" in parsed.path:
                return response({"object": {"sha": "main-tip"}})
            if method == "POST" and parsed.path.endswith("/git/refs"):
                self.branch_exists = True
                return response({"ref": payload["ref"]})
            if "/git/ref/heads/monitor-state" in parsed.path:
                if not self.branch_exists:
                    raise HttpError(404)
                return response({"object": {"sha": "state-tip"}})
        raise AssertionError("Unexpected provider request")


class IntegrationTests(unittest.TestCase):
    def build(self, provider):
        http = RetryingHttpClient(provider, sleep=lambda _: None)
        return Monitor(
            SinChewTagSource(http),
            GitHubStateStore(http, "fake-gh-token", "owner/repo"),
            TelegramNotifier(http, "fake-bot-token", "123", sleep=lambda _: None),
            clock=lambda: datetime(2026, 10, 24, tzinfo=timezone.utc),
        )

    def test_two_fresh_runners_share_durable_deduplication_history(self):
        provider = ProviderSimulation()
        self.build(provider).initialize()
        provider.messages.clear()
        provider.pages = [[4, 3], [2, 1]]
        result = self.build(provider).check()
        self.assertEqual(result.delivered, 2)
        self.assertIn("新闻 3", provider.messages[0])
        self.assertIn("新闻 4", provider.messages[1])
        self.assertEqual(self.build(provider).check().delivered, 0)
        self.assertEqual(len(provider.messages), 2)

    def test_telegram_outage_leaves_durable_queue_for_restarted_runner(self):
        provider = ProviderSimulation()
        self.build(provider).initialize()
        provider.messages.clear()
        provider.pages = [[3], [2, 1]]
        provider.telegram_fails = True
        with self.assertRaises(DeliveryError):
            self.build(provider).check()
        persisted = MonitorState.decode(provider.saved)
        self.assertEqual([a.id for a in persisted.pending], ["post:3"])
        provider.telegram_fails = False
        self.assertEqual(self.build(provider).check().delivered, 1)
        self.assertEqual(len(provider.messages), 1)

    def test_blocked_source_preserves_baseline_and_sends_throttled_alert(self):
        provider = ProviderSimulation()
        self.build(provider).initialize()
        provider.messages.clear()
        provider.source_blocked = True
        for _ in range(2):
            monitor = self.build(provider)
            try:
                monitor.check()
            except SourceError as error:
                monitor.report_failure(error)
        self.assertEqual(len(provider.messages), 1)
        persisted = MonitorState.decode(provider.saved)
        self.assertEqual(persisted.seen, {"post:1", "post:2"})
        self.assertEqual(persisted.consecutive_failures, 2)
