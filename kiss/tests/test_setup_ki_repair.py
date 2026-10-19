"""Real setup ownership/signatures/adoption; KDT and reviewers are fixtures.

No scientific engine, network or provider is executed by these unit tests.
The separate EPANET recipe suite tests its real bounded gate.
"""
from pathlib import Path
import json
import shutil
import sys

import pytest

from kiss_cli import (helper_identity, install, ki_adaptations, ki_guard,
    ki_investigation as inv, ki_maintenance, ki_maintenance_gate as gate,
    ki_verification, paths, setup, setup_ki_repair as repair, software_verification)
from kiss_cli.manifest import Manifest


@pytest.fixture
def case(tmp_path, monkeypatch):
    for name, folder in (("GEOFORGE_KI_INVESTIGATION_HOME", "investigations"),
                         ("GEOFORGE_KI_ADAPTATION_HOME", "adaptations"),
                         ("GEOFORGE_KI_GUARD_HOME", "guard"),
                         ("GEOFORGE_KI_VERIFICATION_HOME", "verification"),
                         ("GEOFORGE_FLOW_KEYS", "keys"),
                         ("GEOFORGE_FLOW_REGISTRY", "registry"),
                         ("GEOFORGE_KDT_HOME", "studio")):
        monkeypatch.setenv(name, str(tmp_path / folder))
    library = tmp_path / "library"
    source = library / "models" / "EPANET"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# EPANET fixture\n")
    (source / "preflight_check.py").write_text("print('original fixture')\n")
    helpers = library / "ki_tools_common"
    helpers.mkdir()
    (helpers / "helper.py").write_text("VALUE = 1\n")
    root = tmp_path / "setup"
    root.mkdir()
    cfg = paths.KissConfig.default(root)
    cfg.python, cfg.relocation = sys.executable, "none"
    setup.prepare_common(cfg, library)
    (root / "kiss.toml").write_text(cfg.dumps(), encoding="utf-8")
    manifest = Manifest(model="EPANET")
    ki_adaptations.materialise(source, root / "ki", cfg, model="EPANET", library_root=library, manifest=manifest)
    (root / "outputs").mkdir()
    (root / "outputs" / "retained.csv").write_text("value\n42\n")
    (root / "status.json").write_text('{"ok":true,"old":true}')
    (root / "setup-agent.log").write_text("Original diagnostic\n")
    (root / "binaries").mkdir()
    (root / "binaries" / "large.exe").write_bytes(b"MZ\0binary-not-review-context")
    return root, source, library, cfg, manifest


def args(case):
    root, source, library, cfg, manifest = case
    return dict(ki_name="EPANET", source_root=source, library_root=library,
                manifest=manifest, issue="Fix the exact failed path check")


def read_args(case):
    return {key: value for key, value in args(case).items() if key in {"source_root", "library_root", "manifest"}}


def reviewer(role, context, digest, stop, emit):
    return {"status": "completed", "summary": "Checked the pinned setup contract.",
            "context_digest": digest, "findings": [{"category": "runtime", "severity": "medium",
            "claim": "Check the exact portability repair", "evidence": ["kis/EPANET/preflight_check.py"],
            "recommendation": "Preserve the model and validation requirements."}],
            "tests_not_run": ["Native model"], "uncertainties": []}


def fixture_gate(monkeypatch, tmp_path, *, model_name="EPANET",
                 recipe_name="epanet_runtime_paths", dispatcher=None):
    """Only the reviewed-recipe/KDT dependency is simulated, never adoption."""
    def capture(source, name):
        retained = tmp_path / ("retained-" + str(len(list(tmp_path.glob("retained-*")))))
        shutil.copytree(source, retained)
        return ki_maintenance._sign(retained, {"original_root": str(source),
            "base_root": str(retained), "base_digest": ki_verification.content_digest(source), "name": name})
    monkeypatch.setattr(ki_maintenance, "capture_source", capture)

    def apply(candidate, *, source, recipe, name, **kwargs):
        assert recipe == recipe_name and name == model_name
        assert kwargs["target_root"] == Path(kwargs["runtime_config"].root) / "ki"
        (Path(candidate) / "preflight_check.py").write_text("print('bounded fixture repair')\n")
        return {"recipe": recipe, "changed_files": ["preflight_check.py"]}

    class FixtureGate:
        @staticmethod
        def verify_candidate(candidate, *, source, name, **kwargs):
            return ki_maintenance._sign(candidate, {"ok": True, "gate_policy": "fixture-only",
                "maintenance_recipe": recipe_name, "source": source,
                "base_digest": source["base_digest"], "candidate_digest": ki_verification.content_digest(candidate),
                "changes": [{"path": "preflight_check.py"}]})

    def require(candidate, report, *, source=None):
        if (not ki_maintenance._authentic(candidate, report) or report.get("ok") is not True
                or report.get("candidate_digest") != ki_verification.content_digest(candidate)
                or (source is not None and report.get("source") != source)):
            raise ValueError("Fixture gate rejected stale candidate")
        return report
    if dispatcher is None:
        from kiss_cli import ki_maintenance_registry
        dispatcher = ki_maintenance_registry
    monkeypatch.setattr(dispatcher, "apply_recipe", apply)
    monkeypatch.setattr(dispatcher, "recipe_verifier", lambda recipe: FixtureGate)
    monkeypatch.setattr(dispatcher, "require_current", require)


