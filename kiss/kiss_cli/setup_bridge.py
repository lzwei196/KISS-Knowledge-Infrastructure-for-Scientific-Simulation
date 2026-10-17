"""One live setup's version-only host runtime operation, shared by all providers.

This capability is not a shell or a filesystem sandbox. It authorizes only the
host callback captured for one fresh workspace and turn; providers never supply
the runtime ticket, destination, download URL, command, or executable.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import secrets
import threading
from urllib.parse import urlsplit
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


_REGISTRY: dict[str, "Capability"] = {}
_REGISTRY_LOCK = threading.Lock()
ENDPOINT = "/api/agent/setup-python-runtime"


def version_argument(value) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"3\.[0-9]{1,2}(?:\.[0-9]{1,3})?", value):
        raise ValueError("version must be a CPython minor or exact release, such as 3.12 or 3.12.9")
    return value


class Capability:
    def __init__(self, root: Path, turn_id: str, callback, *, stopped):
        if not turn_id or not callable(callback) or not callable(stopped):
            raise ValueError("a live setup turn and host callback are required")
        self.root = Path(root).resolve()
        self.turn_id = turn_id
        self._callback = callback
        self._stopped = stopped
        self._closed = threading.Event()
        self._lock = threading.Lock()
        self._token = secrets.token_urlsafe(32)
        with _REGISTRY_LOCK:
            _REGISTRY[self._token] = self

    def stopped(self) -> bool:
        return self._closed.is_set() or self._stopped()

    def call(self, version: str) -> dict:
        version = version_argument(version)
        if self.stopped():
            raise ValueError("fresh setup runtime capability is closed or stopped")
        if not self._lock.acquire(blocking=False):
            raise ValueError("Python runtime preparation is already running for this setup")
        try:
            if self.stopped():
                raise ValueError("fresh setup runtime capability is closed or stopped")
            return self._callback(version, stop=self.stopped)
        finally:
            self._lock.release()

    def environment(self, url: str) -> dict[str, str]:
        _loopback_url(url)
        if self.stopped():
            raise ValueError("fresh setup runtime capability is closed or stopped")
        return {
            "GEOFORGE_SETUP_RUNTIME_URL": url,
            "GEOFORGE_SETUP_RUNTIME_TOKEN": self._token,
            "GEOFORGE_SETUP_RUNTIME_ROOT": str(self.root),
        }

    def close(self) -> None:
        # Revoke first, then join an in-flight request before its ticket or log
        # is closed. The callback receives this cancellation predicate even in
        # the separate HTTP request thread.
        self._closed.set()
        with _REGISTRY_LOCK:
            _REGISTRY.pop(self._token, None)
        with self._lock:
            pass


def invoke(token: str, payload) -> dict:
    with _REGISTRY_LOCK:
        capability = _REGISTRY.get(token) if isinstance(token, str) else None
    if capability is None:
        raise PermissionError("invalid or expired setup runtime capability")
    if not isinstance(payload, dict) or set(payload) != {"version"}:
        raise ValueError("setup runtime request accepts only version")
    return capability.call(payload["version"])


def _loopback_url(url: str) -> str:
    parsed = urlsplit(url)
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
            or parsed.username or parsed.password or not parsed.port
            or parsed.path != ENDPOINT or parsed.query or parsed.fragment):
        raise ValueError("setup runtime host must be the current loopback endpoint")
    return url


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("setup runtime host redirects are not permitted")


def request(version: str) -> dict:
    """CLI transport; it cannot create authority or choose a destination."""
    version = version_argument(version)
    url = os.environ.get("GEOFORGE_SETUP_RUNTIME_URL", "")
    token = os.environ.get("GEOFORGE_SETUP_RUNTIME_TOKEN", "")
    root = os.environ.get("GEOFORGE_SETUP_RUNTIME_ROOT", "")
    if not url or not token or not root:
        raise ValueError("prepare-python-runtime is available only during a fresh GUI setup")
    _loopback_url(url)
    if Path.cwd().resolve() != Path(root).resolve():
        raise ValueError("run prepare-python-runtime from this setup's exact workspace")
    req = Request(url, data=json.dumps({"version": version}).encode("utf-8"),
                  headers={"X-GeoForge-Setup-Token": token,
                           "Content-Type": "application/json"}, method="POST")
    # Never send the capability through the user's proxy or a redirect.
    try:
        with build_opener(ProxyHandler({}), _NoRedirect()).open(req, timeout=900) as response:
            result = json.loads(response.read(128 * 1024).decode("utf-8"))
    except HTTPError as error:
        try:
            detail = json.loads(error.read(4096).decode("utf-8")).get("error")
        except (ValueError, AttributeError):
            detail = None
        raise ValueError(str(detail or "setup runtime host rejected the request")) from None
    if not isinstance(result, dict):
        raise ValueError("invalid setup runtime host response")
    return result
