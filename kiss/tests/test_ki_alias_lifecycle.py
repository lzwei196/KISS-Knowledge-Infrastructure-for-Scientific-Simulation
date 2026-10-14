"""Contained aliases survive host copies; no provider, download or model run."""
import importlib.util
import json
from pathlib import Path
import sys
import os
import subprocess
from types import SimpleNamespace

import pytest

from kiss_cli import calibration, kdtstudio, ki_copy, ki_guard, ki_investigation
from kiss_cli import ki_review_agents, ki_tree, ki_verification, paths, port, setup
from .test_ki_verification_boundaries import isolated_engine, write_package, import_handler


@pytest.fixture
def linked(tmp_path, monkeypatch):
    for name, directory in (("GEOFORGE_KDT_HOME", "studio"),
                            ("GEOFORGE_KI_INVESTIGATION_HOME", "investigations"),
                            ("GEOFORGE_FLOW_REGISTRY", "registry")):
        monkeypatch.setenv(name, str(tmp_path / directory))
    monkeypatch.delenv("GEOFORGE_KDT_ENGINE", raising=False)
    monkeypatch.setattr(ki_guard, "_legacy_installation_roots", lambda: [])
    root = tmp_path / "source"
    write_package(root)
    (root / "s1_grid").mkdir()
    (root / "s1_grid/tool.py").write_text("DATA = 'KISSPATH_DATA/input.nc'\n", encoding="utf-8")
    (root / "tools").mkdir()
    (root / "tools/s1_grid").symlink_to(Path("../s1_grid"), target_is_directory=True)
    (root / "tool_alias.py").symlink_to(Path("s1_grid/tool.py"))
    with isolated_engine(tmp_path) as engine:
        yield SimpleNamespace(root=root, parent=tmp_path, engine=engine)
    ki_investigation._STOPS.clear()
    ki_investigation._RUNNING.clear()


def assert_aliases(root):
    assert (root / "tools/s1_grid").is_symlink()
    assert (root / "tool_alias.py").is_symlink()
    assert (root / "tools/s1_grid/tool.py").resolve() == (root / "s1_grid/tool.py").resolve()
    assert (root / "tool_alias.py").read_bytes() == (root / "s1_grid/tool.py").read_bytes()