def completed(case, monkeypatch, tmp_path):
    fixture_gate(monkeypatch, tmp_path)
    return repair.run(case[0], **args(case), provider="api:deepseek", recipe="epanet_runtime_paths", reviewer=reviewer)


def test_setup_lifecycle_retains_outputs_and_original_projection(case, monkeypatch, tmp_path):
    root, source, library, cfg, manifest = case
    projection = ki_adaptations._read(ki_adaptations._location(root / "ki"))
    result = completed(case, monkeypatch, tmp_path)
    assert result["status"] == "applied" and len(result["reviewers"]) == 3
    assert result["draft"]["setup_local"] is True and result["draft"]["project_local"] is False
    assert result["apply"]["pending_preflight"] is True
    assert result["native_verified"] is False
    assert (root / "outputs/retained.csv").read_text() == "value\n42\n"
    assert not (root / "status.json").exists()
    assert not (root / "runs/flow-state.json").exists()
    assert ki_adaptations._read(ki_adaptations._location(root / "ki")) == projection
    assert repair.require_adoption(root, **read_args(case), cfg=cfg)["adopted_digest"] != projection["projected_digest"]
    # New setup adapter composes authority without rewriting the old proof.
    assert ki_adaptations.setup_repair(root / "ki", cfg, source=source, model="EPANET",
                                     library_root=library, manifest=manifest)
    assert setup.materialise_active(source, root / "ki", cfg, manifest=manifest, library_root=library).dest == root / "ki"


def test_review_packet_is_bounded_and_log_churn_does_not_stale(case):
    root = case[0]
    binding = repair.capture(root, **args(case))
    job = inv.create(root, {}, {"EPANET": root / "ki"}, "api:deepseek", setup_binding=binding)
    context = Path(job["context"]["root"])
    assert not list(context.rglob("large.exe"))
    assert not list(context.rglob("retained.csv"))
    (root / "setup-agent.log").write_text("New provider activity\n")
    (root / "status.json").write_text('{"ok": false}')
    inv._assert_current(inv._load(root, job["id"]))
    assert inv.run_reviews(root, job["id"], reviewer)["status"] == "reviewed"


@pytest.mark.parametrize("change", ["config", "helper", "source", "active", "projection", "policy"])
def test_changed_binding_refuses_review(case, change, monkeypatch):
    root, source, library, cfg, manifest = case
    binding = repair.capture(root, **args(case))
    if change == "config":
        (root / "kiss.toml").write_text(cfg.dumps() + "\n# changed\n")
    elif change == "helper":
        (Path(cfg.roles["ki_tools_common"]) / "helper.py").write_text("VALUE = 2\n")
    elif change == "source":
        (source / "SKILL.md").write_text("Changed source\n")
    elif change == "active":
        (root / "ki/SKILL.md").write_text("Unapproved edit\n")
    elif change == "projection":
        ki_adaptations._location(root / "ki").write_text("{}")
    else:
        monkeypatch.setattr(repair, "_identity", lambda: "new-policy")
    with pytest.raises((ValueError, RuntimeError)):
        repair.require_binding(binding)


@pytest.mark.parametrize("change", ["candidate", "active", "source", "helper", "config", "journal", "pointer"])
def test_reopen_rejects_drift_after_adoption(case, monkeypatch, tmp_path, change):
    result = completed(case, monkeypatch, tmp_path)
    root, source, library, cfg, manifest = case
    if change == "candidate":
        (Path(result["draft"]["path"]) / "SKILL.md").write_text("changed candidate")
    elif change == "active":
        (root / "ki/SKILL.md").write_text("changed active")
    elif change == "source":
        (source / "SKILL.md").write_text("changed source")
    elif change == "helper":
        (Path(cfg.roles["ki_tools_common"]) / "helper.py").write_text("VALUE = 99\n")
    elif change == "config":
        (root / "kiss.toml").write_text(cfg.dumps() + "\n# change")
    elif change == "journal":
        inv._root(root, result["id"]).joinpath("job.json").write_text("{}")
    else:
        repair._pointer(root).write_text("{}")
    with pytest.raises((ValueError, RuntimeError)):
        repair.require_adoption(root, **read_args(case))


