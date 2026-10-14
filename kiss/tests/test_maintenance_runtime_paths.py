"""Runtime-path repair lifecycle: real projection, files, signatures and guards.

Only the KDT engine/provider are fixtures. No preflight or model is executed.
"""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import threading

import pytest

from kiss_cli import api, flowgate, ki_copy, ki_guard, ki_investigation as inv
from kiss_cli import ki_maintenance as maintenance, ki_maintenance_recipes as recipes
from kiss_cli import ki_path_contracts as contract, ki_review_agents as agents
from kiss_cli import ki_verification as gate, paths, published_kdt, software_verification
from .test_ki_maintenance import metadata
from .test_ki_path_contracts import prepare
from .test_ki_verification_boundaries import isolated_engine, write_package
from .test_ki_review_agents import draft as author_draft, author_report, bundle
from .test_rejected_update_maintenance import rejected, make_reviewed, case
from .test_maintenance_interface_runtime import interface_case, verify as verify_interface


@pytest.fixture
def runtime_case(tmp_path, monkeypatch):
    monkeypatch.delenv("GEOFORGE_KDT_ENGINE", raising=False)
    for name, suffix in (("GEOFORGE_KI_INVESTIGATION_HOME", "investigations"),
                         ("GEOFORGE_FLOW_REGISTRY", "registry"), ("GEOFORGE_KDT_HOME", "studio")):
        monkeypatch.setenv(name, str(tmp_path / suffix))
    with isolated_engine(tmp_path) as engine:
        original, _candidate, cfg, active = prepare(tmp_path)
        candidate = tmp_path / "maintenance-candidate"
        write_package(active, "WOFOST")
        metadata(active, "WOFOST")
        for name in (contract.PREFLIGHT, contract.MANIFEST, contract.RUNNER):
            (active / name).write_bytes((original / name).read_bytes())
        (active.parent / paths.CONFIG_NAME).write_text(cfg.dumps(), encoding="utf-8")
        ki_guard.enroll(active)
        source = maintenance.capture_source(active, "WOFOST")
        ki_copy.copytree(Path(source["base_root"]), candidate, dirs_exist_ok=True)
        projection = recipes.apply_recipe(candidate, source=Path(source["base_root"]),
            recipe=contract.RECIPE, name="WOFOST", runtime_config=cfg, target_root=active)
        yield SimpleNamespace(active=active, candidate=candidate, project=Path(cfg.root), cfg=cfg,
                              source=source, engine=engine, projection=projection)
    inv._STOPS.clear()
    inv._RUNNING.clear()


def verify(case, **overrides):
    kwargs = dict(source=case.source, name="WOFOST", maintenance_recipe=contract.RECIPE,
                  runtime_config=case.cfg, target_root=case.active)
    kwargs.update(overrides)
    return maintenance.verify_candidate(case.candidate, **kwargs)


def reviewed(case):
    project, active = case.project, case.active
    (project / "runs").mkdir(exist_ok=True)
    (project / "runs/plan.json").write_text(json.dumps({"selected_kis": ["WOFOST"], "steps": []}))
    (project / "runs/data-inventory.json").write_text('{"items": []}')
    flow = flowgate.load()
    flow.approval.approve(project)
    state = flow.states.FlowContext(project=project)
    state.state = flow.states.State.FAILED
    state.selected_kis = ["WOFOST"]
    state.save()
    job = inv.create(project, {"id": "paths", "goal": "Review failed preflight runtime paths"},
                     {"WOFOST": active}, "deepseek")
    def reviewer(role, context, digest, stop, emit):
        return {"status": "completed", "summary": "Read the frozen runtime-path mismatch.", "context_digest": digest,
                "findings": [{"category": "setup", "severity": "medium", "claim": "Wrong projected paths",
                              "evidence": ["kis/WOFOST/preflight_check.py"],
                              "recommendation": "Apply only the recognized runtime path repair."}],
                "tests_not_run": ["Native preflight"], "uncertainties": []}
    inv.run_reviews(project, job["id"], reviewer)
    return inv.create_draft(project, job["id"], "WOFOST", repair_mode="maintenance", maintenance_recipe=contract.RECIPE)


