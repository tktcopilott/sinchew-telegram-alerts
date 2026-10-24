import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from article_alerts.domain import MonitorState, StateError
from article_alerts.http import HttpError, NetworkError
from article_alerts.state import FileStateStore, GitHubStateStore
from tests.helpers import ScriptedHttp, response


def state():
    return MonitorState("source", datetime(2026, 10, 24, tzinfo=timezone.utc).isoformat(), {"post:1"})


def remote(value, sha="old-sha"):
    return response({"encoding": "base64", "content": base64.b64encode(value.encode()).decode(), "sha": sha})


class StateTests(unittest.TestCase):
    def test_local_store_roundtrip_and_atomic_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = FileStateStore(Path(tmp) / "nested/state.json")
            self.assertIsNone(store.load())
            store.save(state())
            self.assertEqual(store.load().seen, {"post:1"})
            self.assertEqual([p.name for p in (Path(tmp) / "nested").iterdir()], ["state.json"])

    def test_read_failure_is_not_treated_as_fresh_state(self):
        for result in (HttpError(403), NetworkError("offline")):
            store = GitHubStateStore(ScriptedHttp(result), "secret", "owner/repo")
            with self.subTest(result=result), self.assertRaises(StateError):
                store.load()

    def test_github_update_includes_compare_and_swap_sha(self):
        http = ScriptedHttp(remote(state()), response({"content": {"sha": "new-sha"}}))
        store = GitHubStateStore(http, "secret", "owner/repo")
        loaded = store.load()
        loaded.seen.add("post:2")
        store.save(loaded)
        payload = json.loads(http.calls[1][3])
        self.assertEqual(payload["sha"], "old-sha")
        self.assertEqual(payload["branch"], "monitor-state")
        self.assertEqual(store.sha, "new-sha")

    def test_github_initialization_creates_branch_then_file(self):
        http = ScriptedHttp(HttpError(404), HttpError(404), response({"object": {"sha": "main-sha"}}),
                            response({"ref": "refs/heads/monitor-state"}), response({"content": {"sha": "new"}}))
        store = GitHubStateStore(http, "secret", "owner/repo")
        self.assertIsNone(store.load())
        store.save(state())
        self.assertEqual([c[0] for c in http.calls], ["GET", "GET", "GET", "POST", "PUT"])
        self.assertNotIn("sha", json.loads(http.calls[-1][3]))

    def test_lost_commit_response_is_verified_without_duplicate_write(self):
        original = state()
        changed = state()
        changed.seen.add("post:2")
        http = ScriptedHttp(remote(original), NetworkError("lost response"), remote(changed, "new-sha"))
        store = GitHubStateStore(http, "secret", "owner/repo")
        store.load()
        store.save(changed)
        self.assertEqual(store.sha, "new-sha")
        self.assertEqual(sum(c[0] == "PUT" for c in http.calls), 1)

    def test_conflict_never_overwrites_another_run(self):
        http = ScriptedHttp(remote(state()), HttpError(409), remote(state(), "someone-else"))
        store = GitHubStateStore(http, "secret", "owner/repo")
        changed = store.load()
        changed.seen.add("post:2")
        with self.assertRaisesRegex(StateError, "Concurrent"):
            store.save(changed)
        self.assertEqual(sum(c[0] == "PUT" for c in http.calls), 1)

    def test_save_requires_load(self):
        with self.assertRaises(StateError):
            GitHubStateStore(ScriptedHttp(), "secret", "owner/repo").save(state())

    def test_unsupported_or_inconsistent_state_rejected(self):
        for mutate in (
            lambda v: v.update(version=2),
            lambda v: v.update(last_success_at="not-a-date"),
            lambda v: v.update(pending=[{"id":"post:1","title":"x","url":"https://example.test"}]),
            lambda v: v.update(seen="post:1"),
            lambda v: v.update(consecutive_failures=-1),
        ):
            value = json.loads(state().encode())
            mutate(value)
            with self.subTest(value=value), self.assertRaises(StateError):
                MonitorState.decode(json.dumps(value).encode())
