"""Original JSON report downloads and host-derived technical provenance only."""
import hashlib
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import flowgate, gui, projectview


@pytest.fixture
def report(tmp_path):
    project = tmp_path / "project"
    path = project / "outputs" / "fresh-run" / "report.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(b'{"observed":2929,"simulated":2293,"note":"original bytes"}\r\n')
    return project, path


def spec(path="outputs/fresh-run/report.json", kind="file", **extra):
    return {"version": 1, "panels": [{"id": "report", "kind": kind, "title": "Run report", "path": path, **extra}]}


def publish(report, **extra):
    project, _ = report
    return projectview.publish(project, spec(**extra))["panels"][0]


def test_publish_and_gui_resolver_link_original_bytes_without_copying(report, monkeypatch):
    project, path = report
    original = path.read_bytes()
    panel = publish(report, evidence="verified", file_provenance={"sha256": "forged"})
    assert panel["kind"] == "file" and panel["mime"] == "application/json"
    assert panel["file_provenance"] == {"path": "outputs/fresh-run/report.json",
        "sha256": hashlib.sha256(original).hexdigest(), "bytes": len(original),
        "source": "project-output", "scope": "technical-file-association"}
    assert panel["evidence"] == "unvalidated"
    monkeypatch.setattr(gui.sessions, "load", lambda *a: {"id": "b8b03523f587"})
    monkeypatch.setattr(gui.sessions, "project_path", lambda *a: project)
    actual, mime = gui._resolve_project_view_asset(project.parent, "b8b03523f587", panel["path"])
    assert actual == path and actual.read_bytes() == original and mime == "application/json"
    assert list((project / "artifacts").iterdir()) == [project / "artifacts/project-view.json"]
    assert path.read_bytes() == original


def test_existing_http_route_serves_original_json_with_security_headers(report, monkeypatch):
    project, path = report
    monkeypatch.setattr(gui.sessions, "load", lambda *a: {"id": "b8b03523f587"})
    monkeypatch.setattr(gui.sessions, "project_path", lambda *a: project)
    h = object.__new__(gui.Handler)
    h.workroot = project.parent
    h.server = SimpleNamespace(server_port=12345)
    h.csrf_token = "isolated-fixture"
    h.path = "/api/session/b8b03523f587/view-asset?path=outputs%2Ffresh-run%2Freport.json"
    h.wfile = io.BytesIO()
    codes, headers = [], {}
    h.send_response = codes.append
    h.send_header = lambda key, value: headers.update({key: value})
    h.end_headers = lambda: None
    h.do_GET()
    assert codes == [200] and h.wfile.getvalue() == path.read_bytes()
    assert headers["Content-Type"] == "application/json"
    assert headers["Cache-Control"] == "no-store"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert "sandbox" in headers["Content-Security-Policy"]


@pytest.mark.parametrize("path", ["../report.json", "/outputs/report.json", "C:/report.json", 
    "outputs/../report.json", "outputs/.private/report.json", "outputs//report.json", "outputs/x/./report.json",
    "outputs/report.json:stream", "outputs\\report.json", "outputs/trailing /report.json",
    ".geoforge/receipt.json", "runs/plan.json", "session.json", "models/M/kiss.toml",
    "outputs/fresh-run/report.csv", "outputs/fresh-run/report.html", "outputs/fresh-run/report.py",
    "artifacts/report.json", "outputs/fresh-run/missing.json"])
def test_report_path_is_literal_public_outputs_json_only(report, path):
    with pytest.raises((ValueError, OSError)):
        publish(report, path=path)
    with pytest.raises((ValueError, OSError)):
        projectview.resolve_asset(report[0], path)


@pytest.mark.parametrize("kind", ["image", "animation", "map", "table", "model3d"])
def test_output_reports_cannot_expand_media_roots(report, kind):
    with pytest.raises(ValueError):
        publish(report, kind=kind)


@pytest.mark.parametrize("alias", ["file", "output_root", "nested", "hardlink"])
def test_report_aliases_cannot_disclose_other_files(report, tmp_path, alias):
    project, path = report
    outside = tmp_path / "outside"; outside.mkdir()
    external = outside / "report.json"; external.write_bytes(b'{"private":true}')
    rel = "outputs/linked/report.json"
    try:
        if alias == "hardlink":
            link = project / "outputs/hardlink.json"; os.link(external, link); rel = "outputs/hardlink.json"
        elif alias == "file":
            link = project / "outputs/file.json"; link.symlink_to(external); rel = "outputs/file.json"
        elif alias == "nested":
            (project / "outputs/linked").symlink_to(outside, target_is_directory=True)
        else:
            path.unlink(); path.parent.rmdir(); (project / "outputs").rmdir()
            (project / "outputs").symlink_to(outside, target_is_directory=True); rel = "outputs/report.json"
    except OSError as error:
        pytest.skip(f"Host cannot create this alias fixture: {error}")
    with pytest.raises(ValueError):
        publish(report, path=rel)
    with pytest.raises(ValueError):
        projectview.resolve_asset(project, rel)
    assert external.read_bytes() == b'{"private":true}'


