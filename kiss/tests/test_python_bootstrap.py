"""Official runtime acquisition and transactional fresh-setup replacement."""
import base64
import hashlib
import gzip
import io
import json
import os
from pathlib import Path
import stat
import sys
from types import SimpleNamespace
import venv
import zipfile

import pytest

from kiss_cli import (install, ki_adaptations, ki_guard, paths, python_bootstrap as bootstrap,
                     setup, setup_runtime as runtime)
from kiss_cli.catalog import KI
from kiss_cli.manifest import Manifest
from .test_setup_runtime_refresh import case, authority


def call(c, version="3.12"):
    return bootstrap.prepare_python_runtime(c.ticket, c.ki, c.live, c.cfg,
        library_root=c.library, manifest=c.man, version=version)


@pytest.mark.parametrize("version", [None, "", "3", "2.7", "3.12rc1", "3.12;whoami", "https://example.com", "../3.12", "3.12.10.1"])
def test_version_input_cannot_choose_paths_urls_or_code(version, monkeypatch):
    monkeypatch.setattr(bootstrap, "_json", lambda url: pytest.fail("invalid input reached network"))
    with pytest.raises(ValueError):
        bootstrap.resolve_package(version)


def metadata(monkeypatch, *, damage=None):
    version = "3.12.10"
    package = bootstrap._FLAT + version + "/python." + version + ".nupkg"
    catalog = bootstrap._ORIGIN + "/v3/catalog0/data/2025.04.08.14.01.15/python.3.12.10.json"
    registration = {"packageContent": package, "listed": True, "catalogEntry": catalog}
    detail = {"id": "python", "version": version, "packageHashAlgorithm": "SHA512",
              "packageHash": base64.b64encode(b"h" * 64).decode(), "packageSize": 123}
    if damage == "origin": registration["catalogEntry"] = "https://example.com/python.3.12.10.json"
    if damage == "package": registration["packageContent"] = package.replace("python.", "pythonx86.")
    if damage == "unlisted": registration["listed"] = False
    if damage == "identity": detail["id"] = "other"
    if damage == "hash": detail["packageHash"] = "invalid"
    if damage == "algorithm": detail["packageHashAlgorithm"] = "MD5"
    if damage == "size": detail["packageSize"] = bootstrap._MAX_PACKAGE + 1
    docs = {bootstrap._FLAT + "index.json": {"versions": ["3.12.9", "3.12.10", "3.12.99-rc1", "3.13.1"]},
            bootstrap._REGISTRATION + version + ".json": registration, catalog: detail}
    monkeypatch.setattr(bootstrap, "_json", lambda url: docs[url])


def test_minor_resolves_exact_stable_fixed_package_with_catalog_sha512(monkeypatch):
    metadata(monkeypatch)
    result = bootstrap.resolve_package("3.12")
    assert result["version"] == "3.12.10"
    assert result["sha512"] == (b"h" * 64).hex()
    assert result["url"].endswith("/python/3.12.10/python.3.12.10.nupkg")


@pytest.mark.parametrize("damage", ["origin", "package", "unlisted", "identity", "hash", "algorithm", "size"])
def test_package_metadata_must_match_official_identity_and_bounds(monkeypatch, damage):
    metadata(monkeypatch, damage=damage)
    with pytest.raises(ValueError): bootstrap.resolve_package("3.12")


@pytest.mark.parametrize("url", ["http://api.nuget.org/v3-flatcontainer/python/a", "https://evil.example/v3-flatcontainer/python/a",
    "https://api.nuget.org.evil.example/v3-flatcontainer/python/a", "https://user@api.nuget.org/v3-flatcontainer/python/a",
    "https://api.nuget.org/v3-flatcontainer/python/../evil", "https://api.nuget.org/v3-flatcontainer/python/%2e%2e/evil"])
def test_redirects_cannot_escape_verified_official_origin(url):
    with pytest.raises(ValueError): bootstrap._url(url)


