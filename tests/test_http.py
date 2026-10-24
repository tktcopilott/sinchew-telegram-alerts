import unittest

from article_alerts.http import HttpError, NetworkError, RetryingHttpClient, Response, UrlLibHttpClient
from tests.helpers import ScriptedHttp


class HttpTests(unittest.TestCase):
    def test_transient_get_retries_then_succeeds(self):
        inner = ScriptedHttp(HttpError(503), NetworkError("temporary"), Response(b"ok"))
        waits = []
        client = RetryingHttpClient(inner, sleep=waits.append)
        self.assertEqual(client.request("GET", "https://example.test").body, b"ok")
        self.assertEqual(len(waits), 2)

    def test_auth_or_block_errors_are_not_retried(self):
        for status in (400, 401, 403, 404):
            inner = ScriptedHttp(HttpError(status))
            with self.subTest(status=status), self.assertRaises(HttpError):
                RetryingHttpClient(inner, sleep=lambda _: None).request("GET", "https://example.test")
            self.assertEqual(len(inner.calls), 1)

    def test_explicit_telegram_429_honors_retry_after(self):
        waits = []
        inner = ScriptedHttp(HttpError(429, b'{"parameters":{"retry_after":3}}'), Response(b"ok"))
        RetryingHttpClient(inner, sleep=waits.append).request("POST", "https://example.test")
        self.assertEqual(waits, [3])

    def test_long_rate_limit_wait_fails_instead_of_overloading_or_sleeping_forever(self):
        inner = ScriptedHttp(HttpError(429, headers={"Retry-After": "120"}))
        waits = []
        with self.assertRaises(HttpError):
            RetryingHttpClient(inner, sleep=waits.append).request("GET", "https://example.test")
        self.assertEqual(waits, [])

    def test_uncertain_post_never_blindly_retried(self):
        for error in (NetworkError("timeout"), HttpError(503)):
            inner = ScriptedHttp(error)
            with self.subTest(error=error), self.assertRaises(type(error)):
                RetryingHttpClient(inner, sleep=lambda _: None).request("POST", "https://example.test")
            self.assertEqual(len(inner.calls), 1)

    def test_retries_are_bounded(self):
        inner = ScriptedHttp(*[HttpError(503) for _ in range(4)])
        with self.assertRaises(HttpError):
            RetryingHttpClient(inner, sleep=lambda _: None).request("GET", "https://example.test")
        self.assertEqual(len(inner.calls), 4)

    def test_credentials_not_in_error_string(self):
        self.assertEqual(str(HttpError(403, b"secret token")), "HTTP request failed (status 403).")

    def test_plain_http_is_rejected(self):
        with self.assertRaises(NetworkError):
            UrlLibHttpClient().request("GET", "http://example.test")
