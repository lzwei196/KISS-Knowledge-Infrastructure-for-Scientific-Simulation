"""Static guest binding and exact historical Python-hash migration.

Real signatures/projection copies in disposable fixtures. No Linux process,
package change, KI tool or model is executed.
"""
import copy
import json
from types import SimpleNamespace

import pytest

from kiss_cli import dependency_capabilities as capabilities, ki_adaptations as adapt
from kiss_cli import ki_guard, runtime_context, software_verification as verification
from .test_projection_build_refresh import case, refresh


def observed(c):
    return {"protocol": "geoforge.wsl-worker.v1", "uid": 1000,
        "user": c.backend["user"], "home": "/home/fixture", "machine_id": "1" * 32,
        "kernel": "6.6-test", "architecture": "x86_64", "python": "/usr/bin/python3",
        "python_realpath": "/usr/bin/python3.12", "python_sha256": "1" * 64,
        "python_version": [3, 12, 3], "workspace": c.backend["workspace"],
        "workspace_id": c.backend["id"], "filesystem": "0xef53",
        "workspace_device": 42, "workspace_inode": 100, "marker_sha256": "2" * 64}


@pytest.fixture(params=[False, True], ids=["explicit", "opaque"])
def guest(case, monkeypatch, tmp_path, request):
    c = case
    raw = observed(c)
    c.backend["guest_identity"] = runtime_context.guest_digest(raw)
    before = adapt._read(adapt._location(c.live))
    before["projection_binding"] = verification.projection_binding(c.cfg)
    before["runtime_identity"] = verification.runtime_identity(c.cfg)
    if request.param:
        before.pop("projection_binding")
    before = adapt._write(adapt._location(c.live), before)
    profile = tmp_path / "profile"
    monkeypatch.setenv("GEOFORGE_APP_DATA_DIR", str(profile))
    authority = profile / "dependency-capabilities"
    authority.mkdir(parents=True)
    report = {"policy": capabilities.POLICY, "profile": capabilities.PROFILE,
        "implementation": "historical-verifier-is-not-current-authority",
        "model_readiness": False, "backend_identity": c.backend["guest_identity"],
        "binding": {"distro": c.backend["distro"], "user": c.backend["user"],
                    "workspace": c.backend["workspace"], "workspace_id": c.backend["id"],
                    "python": "/usr/bin/python3"},
        "evidence": {"system_files": {raw["python_realpath"]: {
            "path": raw["python_realpath"], "bytes": 1234,
            "sha256": raw["python_sha256"], "package": "python3.12-minimal"}}}}
    path = authority / ("a" * 64 + ".json")
    def save(value=report, *, signed=True):
        value = copy.deepcopy(value)
        if signed:
            value = adapt._receipts().sign(authority, value)
        path.write_text(json.dumps({"capabilities": value}), encoding="utf-8")
    save()
    raw["python_sha256"] = "3" * 64
    def update():
        c.backend["guest_identity"] = runtime_context.guest_digest(raw)
        c.backend["guest_path_identity"] = runtime_context.guest_path_digest(raw)
    update()
    c.backend["source_hash"] = "b" * 64
    monkeypatch.setattr(runtime_context, "guest_observation", lambda: copy.deepcopy(raw))
    return SimpleNamespace(c=c, raw=raw, original=before, path=path, report=report,
                           save=save, update=update)


def test_exact_legacy_preimage_refresh_changes_only_provenance_and_not_readiness(guest):
    g, c = guest, guest.c
    files = {p: p.read_bytes() for p in c.root.rglob("*") if p.is_file()}
    guard = ki_guard.require_intact(c.live)
    with pytest.raises(adapt.AdaptationError, match="runtime|revalidate"):
        adapt.projection(c.live, c.cfg)
    assert adapt._read(adapt._location(c.live)) == g.original
    assert refresh(c)
    doc = adapt.projection(c.live, c.cfg)
    assert doc["projected_digest"] == g.original["projected_digest"]
    assert doc["runtime_identity"] != g.original["runtime_identity"]
    assert doc["projection_binding"] == verification.projection_binding(c.cfg)
    assert doc["projection_refresh"]["model_readiness"] is False
    assert "guest_identity" not in doc["projection_binding"]["backend"]
    audit = adapt._read(next((adapt._home() / "projection-refreshes").glob("*.json")))
    assert audit["guest_path_refresh"]["kind"] == (
        "exact_python_content_preimage" if "projection_binding" in g.original
        else "exact_opaque_runtime_preimage")
    assert audit["previous"] == g.original
    assert audit["model_readiness"] is False
    assert files == {p: p.read_bytes() for p in c.root.rglob("*") if p.is_file()}
    assert ki_guard.require_intact(c.live) == guard
    assert not (c.root / "status.json").exists()
    assert refresh(c) is False