def test_download_verifies_actual_stream_hash_and_size(tmp_path, monkeypatch):
    data = b"official-artifact-fixture"
    class Response(io.BytesIO):
        headers = {"Content-Length": str(len(data))}
        def geturl(self): return bootstrap._FLAT + "fixture"
    monkeypatch.setattr(bootstrap, "_opener", lambda: SimpleNamespace(open=lambda *a, **k: Response(data)))
    target = tmp_path / "package"
    bootstrap._read_url(bootstrap._FLAT + "fixture", limit=100, destination=target,
        expected_size=len(data), expected_hash=hashlib.sha512(data).digest())
    assert target.read_bytes() == data
    with pytest.raises(ValueError, match="SHA512"):
        bootstrap._read_url(bootstrap._FLAT + "fixture", limit=100, expected_size=len(data), expected_hash=b"x" * 64)
    with pytest.raises(ValueError, match="length"):
        bootstrap._read_url(bootstrap._FLAT + "fixture", limit=2)


def test_compressed_nuget_metadata_is_supported_with_bounded_expansion(monkeypatch):
    raw = gzip.compress(b'{"version":"3.12.10"}')
    monkeypatch.setattr(bootstrap, "_read_url", lambda *a, **k: raw)
    assert bootstrap._json(bootstrap._REGISTRATION + "3.12.10.json")["version"] == "3.12.10"
    monkeypatch.setattr(bootstrap, "_MAX_JSON", 10)
    with pytest.raises(ValueError, match="expanded size"):
        bootstrap._json(bootstrap._REGISTRATION + "3.12.10.json")


def archive(tmp_path, names):
    target = tmp_path / "package.nupkg"
    with zipfile.ZipFile(target, "w") as output:
        for name in names:
            if isinstance(name, zipfile.ZipInfo): output.writestr(name, b"x")
            else:
                info = zipfile.ZipInfo(name)
                info.filename = name  # preserve hostile Windows backslashes on Windows too
                output.writestr(info, b"x")
    return target


@pytest.mark.parametrize("names", [["../escape"], ["/absolute"], ["C:/absolute"], ["a\\b"], ["tools/NUL.txt"],
    ["tools/name:stream"], ["tools/a."], ["tools/a "], ["tools/A", "tools/a"], ["a", "a/b"], ["a/b", "a"]])
def test_entire_zip_index_checked_before_any_extraction(tmp_path, names):
    package = archive(tmp_path, names)
    destination = tmp_path / "expanded"
    with pytest.raises(ValueError): bootstrap._extract(package, destination, tmp_path)
    assert not destination.exists()


