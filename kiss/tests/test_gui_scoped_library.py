"""A checked selected library stays coherent from setup to project reopen."""
import io
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from kiss_cli import catalog, gui, install_locations, scoped_ki_updates, sessions


SCOPE = "a" * 32


@pytest.fixture
def scoped(tmp_path, monkeypatch):
    base = tmp_path / "bundled"
    selected = tmp_path / "selected"
    for root in (base, selected):
        (root / "models/WOFOST").mkdir(parents=True)
        (root / "models/WOFOST/SKILL.md").write_text("# WOFOST\n")
        (root / "kiss/manifests").mkdir(parents=True)
        (root / "kiss/manifests/WOFOST.yaml").write_text(root.name)
        (root / "ki_tools_common/ki_tools_common").mkdir(parents=True)
        (root / "ki_tools_common/ki_tools_common/__init__.py").write_text("")
    (base / "models/VIC").mkdir()
    (base / "models/VIC/SKILL.md").write_text("# VIC\n")
    meta = {"source_commit": "1" * 40, "selected_models": ["WOFOST"],
            "requested_models": ["WOFOST"], "selection_scope": True}
    checks = []

    def require(value):
        checks.append(value)
        if value != SCOPE:
            raise ValueError("Unknown or damaged selected library")
        return selected, meta

    monkeypatch.setattr(scoped_ki_updates, "require_selection", require)
    monkeypatch.setattr(gui.ki_guard, "enroll_catalogue", lambda cat: {"errors": {}})
    monkeypatch.setattr(gui.calibration, "ensure_project", lambda root: None)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    work = tmp_path / "work"
    work.mkdir()

    def handler(path="/api/models", scope=SCOPE):
        h = object.__new__(gui.Handler)
        h.repo_root = h.library_root = base
        h.catalog = catalog.Catalog(base / "models")
        h.catalogue_integrity_errors = {}
        h.workroot = work
        h.path = path
        h.headers = {"X-GeoForge-KI-Scope": scope} if scope else {}
        h._json = lambda body, status=200: (status, body)
        h._browser_write_allowed = lambda: (True, "")
        return h

    return handler, selected, meta, checks


def test_request_pins_all_library_components_and_restores(scoped):
    factory, selected, _, checks = scoped
    h = factory()
    old_catalog = h.catalog
    old_library = h.library_root

    def inspect():
        assert list(h.catalog.packages) == ["WOFOST"]
        assert h.catalog.models_dir == selected / "models"
        assert h.library_root == selected
        assert h._shipped_manifest("WOFOST") == selected / "kiss/manifests/WOFOST.yaml"
        assert h._helper_repo_root() == selected
        assert h._workdir(h.catalog.get("WOFOST")) == h.workroot / "scopes" / SCOPE / "wofost"
        assert h.repo_root == old_library
        return "done"

    assert h._with_request_library(inspect) == "done"
    assert checks == [SCOPE]
    assert h.catalog is old_catalog
    assert h.library_root == old_library
    assert "library_scope" not in vars(h)
    assert "_resolved_workroot" not in vars(h)


def test_scope_does_not_reuse_global_install_selection(scoped, tmp_path):
    factory, _, _, _ = scoped
    h = factory()
    previous = install_locations.select(h.workroot, "WOFOST", tmp_path / "old-install")
    result = h._with_request_library(lambda: h._workdir(h.catalog.get("WOFOST")))
    assert result != previous
    assert install_locations.resolve(h.workroot, "WOFOST") == previous


def test_keepalive_next_request_returns_to_global_library(scoped):
    factory, selected, _, checks = scoped
    h = factory()
    assert h._with_request_library(lambda: h.library_root) == selected
    h.headers = {}
    assert h._with_request_library(lambda: h.library_root) == h.repo_root
    assert list(h.catalog.packages) == ["VIC", "WOFOST"]
    assert checks == [SCOPE]


def test_scope_restores_after_operation_exception(scoped):
    h = scoped[0]()
    def fail():
        raise RuntimeError("operation failed")
    with pytest.raises(RuntimeError, match="operation failed"):
        h._with_request_library(fail)
    assert h.library_root == h.repo_root
    assert "library_scope" not in vars(h)