@pytest.mark.parametrize("field,value", [
    ("python_sha256", "4" * 64), ("python_version", [3, 12, 4]), ("kernel", "6.7-test")])
def test_new_static_record_survives_runtime_content_but_full_readiness_expires(guest, field, value):
    assert refresh(guest.c)
    before = adapt.projection(guest.c.live, guest.c.cfg)
    runtime = verification.runtime_identity(guest.c.cfg)
    guest.raw[field] = value
    guest.update()
    assert verification.runtime_identity(guest.c.cfg) != runtime
    assert adapt.projection(guest.c.live, guest.c.cfg) == before
    assert refresh(guest.c) is False


@pytest.mark.parametrize("field,value", [("uid", 1001), ("machine_id", "f" * 32),
    ("workspace_inode", 999), ("marker_sha256", "f" * 64),
    ("python_realpath", "/usr/bin/python3.13"), ("architecture", "aarch64")])
def test_new_static_record_cannot_migrate_location_or_ownership_changes(guest, field, value):
    assert refresh(guest.c)
    before = adapt._location(guest.c.live).read_bytes()
    guest.raw[field] = value
    guest.update()
    with pytest.raises(adapt.AdaptationError, match="runtime binding changed"):
        adapt.projection(guest.c.live, guest.c.cfg)
    with pytest.raises(adapt.AdaptationError):
        refresh(guest.c)
    assert adapt._location(guest.c.live).read_bytes() == before


@pytest.mark.parametrize("field,value", [
    ("uid", 1001), ("user", "other"), ("home", "/home/other"),
    ("machine_id", "f" * 32), ("architecture", "aarch64"),
    ("python", "/usr/bin/python-other"), ("python_realpath", "/usr/bin/python3.13"),
    ("workspace", "/other"), ("workspace_id", "e" * 32), ("filesystem", "0x123"),
    ("workspace_device", 99), ("workspace_inode", 999), ("marker_sha256", "f" * 64),
    ("protocol", "other"), ("python_version", [3, 12, 4]), ("kernel", "6.7-test")])
def test_legacy_bridge_refuses_every_other_guest_change(guest, field, value):
    guest.raw[field] = value
    guest.update()
    before = adapt._location(guest.c.live).read_bytes()
    with pytest.raises(adapt.AdaptationError):
        refresh(guest.c)
    assert adapt._location(guest.c.live).read_bytes() == before
    assert not list((adapt._home() / "projection-refreshes").glob("*"))


@pytest.mark.parametrize("damage", ["unsigned", "wrong_binding", "wrong_hash", "wrong_path", "wrong_policy",
    "wrong_profile", "missing_file", "missing_report", "readiness", "non_integer_size", "missing_size"])
def test_legacy_bridge_requires_exact_authenticated_candidate(guest, damage):
    report = copy.deepcopy(guest.report)
    row = report["evidence"]["system_files"][guest.raw["python_realpath"]]
    if damage == "unsigned": guest.save(report, signed=False)
    elif damage == "missing_report": guest.path.unlink()
    else:
        if damage == "wrong_binding": report["binding"]["user"] = "other"
        elif damage == "wrong_hash": row["sha256"] = "5" * 64
        elif damage == "wrong_path": row["path"] = "/usr/bin/other"
        elif damage == "wrong_policy": report["policy"] = "other"
        elif damage == "wrong_profile": report["profile"] = "other"
        elif damage == "missing_file": report["evidence"]["system_files"] = {}
        elif damage == "readiness": report["model_readiness"] = True
        elif damage == "non_integer_size": row["bytes"] = True
        elif damage == "missing_size": row.pop("bytes")
        guest.save(report)
    with pytest.raises(adapt.AdaptationError):
        refresh(guest.c)
    assert adapt._read(adapt._location(guest.c.live)) == guest.original


@pytest.mark.parametrize("damage", ["role", "python_path", "relocation", "outer_user", "outer_distro",
    "live", "source", "helper", "recipe"])
