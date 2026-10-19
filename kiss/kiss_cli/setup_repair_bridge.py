"""One setup turn's repair request, shared by API and CLI providers.

Requests queue host work; they never accept candidate paths, edits, verification
receipts or destinations. Adoption runs only after provider workers drain.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import threading
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from .setup_bridge import _NoRedirect

ENDPOINT = "/api/agent/setup-ki-repair"
_REGISTRY = {}
_LOCK = threading.Lock()


def issue_argument(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise ValueError("issue must be a nonempty description of at most 2000 characters")
    return value.strip()


def _loopback_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
            or parsed.username or parsed.password or not parsed.port
            or parsed.path != ENDPOINT or parsed.query or parsed.fragment):
        raise ValueError("setup repair host must be the current loopback endpoint")
    return url


class Capability:
    def __init__(self, root, turn_id, callback, *, stopped):
        if not turn_id or not callable(callback) or not callable(stopped):
            raise ValueError("a live setup turn and host callback are required")
        self.root = Path(root).resolve()
        self.turn_id = turn_id
        self._callback, self._stopped = callback, stopped
        self._closed = threading.Event()
        self._lock = threading.Lock()
        self._token = secrets.token_urlsafe(32)
        with _LOCK:
            _REGISTRY[self._token] = self

    def call(self, issue):
        issue = issue_argument(issue)
        with self._lock:
            if self._closed.is_set() or self._stopped():
                raise ValueError("setup repair capability is closed or stopped")
            return self._callback(issue)

    def environment(self, url):
        _loopback_url(url)
        if self._closed.is_set() or self._stopped():
            raise ValueError("setup repair capability is closed or stopped")
        return {"GEOFORGE_SETUP_REPAIR_URL": url,
                "GEOFORGE_SETUP_REPAIR_TOKEN": self._token,
                "GEOFORGE_SETUP_REPAIR_ROOT": str(self.root)}

    def close(self):
        self._closed.set()
        with _LOCK:
            _REGISTRY.pop(self._token, None)
        with self._lock:
            pass


def invoke(token, payload):
    with _LOCK:
        capability = _REGISTRY.get(token) if isinstance(token, str) else None
    if capability is None:
        raise PermissionError("invalid or expired setup repair capability")
    if not isinstance(payload, dict) or set(payload) != {"issue"}:
        raise ValueError("setup repair request accepts only issue")
    return capability.call(payload["issue"])


def request(issue):
    issue = issue_argument(issue)
    url = os.environ.get("GEOFORGE_SETUP_REPAIR_URL", "")
    token = os.environ.get("GEOFORGE_SETUP_REPAIR_TOKEN", "")
    root = os.environ.get("GEOFORGE_SETUP_REPAIR_ROOT", "")
    if not url or not token or not root:
        raise ValueError("request-ki-repair is available only during an active GUI setup")
    _loopback_url(url)
    if Path.cwd().resolve() != Path(root).resolve():
        raise ValueError("run request-ki-repair from this setup's exact workspace")
    req = Request(url, data=json.dumps({"issue": issue}).encode("utf-8"),
        headers={"X-GeoForge-Setup-Token": token, "Content-Type": "application/json"},
        method="POST")
    try:
        with build_opener(ProxyHandler({}), _NoRedirect()).open(req, timeout=30) as response:
            result = json.loads(response.read(128 * 1024).decode("utf-8"))
    except HTTPError as error:
        try:
            detail = json.loads(error.read(4096).decode("utf-8")).get("error")
        except (ValueError, AttributeError):
            detail = None
        raise ValueError(str(detail or "setup repair host rejected the request")) from None
    if not isinstance(result, dict):
        raise ValueError("invalid setup repair host response")
    return result
