"""Exercise urllib's real redirect dispatch using a network-free transport."""
from __future__ import annotations

import io
import ssl
import urllib.request
import urllib.response
from email.message import Message
from types import SimpleNamespace

import pytest

from kiss_cli import ki_updates, settings


class CountingBody(io.BytesIO):
    def __init__(self, body):
        super().__init__(body)
        self.read_sizes = []

    def read(self, size=-1):
        self.read_sizes.append(size)
        return super().read(size)


class FixtureTransport(urllib.request.BaseHandler):
    """Respond before urllib's real HTTPS handler; HTTP must never be reached."""
    handler_order = 100

    def __init__(self, routes):
        self.routes, self.requests, self.bodies = routes, [], []

    def https_open(self, request):
        self.requests.append(request)
        route = self.routes[request.full_url]
        if isinstance(route, Exception):
            raise route
        code, headers, body = route
        fields = Message()
        for key, value in headers.items():
            fields[key] = value
        stream = CountingBody(body)
        self.bodies.append(stream)
        response = urllib.response.addinfourl(stream, fields, request.full_url, code)
        response.msg = "fixture response"
        return response

    def http_open(self, request):
        pytest.fail(f"Updater attempted unencrypted transport: {request.full_url}")


@pytest.fixture
def transport(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_KI_UPDATE_HOME", str(tmp_path / "updates"))
    monkeypatch.setattr(settings, "proxy_url_for", lambda _: "")
    manager = ki_updates.UpdateManager(tmp_path / "library", lambda _: None)
    fake = FixtureTransport({})
    real_build = urllib.request.build_opener
    captured = []

    def build(*handlers):
        captured.append(handlers)
        return real_build(*handlers, fake)

    monkeypatch.setattr(urllib.request, "build_opener", build)
    return SimpleNamespace(manager=manager, fake=fake, handlers=captured, root=tmp_path)


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_https_to_http_redirect_is_refused_before_following(transport, code):
    origin = "https://api.github.com/repos/example/commits/windows-version"
    transport.fake.routes[origin] = (code, {"Location": "http://api.github.com/forged-root"}, b"")
    with pytest.raises(RuntimeError, match="redirect without HTTPS"):
        transport.manager._request_json(origin)
    assert [request.full_url for request in transport.fake.requests] == [origin]


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_authenticated_https_redirects_remain_supported(transport, code):
    origin, target = "https://api.github.com/source", "https://github.com/redirect-target"
    transport.fake.routes.update({origin: (code, {"Location": target}, b""),
                                  target: (200, {}, b'{"ok": true}')})
    assert transport.manager._request_json(origin) == {"ok": True}
    assert [request.full_url for request in transport.fake.requests] == [origin, target]


@pytest.mark.parametrize("target", ["/target", "//api.github.com/target"])
def test_relative_redirects_keep_https(transport, target):
    origin, absolute = "https://api.github.com/source", "https://api.github.com/target"
    transport.fake.routes.update({origin: (302, {"Location": target}, b""),
                                  absolute: (200, {}, b'{"ok": true}')})
    assert transport.manager._request_json(origin) == {"ok": True}
    assert transport.fake.requests[-1].full_url == absolute


def test_downgrade_on_later_redirect_is_also_refused(transport):
    origin, middle = "https://api.github.com/source", "https://github.com/middle"
    transport.fake.routes.update({origin: (302, {"Location": middle}, b""),
        middle: (307, {"Location": "http://github.com/final"}, b"")})
    with pytest.raises(RuntimeError, match="redirect without HTTPS"):
        transport.manager._request_json(origin)
    assert [request.full_url for request in transport.fake.requests] == [origin, middle]


@pytest.mark.parametrize("url", ["http://api.github.com/source", "ftp://github.com/source"])
def test_initial_non_https_request_is_refused_before_opening(transport, url):
    with pytest.raises(ValueError, match="require HTTPS"):
        transport.manager._open(urllib.request.Request(url), timeout=30)
    assert transport.handlers == [] and transport.fake.requests == []


def test_redirect_policy_is_added_after_saved_proxy_and_verified_tls(transport, monkeypatch):
    origin, target = "https://api.github.com/source", "https://api.github.com/target"
    context = ssl.create_default_context()
    selected_routes = []
    def proxy(route):
        selected_routes.append(route)
        return "http://127.0.0.1:7897"
    monkeypatch.setattr(settings, "proxy_url_for", proxy)
    monkeypatch.setattr(ki_updates.tls, "context", lambda: context)
    transport.fake.routes.update({origin: (302, {"Location": target}, b""),
                                  target: (200, {}, b'{"ok": true}')})
    assert transport.manager._request_json(origin) == {"ok": True}
    handlers = transport.handlers[0]
    assert isinstance(handlers[0], urllib.request.ProxyHandler)
    assert handlers[0].proxies == {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}
    assert isinstance(handlers[1], urllib.request.HTTPSHandler) and handlers[1]._context is context
    assert isinstance(handlers[2], ki_updates._HTTPSOnlyRedirectHandler)
    assert selected_routes == [settings.GITHUB_PROXY_TARGET]


def test_json_read_is_bounded_before_parsing(transport, monkeypatch):
    monkeypatch.setattr(ki_updates, "MAX_JSON_BYTES", 32)
    origin = "https://api.github.com/oversized"
    transport.fake.routes[origin] = (200, {}, b'{"body":"' + b"x" * 80 + b'"}')
    with pytest.raises(RuntimeError, match="JSON response exceeded"):
        transport.manager._request_json(origin)
    assert transport.fake.bodies[-1].read_sizes == [33]


@pytest.mark.parametrize("body", [b"[]", b"not JSON"])
def test_invalid_json_root_is_rejected(transport, body):
    origin = "https://api.github.com/invalid"
    transport.fake.routes[origin] = (200, {}, body)
    with pytest.raises((RuntimeError, ValueError)):
        transport.manager._request_json(origin)


@pytest.mark.parametrize("headers,expected_reads", [({"Content-Length": "100"}, []), ({}, [9])])
def test_raw_metadata_is_bounded_by_header_and_actual_read(transport, headers, expected_reads):
    origin = "https://raw.githubusercontent.com/example/repo/commit/file"
    transport.fake.routes[origin] = (200, headers, b"x" * 100)
    with pytest.raises(RuntimeError, match="byte limit"):
        transport.manager._request_bytes(origin, max_bytes=8)
    assert transport.fake.bodies[-1].read_sizes == expected_reads


@pytest.mark.parametrize("url", ["http://raw.githubusercontent.com/repo/file", "https://example.com/file"])
def test_raw_metadata_requires_official_https_host_before_transport(transport, url):
    with pytest.raises(ValueError, match="official HTTPS raw-content host"):
        transport.manager._request_bytes(url, max_bytes=8)
    assert transport.fake.requests == []


def test_raw_metadata_downgrade_is_refused(transport):
    origin = "https://raw.githubusercontent.com/example/repo/commit/file"
    transport.fake.routes[origin] = (302, {"Location": "http://raw.githubusercontent.com/forged"}, b"")
    with pytest.raises(RuntimeError, match="redirect without HTTPS"):
        transport.manager._request_bytes(origin, max_bytes=8)
    assert len(transport.fake.requests) == 1


def test_archive_downgrade_creates_no_download_file(transport):
    manager = transport.manager
    origin = f"{ki_updates.ARCHIVE_ROOT}/{manager._archive_ref.replace('/', '%2F')}"
    transport.fake.routes[origin] = (302, {"Location": "http://codeload.github.com/forged"}, b"")
    output = transport.root / "download.zip"
    with pytest.raises(RuntimeError, match="redirect without HTTPS"):
        manager._download(output)
    assert not output.exists()


def test_tls_verification_failure_is_not_retried_over_another_route(transport):
    origin = "https://api.github.com/source"
    transport.fake.routes[origin] = ssl.SSLCertVerificationError("fixture certificate rejected")
    with pytest.raises(ssl.SSLCertVerificationError):
        transport.manager._request_json(origin)
    assert [request.full_url for request in transport.fake.requests] == [origin]