def test_guest_migration_does_not_waive_existing_path_source_and_guard_checks(guest, damage):
    c = guest.c
    if damage == "role": c.cfg.roles["unused"] = c.root / "other"
    elif damage == "python_path": c.cfg.python += "-other"
    elif damage == "relocation": c.cfg.relocation = "port"
    elif damage == "outer_user": c.backend["user"] = "other"
    elif damage == "outer_distro": c.backend["distro"] = "Other"
    elif damage == "live": (c.live / "tool.py").write_text("tampered")
    elif damage == "source": (c.source / "tool.py").write_text("tampered")
    elif damage == "helper": (c.cfg.roles["ki_tools_common"] / "common.py").write_text("tampered")
    elif damage == "recipe": c.man.notes = "other recipe"
    with pytest.raises((ValueError, RuntimeError)):
        refresh(c)
    assert adapt._read(adapt._location(c.live)) == guest.original


def test_identical_guest_can_upgrade_static_schema_without_historical_capability(guest):
    guest.raw["python_sha256"] = "1" * 64
    guest.update()
    guest.path.unlink()
    assert refresh(guest.c)
    audit = adapt._read(next((adapt._home() / "projection-refreshes").glob("*.json")))
    assert audit["guest_path_refresh"]["kind"] == (
        "identical_guest_path_schema" if "projection_binding" in guest.original
        else "exact_application_source_preimage")


def test_worker_digest_matches_protocol_and_rejects_unrecognized_identity_fields(guest):
    from kiss_cli import runtime_backend
    import hashlib
    raw = guest.raw
    assert runtime_context.guest_digest(raw) == hashlib.sha256(runtime_backend._canonical(raw)).hexdigest()
    for invalid in ({**raw, "new_field": "unreviewed"}, {k: v for k, v in raw.items() if k != "uid"}):
        with pytest.raises(ValueError, match="Incomplete"):
            runtime_context.guest_path_digest(invalid)


def test_opaque_project_refresh_uses_its_exact_saved_paths_and_retained_library(guest):
    from kiss_cli import project_paths, project_verification, setup
    c = guest.c
    project = c.guest / "projects" / "opaque-existing"
    project.mkdir(parents=True)
    cfg = project_paths.model_config(project, "Demo", c.cfg)
    home = project / "models" / "Demo"
    cfg.roles["ki_tools_common"] = home / "ki_tools_common"
    setup.prepare_common(cfg, c.library)
    saved = home / "kiss.toml"
    saved.write_text(cfg.dumps(), encoding="utf-8")
    live = home / "ki"
    current = dict(c.backend)
    c.backend.update(guest_identity=guest.report["backend_identity"], source_hash="a" * 64)
    c.backend.pop("guest_path_identity")
    adapt.materialise(c.source, live, cfg, model="Demo", library_root=c.library, manifest=c.man)
    original = adapt._read(adapt._location(live))
    original.pop("projection_binding")
    original = adapt._write(adapt._location(live), original)
    c.backend.clear(); c.backend.update(current)
    before = {p: p.read_bytes() for p in project.rglob("*") if p.is_file()}
    strict = project_verification._config(project, home, "Demo")
    with pytest.raises(adapt.AdaptationError, match="revalidate"):
        adapt.projection(live, strict)
    assert adapt.refresh_project_projection(live, strict, model="Demo", manifest=c.man)
    updated = adapt.projection(live, strict)
    assert updated["projected_digest"] == original["projected_digest"]
    assert updated["library_root"] == str(c.library)
    assert updated["projection_refresh"]["model_readiness"] is False
    assert before == {p: p.read_bytes() for p in project.rglob("*") if p.is_file()}
    assert not (project / ".geoforge" / "project-verification").exists()


def test_opaque_candidate_needs_the_exact_whole_runtime_hash_and_retained_app(guest):
    c = guest.c
    original = copy.deepcopy(guest.original)
    original.pop("projection_binding", None)
    original["runtime_identity"] = "f" * 64
    original = adapt._write(adapt._location(c.live), original)
    with pytest.raises(adapt.AdaptationError, match="preimage"):
        refresh(c)
    assert adapt._read(adapt._location(c.live)) == original

    original["runtime_identity"] = guest.original["runtime_identity"]
    original = adapt._write(adapt._location(c.live), original)
    (c.guest / "app" / ("a" * 64)).rmdir()
    with pytest.raises(adapt.AdaptationError, match="preimage"):
        refresh(c)
    assert adapt._read(adapt._location(c.live)) == original