def test_concurrent_handlers_do_not_mutate_each_other(scoped):
    factory, selected, _, _ = scoped
    h, ordinary = factory(), factory(scope="")
    barrier = threading.Barrier(2)
    def check_scoped():
        def inside():
            barrier.wait(timeout=5)
            barrier.wait(timeout=5)
            return h.library_root
        return h._with_request_library(inside)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(check_scoped)
        barrier.wait(timeout=5)
        assert ordinary.library_root == ordinary.repo_root
        assert "VIC" in ordinary.catalog.packages
        barrier.wait(timeout=5)
        assert pending.result() == selected


@pytest.mark.parametrize("path", ["/api/models", "/setup?model=WOFOST", "/api/status"])
def test_invalid_scope_stops_get_before_dispatch(scoped, path):
    h = scoped[0](path, scope="/arbitrary/local/library")
    h._do_GET = lambda: pytest.fail("invalid scope reached GET")
    status, body = h.do_GET()
    assert status == 409
    assert "identifier" in body["error"]


@pytest.mark.parametrize("entry", ["get", "post_route", "post_body"])
@pytest.mark.parametrize("sid,expected", [("invalid", 400), ("0123456789ab", 404)])
def test_session_lookup_keeps_http_status_before_scoped_dispatch(scoped, entry, sid, expected):
    factory, _, _, checks = scoped
    path = "/api/setup-project-preflight" if entry == "post_body" else f"/api/session/{sid}/acquire"
    h = factory(path)
    h._do_GET = lambda: pytest.fail("invalid or missing session reached GET")
    h._do_POST_json = lambda *_: pytest.fail("invalid or missing session reached POST")
    body = json.dumps({"session": sid} if entry == "post_body" else {}).encode()
    h.headers["Content-Length"] = str(len(body))
    h.rfile = io.BytesIO(body)

    status, response = h.do_GET() if entry == "get" else h.do_POST()

    assert status == expected and response["error"]
    # A body-only session is discovered after the first, header-scoped pass.
    # Once known, a missing session must stop the nested dispatch immediately.
    assert checks == ([SCOPE] if entry == "post_body" else [])
    assert h.library_root == h.repo_root
    assert "library_scope" not in vars(h)


@pytest.mark.parametrize("sid", [["0123456789ab"], {"id": "0123456789ab"}, 123, [], {}, 0, None, False])
def test_malformed_body_session_is_bad_request_before_scoped_dispatch(scoped, sid):
    h = scoped[0]("/api/setup-project-preflight")
    h._do_POST_json = lambda *_: pytest.fail("malformed session reached POST")
    body = json.dumps({"session": sid}).encode()
    h.headers["Content-Length"] = str(len(body))
    h.rfile = io.BytesIO(body)

    status, response = h.do_POST()

    assert status == 400 and "Invalid project session" in response["error"]
    assert h.library_root == h.repo_root
    assert "library_scope" not in vars(h)


def test_conflicting_valid_session_strings_remain_conflict(scoped):
    h = scoped[0]("/api/session/0123456789ab/run?session=abcdef123456")
    h._do_GET = lambda: pytest.fail("conflicting sessions reached GET")

    status, response = h.do_GET()

    assert status == 409 and "Conflicting project sessions" in response["error"]
    assert scoped[3] == []
    assert h.library_root == h.repo_root


def test_saved_project_reopens_scope_without_client_id(scoped):
    factory, selected, _, checks = scoped
    h = factory()
    h.path = "/api/sessions"
    payload = {"models": ["WOFOST"], "provider": "api:deepseek"}
    body = json.dumps(payload).encode()
    h.headers["Content-Length"] = str(len(body))
    h.rfile = io.BytesIO(body)
    status, created = h.do_POST()
    assert status == 200
    assert created["library_scope"] == SCOPE
    assert Path(created["project_path"]).is_relative_to(h.workroot / "projects")
    h.path = "/api/session/" + created["id"] + "/data"
    h.headers = {}
    assert h._with_request_library(lambda: h.library_root) == selected
    assert checks[-1] == SCOPE


