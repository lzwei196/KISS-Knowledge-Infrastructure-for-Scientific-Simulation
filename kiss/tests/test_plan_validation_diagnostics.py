"""Host-only plan diagnostics retain useful failures without changing Flow."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest

from kiss_cli import api, flowgate, obs_subset
from .test_flowgate import _cfg, _ki, _plan, _session


@pytest.fixture
def planning(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    monkeypatch.setenv("GEOFORGE_FLOW_REGISTRY", str(tmp_path / "registry.json"))
    ki = _ki(tmp_path)
    project, session = _session(tmp_path, ki, [
        ("task_received", None), ("kis_resolved", {"selected_kis": [ki.name]})])
    plan, inventory = _plan(ki)
    return ki, project, session, plan, inventory


def entries(project):
    path = project / flowgate.PLAN_VALIDATION_LOG
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def submit(ki, project, session, plan, inventory):
    return api.execute_tool("write_plan", {"plan": plan, "data_inventory": inventory},
                            ki, _cfg(project), project_mode=True, flow=session)


def test_normal_api_rejected_then_fixed_preserves_draft_state_and_history(planning):
    ki, project, session, plan, inventory = planning
    session.flow.plan.write_artifacts(project, plan, inventory)
    drafts = {name: (project / "runs" / name).read_bytes()
              for name in ("plan.json", "data-inventory.json")}
    state_before = (project / "runs/flow-state.json").read_bytes()
    rejected = copy.deepcopy(plan)
    rejected["goal"] = "unlogged provider prose"
    rejected["steps"][0]["tool"] = None
    response = submit(ki, project, session, rejected, inventory)
    assert response.startswith("PLAN NOT WRITTEN")
    assert "has no tool" in response
    assert all((project / "runs" / name).read_bytes() == content for name, content in drafts.items())
    first, = entries(project)
    assert first["result"] == "rejected" and first["stage"] == "schema_validation"
    assert first["errors"] == [
        "step 'M:run' has no tool — not ready to execute",
        "step 'M:run' declares outputs but has no tool to record them; assign a KI tool "
        "or typed project_data_tool; move narrative-only notes outside executable steps",
    ]
    assert first["steps_count"] == first["items_count"] == 1
    assert first["plan_sha256"] == session.flow.plan.sha256(rejected)
    assert "unlogged provider prose" not in json.dumps(first)

    assert submit(ki, project, session, plan, inventory).startswith("Plan files written")
    history = entries(project)
    assert history[0] == first
    assert history[1]["result"] == "written" and history[1]["errors"] == []
    assert history[1]["plan_sha256"] != first["plan_sha256"]
    assert (project / "runs/flow-state.json").read_bytes() == state_before
    assert not (project / "runs/approval.json").exists()
    assert session.state.value == "PLANNING"


@pytest.mark.parametrize("stage", ["calibration_binding", "acquisition_binding"])
def test_rejections_record_the_actual_binding_stage(planning, monkeypatch, stage):
    ki, project, session, plan, inventory = planning
    if stage == "calibration_binding":
        monkeypatch.setattr(session, "prepare_calibration_steps", lambda _plan: ["unavailable calibration adapter"])
    else:
        inventory["items"][0]["acquisition_id"] = "a" * 32
        def reject(*_args):
            raise ValueError("changed acquisition selection")
        monkeypatch.setattr(obs_subset, "stamp_item", reject)
    assert submit(ki, project, session, plan, inventory).startswith("PLAN NOT WRITTEN")
    row, = entries(project)
    assert row["result"] == "rejected" and row["stage"] == stage
    assert not (project / "runs/plan.json").exists()


def test_recognizable_secrets_are_redacted_and_proposals_are_only_fingerprinted(planning, monkeypatch):
    ki, project, session, plan, inventory = planning
    secrets = ["assigned-secret", "quoted secret value", "flag-secret", "bearer-secret",
               "userinfo-secret", "query-secret", "fragment-secret", "encoded-secret"]
    error = ("bad item token=assigned-secret, password='quoted secret value', "
             "--api-key flag-secret Authorization: Bearer bearer-secret "
             "https://user:userinfo-secret@example.org/path?token=query-secret#fragment-secret "
             "https://example.org/path?%74oken=encoded-secret")
    monkeypatch.setattr(session.flow.plan, "validate", lambda *_a, **_k: [error])
    plan["goal"] = "raw prompt must not be stored"
    assert submit(ki, project, session, plan, inventory).startswith("PLAN NOT WRITTEN")
    text = (project / flowgate.PLAN_VALIDATION_LOG).read_text(encoding="utf-8")
    assert all(secret not in text for secret in secrets)
    assert "raw prompt must not be stored" not in text
    row, = entries(project)
    assert row["errors"][0].startswith("bad item token=[redacted]")
    assert row["error_count"] == 1


@pytest.mark.parametrize("synthetic_token", [
    "gfd_synthetic0123456789abcdef",
    "gfd_synthetic-0123456789_abcdef",
])
def test_bare_geoforge_credentials_are_redacted_from_real_validation_errors(planning, synthetic_token):
    ki, project, session, plan, inventory = planning
    plan["steps"][0]["id"] = synthetic_token
    plan["steps"][0]["tool"] = None
    assert submit(ki, project, session, plan, inventory).startswith("PLAN NOT WRITTEN")
    text = (project / flowgate.PLAN_VALIDATION_LOG).read_text(encoding="utf-8")
    assert synthetic_token not in text
    row, = entries(project)
    assert row["errors"][0] == "step '[redacted credential]' has no tool — not ready to execute"


def test_logging_rotates_and_bounds_error_count_and_bytes(planning, monkeypatch):
    _ki_obj, project, _session_obj, plan, inventory = planning
    monkeypatch.setattr(flowgate, "_PLAN_LOG_BYTES", 16384)
    monkeypatch.setattr(flowgate, "_PLAN_RECORD_BYTES", 8192)
    summary = flowgate._plan_proposal_summary(plan, inventory)
    errors = [f"error {n}: " + "界" * 2500 for n in range(100)]
    for _ in range(6):
        flowgate._record_plan_validation(project, summary, result="rejected", stage="schema_validation", errors=errors)
    flowgate._record_plan_validation(project, summary, result="written", stage="complete")
    files = list((project / ".geoforge").glob("plan-validation*.jsonl"))
    assert len(files) == 2
    all_rows = []
    for path in files:
        assert path.stat().st_size <= 16384
        all_rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    assert any(row["result"] == "rejected" and row["errors_truncated"] and row["error_count"] == 100
               for row in all_rows)
    assert entries(project)[-1]["result"] == "written"


def test_io_failure_does_not_change_success_or_rejection(planning, monkeypatch):
    ki, project, session, plan, inventory = planning
    original_open = Path.open
    def failing_open(path, *args, **kwargs):
        if path.name == "plan-validation.jsonl":
            raise PermissionError("diagnostic disk unavailable")
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", failing_open)
    rejected = copy.deepcopy(plan)
    rejected["steps"][0]["tool"] = None
    assert submit(ki, project, session, rejected, inventory).startswith("PLAN NOT WRITTEN")
    assert not (project / "runs/plan.json").exists()
    assert submit(ki, project, session, plan, inventory).startswith("Plan files written")
    assert not (project / "runs/approval.json").exists()


def test_original_artifact_failure_is_logged_and_reraised(planning, monkeypatch):
    _ki_obj, project, session, plan, inventory = planning
    def fail_write(*_args):
        raise OSError("simulated plan write failure")
    monkeypatch.setattr(session.flow.plan, "write_artifacts", fail_write)
    with pytest.raises(OSError, match="simulated plan write failure"):
        session.write_plan(plan, inventory)
    row, = entries(project)
    assert (row["result"], row["stage"]) == ("error", "write_artifacts")


def test_diagnostic_path_is_protected_in_every_flow_state(planning):
    _ki_obj, project, session, _plan_doc, _inventory = planning
    for state in session.flow.states.State:
        for suffix in ("plan-validation.jsonl", "plan-validation.previous.jsonl"):
            assert not session.flow.policy.write_allowed(project / ".geoforge" / suffix,
                                                         project, list(session.ki_roots.values()), state)


@pytest.mark.parametrize("escape", ["directory_symlink", "file_symlink", "file_hardlink"])
def test_diagnostics_never_follow_links(planning, tmp_path, escape):
    _ki_obj, project, _session_obj, plan, inventory = planning
    if escape == "directory_symlink":
        project = tmp_path / "fresh-project"
        project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("untouched", encoding="utf-8")
    path = project / flowgate.PLAN_VALIDATION_LOG
    try:
        if escape == "directory_symlink":
            path.parent.symlink_to(outside, target_is_directory=True)
        else:
            path.parent.mkdir(exist_ok=True)
            if escape == "file_symlink":
                path.symlink_to(sentinel)
            else:
                os.link(sentinel, path)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"filesystem link unavailable: {error}")
    flowgate._record_plan_validation(project, flowgate._plan_proposal_summary(plan, inventory),
                                     result="written", stage="complete")
    assert sentinel.read_text(encoding="utf-8") == "untouched"
    assert not (outside / "plan-validation.jsonl").exists()