def test_zip_symlinks_and_expanded_bombs_rejected(tmp_path, monkeypatch):
    link = zipfile.ZipInfo("tools/link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    package = archive(tmp_path, [link])
    with pytest.raises(ValueError): bootstrap._extract(package, tmp_path / "expanded", tmp_path)
    package = archive(tmp_path, ["tools/python.exe", "tools/data"])
    monkeypatch.setattr(bootstrap, "_MAX_EXPANDED", 1)
    with pytest.raises(ValueError, match="expanded size"):
        bootstrap._extract(package, tmp_path / "expanded", tmp_path)


@pytest.mark.skipif(os.name != "nt", reason="Windows runtime transaction")
@pytest.mark.parametrize("stopped", [False, True])
def test_failed_or_cancelled_creation_restores_exact_old_environment(case, monkeypatch, stopped):
    c = case
    before = Path(c.cfg.python).read_bytes()
    proof = authority(c)
    monkeypatch.setattr(bootstrap, "_acquire", lambda *a: (Path(sys.executable), {"version": "3.12.10"}, {}))
    error = install.InstallStopped("fixture stopped") if stopped else ValueError("fixture failed")
    def run(*args, **kwargs):
        environment = Path(c.cfg.roles["python_env"])
        environment.mkdir()
        (environment / "partial.txt").write_text("diagnostic retained")
        raise error
    monkeypatch.setattr(install, "_run", run)
    with pytest.raises(type(error), match="fixture"):
        call(c)
    assert Path(c.cfg.python).read_bytes() == before
    assert authority(c) == proof
    assert len(list(c.root.glob("venv.failed-bootstrap-*/partial.txt"))) == 1
    assert not list(c.root.glob("venv.before-bootstrap-*"))
    assert not (c.root / "status.json").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows runtime transaction")
@pytest.mark.parametrize("damage", ["closed", "helpers", "config"])
def test_bootstrap_cannot_acquire_without_active_exact_fresh_authority(case, monkeypatch, damage):
    c = case
    if damage == "closed": runtime.close(c.ticket)
    if damage == "helpers": (c.cfg.roles["ki_tools_common"] / "ki_tools_common/__init__.py").write_text("changed")
    if damage == "config": (c.root / paths.CONFIG_NAME).write_text("invalid")
    monkeypatch.setattr(bootstrap, "_acquire", lambda *a: pytest.fail("invalid authority reached acquisition"))
    with pytest.raises((ValueError, OSError)):
        call(c)


@pytest.mark.skipif(os.name != "nt", reason="Windows runtime transaction")
@pytest.mark.parametrize("target", ["active", "helper", "data_ki", "host_metadata", "environment_in_helper"])
def test_host_authorized_roles_still_cannot_place_runtime_inside_protected_trees(case, monkeypatch, target):
    c = case
    # Independently exercise destination containment even for a path mapping
    # that a host could have captured initially. Authority tampering itself is
    # tested separately above; it must not be our only containment defense.
    monkeypatch.setattr(runtime, "require_current", lambda *a, **k: {})
    before = ki_guard.require_intact(c.live.root)
    destinations = {"active": c.live.root, "helper": c.cfg.roles["ki_tools_common"] / "runtime",
                    "data_ki": c.cfg.roles["data_ki"] / "runtime", "host_metadata": c.root / ".geoforge/runtime"}
    if target == "environment_in_helper":
        environment = c.cfg.roles["ki_tools_common"] / "runtime"
        environment.mkdir()
        c.cfg.roles["python_env"] = environment
        c.cfg.python = str(environment / "Scripts/python.exe")
    else:
        c.cfg.roles["binaries"] = destinations[target]
    monkeypatch.setattr(bootstrap, "_acquire", lambda *a: pytest.fail("protected destination reached acquisition"))
    with pytest.raises(ValueError, match="outside KI"):
        call(c)
    assert ki_guard.require_intact(c.live.root) == before


@pytest.mark.skipif(os.name != "nt", reason="Windows runtime transaction")
@pytest.mark.parametrize("phase", ["projection_write", "ticket_write", "cancel_after_refresh", "cancel_final_emit"])
def test_failure_after_proof_writes_restores_runtime_and_both_host_records(case, monkeypatch, phase):
    c = case
    before_runtime, before_proof = Path(c.cfg.python).read_bytes(), authority(c)
    before_ticket = runtime._read(c.ticket)
    version = ".".join(map(str, sys.version_info[:3]))
    monkeypatch.setattr(bootstrap, "_acquire", lambda *a: (Path(sys.executable), {"version": version}, {}))
    original_run = install._run
    def run(args, **kwargs):
        result = original_run(args, **kwargs)
        if "venv" in args and result[0] == 0:
            selected = Path(c.cfg.python)
            selected.write_bytes(selected.read_bytes() + b"\nchanged launcher fixture\n")
        return result
    monkeypatch.setattr(install, "_run", run)
    original_write, fired = ki_adaptations._write, False
    def write(path, document):
        nonlocal fired
        result = original_write(path, document)
        matched = ((phase == "projection_write" and Path(path) == ki_adaptations._location(c.live.root)
                    and document.get("runtime_refresh")) or
                   (phase == "ticket_write" and Path(path) == runtime._location(c.ticket)
                    and document.get("refreshes")))
        if matched and not fired:
            fired = True
            raise OSError("injected failure after committed write")
        return result
    monkeypatch.setattr(ki_adaptations, "_write", write)
    if phase == "cancel_after_refresh":
        original_refresh = runtime.refresh
        def refresh(*a, **k):
            original_refresh(*a, **k)
            raise install.InstallStopped("injected cancellation after proof")
        monkeypatch.setattr(runtime, "refresh", refresh)
    def emit(text):
        if phase == "cancel_final_emit" and "is ready at" in text:
            raise install.InstallStopped("injected cancellation during final emit")
    with pytest.raises((OSError, install.InstallStopped), match="injected"):
        bootstrap.prepare_python_runtime(c.ticket, c.ki, c.live, c.cfg,
            library_root=c.library, manifest=c.man, version=version, emit=emit)
    assert Path(c.cfg.python).read_bytes() == before_runtime
    assert authority(c) == before_proof
    assert runtime._read(c.ticket) == before_ticket
    assert ki_adaptations.projection(c.live.root, c.cfg)
    audit = json.loads(next((c.root / ".geoforge/python-bootstrap").glob("*.json")).read_text())
    assert audit["previous_environment_restored"]
    assert audit["state"] in {"failed", "stopped"}
    assert Path(audit["failed_environment"]).is_dir()


def test_generic_python_ki_can_capture_bootstrap_authority_without_path_projection(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_KI_ADAPTATION_HOME", str(tmp_path / "authority"))
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    library, root = tmp_path / "library", tmp_path / "workspace"
    source = library / "models" / "Demo"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# Ordinary Python fixture\n")
    common = library / "ki_tools_common" / "ki_tools_common"
    common.mkdir(parents=True)
    (common / "__init__.py").write_text("# helper fixture\n")
    root.mkdir()
    cfg = paths.KissConfig.default(root)
    venv.EnvBuilder(with_pip=False).create(cfg.roles["python_env"])
    cfg.python = str(cfg.roles["python_env"] / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
    cfg.relocation = "none"
    ki, man, live = KI("Demo", source), Manifest(model="Demo"), KI("Demo", root / "ki")
    ki_guard.enroll(source)
    ticket = runtime.begin(root)
    setup.prepare_common(cfg, library)
    (root / paths.CONFIG_NAME).write_text(cfg.dumps(), encoding="utf-8")
    setup.materialise_active(source, live.root, cfg, manifest=man, library_root=library)
    runtime.capture(ticket, ki, live, cfg, library_root=library, manifest=man)
    record = runtime.require_current(ticket, ki, live, cfg, library_root=library, manifest=man)
    assert record["state"] == "captured_basic"
    assert not record["projection"].get("path_projection")
    assert runtime.refresh(ticket, ki, live, cfg, library_root=library, manifest=man) is False
    (cfg.roles["ki_tools_common"] / "ki_tools_common/__init__.py").write_text("changed")
    with pytest.raises(ValueError): runtime.require_current(ticket, ki, live, cfg, library_root=library, manifest=man)


@pytest.mark.skipif(os.name != "nt" or os.environ.get("GEOFORGE_TEST_REAL_PYTHON_BOOTSTRAP") != "1",
                   reason="explicit isolated official-package integration opt-in")
def test_real_official_python_creates_final_path_venv_and_refreshes_exact_projection(case):
    c = case
    before = ki_guard.require_intact(c.live.root)
    config = (c.root / paths.CONFIG_NAME).read_bytes()
    helpers = runtime._helpers(c.cfg)
    with install.cancellation_context():
        result = call(c)
    assert result["ok"] and result["python_version"].startswith("3.12.")
    assert result["package"]["id"] == "python" and result["projection_refreshed"]
    assert ki_guard.require_intact(c.live.root) == before
    assert config == (c.root / paths.CONFIG_NAME).read_bytes()
    assert helpers == runtime._helpers(c.cfg)
    assert result["runtime_identity"]["prefix"] == str(c.cfg.roles["python_env"])
    assert not (c.root / "status.json").exists()
    # Real pip launcher records the final venv path and still works after creation.
    rc, output = install._run([str(c.cfg.roles["python_env"] / "Scripts/pip.exe"), "--version"], cwd=c.root)
    assert rc == 0, output
    runtime.close(c.ticket)
    assert ki_adaptations.projection(c.live.root, setup.load_runtime_config(c.root))
    report = os.environ.get("GEOFORGE_BOOTSTRAP_REPORT")
    if report:
        Path(report).write_text(json.dumps({**result, "isolated_workspace": str(c.root),
            "ki_unchanged": True, "helpers_unchanged": True, "config_unchanged": True,
            "scientific_model_executed": False}, indent=2), encoding="utf-8")