@pytest.mark.parametrize("original", ["", SCOPE])
def test_existing_project_cannot_change_scope(scoped, original):
    factory, _, _, _ = scoped
    h = factory()
    s = sessions.create(h.workroot, ["WOFOST"], "api:deepseek")
    if original:
        s["library_scope"] = original
        sessions.save(h.workroot, s)
    h.path = "/api/session/" + s["id"] + "/chat"
    h.headers = {"X-GeoForge-KI-Scope": "b" * 32}
    status, result = h._with_request_library(lambda: pytest.fail("scope changed"))
    assert status == 409
    assert "original KI library" in result["error"]


def test_posted_setup_session_uses_persisted_scope(scoped):
    factory, selected, _, _ = scoped
    h = factory("/api/setup-project-preflight", scope="")
    s = sessions.create(h.workroot, ["WOFOST"], "api:deepseek")
    s["library_scope"] = SCOPE
    sessions.save(h.workroot, s)
    data = json.dumps({"model": "WOFOST", "session": s["id"]}).encode()
    h.headers["Content-Length"] = str(len(data))
    h.rfile = io.BytesIO(data)
    h._do_POST_json = lambda route, req: h.library_root
    assert h.do_POST() == selected


def test_setup_metadata_has_scope_and_commit_without_raw_root(scoped):
    h = scoped[0]()
    def record():
        root = h._workdir(h.catalog.get("WOFOST"))
        h._record_setup_library(root)
        return json.loads((root / ".geoforge/ki-library-selection.json").read_text())
    metadata = h._with_request_library(record)
    assert metadata == {"library_scope": SCOPE, "source_commit": "1" * 40,
                        "models": ["WOFOST"]}


def test_selected_new_project_cannot_select_unchecked_model(scoped):
    h = scoped[0]("/api/sessions")
    status, body = h._with_request_library(h._do_POST_json, "/api/sessions",
                                           {"models": ["VIC"]})
    assert status == 400
    assert "no KI named" in body["error"]


def test_tampered_scope_cannot_fall_back_to_global(scoped, monkeypatch):
    h = scoped[0]()
    monkeypatch.setattr(scoped_ki_updates, "require_selection",
                        lambda scope: (_ for _ in ()).throw(ValueError("changed bytes")))
    status, result = h._with_request_library(lambda: pytest.fail("scope was downgraded"))
    assert status == 409
    assert result["error"] == "changed bytes"


@pytest.mark.parametrize("route", ["/api/setup-stop", "/api/setup-project-preflight-stop",
                                  "/api/session/0123456789ab/stop"])
def test_damaged_source_cannot_block_cancellation(scoped, monkeypatch, route):
    factory, _, _, _ = scoped
    h = factory(route)
    if "/session/" in route:
        monkeypatch.setattr(sessions, "load", lambda workroot, sid: {
            "id": sid, "library_scope": SCOPE})
    monkeypatch.setattr(scoped_ki_updates, "require_selection",
                        lambda scope: pytest.fail("Cancellation read damaged KI contents"))
    result = h._with_request_library(lambda: gui._installation_workroot(h))
    assert result == h.workroot / "scopes" / SCOPE
    assert "library_scope" not in vars(h)


def test_stop_still_rejects_arbitrary_scope_path(scoped):
    h = scoped[0]("/api/setup-stop", scope="../../outside")
    status, result = h._with_request_library(lambda: pytest.fail("invalid scope reached Stop"))
    assert status == 409
    assert "identifier" in result["error"]


def test_damaged_scoped_setup_stop_uses_its_own_job_namespace(scoped, monkeypatch):
    h = scoped[0]("/api/setup-stop")
    calls = []
    monkeypatch.setattr(scoped_ki_updates, "require_selection",
                        lambda scope: pytest.fail("Stop required an intact source"))
    monkeypatch.setattr(gui.setup_jobs, "stop", lambda workroot, model, job:
                        calls.append((workroot, model, job)) or {"id": job, "state": "stopping"})
    payload = json.dumps({"model": "WOFOST", "job_id": "owned-job"}).encode()
    h.headers["Content-Length"] = str(len(payload))
    h.rfile = io.BytesIO(payload)
    status, body = h.do_POST()
    assert status == 200 and body["job"]["state"] == "stopping"
    assert calls == [(h.workroot / "scopes" / SCOPE, "WOFOST", "owned-job")]
