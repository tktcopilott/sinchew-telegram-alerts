"""Bounded HTTP transport. Exceptions never include request URLs or credentials."""

from __future__ import annotations

import json
import random
import socket
import time
from http.client import HTTPException
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .domain import AlertError, utc_now


class HttpError(AlertError):
    def __init__(self, status: int, body: bytes = b"", headers: Mapping[str, str] | None = None):
        super().__init__(f"HTTP request failed (status {status}).")
        self.status = status
        self.body = body
        self.headers = headers or {}


class NetworkError(AlertError):
    pass


@dataclass(frozen=True)
class Response:
    body: bytes
    status: int = 200

    def json(self):
        try:
            return json.loads(self.body)
        except (ValueError, UnicodeError):
            raise AlertError("Remote service returned invalid JSON.") from None


class HttpClient(Protocol):
    def request(self, method: str, url: str, *, headers: Mapping[str, str] | None = None,
                body: bytes | None = None) -> Response: ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not forward credentials to a redirect destination.
        return None


class UrlLibHttpClient:
    def __init__(self, timeout: float = 20, max_bytes: int = 4_000_000):
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.opener = build_opener(_NoRedirect())

    def request(self, method, url, *, headers=None, body=None) -> Response:
        if urlsplit(url).scheme != "https":
            raise NetworkError("Only HTTPS endpoints are supported.")
        request = Request(url, data=body, method=method, headers=dict(headers or {}))
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                content = response.read(self.max_bytes + 1)
                if len(content) > self.max_bytes:
                    raise NetworkError("Remote response exceeded the configured size limit.")
                return Response(content, response.status)
        except HTTPError as exc:
            try:
                content = exc.read(self.max_bytes)
            finally:
                exc.close()
            raise HttpError(exc.code, content, dict(exc.headers)) from None
        except (URLError, TimeoutError, socket.timeout, OSError, HTTPException):
            raise NetworkError("Network request failed or timed out; no credentials were logged.") from None


def retry_delay(headers: Mapping[str, str], body: bytes, attempt: int) -> float:
    """Honor Telegram/GitHub rate limits without unbounded runner sleeps."""
    retry_after = next((value for key, value in headers.items() if key.lower() == "retry-after"), None)
    delay: float | None = None
    if retry_after:
        try:
            delay = float(retry_after)
        except ValueError:
            try:
                delay = (parsedate_to_datetime(retry_after) - utc_now()).total_seconds()
            except (ValueError, TypeError, OverflowError):
                pass
    if delay is None:
        try:
            value = json.loads(body)
            delay = float(value.get("parameters", {}).get("retry_after"))
        except (ValueError, TypeError, AttributeError, UnicodeError):
            pass
    return delay if delay is not None else 2 ** attempt + random.uniform(0, 0.5)


class RetryingHttpClient:
    """Retry safe reads and explicit 429 responses; do not blindly replay POSTs."""

    def __init__(self, inner: HttpClient, attempts: int = 4, sleep: Callable[[float], None] = time.sleep):
        self.inner, self.attempts, self.sleep = inner, attempts, sleep

    def request(self, method, url, *, headers=None, body=None):
        for attempt in range(self.attempts):
            try:
                return self.inner.request(method, url, headers=headers, body=body)
            except HttpError as exc:
                retryable = exc.status == 429 or (method == "GET" and exc.status in {500, 502, 503, 504})
                delay = retry_delay(exc.headers, exc.body, attempt)
                if not retryable or attempt + 1 == self.attempts or delay > 60:
                    raise
            except NetworkError:
                if method != "GET" or attempt + 1 == self.attempts:
                    raise
                delay = 2 ** attempt + random.uniform(0, 0.5)
            self.sleep(max(1, delay))
        raise AssertionError("unreachable")
