"""The desktop tool proxy under the flow (plan v3 B4/B5): schemas filtered by state, every
call re-checked, protected writes refused, receipts from run_ki_tool, stage never moved by
an agent report. Runs against a fake KI and the real bundled ki_tools_common.flow."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "kiss"))

from kiss_cli import api, flowgate, obs_access, projectrun  # noqa: E402


@pytest.fixture(autouse=True)
def _keys(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path_factory.mktemp("keys")))


def _ki(tmp_path, name="M"):
    root = tmp_path / "kis" / name
    (root / "tools").mkdir(parents=True)
    (root / "SKILL.md").write_text("# M\n> **MANDATORY EXECUTION POLICY**\n> run the real model\n\n")
    (root / "dag.yaml").write_text("outputs:\n- var: discharge\n  validation_rank: 1\n  unit: m3/s\n")
    (root / "tools" / "run.py").write_text(
        "import sys, pathlib\n"
        "out = pathlib.Path(sys.argv[1]); out.parent.mkdir(parents=True, exist_ok=True)\n"
        "out.write_text('t,q\\n1,0.5\\n2,1.2\\n3,0.8\\n')\nprint('ran')\n")
    return SimpleNamespace(name=name, root=root)


def _cfg(project):
    return SimpleNamespace(root=project, python=sys.executable, roles={"binaries": project / "bin"})


def _plan(ki):
    return ({"schema_version": "1.0", "goal": "g", "selected_kis": [ki.name], "created_at": "t",
             "unresolved_questions": [],
             "steps": [{"id": "M:run", "ki": ki.name, "tool": str(ki.root / "tools" / "run.py"), "kind": "run",
                        "inputs": ["forcing"], "outputs": ["q"], "status": "planned"}],
             "scientific_choices": [{"id": "x", "kind": "other", "high_impact": False}]},
            {"schema_version": "1.0", "items": [{"id": "forcing", "required_by": [ki.name], "status": "resolved",
                                                 "acceptable_sources": ["cmfd_v1"], "chosen_source": "cmfd_v1",
                                                 "local_paths": [], "agent_resolvable": True, "needs_user": False}]})


def _session(tmp_path, ki, state_events=()):
    project = tmp_path / "project"; (project / "runs").mkdir(parents=True)
    fs = flowgate.FlowSession.open(project, {ki.name: ki.root}, python=sys.executable)
    for ev, evidence in state_events:
        fs.move(ev, evidence)
    return project, fs


def test_flow_loads_from_the_bundled_source():
    pkg = flowgate.load()
    assert pkg.__file__.startswith(str(REPO / "ki_tools_common"))
    for submodule in ("states", "resolve", "plan", "approval", "contracts",
                      "receipts", "policy", "tools", "build_data"):
        loaded = sys.modules[f"ki_tools_common.flow.{submodule}"]
        assert str(loaded.__file__).startswith(str(REPO / "ki_tools_common"))


def test_planning_filters_schemas_and_refuses_execution(tmp_path):
    ki = _ki(tmp_path)
    project, fs = _session(tmp_path, ki, [("task_received", None), ("kis_resolved", {"selected_kis": ["M"]})])
    names = {t["name"] for t in api.tool_schemas(ki, project_mode=True, flow=fs)}
    assert "write_plan" in names and "search_catalogue" in names and "estimate_clip" in names
    assert "run_ki_tool" not in names and "fetch_data" not in names
    with pytest.raises(api.ToolError, match="not allowed while the project is in PLANNING"):
        api.execute_tool("run_ki_tool", {"tool_path": "tools/run.py"}, ki, _cfg(project), project_mode=True, flow=fs)
    with pytest.raises(api.ToolError):
        api.execute_tool("fetch_data", {"url": "https://x/y", "item_id": "forcing"}, ki, _cfg(project),
                         project_mode=True, flow=fs)
    # the planning turn may write ONLY the two plan files
    with pytest.raises(api.ToolError, match="not allowed while the project is in PLANNING"):
        api.execute_tool("write_project_file", {"path": "outputs/x.csv", "content": "1"}, ki, _cfg(project),
                         project_mode=True, flow=fs)


def test_planning_agent_can_search_catalogue_but_cannot_download(tmp_path, monkeypatch):
    ki = _ki(tmp_path)
    project, fs = _session(tmp_path, ki, [
        ("task_received", None), ("kis_resolved", {"selected_kis": ["M"]})])

    class FakeClient:
        def catalogue(self, **kwargs):
            return {"total": 2, "datasets": [
                {"id": "obs-1", "name": "Bengbu discharge gauge", "variables": ["flow"]},
                {"id": "obs-2", "name": "Elsewhere", "variables": ["flow"]}]}

    monkeypatch.setattr(obs_access, "Client", FakeClient)
    output = api.execute_tool(
        "search_catalogue", {"query": "Bengbu discharge"}, ki,
        _cfg(project), project_mode=True, flow=fs)
    assert "obs-1" in output and "obs-2" not in output   # filtered locally from the app store
    with pytest.raises(api.ToolError, match="not allowed while the project is in PLANNING"):
        api.execute_tool("run_ki_tool", {"tool_path": "tools/run.py"}, ki,
                         _cfg(project), project_mode=True, flow=fs)


def test_approved_catalogue_download_is_fetched_by_the_host_and_receipted(tmp_path, monkeypatch):
    """Step 3: served data comes in during ACQUIRING through the host, never an agent tool."""
    from kiss_cli import acquire
    ki = _ki(tmp_path)
    project, fs = _session(tmp_path, ki, [
        ("task_received", None), ("kis_resolved", {"selected_kis": ["M"]})])
    pj, inv = _plan(ki)
    inv["items"][0].update(dataset_id="obs-1", delivery="served")
    fs.write_plan(pj, inv)
    fs.flow.approval.approve(project, by="auto"); fs.reload_artifacts()
    fs.move("plan_written", {"plan_valid": True}); fs.move("approved", {"approval": "OK"})

    class FakeClient:
        calls = 0

        def download(self, dataset_id, root, destination=None):
            FakeClient.calls += 1
            target = root / "inputs" / "observations" / dataset_id / "forcing.nc"
            target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(b"real")
            return {"ok": True, "served": True, "dataset_id": dataset_id,
                    "destination": str(target.parent), "raw_file": str(target),
                    "files": [str(target)], "sha256": "00", "size": 4}

    monkeypatch.setattr(obs_access, "Client", FakeClient)
    result = acquire.run(project)
    assert result["status"] == "done" and result["items"]["forcing"]["status"] == "done"
    receipt = json.loads(Path(result["items"]["forcing"]["receipt"]).read_text())
    assert receipt["item_id"] == "forcing" and receipt["plan_step_id"] == "M:run"
    assert receipt["approval_sha256"] == fs.approval_id
    # idempotent: a second pass reuses the receipt and downloads nothing
    again = acquire.run(project)
    assert again["status"] == "done" and FakeClient.calls == 1
    # no agent tool downloads catalogue data any more
    fs.move("execution_started", {"setup_verified": True})
    assert "download_observation_data" not in {t["name"] for t in api.tool_schemas(ki, project_mode=True, flow=fs)}
    with pytest.raises(api.ToolError, match="not allowed"):
        api.execute_tool("download_observation_data", {"dataset_id": "obs-1", "item_id": "forcing"},
                         ki, _cfg(project), project_mode=True, flow=fs)


def test_manual_catalogue_credentials_go_to_private_card_and_placed_files_get_a_receipt(tmp_path, monkeypatch):
    from kiss_cli import acquire, setup as setup_flow
    ki = _ki(tmp_path)
    project, fs = _session(tmp_path, ki, [
        ("task_received", None), ("kis_resolved", {"selected_kis": ["M"]})])
    pj, inv = _plan(ki)
    inv["items"][0].update(dataset_id="large-1", delivery="manual")
    fs.write_plan(pj, inv)
    fs.flow.approval.approve(project, by="auto"); fs.reload_artifacts()
    fs.move("plan_written", {"plan_valid": True}); fs.move("approved", {"approval": "OK"})

    class FakeClient:
        def download(self, dataset_id, root, destination=None):
            return {"ok": True, "served": False, "dataset_id": dataset_id,
                    "name": "Large data", "size": 18 * 1024**3,
                    "baidu_url": "https://pan.baidu.com/s/private", "baidu_pwd": "p4ss",
                    "destination": str(root / "inputs" / "observations" / dataset_id)}

    monkeypatch.setattr(obs_access, "Client", FakeClient)
    result = acquire.run(project)
    assert result["status"] == "waiting" and result["items"]["forcing"]["status"] == "waiting"
    assert "p4ss" not in json.dumps(result) and "pan.baidu.com" not in json.dumps(result)
    request = json.loads((project / "setup-request.json").read_text())
    assert request["kind"] == "download" and request["id"] == acquire.MANUAL_REQUEST_ID
    assert "p4ss" in request["message"] and request["rows"][0]["code"] == "p4ss"
    assert request["rows"][0]["expected_path"].endswith("inputs/observations/large-1")
    # the user places the files: the next pass signs what is there and clears the card
    dest = Path(request["rows"][0]["expected_path"]); dest.mkdir(parents=True)
    (dest / "part1.nc").write_bytes(b"data-a"); (dest / "part2.nc").write_bytes(b"data-b")
    result = acquire.run(project)
    assert result["status"] == "done"
    receipt = json.loads(Path(result["items"]["forcing"]["receipt"]).read_text())
    assert receipt["source"].startswith("manual placement")
    assert sorted(f["path"] for f in receipt["raw_files"]) == [
        "inputs/observations/large-1/part1.nc", "inputs/observations/large-1/part2.nc"]
    assert "p4ss" not in json.dumps(receipt) and "pan.baidu.com" not in json.dumps(receipt)
    assert setup_flow.request(project) is None
    ev = fs.evidence()
    assert not [a for a in ev.get("unreceipted_artifacts") or [] if a.startswith("inputs/observations/large-1/")]
    # a swapped file invalidates the old receipt; the next pass signs the new content
    first = json.loads(Path(result["items"]["forcing"]["receipt"]).read_text())
    (dest / "part1.nc").write_bytes(b"tampered")
    second = json.loads(Path(acquire.run(project)["items"]["forcing"]["receipt"]).read_text())
    assert second["raw_files"][0]["sha256"] != first["raw_files"][0]["sha256"]


def test_write_plan_validates_then_writes(tmp_path):
    ki = _ki(tmp_path)
    project, fs = _session(tmp_path, ki, [("task_received", None), ("kis_resolved", {"selected_kis": ["M"]})])
    pj, inv = _plan(ki)
    bad = json.loads(json.dumps(pj)); bad["steps"][0]["tool"] = str(ki.root / "SKILL.md")
    out = api.execute_tool("write_plan", {"plan": bad, "data_inventory": inv}, ki, _cfg(project), project_mode=True, flow=fs)
    assert out.startswith("PLAN NOT WRITTEN") and not (project / "runs" / "plan.json").exists()
    out = api.execute_tool("write_plan", {"plan": pj, "data_inventory": inv}, ki, _cfg(project), project_mode=True, flow=fs)
    assert "Plan files written" in out and (project / "runs" / "plan.json").exists()


def test_protected_files_are_never_agent_writable(tmp_path):
    ki = _ki(tmp_path)
    project, fs = _session(tmp_path, ki, [("task_received", None), ("kis_resolved", {"selected_kis": ["M"]})])
    pj, inv = _plan(ki)
    fs.write_plan(pj, inv); fs.flow.approval.approve(project, by="auto"); fs.reload_artifacts()
    fs.move("plan_written", {"plan_valid": True}); fs.move("approved", {"approval": "OK"})
    fs.move("execution_started", {"setup_verified": True})
    for rel in ("runs/approval.json", "runs/flow-state.json", "runs/plan.json", "runs/anything.json"):
        with pytest.raises(api.ToolError):
            api.execute_tool("write_project_file", {"path": rel, "content": "{}"}, ki, _cfg(project),
                             project_mode=True, flow=fs)
    assert "wrote outputs/note.txt" in api.execute_tool(
        "write_project_file", {"path": "outputs/note.txt", "content": "x"}, ki, _cfg(project), project_mode=True, flow=fs)


def test_run_ki_tool_in_executing_writes_a_receipt_and_validates(tmp_path):
    ki = _ki(tmp_path)
    project, fs = _session(tmp_path, ki, [("task_received", None), ("kis_resolved", {"selected_kis": ["M"]})])
    pj, inv = _plan(ki)
    fs.write_plan(pj, inv); fs.flow.approval.approve(project, by="auto"); fs.reload_artifacts()
    fs.move("plan_written", {"plan_valid": True}); fs.move("approved", {"approval": "OK"})
    fs.move("execution_started", {"setup_verified": True})
    names = {t["name"] for t in api.tool_schemas(ki, project_mode=True, flow=fs)}
    assert "run_ki_tool" in names and "fetch_data" in names and "write_plan" not in names
    with pytest.raises(api.ToolError, match="plan_step_id is required"):
        api.execute_tool("run_ki_tool", {"tool_path": "tools/run.py", "arguments": ["outputs/q.csv"]},
                         ki, _cfg(project), project_mode=True, flow=fs)
    out = api.execute_tool("run_ki_tool", {"tool_path": "tools/run.py", "arguments": ["outputs/q.csv"],
                                           "plan_step_id": "M:run"}, ki, _cfg(project), project_mode=True, flow=fs)
    assert out.startswith("exit_code=0") and "[RECEIPT]" in out
    summary = json.loads(out.splitlines()[1].split("[RECEIPT] ", 1)[1])
    assert summary["validation"] == "passed" and "outputs/q.csv" in summary["outputs"]
    rec = json.loads(Path(summary["receipt"]).read_text())
    assert fs.flow.receipts.verify(project, rec) and rec["plan_step_id"] == "M:run" and rec["exit_code"] == 0
    ev = fs.evidence()
    assert ev["receipts_verified"] is True and ev["validation"] == "passed" and ev["steps_missing"] == []
    # a step id not in the plan is refused
    with pytest.raises(api.ToolError, match="not a step of the approved plan"):
        api.execute_tool("run_ki_tool", {"tool_path": "tools/run.py", "arguments": ["outputs/z.csv"],
                                         "plan_step_id": "M:ghost"}, ki, _cfg(project), project_mode=True, flow=fs)


def test_direct_api_tool_gets_approved_step_environment_only(tmp_path, monkeypatch):
    ki = _ki(tmp_path)
    tool = ki.root / "tools" / "env.py"
    tool.write_text(
        "import json, os, pathlib\n"
        "p = pathlib.Path(os.environ['MODEL_OUTPUT'])\n"
        "p.parent.mkdir(parents=True, exist_ok=True)\n"
        "p.write_text(json.dumps({'root': os.environ['MODEL_KI_ROOT'], "
        "'secret': 'PRIVATE_API_KEY' in os.environ}))\n")
    project, fs = _session(tmp_path, ki, [
        ("task_received", None), ("kis_resolved", {"selected_kis": ["M"]})])
    pj, inv = _plan(ki)
    pj["steps"][0].update({
        "tool": str(tool),
        "env": {"MODEL_OUTPUT": "${PROJECT}/outputs/env.json",
                "MODEL_KI_ROOT": "${KI_ROOT}"},
    })
    fs.write_plan(pj, inv); fs.flow.approval.approve(project, by="auto"); fs.reload_artifacts()
    fs.move("plan_written", {"plan_valid": True}); fs.move("approved", {"approval": "OK"})
    fs.move("execution_started", {"setup_verified": True})
    monkeypatch.setenv("PRIVATE_API_KEY", "must-not-leak")
    output = api.execute_tool(
        "run_ki_tool", {"tool_path": "tools/env.py", "plan_step_id": "M:run"},
        ki, _cfg(project), project_mode=True, flow=fs)
    assert output.startswith("exit_code=0")
    observed = json.loads((project / "outputs" / "env.json").read_text())
    assert observed == {"root": str(ki.root.resolve()), "secret": False}


def test_run_ki_tool_refused_when_approval_drifts(tmp_path):
    ki = _ki(tmp_path)
    project, fs = _session(tmp_path, ki, [("task_received", None), ("kis_resolved", {"selected_kis": ["M"]})])
    pj, inv = _plan(ki)
    fs.write_plan(pj, inv); fs.flow.approval.approve(project, by="auto"); fs.reload_artifacts()
    fs.move("plan_written", {"plan_valid": True}); fs.move("approved", {"approval": "OK"})
    fs.move("execution_started", {"setup_verified": True})
    pj["goal"] = "changed"; fs.flow.plan.write_artifacts(project, pj, inv)
    with pytest.raises(api.ToolError, match="no valid approval"):
        api.execute_tool("run_ki_tool", {"tool_path": "tools/run.py", "arguments": ["outputs/q.csv"],
                                         "plan_step_id": "M:run"}, ki, _cfg(project), project_mode=True, flow=fs)


def test_run_ki_tool_refuses_a_step_with_no_approved_tool(tmp_path):
    ki = _ki(tmp_path)
    project, fs = _session(tmp_path, ki, [
        ("task_received", None), ("kis_resolved", {"selected_kis": ["M"]})])
    pj, inv = _plan(ki); pj["steps"][0]["tool"] = None; pj["steps"][0]["kind"] = "check"
    fs.write_plan(pj, inv); fs.flow.approval.approve(project, by="auto"); fs.reload_artifacts()
    fs.move("plan_written", {"plan_valid": True}); fs.move("approved", {"approval": "OK"})
    fs.move("execution_started", {"setup_verified": True})
    with pytest.raises(api.ToolError, match="has no approved tool"):
        api.execute_tool(
            "run_ki_tool", {"tool_path": "tools/run.py", "arguments": ["outputs/q.csv"],
                            "plan_step_id": "M:run"},
            ki, _cfg(project), project_mode=True, flow=fs)


def test_run_ki_tool_refused_when_approved_tool_bytes_drift(tmp_path):
    ki = _ki(tmp_path)
    project, fs = _session(tmp_path, ki, [
        ("task_received", None), ("kis_resolved", {"selected_kis": ["M"]})])
    pj, inv = _plan(ki)
    fs.write_plan(pj, inv); fs.flow.approval.approve(project, by="auto"); fs.reload_artifacts()
    fs.move("plan_written", {"plan_valid": True}); fs.move("approved", {"approval": "OK"})
    fs.move("execution_started", {"setup_verified": True})
    (ki.root / "tools" / "run.py").write_text("print('changed after approval')\n")
    with pytest.raises(api.ToolError, match="no valid approval"):
        api.execute_tool(
            "run_ki_tool", {"tool_path": "tools/run.py", "arguments": ["outputs/q.csv"],
                            "plan_step_id": "M:run"},
            ki, _cfg(project), project_mode=True, flow=fs)


def test_progress_report_cannot_move_the_stage_once_flow_owned(tmp_path):
    ki = _ki(tmp_path)
    project, fs = _session(tmp_path, ki, [("task_received", None), ("kis_resolved", {"selected_kis": ["M"]})])
    projectrun.set_stage(project, "preparing", "planning")
    out = api.execute_tool("report_project_progress", {"stage": "results", "status": "complete", "summary": "done!"},
                           ki, _cfg(project), project_mode=True, flow=fs)
    state = projectrun.load(project)
    assert state["stage"] == "preparing" and state["summary"] == "done!" and "tracked by GeoForge" in out
    # a native agent's status file cannot move it either
    (project / "runs" / "project-agent-status.json").write_text(json.dumps({"stage": "results", "status": "complete"}))
    assert projectrun.load(project)["stage"] == "preparing"
    with pytest.raises(ValueError):
        projectrun.set_stage(project, "results", source="agent")


def test_multi_ki_run_ki_tool_selects_by_name(tmp_path):
    a, b = _ki(tmp_path, "A"), _ki(tmp_path, "B")
    project = tmp_path / "project"; (project / "runs").mkdir(parents=True)
    fs = flowgate.FlowSession.open(project, {"A": a.root, "B": b.root}, python=sys.executable)
    fs.move("task_received"); fs.move("kis_resolved", {"selected_kis": ["A", "B"]})
    pj, inv = _plan(a); pj["selected_kis"] = ["A", "B"]
    pj["steps"] = [{"id": "A:run", "ki": "A", "tool": str(a.root / "tools" / "run.py"), "kind": "run", "inputs": ["forcing"], "outputs": [], "status": "planned"},
                   {"id": "B:run", "ki": "B", "tool": str(b.root / "tools" / "run.py"), "kind": "run", "inputs": ["forcing"], "outputs": [], "status": "planned"}]
    inv["items"][0]["required_by"] = ["A", "B"]
    assert fs.write_plan(pj, inv) == []
    fs.flow.approval.approve(project, by="auto"); fs.reload_artifacts()
    fs.move("plan_written", {"plan_valid": True}); fs.move("approved", {"approval": "OK"}); fs.move("execution_started", {"setup_verified": True})
    out = api.execute_tool("run_ki_tool", {"tool_path": "tools/run.py", "arguments": ["outputs/b.csv"], "ki": "B",
                                           "plan_step_id": "B:run"}, a, _cfg(project), project_mode=True, flow=fs)
    assert out.startswith("exit_code=0")
    with pytest.raises(api.ToolError, match="not one of the selected KIs"):
        api.execute_tool("run_ki_tool", {"tool_path": "tools/run.py", "ki": "C", "plan_step_id": "A:run"},
                         a, _cfg(project), project_mode=True, flow=fs)


def test_read_and_list_ki_files_reach_every_selected_ki(tmp_path):
    a, b = _ki(tmp_path, "A"), _ki(tmp_path, "B")
    (b.root / "docs").mkdir(); (b.root / "docs" / "note.md").write_text("B doc")
    project = tmp_path / "project"; (project / "runs").mkdir(parents=True)
    fs = flowgate.FlowSession.open(project, {"A": a.root, "B": b.root}, python=sys.executable)
    fs.move("task_received"); fs.move("kis_resolved", {"selected_kis": ["A", "B"]})
    assert api.execute_tool("read_ki_file", {"path": "docs/note.md", "ki": "B"}, a, _cfg(project),
                            project_mode=True, flow=fs) == "B doc"
    assert "docs/note.md" in api.execute_tool("list_ki_files", {"ki": "B"}, a, _cfg(project), project_mode=True, flow=fs)
    with pytest.raises(api.ToolError, match="not one of the selected KIs"):
        api.execute_tool("read_ki_file", {"path": "SKILL.md", "ki": "C"}, a, _cfg(project), project_mode=True, flow=fs)
    with pytest.raises(api.ToolError, match="escapes"):
        api.execute_tool("read_ki_file", {"path": "../A/SKILL.md", "ki": "B"}, a, _cfg(project), project_mode=True, flow=fs)


def test_progress_prompt_has_no_stage_under_the_flow(tmp_path):
    project = tmp_path / "project"; (project / "runs").mkdir(parents=True)
    assert '"stage":' in projectrun.prompt_block(project)
    fs = flowgate.FlowSession.open(project, {}); fs.move("task_received")
    assert '"stage":' not in projectrun.prompt_block(project) and "GEOFORGE TRACKS THE STAGE" in projectrun.prompt_block(project)


def test_write_plan_accepts_two_calls_and_json_strings(tmp_path, monkeypatch):
    ki = _ki(tmp_path)
    project, fs = _session(tmp_path, ki, [
        ("task_received", None), ("kis_resolved", {"selected_kis": ["M"]})])
    pj, inv = _plan(ki)
    first = api.execute_tool("write_plan", {"plan": json.dumps(pj)}, ki, _cfg(project),
                             project_mode=True, flow=fs)
    assert "now call write_plan again with only data_inventory" in first
    assert not (project / "runs" / "plan.json").exists()
    second = api.execute_tool("write_plan", {"data_inventory": inv}, ki, _cfg(project),
                              project_mode=True, flow=fs)
    assert "Plan files written" in second
    assert (project / "runs" / "plan.json").exists()
    with pytest.raises(api.ToolError, match="Call write_plan twice"):
        api.execute_tool("write_plan", {"_vendor_argument_error": "cut off"}, ki, _cfg(project),
                         project_mode=True, flow=fs)


def test_api_runs_the_declared_model_binary_with_a_receipt(tmp_path, monkeypatch):
    ki = _ki(tmp_path)
    exe = tmp_path / "binaries" / "vic_classic.exe"
    exe.parent.mkdir()
    exe.write_text("#!/bin/sh\necho ran \"$@\"\n")
    exe.chmod(0o755)
    (ki.root / "knowledge_infrastructure.yaml").write_text(
        f"model:\n  binary:\n    path: {exe}\n")
    project, fs = _session(tmp_path, ki, [
        ("task_received", None), ("kis_resolved", {"selected_kis": ["M"]})])
    pj, inv = _plan(ki)
    pj["steps"][0]["tool"] = str(exe)
    assert fs.write_plan(pj, inv) == []
    fs.flow.approval.approve(project, by="user"); fs.reload_artifacts()
    fs.move("plan_written", {"plan_valid": True}); fs.move("approved", {"approval": "OK"})
    fs.move("execution_started", {"setup_verified": True})
    out = api.execute_tool(
        "run_ki_tool", {"tool_path": str(exe), "plan_step_id": pj["steps"][0]["id"],
                        "arguments": ["-g", "runs/global.txt"]},
        ki, _cfg(project), project_mode=True, flow=fs)
    assert "ran -g runs/global.txt" in out


def test_request_replan_unlocks_write_plan_in_the_same_turn(tmp_path):
    ki = _ki(tmp_path)
    project, fs = _session(tmp_path, ki, [
        ("task_received", None), ("kis_resolved", {"selected_kis": ["M"]})])
    pj, inv = _plan(ki)
    assert fs.write_plan(pj, inv) == []
    fs.flow.approval.approve(project, by="user"); fs.reload_artifacts()
    fs.move("plan_written", {"plan_valid": True}); fs.move("approved", {"approval": "OK"})
    fs.move("execution_started", {"setup_verified": True})
    assert "request_replan" in fs.api_tools() and "write_plan" not in fs.api_tools()
    with pytest.raises(api.ToolError, match="not allowed while the project is in EXECUTING"):
        api.execute_tool("write_plan", {"plan": pj, "data_inventory": inv}, ki, _cfg(project),
                         project_mode=True, flow=fs)
    out = api.execute_tool("request_replan", {"reason": "S1 needs a site polygon"}, ki, _cfg(project),
                           project_mode=True, flow=fs)
    assert "REPLAN_REQUIRED" in out and fs.state.value == "REPLAN_REQUIRED"
    assert not (project / "runs" / "approval.json").exists()
    assert "write_plan" in fs.api_tools()
    pj["steps"][0]["id"] = "M:run2"
    written = api.execute_tool("write_plan", {"plan": pj, "data_inventory": inv}, ki, _cfg(project),
                               project_mode=True, flow=fs)
    assert "Plan files written" in written
    with pytest.raises(api.ToolError, match="not allowed while the project is in REPLAN_REQUIRED"):
        api.execute_tool("request_replan", {"reason": "again"}, ki, _cfg(project),
                         project_mode=True, flow=fs)


def test_renamed_item_after_replan_reuses_verified_files_without_redownload(tmp_path, monkeypatch):
    """Live 2026-09-18: a replan renamed gdhy_harbin_pixel; the files were already verified."""
    from kiss_cli import acquire
    ki = _ki(tmp_path)
    project, fs = _session(tmp_path, ki, [("task_received", None), ("kis_resolved", {"selected_kis": ["M"]})])
    pj, inv = _plan(ki)
    inv["items"][0].update(dataset_id="obs-1", delivery="served")
    fs.write_plan(pj, inv); fs.flow.approval.approve(project, by="auto"); fs.reload_artifacts()
    fs.move("plan_written", {"plan_valid": True}); fs.move("approved", {"approval": "OK"})

    class FakeClient:
        calls = 0

        def download(self, dataset_id, root, destination=None):
            FakeClient.calls += 1
            raw = root / ".geoforge" / "downloads" / dataset_id / f"{dataset_id}.zip"
            out = root / "inputs" / "observations" / dataset_id / "forcing.nc"
            raw.parent.mkdir(parents=True, exist_ok=True); out.parent.mkdir(parents=True, exist_ok=True)
            raw.write_bytes(b"zip"); out.write_bytes(b"real")
            return {"ok": True, "served": True, "dataset_id": dataset_id, "destination": str(out.parent),
                    "raw_file": str(raw), "files": [str(out)], "sha256": "00", "size": 4}

    monkeypatch.setattr(obs_access, "Client", FakeClient)
    assert acquire.run(project)["status"] == "done" and FakeClient.calls == 1
    # replan: same dataset, new item id, new approval
    pj["steps"][0]["inputs"] = ["forcing_v2"]
    inv["items"][0]["id"] = "forcing_v2"
    fs.move("execution_started", {"setup_verified": True}); fs.move("replan")
    fs.flow.approval.revoke(project, "replan")
    fs.write_plan(pj, inv); fs.flow.approval.approve(project, by="auto"); fs.reload_artifacts()
    fs.move("plan_written", {"plan_valid": True}); fs.move("approved", {"approval": "OK"})
    result = acquire.run(project)
    assert result["status"] == "done" and FakeClient.calls == 1          # no second download
    receipt = json.loads(Path(result["items"]["forcing_v2"]["receipt"]).read_text())
    assert receipt["item_id"] == "forcing_v2" and receipt["approval_sha256"] == fs.approval_id
    assert receipt["raw_files"][0]["path"] == ".geoforge/downloads/obs-1/obs-1.zip"


def test_rebind_survives_a_lost_transport_archive(tmp_path, monkeypatch):
    """Live 2026-09-18: a failed retry had deleted the raw zips; the extracted files were intact."""
    from kiss_cli import acquire
    ki = _ki(tmp_path)
    project, fs = _session(tmp_path, ki, [("task_received", None), ("kis_resolved", {"selected_kis": ["M"]})])
    pj, inv = _plan(ki)
    inv["items"][0].update(dataset_id="obs-1", delivery="served")
    fs.write_plan(pj, inv); fs.flow.approval.approve(project, by="auto"); fs.reload_artifacts()
    fs.move("plan_written", {"plan_valid": True}); fs.move("approved", {"approval": "OK"})

    class FakeClient:
        calls = 0

        def download(self, dataset_id, root, destination=None):
            out = root / "inputs" / "observations" / dataset_id / "forcing.nc"
            if out.exists():        # the real client refuses a non-empty destination
                raise obs_access.ObsAccessError("destination_not_empty", "already contains files")
            FakeClient.calls += 1
            raw = root / ".geoforge" / "downloads" / dataset_id / f"{dataset_id}.zip"
            raw.parent.mkdir(parents=True, exist_ok=True); out.parent.mkdir(parents=True, exist_ok=True)
            raw.write_bytes(b"zip"); out.write_bytes(b"real")
            return {"ok": True, "served": True, "dataset_id": dataset_id, "destination": str(out.parent),
                    "raw_file": str(raw), "files": [str(out)], "sha256": "00", "size": 4}

    monkeypatch.setattr(obs_access, "Client", FakeClient)
    assert acquire.run(project)["status"] == "done"
    (project / ".geoforge/downloads/obs-1/obs-1.zip").unlink()
    inv["items"][0]["id"] = "forcing_v2"; pj["steps"][0]["inputs"] = ["forcing_v2"]
    fs.move("execution_started", {"setup_verified": True}); fs.move("replan"); fs.flow.approval.revoke(project, "r")
    fs.write_plan(pj, inv); fs.flow.approval.approve(project, by="auto"); fs.reload_artifacts()
    fs.move("plan_written", {"plan_valid": True}); fs.move("approved", {"approval": "OK"})
    result = acquire.run(project)
    assert result["status"] == "done" and FakeClient.calls == 1
    receipt = json.loads(Path(result["items"]["forcing_v2"]["receipt"]).read_text())
    assert receipt["transform_tool"] == "rebound_extracted_files"
    assert receipt["raw_files"][0]["path"] == "inputs/observations/obs-1/forcing.nc"
    assert fs.flow.receipts._download_files_valid(project, receipt)
    # a tampered extracted file is not re-bound
    (project / "inputs/observations/obs-1/forcing.nc").write_bytes(b"bad")
    (project / ".geoforge/receipts/data-receipts/forcing_v2.json").unlink()
    result = acquire.run(project)
    assert result["items"]["forcing_v2"]["status"] == "failed" and FakeClient.calls == 1


def test_manual_path_with_the_real_client_signs_placed_files(tmp_path, monkeypatch):
    """Review B-1: the real Client.download refuses a non-empty destination; the manual
    branch must check placed files first and never ask the server again once they are there."""
    from kiss_cli import acquire, setup as setup_flow
    from kiss_cli.obs_access import Client
    from .test_obs_access import Opener, json_response
    ki = _ki(tmp_path)
    project, fs = _session(tmp_path, ki, [("task_received", None), ("kis_resolved", {"selected_kis": ["M"]})])
    pj, inv = _plan(ki)
    inv["items"][0].update(dataset_id="large-1", delivery="manual")
    fs.write_plan(pj, inv); fs.flow.approval.approve(project, by="auto"); fs.reload_artifacts()
    fs.move("plan_written", {"plan_valid": True}); fs.move("approved", {"approval": "OK"})
    handoff = {"served": False, "name": "Large data", "size": 123, "baidu_url": "https://pan.baidu.com/s/x",
               "baidu_pwd": "p4ss"}
    opener = Opener(json_response(handoff))
    monkeypatch.setattr(obs_access, "Client", lambda: Client(opener=opener, token_getter=lambda: "tok"))
    first = acquire.run(project)
    assert first["status"] == "waiting" and len(opener.requests) == 1
    card = setup_flow.request(project)
    dest = Path(card["rows"][0]["expected_path"])
    assert dest == project.resolve() / "inputs" / "observations" / "large-1"
    dest.mkdir(parents=True); (dest / "a.nc").write_bytes(b"data")
    second = acquire.run(project)
    assert second["status"] == "done" and len(opener.requests) == 1      # no second server call
    assert setup_flow.request(project) is None
    receipt = json.loads(Path(second["items"]["forcing"]["receipt"]).read_text())
    assert receipt["raw_files"][0]["path"] == "inputs/observations/large-1/a.nc"


def test_served_folder_without_receipt_is_an_actionable_failure(tmp_path, monkeypatch):
    from kiss_cli import acquire
    from kiss_cli.obs_access import Client
    from .test_obs_access import Opener
    ki = _ki(tmp_path)
    project, fs = _session(tmp_path, ki, [("task_received", None), ("kis_resolved", {"selected_kis": ["M"]})])
    pj, inv = _plan(ki)
    inv["items"][0].update(dataset_id="obs-9", delivery="served")
    fs.write_plan(pj, inv); fs.flow.approval.approve(project, by="auto"); fs.reload_artifacts()
    fs.move("plan_written", {"plan_valid": True}); fs.move("approved", {"approval": "OK"})
    folder = project / "inputs" / "observations" / "obs-9"; folder.mkdir(parents=True)
    (folder / "stray.nc").write_bytes(b"?")
    opener = Opener()
    monkeypatch.setattr(obs_access, "Client", lambda: Client(opener=opener, token_getter=lambda: "tok"))
    result = acquire.run(project)
    assert result["status"] == "failed" and "no receipt" in result["items"]["forcing"]["error"]
    assert not opener.requests                                            # nothing downloaded over it


def test_stale_acquisition_entries_do_not_survive_a_replan(tmp_path, monkeypatch):
    """Review B-3: BLOCKED → Modify → the failed item is dropped → the next pass must be done."""
    from kiss_cli import acquire
    ki = _ki(tmp_path)
    project, fs = _session(tmp_path, ki, [("task_received", None), ("kis_resolved", {"selected_kis": ["M"]})])
    pj, inv = _plan(ki)
    inv["items"][0].update(dataset_id="gone-1", delivery="served")
    fs.write_plan(pj, inv); fs.flow.approval.approve(project, by="auto"); fs.reload_artifacts()
    fs.move("plan_written", {"plan_valid": True}); fs.move("approved", {"approval": "OK"})

    class Failing:
        def download(self, dataset_id, root, destination=None):
            raise obs_access.ObsAccessError("server_unavailable", "HTTP 503")

    monkeypatch.setattr(obs_access, "Client", Failing)
    assert acquire.run(project)["status"] == "failed"
    # replan: the item is replaced by a locally provided input, new approval
    pj["steps"][0]["inputs"] = ["local_forcing"]
    inv["items"] = [{"id": "local_forcing", "required_by": ["M"], "status": "ready", "acceptable_sources": [],
                     "chosen_source": "user", "local_paths": ["inputs/local/f.nc"], "agent_resolvable": True,
                     "needs_user": False}]
    (project / "inputs/local").mkdir(parents=True); (project / "inputs/local/f.nc").write_bytes(b"x")
    fs.move("acquire", {"approval": "OK"}); fs.move("acquisition_failed"); fs.move("unblocked")
    fs.flow.approval.revoke(project, "modify")
    fs.write_plan(pj, inv); fs.flow.approval.approve(project, by="auto"); fs.reload_artifacts()
    fs.move("plan_written", {"plan_valid": True}); fs.move("approved", {"approval": "OK"})
    result = acquire.run(project)
    assert result["status"] == "done" and "forcing" not in result["items"]


def test_manual_card_is_the_run_blocker_even_when_unchanged(tmp_path, monkeypatch):
    """Live 2026-09-18: the request file held the download rows but Project status kept
    showing the earlier Retry card, because the run's blocker record was never updated."""
    from kiss_cli import acquire, projectrun, setup as setup_flow
    ki = _ki(tmp_path)
    project, fs = _session(tmp_path, ki, [("task_received", None), ("kis_resolved", {"selected_kis": ["M"]})])
    pj, inv = _plan(ki)
    inv["items"][0].update(dataset_id="large-1", delivery="manual")
    fs.write_plan(pj, inv); fs.flow.approval.approve(project, by="auto"); fs.reload_artifacts()
    fs.move("plan_written", {"plan_valid": True}); fs.move("approved", {"approval": "OK"})

    class FakeClient:
        def download(self, dataset_id, root, destination=None):
            return {"ok": True, "served": False, "dataset_id": dataset_id, "name": "Large", "size": 5,
                    "baidu_url": "https://pan.baidu.com/s/x", "baidu_pwd": "p"}

    monkeypatch.setattr(obs_access, "Client", FakeClient)
    acquire.run(project)
    # an older card is recorded as the blocker afterwards (e.g. a Retry card)
    projectrun.report(project, {"status": "waiting_for_user", "summary": "old", "blocker": {"id": "flow-acquisition-blocked"}}, source="flow")
    acquire.run(project)                      # unchanged rows: dedupe path
    assert projectrun.load(project)["blocker"]["id"] == acquire.MANUAL_REQUEST_ID
    assert setup_flow.request(project)["rows"][0]["code"] == "p"
    # placed files clear both the card and the blocker
    dest = Path(setup_flow.request(project)["rows"][0]["expected_path"]); dest.mkdir(parents=True)
    (dest / "a.nc").write_bytes(b"x")
    assert acquire.run(project)["status"] == "done"
    assert setup_flow.request(project) is None and "blocker" not in projectrun.load(project)


