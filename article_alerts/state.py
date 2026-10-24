"""Atomic local files for development; compare-and-swap GitHub commits for production."""

from __future__ import annotations

import base64
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import quote

from .domain import AlertError, MonitorState, StateError
from .http import HttpClient, HttpError, NetworkError


class FileStateStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> MonitorState | None:
        try:
            return MonitorState.decode(self.path.read_bytes())
        except FileNotFoundError:
            return None

    def save(self, state: MonitorState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=self.path.parent)
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(state.encode())
                file.flush()
                os.fsync(file.fileno())
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)


class GitHubStateStore:
    def __init__(self, http: HttpClient, token: str, repository: str,
                 branch: str = "monitor-state", path: str = "state.json", default_branch: str = "main"):
        self.http, self.repository = http, repository
        self.branch, self.path, self.default_branch = branch, path, default_branch
        self.base = f"https://api.github.com/repos/{repository}"
        self.headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "PersonalArticleAlerts/1.0"}
        self.sha: str | None = None
        self.loaded = False

    def _request(self, method: str, endpoint: str, payload=None):
        headers = dict(self.headers)
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode()
        return self.http.request(method, self.base + endpoint, headers=headers, body=body).json()

    def _remote(self) -> tuple[bytes, str] | None:
        try:
            result = self._request("GET", f"/contents/{quote(self.path)}?ref={quote(self.branch, safe='')}")
        except HttpError as exc:
            if exc.status == 404:
                return None
            raise
        if not isinstance(result, dict) or result.get("encoding") != "base64" or not isinstance(result.get("sha"), str):
            raise StateError("GitHub returned an unexpected state-file response.")
        try:
            return base64.b64decode(result["content"]), result["sha"]
        except (ValueError, TypeError, KeyError):
            raise StateError("GitHub returned invalid state-file content.") from None

    def load(self) -> MonitorState | None:
        try:
            remote = self._remote()
            self.loaded = True
            if remote is None:
                self.sha = None
                return None
            raw, self.sha = remote
            return MonitorState.decode(raw)
        except (HttpError, NetworkError):
            raise StateError("Cannot read GitHub state. Check repository permissions and availability.") from None

    def _ensure_branch(self) -> None:
        try:
            self._request("GET", "/git/ref/heads/" + quote(self.branch, safe="/"))
            return
        except HttpError as exc:
            if exc.status != 404:
                raise
        default = self._request("GET", "/git/ref/heads/" + quote(self.default_branch, safe="/"))
        try:
            self._request("POST", "/git/refs", {"ref": "refs/heads/" + self.branch, "sha": default["object"]["sha"]})
        except (HttpError, NetworkError):
            # A lost creation response or another initializer may already have created it.
            self._request("GET", "/git/ref/heads/" + quote(self.branch, safe="/"))

    def save(self, state: MonitorState) -> None:
        if not self.loaded:
            raise StateError("Load state before saving it.")
        content = state.encode()
        if len(content) > 900_000:
            raise StateError("State is approaching GitHub's file-content API limit; archive it deliberately.")
        try:
            if self.sha is None:
                self._ensure_branch()
            payload = {"message": "Checkpoint article monitor", "branch": self.branch,
                       "content": base64.b64encode(content).decode()}
            if self.sha is not None:
                payload["sha"] = self.sha
            try:
                result = self._request("PUT", "/contents/" + quote(self.path), payload)
            except (HttpError, NetworkError) as exc:
                # A commit may have succeeded despite a lost response. Verify, never blindly overwrite.
                remote = self._remote()
                if remote is not None and remote[0] == content:
                    self.sha = remote[1]
                    return
                if isinstance(exc, HttpError) and exc.status in {409, 422}:
                    raise StateError("Concurrent state change detected; this run stopped without overwriting it.") from None
                raise
            if not isinstance(result, dict) or not isinstance(result.get("content"), dict) or not result["content"].get("sha"):
                raise StateError("GitHub did not acknowledge the state checkpoint.")
            self.sha = result["content"]["sha"]
        except (HttpError, NetworkError):
            raise StateError("Cannot checkpoint GitHub state; stopped to avoid silently losing delivery history.") from None
        except (KeyError, TypeError, AlertError) as exc:
            if isinstance(exc, StateError):
                raise
            raise StateError("GitHub state operation failed; inspect repository access and service availability.") from None