def test_exact_runtime_paths_use_current_kdt_and_separate_non_native_evidence(runtime_case):
    c = runtime_case
    before = gate.content_digest(c.active)
    report = verify(c)
    assert report["ok"], report
    assert len(c.engine.seen) == 1
    assert report["maintenance_recipe"] == contract.RECIPE
    assert [row["path"] for row in report["changes"]] == [contract.MANIFEST, contract.PREFLIGHT]
    assert report["preflight_regression"]["status"] == "not_required"
    assert report["interface_regression"]["status"] == "not_required"
    binding = report["path_binding_regression"]
    assert binding["runtime"]["target_ki"] == str(c.active)
    assert all(binding[key] is False for key in ("preflight_passed", "native_execution", "model_execution", "scientific_validation"))
    assert maintenance.require_current(c.candidate, report) == report
    assert gate.content_digest(c.active) == before
    assert not gate.current_report(c.candidate)


@pytest.mark.parametrize("failure", ["missing_config", "missing_target", "other_target", "generic_recipe", "wrong_recipe"])
def test_path_projection_cannot_bypass_explicit_runtime_recipe(runtime_case, failure):
    c = runtime_case
    kwargs = {
        "missing_config": {"runtime_config": None}, "missing_target": {"target_root": None},
        "other_target": {"target_root": c.candidate},
        "generic_recipe": {"maintenance_recipe": None, "runtime_config": None, "target_root": None},
        "wrong_recipe": {"maintenance_recipe": "tool_inventory"},
    }[failure]
    with pytest.raises(ValueError):
        verify(c, **kwargs)
    assert c.engine.seen == []


@pytest.mark.parametrize("failure", ["partial", "scientific", "runner", "evidence", "new_file"])
def test_only_complete_exact_path_projection_can_reuse_evidence(runtime_case, failure):
    c = runtime_case
    if failure == "partial":
        (c.candidate / contract.MANIFEST).write_bytes((c.active / contract.MANIFEST).read_bytes())
    elif failure == "new_file":
        (c.candidate / "fake_paper.txt").write_text("invented")
    else:
        path = c.candidate / {"scientific": "dag.yaml", "runner": contract.RUNNER,
                              "evidence": "docs/papers.json"}[failure]
        path.write_bytes(path.read_bytes() + b"\n# unrelated edit\n")
    with pytest.raises(ValueError):
        verify(c)
    assert c.engine.seen == []


def test_selected_path_recipe_does_not_merge_competing_manifest_inventory_projection(runtime_case, monkeypatch):
    c = runtime_case
    monkeypatch.setattr(recipes, "expected_changes", lambda *_: {contract.MANIFEST: b"wrong inventory projection"})
    assert verify(c)["ok"]
    with pytest.raises(ValueError):
        maintenance.verify_candidate(c.candidate, source=c.source, name="WOFOST")


def test_kdt_failure_is_not_hidden_by_valid_path_binding(runtime_case):
    c = runtime_case
    c.engine.ok = False
    report = verify(c)
    assert not report["ok"] and "fixture KDT failure" in report["failures"]
    with pytest.raises(ValueError):
        maintenance.require_current(c.candidate, report)


@pytest.mark.parametrize("bad_report", [None, {}, {"ok": 1}, {"ok": True}])
def test_incomplete_path_report_cannot_be_signed_as_success(runtime_case, monkeypatch, bad_report):
    monkeypatch.setattr(contract, "validate_behavior", lambda *_, **__: bad_report)
    with pytest.raises(ValueError):
        verify(runtime_case)
    assert runtime_case.engine.seen == []


