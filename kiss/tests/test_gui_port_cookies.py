"""Browser cookie isolation for concurrent Desktop listeners; no live server."""
from email.message import Message
from http.cookies import SimpleCookie
from types import SimpleNamespace

import pytest

from kiss_cli import gui


def handler(port=8791, token="current-instance-token", **headers):
    request = object.__new__(gui.Handler)
    request.server = SimpleNamespace(server_port=port)
    request.csrf_token = token
    request.headers = Message()
    values = {"Host": f"127.0.0.1:{port}", "Origin": f"http://127.0.0.1:{port}",
              "Sec-Fetch-Site": "same-origin", **headers}
    for key, value in values.items():
        request.headers[key] = value
    return request


def set_cookie(request):
    headers = {}
    request.send_header = lambda name, value: headers.update({name: value})
    request._set_browser_security_headers()
    return headers


def with_cookie(request, value):
    if "Cookie" in request.headers:
        del request.headers["Cookie"]
    request.headers["Cookie"] = value
    return request._browser_write_allowed()


def test_two_polling_instances_keep_both_tokens_in_same_host_cookie_jar():
    older = handler(8790, "older-process-token")
    newer = handler(8791, "newer-process-token")
    jar = SimpleCookie()
    for request in (older, newer, older, newer, older):
        jar.load(set_cookie(request)["Set-Cookie"])
    assert set(jar) == {"geoforge_csrf_8790", "geoforge_csrf_8791"}
    browser_cookie = "; ".join(f"{key}={item.value}" for key, item in jar.items())
    assert with_cookie(older, browser_cookie) == (True, "")
    assert with_cookie(newer, browser_cookie) == (True, "")


def test_cookie_name_uses_bound_port_not_host_header():
    request = handler(8791, Host="127.0.0.1:9999")
    assert request._csrf_cookie_name() == "geoforge_csrf_8791"
    assert set_cookie(request)["Set-Cookie"].startswith("geoforge_csrf_8791=")


def test_security_cookie_flags_and_other_headers_are_preserved():
    headers = set_cookie(handler())
    cookie = SimpleCookie(headers["Set-Cookie"])["geoforge_csrf_8791"]
    assert cookie["path"] == "/"
    assert cookie["httponly"] is True
    assert cookie["samesite"] == "Strict"
    assert not cookie["domain"]
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "no-referrer"


@pytest.mark.parametrize("cookie", [
    "",
    "geoforge_csrf_8791=old-instance-token",
    "geoforge_csrf_8790=current-instance-token",
    "geoforge_csrf=current-instance-token",
    "geoforge_csrf_8791=wrong; geoforge_csrf_8790=current-instance-token",
])
def test_missing_stale_legacy_and_other_port_tokens_are_rejected(cookie):
    ok, reason = with_cookie(handler(), cookie)
    assert not ok and "token" in reason


def test_refresh_after_same_port_restart_sets_fresh_token():
    old = handler(token="old-instance-token")
    fresh = handler(token="fresh-instance-token")
    jar = SimpleCookie(set_cookie(old)["Set-Cookie"])
    assert not with_cookie(fresh, "geoforge_csrf_8791=" + jar["geoforge_csrf_8791"].value)[0]
    jar.load(set_cookie(fresh)["Set-Cookie"])
    assert with_cookie(fresh, "geoforge_csrf_8791=" + jar["geoforge_csrf_8791"].value) == (True, "")


@pytest.mark.parametrize("headers", [
    {"Origin": "http://127.0.0.1:8790"},
    {"Host": "127.0.0.1:9999"},
    {"Origin": "https://evil.example"},
    {"Origin": "http://evil.example:8791", "Host": "evil.example:8791"},
    {"Origin": "null"},
    {"Sec-Fetch-Site": "cross-site"},
    {"Sec-Fetch-Site": "none"},
])
def test_cross_origin_and_opaque_contexts_remain_blocked_with_correct_cookie(headers):
    ok, reason = with_cookie(handler(**headers), "geoforge_csrf_8791=current-instance-token")
    assert not ok and reason
