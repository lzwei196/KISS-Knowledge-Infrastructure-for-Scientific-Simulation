"""GUI workspace integration: portable repair selection is not runtime readiness.

KDT acceptance is an explicitly synthetic signed fixture. Helper preparation,
GUI projection, immutable adoption and harmless project preflight are real;
no scientific model, dependency installer or provider is launched.
"""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from kiss_cli import catalog, flowgate, gui, kdtstudio, ki_adaptations as adapt, ki_copy, ki_guard
from kiss_cli import ki_updates, paths, port, project_verification, setup
from kiss_cli.manifest import Manifest
from .test_ki_adaptations import accepted


@pytest.fixture
def gui_case(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_KI_ADAPTATION_HOME", str(tmp_path / "adaptations"))
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    monkeypatch.delenv("GEOFORGE_KDT_ENGINE", raising=False)
    monkeypatch.setattr(kdtstudio, "engine_source_digest", lambda: "e" * 64)
    library = tmp_path / "snapshot-a"
    source = library / "models/Demo"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# Harmless GUI adaptation fixture\n")
    (source / "kiss.yaml").write_text("kiss_manifest_version: 1\nmodel: Demo\n")
    (source / "reader.py").write_text("output = 'KISSPATH_OUTPUTS/result.txt'\ndef read(): return 1\n")
    (source / "preflight_check.py").write_text(
        "import json\nprint('PREFLIGHT_REPORT=' + json.dumps({'checks': "
        "[{'name': 'harmless-fixture', 'critical': True, 'status': 'pass'}]}))\n")
    helpers = library / "ki_tools_common"
    (helpers / "ki_tools_common").mkdir(parents=True)
    (helpers / "ki_tools_common/__init__.py").write_text("VALUE = 1\n")
    (helpers / "pyproject.toml").write_text('[project]\nname="ki_tools_common"\nversion="0.0.1"\n')
    (library / ki_updates.SNAPSHOT_MANIFEST).write_text(json.dumps({
        "source_commit": "a" * 40, "content_sha256": "a" * 64,
        "trees": {"shared_tools": "b" * 40}}))
    shared = paths.KissConfig.default(tmp_path / "shared-install")
    shared.root.mkdir()
    shared.python, shared.relocation = sys.executable, "none"
    setup.prepare_common(shared, library)
    (shared.root / paths.CONFIG_NAME).write_text(shared.dumps(), encoding="utf-8")
    ki_guard.enroll(source)
    handler = object.__new__(gui.Handler)
    handler.repo_root = handler.library_root = library
    handler.workroot = tmp_path / "workroot"
    handler._config = lambda _ki: paths.KissConfig.load(shared.root)
    handler._manifest = lambda ki: Manifest.load(ki.manifest)
    ki = catalog.KI("Demo", source)
    project = tmp_path / "project-a"
    working, cfg = handler._session_workspace(project, ki)
    case = SimpleNamespace(base=tmp_path, library=library, source=ki, handler=handler,
                           shared=shared, project=project, working=working, cfg=cfg)
    origin = adapt.projection(working.root, cfg)
    portable = tmp_path / "portable-repair"
    ki_copy.copytree(Path(origin["portable_root"]), portable)
    reader = portable / "reader.py"
    reader.write_text(reader.read_text().replace("return 1", "return 2"))
    runtime = tmp_path / "runtime-repair"
    port.materialise(portable, runtime, cfg)
    ticket = adapt.prepare_registration(working.root, cfg, portable, accepted(portable),
                                        runtime, accepted(runtime))
    ki_guard.activate(working.root, runtime, ticket["runtime_report"], quiescent=True)
    case.adopted = adapt.register(ticket, working.root, cfg)
    return case


def refreshed(case, *, relevant=False):
    library = case.base / "snapshot-b"
    ki_copy.copytree(case.library, library)
    (library / ki_updates.SNAPSHOT_MANIFEST).write_text(json.dumps({
        "source_commit": "c" * 40, "content_sha256": "d" * 64,
        "trees": {"shared_tools": "e" * 40}}))
    source = library / "models/Demo"
    if relevant:
        (source / "new-upstream.txt").write_text("Changed source requires reconciliation\n")
    ki_guard.enroll(source)
    case.handler.library_root = library
    return catalog.KI("Demo", source)


def test_gui_new_project_uses_reviewed_portable_repair_then_real_preflight(gui_case):
    c = gui_case
    project = c.base / "project-b"
    working, cfg = c.handler._session_workspace(project, c.source)
    text = (working.root / "reader.py").read_text()
    assert "return 2" in text
    assert cfg.roles["outputs"].as_posix() in text
    assert c.cfg.roles["outputs"].as_posix() not in text
    assert adapt.projection(working.root, cfg)["adaptation_id"] == c.adopted["adaptation_id"]
    assert not project_verification.status(project, working)["can_run"]
    receipt = project_verification.verify(project, working, c.handler._manifest(working))
    assert receipt["can_run"]
    assert project_verification.status(project, working)["can_run"]


def test_gui_unrelated_refresh_reuses_helper_source_and_portable_repair(gui_case):
    from kiss_cli import helper_identity
    c = gui_case
    source = refreshed(c)
    working, cfg = c.handler._session_workspace(c.base / "project-b", source)
    assert cfg.roles["ki_tools_common"] != c.cfg.roles["ki_tools_common"]
    assert cfg.roles["ki_tools_common"].is_relative_to(c.base / "project-b")
    assert helper_identity.prepared_source_identity(cfg.roles["ki_tools_common"]) == \
        helper_identity.prepared_source_identity(c.cfg.roles["ki_tools_common"])
    assert "return 2" in (working.root / "reader.py").read_text()
    assert adapt.projection(working.root, cfg)["adaptation_id"] == c.adopted["adaptation_id"]
    assert not project_verification.status(c.base / "project-b", working)["can_run"]


def test_gui_relevant_refresh_requires_reconciliation_and_preserves_old_project(gui_case):
    c = gui_case
    before = ki_guard.require_intact(c.working.root)
    config_before = (c.working.root.parent / paths.CONFIG_NAME).read_bytes()
    source = refreshed(c, relevant=True)
    working, cfg = c.handler._session_workspace(c.base / "project-b", source)
    lineage = adapt.projection(working.root, cfg)
    assert "return 1" in (working.root / "reader.py").read_text()
    assert lineage["adaptation_id"] is None and lineage["reconciliation_needed"]
    retained, _ = c.handler._session_workspace(c.project, source)
    assert retained.root == c.working.root
    assert ki_guard.require_intact(retained.root) == before
    assert (retained.root.parent / paths.CONFIG_NAME).read_bytes() == config_before
    assert "return 2" in (retained.root / "reader.py").read_text()


def test_gui_tampered_retained_repair_cannot_become_a_fresh_project(gui_case):
    c = gui_case
    baseline = ki_guard.require_intact(c.working.root)
    retained = Path(c.adopted["portable_root"])
    (retained / "reader.py").write_text("return_value = 'tampered'\n")
    project = c.base / "project-b"
    with pytest.raises(adapt.AdaptationError, match="Retained|retained"):
        c.handler._session_workspace(project, c.source)
    assert not (project / "models/Demo/ki/SKILL.md").exists()
    assert ki_guard.require_intact(c.working.root) == baseline


def test_gui_config_survives_full_investigation_and_fresh_project_reuse(gui_case, monkeypatch):
    """Exercise the controller bridge, not only the adaptation module directly."""
    from kiss_cli import ki_investigation as inv
    from .test_ki_investigation import accepted as accept_gate_fixture
    c = gui_case
    for key, folder in (("GEOFORGE_KI_INVESTIGATION_HOME", "investigations"),
                        ("GEOFORGE_KDT_HOME", "studio"),
                        ("GEOFORGE_FLOW_REGISTRY", "flow-registry")):
        monkeypatch.setenv(key, str(c.base / folder))
    accept_gate_fixture(monkeypatch)
    config = c.working.root.parent / paths.CONFIG_NAME
    original = config.read_bytes()
    assert c.cfg.root == c.project and config.parent == c.project / "models/Demo"
    runs = c.project / "runs"
    runs.mkdir(exist_ok=True)
    (runs / "plan.json").write_text(json.dumps({"selected_kis": ["Demo"],
        "steps": [{"id": "read", "ki": "Demo", "tool": str(c.working.root / "reader.py") }]}))
    (runs / "data-inventory.json").write_text('{"items": []}')
    flow = flowgate.load()
    flow.approval.approve(c.project)
    context = flow.states.FlowContext(project=c.project)
    context.state, context.selected_kis = flow.states.State.FAILED, ["Demo"]
    context.save()

    job = inv.create(c.project, {"id": "gui-fixture"}, {"Demo": c.working.root},
                     "deepseek", issue="Exercise a reviewed reader repair")
    def reviewer(role, context, digest, stop, emit):
        return {"status": "completed", "summary": "Read the captured fixture reader.",
                "context_digest": digest, "findings": [{"category": "reader", "severity": "medium",
                "claim": "Update the fixture return value", "evidence": ["portable_kis/Demo/reader.py"],
                "recommendation": "Verify the portable and projected candidates."}],
                "tests_not_run": ["Scientific model execution"], "uncertainties": []}
    inv.run_reviews(c.project, job["id"], reviewer)
    job = inv.create_draft(c.project, job["id"], "Demo")
    assert job["draft"]["authoring_scope"] == "portable"
    candidate = Path(job["draft"]["path"]) / "reader.py"
    candidate.write_text(candidate.read_text().replace("return 2", "return 3"))
    verified = inv.verify_draft(c.project, job["id"])
    assert verified["can_apply"] and inv.get(c.project, job["id"])["can_apply"]
    applied = inv.apply(c.project, job["id"], verified["verification"]["id"])
    assert applied["status"] == "applied" and applied["apply"]["reusable"]
    assert not applied["apply"]["native_verified"] and inv.pending_preflight(c.project)["pending"]
    assert flow.approval.check(c.project) != "OK"
    assert "return 3" in (c.working.root / "reader.py").read_text()
    assert config.read_bytes() == original

    project = c.base / "project-after-investigation"
    working, cfg = c.handler._session_workspace(project, c.source)
    text = (working.root / "reader.py").read_text()
    assert "return 3" in text and cfg.roles["outputs"].as_posix() in text
    assert c.cfg.roles["outputs"].as_posix() not in text
    assert not project_verification.status(project, working)["can_run"]