def test_run_blocker_keeps_the_download_rows(tmp_path):
    from kiss_cli import projectrun
    projectrun.report(tmp_path, {"status": "waiting_for_user", "summary": "dl", "blocker": {
        "id": "flow-manual-download", "kind": "download", "title": "t",
        "rows": [{"item_id": "a", "dataset_id": "d", "name": "n", "size": 5, "url": "https://x/y",
                  "code": "c1", "expected_path": "/p/a"},
                 {"item_id": "b", "url": "javascript:alert(1)", "expected_path": "/p/b"}]}}, source="flow")
    rows = projectrun.load(tmp_path)["blocker"]["rows"]
    assert rows[0]["code"] == "c1" and rows[0]["url"] == "https://x/y" and rows[0]["size"] == 5
    assert rows[1]["url"] is None


def test_two_items_on_one_manual_dataset_make_one_download_row(tmp_path, monkeypatch):
    from kiss_cli import acquire, setup as setup_flow
    ki = _ki(tmp_path)
    project, fs = _session(tmp_path, ki, [("task_received", None), ("kis_resolved", {"selected_kis": ["M"]})])
    pj, inv = _plan(ki)
    inv["items"][0].update(dataset_id="large-1", delivery="manual")
    inv["items"].append({**inv["items"][0], "id": "forcing_b"})
    pj["steps"][0]["inputs"].append("forcing_b")
    fs.write_plan(pj, inv); fs.flow.approval.approve(project, by="auto"); fs.reload_artifacts()
    fs.move("plan_written", {"plan_valid": True}); fs.move("approved", {"approval": "OK"})

    class FakeClient:
        def download(self, dataset_id, root, destination=None):
            return {"ok": True, "served": False, "dataset_id": dataset_id, "name": "Large",
                    "baidu_url": "https://pan.baidu.com/s/x", "baidu_pwd": "p"}

    monkeypatch.setattr(obs_access, "Client", FakeClient)
    result = acquire.run(project)
    assert result["status"] == "waiting" and len(setup_flow.request(project)["rows"]) == 1
    dest = Path(setup_flow.request(project)["rows"][0]["expected_path"]); dest.mkdir(parents=True)
    (dest / "a.nc").write_bytes(b"x")
    result = acquire.run(project)
    assert result["status"] == "done" and {v["status"] for v in result["items"].values()} == {"done"}