@pytest.mark.parametrize("failure", ["python", "helper", "helper_marker", "target_runner"])
def test_changed_runtime_blocks_direct_adoption_before_active_mutation(runtime_case, failure):
    c = runtime_case
    report = verify(c)
    before = gate.content_digest(c.active)
    if failure == "python":
        Path(c.cfg.python).write_bytes(b"different runtime")
    elif failure == "helper":
        (c.cfg.roles["ki_tools_common"] / "ki_tools_common/__init__.py").write_text("changed")
    elif failure == "helper_marker":
        (c.cfg.roles["ki_tools_common"] / ".geoforge-common.json").write_text("{}")
    else:
        (c.active / contract.RUNNER).write_bytes((c.active / contract.RUNNER).read_bytes() + b"\n# changed\n")
        before = gate.content_digest(c.active)
    with pytest.raises(ValueError):
        ki_guard.activate_maintenance(c.active, c.candidate, report, source=c.source, quiescent=True)
    assert gate.content_digest(c.active) == before


def test_runtime_change_during_kdt_invalidates_path_result(runtime_case, monkeypatch):
    c = runtime_case
    original = gate._check_candidate
    def check(*args, **kwargs):
        result = original(*args, **kwargs)
        Path(c.cfg.python).write_bytes(b"changed while gate ran")
        return result
    monkeypatch.setattr(gate, "_check_candidate", check)
    with pytest.raises(ValueError):
        verify(c)


@pytest.mark.parametrize("failure", ["missing_report", "missing_recipe", "different_target", "config_hash"])
def test_even_authentic_incomplete_path_receipts_cannot_apply(runtime_case, failure):
    c = runtime_case
    report = deepcopy(verify(c))
    if failure == "missing_report":
        report.pop("path_binding_regression")
    elif failure == "missing_recipe":
        report.pop("maintenance_recipe")
    elif failure == "different_target":
        report["path_binding_regression"]["runtime"]["target_ki"] = str(c.candidate)
    else:
        report["path_binding_regression"]["runtime"]["config_sha256"] = "0" * 64
    report = maintenance._sign(c.candidate, report)
    with pytest.raises(ValueError):
        maintenance.require_current(c.candidate, report)


def test_normalizer_code_change_invalidates_unapplied_receipts(runtime_case, monkeypatch):
    c = runtime_case
    report = verify(c)
    original = published_kdt._module_identity
    monkeypatch.setattr(published_kdt, "_module_identity",
                        lambda module: "new-path-policy" if module is contract else original(module))
    with pytest.raises(ValueError):
        maintenance.require_current(c.candidate, report)
    # Already active guarded bytes remain intact; policy changes are no adoption.
    assert ki_guard.require_intact(c.active)


def test_already_adopted_parameter_routing_baseline_survives_new_maintenance_policy(interface_case, monkeypatch):
    c = interface_case
    report = verify_interface(c)
    ki_guard.activate_maintenance(c.base, c.candidate, report, source=c.source, quiescent=True)
    before = gate.content_digest(c.base)
    monkeypatch.setattr(maintenance, "POLICY", maintenance.POLICY + "-next-path-policy")
    baseline = ki_guard.require_intact(c.base)
    assert baseline["origin"] == "verified_maintenance_candidate"
    fresh = maintenance.capture_source(c.base, "WOFOST")
    assert fresh["base_digest"] == before == gate.content_digest(c.base)
    assert fresh["policy"] == maintenance.POLICY


def test_real_investigation_binds_saved_config_and_requires_post_adoption_preflight(runtime_case):
    c = runtime_case
    before = gate.content_digest(c.active)
    job = reviewed(c)
    assert gate.content_digest(c.active) == before
    result = inv.verify_draft(c.project, job["id"])
    assert result["can_apply"], result.get("verification")
    expected = inv._project_runtime_config(c.project, "WOFOST", c.active)
    assert result["verification"]["runtime_identity"] == software_verification.runtime_identity(expected)
    applied = inv.apply(c.project, job["id"], result["verification"]["id"])
    assert applied["apply"]["requires_preflight"] and applied["apply"]["requires_plan_review"]
    assert inv.pending_preflight(c.project)["pending"]
    assert not applied["verification"]["native_regression"]["verified"]
    assert ki_guard.require_intact(c.active)["origin"] == "verified_maintenance_candidate"