def test_checked_copy_preserves_alias_identity_and_tool_count(linked, monkeypatch):
    target = linked.parent / "copy"
    ki_copy.copytree(linked.root, target)
    assert_aliases(target)
    assert ki_tree.digest(target) == ki_tree.digest(linked.root)
    assert sum(e.kind == "link" for e in ki_tree.scan(target).entries) == 2
    # Exercise the actual shared KDT tool counter, not a test imitation.
    module_path = Path(__file__).parents[2] / "ki_tools_common/ki_tools_common/ki_projection_common.py"
    monkeypatch.setattr(sys, "path", list(sys.path))
    spec = importlib.util.spec_from_file_location("alias_test_tool_counter", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.tool_files(target) == module.tool_files(linked.root)
    assert len(module.tool_files(target)) == 1


@pytest.mark.parametrize("bad", ["outside", "dangling", "self"])
def test_copy_rejects_unsafe_alias_before_creating_destination(linked, bad):
    alias = linked.root / "tools/s1_grid"
    alias.unlink()
    spelling = {"outside": linked.parent, "dangling": Path("../missing"), "self": Path(".")}[bad]
    alias.symlink_to(spelling, target_is_directory=True)
    target = linked.parent / "rejected"
    with pytest.raises(ValueError):
        ki_copy.copytree(linked.root, target)
    assert not target.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows junction regression")
def test_copy_rejects_empty_destination_junction_before_any_write(linked):
    outside = linked.parent / "outside"
    outside.mkdir()
    target = linked.parent / "junction"
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(target), str(outside)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert not target.is_symlink()
    with pytest.raises(ValueError, match="reparse"):
        ki_copy.copytree(linked.root, target, dirs_exist_ok=True)
    assert list(outside.iterdir()) == []


def test_materialisation_rewrites_canonical_file_and_retains_aliases(linked):
    target = linked.parent / "materialised"
    cfg = paths.KissConfig.default(linked.parent / "work")
    result = port.materialise(linked.root, target, cfg)
    assert not result.unresolved
    assert_aliases(target)
    assert cfg.roles["data"].as_posix() in (target / "tool_alias.py").read_text()
    before = ki_tree.digest(target)
    port.materialise(linked.root, target, cfg)
    assert ki_tree.digest(target) == before
    assert "KISSPATH_DATA" in (linked.root / "s1_grid/tool.py").read_text()


def test_changed_alias_binding_blocks_refresh_before_writing(linked):
    target = linked.parent / "materialised"
    cfg = paths.KissConfig.default(linked.parent / "work")
    port.materialise(linked.root, target, cfg)
    alias = target / "tool_alias.py"
    alias.unlink()
    alias.symlink_to(Path("SKILL.md"))
    before = (target / "SKILL.md").read_bytes()
    with pytest.raises(ValueError, match="alias differs"):
        port.materialise(linked.root, target, cfg)
    assert (target / "SKILL.md").read_bytes() == before


def test_materialisation_requires_a_source_identity_before_writing(linked, monkeypatch):
    target = linked.parent / "materialised"
    monkeypatch.setattr(ki_tree, "digest", lambda *_: None)
    with pytest.raises(ValueError, match="source identity"):
        port.materialise(linked.root, target, paths.KissConfig.default(linked.parent / "work"))
    assert not target.exists()


def test_guard_backup_recovery_and_target_drift(linked):
    baseline = ki_guard.enroll(linked.root)
    backup = ki_guard._entry(linked.root) / baseline["digest"][:12]
    assert_aliases(backup)
    (linked.root / "s1_grid/tool.py").write_text("unreviewed = True\n", encoding="utf-8")
    with pytest.raises(ki_guard.KIIntegrityError, match="changed"):
        ki_guard.require_intact(linked.root)
    drift = ki_guard.recover_drift(linked.root, quiescent=True)
    assert_aliases(drift)
    assert_aliases(linked.root)
    assert "KISSPATH_DATA" in (linked.root / "tool_alias.py").read_text()


def test_authoring_verification_copies_aliases_without_changing_source(linked, monkeypatch):
    seen = []
    def verify(candidate, *, kind):
        assert_aliases(candidate)
        seen.append(ki_tree.digest(candidate))
        return {"ok": True, "failures": [], "warnings": [], "info": {}}
    before = ki_tree.digest(linked.root)
    # Undo this nested override before isolated_engine restores the real loader.
    with monkeypatch.context() as patcher:
        patcher.setattr(kdtstudio, "_load_engine_module", lambda *_: SimpleNamespace(verify=verify))
        report = ki_verification.verify_candidate(linked.root, name="Demo")
    assert seen and report["ok"]
    assert report["candidate_digest"] == before == ki_tree.digest(linked.root)
    ki_verification.require_current(linked.root, report)


def test_deferred_preflight_alias_does_not_replace_another_canonical_tool(linked, monkeypatch):
    canonical = linked.root / "s1_grid/preflight.py"
    canonical.write_bytes((linked.root / "preflight_check.py").read_bytes())
    (linked.root / "preflight_check.py").unlink()
    (linked.root / "preflight_check.py").symlink_to(Path("s1_grid/preflight.py"))
    original = canonical.read_bytes()
    def verify(candidate, *, kind):
        assert not (candidate / "preflight_check.py").is_symlink()
        assert (candidate / "s1_grid/preflight.py").read_bytes() == original
        return {"ok": True, "failures": [], "warnings": [], "info": {}}
    with monkeypatch.context() as patcher:
        patcher.setattr(kdtstudio, "_load_engine_module", lambda *_: SimpleNamespace(verify=verify))
        assert ki_verification.verify_candidate(linked.root, name="Demo")["ok"]
    assert canonical.read_bytes() == original


def test_verified_export_and_gui_import_roundtrip_contained_aliases(linked):
    report = ki_verification.verify_candidate(linked.root, name="Demo", desktop=False)
    archive = linked.parent / "verified.zip"
    kdtstudio._export_verified_tree(linked.root, archive, report["candidate_digest"])
    request, response = import_handler(linked.parent)
    request._import_ki_bytes(archive.read_bytes())
    assert response["code"] == 200, response
    imported = request.catalog.user_dir / "Demo"
    assert_aliases(imported)
    ki_guard.require_intact(imported)
    assert (imported / "s1_grid/tool.py").read_bytes() == (linked.root / "s1_grid/tool.py").read_bytes()
    (imported / "tool_alias.py").write_text("changed through alias\n", encoding="utf-8")
    assert ki_verification.current_report(imported) is None


def test_review_context_is_link_free_while_draft_and_runtime_preserve_aliases(linked):
    project = linked.parent / "project"
    active = project / "models/Demo/ki"
    ki_copy.copytree(linked.root, active)
    ki_guard.enroll(active)
    job = ki_investigation.create(project, {"id": "test"}, {"Demo": active}, "deepseek")
    packet = Path(job["context"]["root"])
    context = packet / "kis/Demo"
    assert not (context / "tools/s1_grid").exists()
    assert not (context / "tool_alias.py").exists()
    assert (context / "s1_grid/tool.py").read_bytes() == (active / "s1_grid/tool.py").read_bytes()
    assert not any(ki_review_agents._linked(path) for path in packet.rglob("*"))
    # Exercise the exact boundary used by API and CLI reviewers, rather than
    # substituting a fixture reviewer that never checked the packet itself.
    ki_review_agents._seal(packet, job["context"]["digest"])
    manifest = json.loads((packet / "manifest.json").read_text(encoding="utf-8"))
    rows = {row["path"]: row for row in manifest["files"]}
    for alias, target in (("tools/s1_grid", "s1_grid"), ("tool_alias.py", "s1_grid/tool.py")):
        row = rows[f"kis/Demo/{alias}"]
        assert row["alias_target"] == target
        assert row["representation"] == "alias_identity_in_manifest"
        assert row["canonical_context_path"] == f"kis/Demo/{target}"
        assert row["omitted"] == "alias_inventory_only"
    def reviewer(_role, _context, digest, _stop, _emit):
        return {"status": "completed", "summary": "Fixture review", "context_digest": digest,
                "findings": [], "tests_not_run": ["Native model"], "uncertainties": []}
    ki_investigation.run_reviews(project, job["id"], reviewer)
    draft = ki_investigation.create_draft(project, job["id"], "Demo")
    candidate = Path(draft["draft"]["path"])
    assert_aliases(candidate)
    assert ki_tree.digest(candidate) == ki_tree.digest(active)
    report = ki_verification.verify_candidate(candidate, name="Demo")
    ki_guard.activate(active, candidate, report, quiescent=True)
    assert_aliases(active)


def test_review_alias_identity_does_not_expose_filtered_canonical_credentials(linked):
    (linked.root / "credentials.json").write_text('{"token":"private-value"}', encoding="utf-8")
    (linked.root / "credential_alias.json").symlink_to(Path("credentials.json"))
    (linked.root / "s1_grid/tool.py").write_text('API_KEY="private-value"\n', encoding="utf-8")
    project = linked.parent / "project"
    project.mkdir()
    job = ki_investigation.create(project, {"id":"test"}, {"Demo":linked.root}, "deepseek")
    packet = Path(job["context"]["root"])
    ki_review_agents._seal(packet, job["context"]["digest"])
    assert not (packet / "kis/Demo/credentials.json").exists()
    assert not (packet / "kis/Demo/credential_alias.json").exists()
    assert "private-value" not in (packet / "kis/Demo/s1_grid/tool.py").read_text(encoding="utf-8")
    manifest = json.loads((packet / "manifest.json").read_text(encoding="utf-8"))
    alias = next(row for row in manifest["files"] if row["path"] == "kis/Demo/credential_alias.json")
    assert alias["canonical_context_path"] is None
    assert alias["omitted"] == "alias_inventory_only"


def test_calibration_runtime_copy_preserves_aliases(linked):
    project = linked.parent / "project"
    snapshot = SimpleNamespace(contract_bytes=b"version: 1\n", runner_bytes=b"print('fixture')\n")
    target = calibration._runtime_ki(project, "Demo", linked.root, snapshot=snapshot, run_id="fixture")
    assert_aliases(target)
    assert (target / "s1_grid/tool.py").read_bytes() == (linked.root / "s1_grid/tool.py").read_bytes()


@pytest.mark.parametrize("alias", ["contract", "runner", "tools_directory"])
def test_calibration_override_does_not_write_through_aliases(linked, alias):
    if alias == "contract":
        (linked.root / "calibration.yaml").symlink_to(Path("SKILL.md"))
    elif alias == "runner":
        (linked.root / "tools/calib_run.py").symlink_to(Path("../s1_grid/tool.py"))
    else:
        (linked.root / "tools").rename(linked.root / "canonical_tools")
        (linked.root / "tools").symlink_to(Path("canonical_tools"), target_is_directory=True)
    source_digest = ki_tree.digest(linked.root)
    skill = (linked.root / "SKILL.md").read_bytes()
    tool = (linked.root / "s1_grid/tool.py").read_bytes()
    project = linked.parent / "project"
    snapshot = SimpleNamespace(contract_bytes=b"version: 1\n", runner_bytes=b"print('fixture')\n")
    if alias == "tools_directory":
        with pytest.raises(ValueError, match="canonical tools directory"):
            calibration._runtime_ki(project, "Demo", linked.root, snapshot=snapshot, run_id="fixture")
        assert not (project / "calibration/runtime/Demo/fixture").exists()
    else:
        runtime = calibration._runtime_ki(project, "Demo", linked.root, snapshot=snapshot, run_id="fixture")
        assert (runtime / "SKILL.md").read_bytes() == skill
        assert (runtime / "s1_grid/tool.py").read_bytes() == tool
        assert not (runtime / "calibration.yaml").is_symlink()
        assert not (runtime / "tools/calib_run.py").is_symlink()
        assert (runtime / "calibration.yaml").read_bytes() == snapshot.contract_bytes
        assert (runtime / "tools/calib_run.py").read_bytes() == snapshot.runner_bytes
    assert ki_tree.digest(linked.root) == source_digest