def test_project_apply_cannot_adopt_setup_target(case, monkeypatch, tmp_path):
    fixture_gate(monkeypatch, tmp_path)
    root = case[0]
    binding = repair.capture(root, **args(case))
    job = inv.create(root, {}, {"EPANET": root / "ki"}, "api:deepseek", setup_binding=binding)
    inv.run_reviews(root, job["id"], reviewer)
    inv.create_draft(root, job["id"], "EPANET", repair_mode="maintenance", maintenance_recipe="epanet_runtime_paths")
    job = inv.verify_draft(root, job["id"])
    with pytest.raises(ValueError, match="project-local"):
        inv.apply(root, job["id"], job["verification"]["id"])
    with ki_guard.worker(root / "ki"), pytest.raises(ki_guard.KIIntegrityError, match="worker"):
        repair.apply(root, job["id"], job["verification"]["id"])
    assert not repair._pointer(root).exists()


def test_review_failure_and_cancel_do_not_adopt(case, monkeypatch, tmp_path):
    fixture_gate(monkeypatch, tmp_path)
    result = repair.run(case[0], **args(case), provider="api:deepseek", recipe="epanet_runtime_paths",
                        reviewer=lambda *args: {"status": "failed", "error": "fixture incomplete"})
    assert result["status"] == "review_failed"
    assert not repair._pointer(case[0]).exists()
    with pytest.raises(ValueError, match="cancelled"):
        repair.run(case[0], **args(case), provider="api:deepseek", recipe="epanet_runtime_paths", reviewer=reviewer, stop=lambda: True)


def test_preflight_true_requires_exact_retained_execution(case, monkeypatch, tmp_path):
    result = completed(case, monkeypatch, tmp_path)
    root, _, _, cfg, _ = case
    with pytest.raises(OSError):
        repair.finish_preflight(root, passed=True, **read_args(case))
    assert repair.finish_preflight(root, passed=False, **read_args(case))["pending_preflight"]
    record = repair.require_adoption(root, **read_args(case))
    execution_path = root / ".geoforge/preflight/fixture/execution.json"
    execution_path.parent.mkdir(parents=True)
    evidence = {"policy": install.PREFLIGHT_POLICY, "ok": True, "state": "completed", "returncode": 0,
                "source_intact": True, "launch_attempted": True, "source_root": str(root / "ki"),
                "workspace_root": str(root), "source_digest": record["adopted_digest"],
                "execution_digest": record["adopted_digest"], "runtime_identity": record["binding"]["runtime_identity"],
                "record_path": str(execution_path)}
    execution_path.write_text(json.dumps(evidence))
    status = {"ok": True, "model": "EPANET", "ki_content_digest": record["adopted_digest"],
              "runtime_identity": record["binding"]["runtime_identity"], "checked_at": record["applied_at"] + 1,
              "steps": [{"name": "preflight", "ok": True, "evidence": evidence}]}
    (root / "status.json").write_text(json.dumps(status))
    finished = repair.finish_preflight(root, passed=True, **read_args(case), cfg=cfg)
    assert finished["pending_preflight"] is False and finished["preflight_passed"] is True
    assert repair.require_adoption(root, **read_args(case))["pending_preflight"] is False
    status["ki_content_digest"] = "wrong-old-ki"
    (root / "status.json").write_text(json.dumps(status))
    with pytest.raises(ValueError, match="exact setup preflight"):
        repair.finish_preflight(root, passed=True, **read_args(case))


def test_host_selection_drift_blocks_before_adoption(case, monkeypatch, tmp_path):
    fixture_gate(monkeypatch, tmp_path)
    calls = []
    def changed():
        calls.append(True)
        if len(calls) >= 4:
            raise ValueError("selected setup moved")
    with pytest.raises(ValueError, match="selected setup moved"):
        repair.run(case[0], **args(case), provider="api:deepseek", recipe="epanet_runtime_paths",
                   reviewer=reviewer, check_binding=changed)
    assert not repair._pointer(case[0]).exists()


def test_capability_is_explicit_and_absence_is_not_adoption(case):
    assert repair.recipe_for("EPANET") == "epanet_runtime_paths"
    assert repair.recipe_for("unknown") is None
    assert repair.require_adoption(case[0], **read_args(case)) is None