@pytest.mark.parametrize("when", ["draft", "verification", "apply"])
def test_investigation_rejects_saved_runtime_repointing_at_each_boundary(runtime_case, monkeypatch, when):
    c = runtime_case
    job = reviewed(c)
    expected = inv._project_runtime_config(c.project, "WOFOST", c.active)
    different = deepcopy(expected)
    different.roles["python_env"] = c.project / "other-selected-runtime"
    original = maintenance.verify_candidate
    if when == "verification":
        def verify_then_change(*args, **kwargs):
            result = original(*args, **kwargs)
            monkeypatch.setattr(inv, "_project_runtime_config", lambda *_: different)
            return result
        monkeypatch.setattr(maintenance, "verify_candidate", verify_then_change)
    elif when == "draft":
        monkeypatch.setattr(inv, "_project_runtime_config", lambda *_: different)
    before = gate.content_digest(c.active)
    flow = flowgate.load()
    approval = flow.approval.read(c.project)
    if when == "apply":
        result = inv.verify_draft(c.project, job["id"])
        monkeypatch.setattr(inv, "_project_runtime_config", lambda *_: different)
        assert not inv.get(c.project, job["id"])["can_apply"]
        with pytest.raises(ValueError, match="Runtime"):
            inv.apply(c.project, job["id"], result["verification"]["id"])
    else:
        with pytest.raises(ValueError, match="Runtime"):
            inv.verify_draft(c.project, job["id"])
    assert gate.content_digest(c.active) == before
    assert flow.approval.read(c.project) == approval
    assert not inv.pending_preflight(c.project)["pending"]


def test_path_recipe_cannot_borrow_ancestor_configuration(runtime_case):
    c = runtime_case
    config = c.active.parent / paths.CONFIG_NAME
    (c.project / paths.CONFIG_NAME).write_bytes(config.read_bytes())
    config.unlink()
    with pytest.raises(FileNotFoundError, match="kiss.toml"):
        reviewed(c)


def test_path_recipe_cannot_use_rejected_publication_source(rejected):
    _, package, _, project, _ = rejected
    original = gate.content_digest(package)
    job = make_reviewed(rejected)
    with pytest.raises(ValueError, match="prepared project KI"):
        inv.create_draft(project, job["id"], "Demo", repair_mode="maintenance", maintenance_recipe=contract.RECIPE)
    assert gate.content_digest(package) == original


def test_author_has_exact_path_audit_scope_and_no_execution_tools(author_draft, monkeypatch):
    _root, candidate, active, states = author_draft
    prompts = []
    def answer(_provider, _model, system, messages, tools, _key, **kwargs):
        prompts.append(system + str(messages))
        assert not any(tool["name"].startswith("run_") for tool in tools)
        return author_report(), [], {"role": "assistant", "content": author_report()}
    monkeypatch.setattr(api, "_openai_turn", answer)
    result = agents.author_draft("fixture", provider="api:deepseek", repair_mode="maintenance",
        maintenance_recipe=contract.RECIPE, stop_event=threading.Event(), emit=lambda _: None, managed_roots=[active])
    assert result["status"] == "completed", result
    assert "three generated preflight assignments" in prompts[0]
    assert "Preserve every check" in prompts[0]
    assert not result["verified"] and not result["native_execution_verified"]
    assert states[-1] == "built"


def test_rejected_download_author_cannot_start_runtime_path_recipe(author_draft, monkeypatch):
    monkeypatch.setattr(api, "_openai_turn", lambda *_, **__: pytest.fail("must not start provider"))
    result = agents.author_draft("fixture", provider="api:deepseek", repair_mode="maintenance", draft_only=True,
        maintenance_recipe=contract.RECIPE, stop_event=threading.Event(), emit=lambda _: None)
    assert result["status"] == "failed" and "selected project runtime" in result["error"]
