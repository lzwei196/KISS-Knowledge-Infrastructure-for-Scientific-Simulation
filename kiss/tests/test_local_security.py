"""Local HTTP and private-settings regression tests."""
from __future__ import annotations

import json
import os
import stat
import threading
from email.message import Message
from types import SimpleNamespace

from kiss_cli import gui, settings


def _request_headers(**values):
    headers = Message()
    for key, value in values.items():
        headers[key.replace("_", "-")] = value
    return headers


def _handler(headers):
    handler = object.__new__(gui.Handler)
    handler.server = SimpleNamespace(server_port=8765)
    handler.csrf_token = "test-request-token"
    handler.headers = headers
    return handler


def test_local_post_requires_process_cookie_and_same_origin():
    cookie = "geoforge_csrf_8765=test-request-token"
    ok, _ = _handler(_request_headers(
        Host="127.0.0.1:8765", Origin="http://127.0.0.1:8765",
        Sec_Fetch_Site="same-origin", Cookie=cookie,
    ))._browser_write_allowed()
    assert ok

    ok, why = _handler(_request_headers(
        Host="127.0.0.1:8765", Origin="https://evil.example",
        Sec_Fetch_Site="cross-site", Cookie=cookie,
    ))._browser_write_allowed()
    assert not ok and "site" in why

    ok, why = _handler(_request_headers(
        Host="127.0.0.1:8765", Origin="http://127.0.0.1:8765",
        Sec_Fetch_Site="same-origin",
    ))._browser_write_allowed()
    assert not ok and "token" in why


def test_settings_updates_are_atomic_private_and_do_not_lose_fields(tmp_path,
                                                                    monkeypatch):
    path = tmp_path / "private" / "settings.json"
    monkeypatch.setattr(settings, "_path", lambda: path)
    for key in settings.KEY_NAMES:
        monkeypatch.delenv(key, raising=False)

    barrier = threading.Barrier(4)
    errors = []

    def worker(key, value):
        try:
            barrier.wait()
            settings.update({"api_keys": {key: value}})
        except BaseException as error:  # retained and asserted on the main thread
            errors.append(error)

    threads = [threading.Thread(target=worker, args=(key, f"secret-{index}"))
               for index, key in enumerate(settings.KEY_NAMES)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert set(saved["api_keys"]) == set(settings.KEY_NAMES)
    if os.name != "nt":
        # Windows reports synthetic POSIX mode bits; privacy is enforced by
        # the user's profile ACL rather than chmod(0600).
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not list(path.parent.glob(".settings-*.json"))

    for key in settings.KEY_NAMES:
        os.environ.pop(key, None)