def test_size_checked_on_publish_and_each_download(report, monkeypatch):
    panel = publish(report)
    monkeypatch.setattr(projectview, "MAX_ASSET_BYTES", 4)
    with pytest.raises(ValueError, match="larger"):
        projectview.resolve_asset(report[0], panel["path"])
    with pytest.raises(ValueError, match="larger"):
        publish(report)


def test_aliased_project_root_cannot_expand_json_read_or_publish_scope(report, tmp_path):
    project, path = report
    alias = tmp_path / "aliased-project"
    try:
        alias.symlink_to(project, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Host cannot create directory alias: {error}")
    with pytest.raises(ValueError):
        projectview.publish(alias, spec())
    with pytest.raises(ValueError):
        projectview.resolve_asset(alias, "outputs/fresh-run/report.json")
    assert not (project / "artifacts").exists()


def test_changed_and_removed_report_rechecked_on_view_load(report):
    project, path = report
    first = publish(report)
    path.write_bytes(b'{"changed":true}')
    next_panel = projectview.load(project)["panels"][0]
    assert next_panel["file_provenance"]["sha256"] != first["file_provenance"]["sha256"]
    assert next_panel["revision"] != first["revision"]
    path.unlink()
    loaded = projectview.load(project)
    assert not loaded["panels"] and loaded["error"]


@pytest.fixture
def signed_report(report, tmp_path, monkeypatch):
    """Synthetic host receipt boundary; no native or scientific success claimed."""
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    project, path = report
    ki = tmp_path / "ki"; (ki / "tools").mkdir(parents=True)
    tool = ki / "tools/read.py"; tool.write_text("print('harmless reader')", encoding="utf-8")
    fs = flowgate.FlowSession.open(project, {"Demo": ki})
    fs.move("task_received"); fs.move("kis_resolved", {"selected_kis": ["Demo"]})
    step = {"id": "Demo:report", "ki": "Demo", "kind": "check", "tool": str(tool),
            "inputs": [], "outputs": ["report"], "status": "planned"}
    plan = {"schema_version": "1.0", "goal": "Read a real report", "created_at": "fixture",
            "selected_kis": ["Demo"], "scientific_choices": [], "unresolved_questions": [], "steps": [step]}
    inventory = {"schema_version": "1.0", "items": [{"id": "report", "required_by": ["Demo"],
        "status": "resolved", "acceptable_sources": [], "local_paths": ["outputs/fresh-run/report.json"],
        "output_validation": "json_report_v1", "agent_resolvable": True, "needs_user": False}]}
    assert fs.write_plan(plan, inventory) == []
    flow = fs.flow
    flow.approval.approve(project, by="user")
    def record(finished=2, passed=True, outputs=None):
        from ki_tools_common.flow import declared_outputs
        return flow.receipts.record_run(project, ki="Demo", executable=str(tool), command=[str(tool)],
            cwd=str(project), started_at=finished-1, finished_at=finished, exit_code=0 if passed else 1,
            execution_status="succeeded" if passed else "failed", process_started=True,
            inputs=[], outputs=outputs if outputs is not None else [path],
            approval_sha256=flow.approval.approval_id(flow.approval.read(project)), plan_step_id=step["id"],
            validation={"status": "passed" if passed else "failed", "checks": []},
            declared_outputs=declared_outputs.binding(project, step, inventory))
    receipt = record()
    return report, flow, record, receipt


def test_current_receipt_associates_actual_report_but_never_scientific_verified(signed_report):
    report, flow, record, receipt = signed_report
    panel = publish(report)
    assert panel["evidence"] == "receipt_bound"
    assert panel["file_provenance"]["receipt"]["path"] == receipt.relative_to(report[0]).as_posix()
    assert panel["file_provenance"]["scope"] == "technical-file-association"
    assert "verified" not in panel["evidence"]


@pytest.mark.parametrize("change", ["bytes", "approval", "plan", "receipt", "state", "later_failure", "later_missing"])
def test_stale_forged_or_superseded_proof_cannot_label_report_current(signed_report, change):
    report, flow, record, receipt = signed_report
    project, path = report
    assert publish(report)["evidence"] == "receipt_bound"
    if change == "bytes": path.write_bytes(b'{"changed":true}')
    elif change == "approval": flow.approval.approve(project, by="user")
    elif change == "plan":
        p = project / "runs/plan.json"; d = json.loads(p.read_text()); d["goal"] = "Changed plan"; p.write_text(json.dumps(d))
    elif change == "receipt":
        d = json.loads(receipt.read_text()); d["exit_code"] = 99; receipt.write_text(json.dumps(d))
    elif change == "state":
        p = project / "runs/flow-state.json"; d = json.loads(p.read_text()); d["state"] = "COMPLETED"; p.write_text(json.dumps(d))
    elif change == "later_failure": record(finished=5, passed=False)
    else: record(finished=5, outputs=[])
    panel = projectview.load(project)["panels"][0]
    assert panel["evidence"] == "unvalidated" and "receipt" not in panel["file_provenance"]
    assert path.exists()
