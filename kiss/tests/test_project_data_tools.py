"""Offline real-child checks of the reviewed project-data fallback; no provider."""
import copy
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from kiss_cli import api, flowgate, ki_guard, project_data_tools
from .test_flowgate import _ki, _cfg, _session, _plan


@pytest.fixture(autouse=True)
def keys(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "signing-keys"))


CSV_READER = '''import csv, json, pathlib, sys
raw = pathlib.Path(sys.argv[1])
with raw.open(newline='', encoding='utf-8') as stream:
    rows = list(csv.DictReader(stream))
out = pathlib.Path(sys.argv[2]); out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps({'rows': rows, 'count': len(rows)}), encoding='utf-8')
'''


def case(tmp_path, source=CSV_READER, arguments=None):
    ki = _ki(tmp_path)
    # Host preparation fixes the selected KI baseline before authoring or any
    # tested mutation. Project readers remain separately reviewed draft tools.
    ki_guard.enroll(ki.root)
    project, fs = _session(tmp_path, ki, [("task_received", None), ("kis_resolved", {"selected_kis": ["M"]})])
    raw = project / "inputs" / "raw.csv"
    raw.parent.mkdir(); raw.write_text("date,value,flag\n2020-02-28,1,B\n2020-02-29,,E\n", encoding="utf-8")
    authored = json.loads(api.execute_tool("write_project_data_tool", {
        "ki": "M", "name": "reader", "source": source, "purpose": "reader"},
        ki, _cfg(project), project_mode=True, flow=fs))
    plan, inv = _plan(ki)
    plan["steps"][0].update(id="M:read", kind="check", tool=authored["tool"],
                            project_data_tool=authored["project_data_tool"], outputs=["inspection"])
    plan["steps"][0]["project_data_tool"]["arguments"] = arguments or ["inputs/raw.csv", "outputs/inspection.json"]
    inv["items"][0].update(status="ready", local_paths=[str(raw)])
    return ki, project, fs, plan, inv, authored


def approve(c):
    ki, project, fs, plan, inv, authored = c
    assert fs.write_plan(plan, inv) == []
    fs.flow.approval.approve(project, by="auto")
    fs.reload_artifacts()
    fs.move("plan_written", {"plan_valid": True}); fs.move("approved", {"approval": "OK"})
    fs.move("execution_started", {"setup_verified": True})


def run(c, **extra):
    ki, project, fs, plan, inv, authored = c
    return api.execute_tool("run_project_data_tool", {
        "ki": "M", "tool_path": authored["tool"], "plan_step_id": "M:read", **extra},
        ki, _cfg(project), project_mode=True, flow=fs)


def test_author_is_planning_only_no_execution_and_source_not_a_ki_tool(tmp_path):
    c = case(tmp_path)
    ki, project, fs, plan, inv, authored = c
    assert authored["executed"] is False and not (project / "outputs").exists()
    assert fs.flow.tools.is_ki_tool(ki.root, authored["tool"]) is False
    for state in fs.flow.states.State:
        assert fs.flow.policy.api_tool_allowed(state, "write_project_data_tool") == (
            state.value in {"PLANNING", "REPLAN_REQUIRED"})
        assert fs.flow.policy.api_tool_allowed(state, "run_project_data_tool") == (state.value == "EXECUTING")
    with pytest.raises(api.ToolError, match="not allowed"):
        run(c)
    approve(c)
    with pytest.raises(api.ToolError, match="not allowed"):
        api.execute_tool("write_project_data_tool", {"ki":"M", "name":"second", "source":"pass", "purpose":"reader"},
                         ki, _cfg(project), project_mode=True, flow=fs)


def test_project_reader_authoring_cannot_enroll_an_unknown_ki_implicitly(tmp_path):
    ki, project, fs, _plan_doc, _inventory, _authored = case(tmp_path)
    unregistered = tmp_path / "unregistered-ki"
    shutil.copytree(ki.root, unregistered)
    unknown = type(ki)(name=ki.name, root=unregistered)
    assert not ki_guard.is_managed(unregistered)
    with pytest.raises(api.ToolError, match="no host baseline"):
        api.execute_tool("write_project_data_tool", {
            "ki": "M", "name": "unknown", "source": "pass", "purpose": "reader"},
            unknown, _cfg(project), project_mode=True, flow=fs)
    assert not ki_guard.is_managed(unregistered)
    assert not any(path.name == "unknown.py" for path in project.rglob("*.py"))


def test_project_reader_execution_refuses_changed_selected_ki_after_approval(tmp_path):
    c = case(tmp_path)
    approve(c)
    protocol = c[0].root / "SKILL.md"
    protocol.write_text(protocol.read_text(encoding="utf-8") + "\nChanged protocol\n", encoding="utf-8")
    with pytest.raises(api.ToolError, match="Active KI changed"):
        run(c)
    assert not (c[1] / "outputs").exists()


def test_csv_reader_preserves_values_flags_and_missingness_with_signed_receipt(tmp_path):
    c = case(tmp_path); approve(c)
    raw = c[1] / "inputs/raw.csv"; before = raw.read_bytes()
    output = run(c)
    assert output.startswith("exit_code=0"), output
    data = json.loads((c[1] / "outputs/inspection.json").read_text())
    assert data == {"rows":[{"date":"2020-02-28","value":"1","flag":"B"},
                            {"date":"2020-02-29","value":"","flag":"E"}], "count":2}
    assert raw.read_bytes() == before
    summary = json.loads(output.splitlines()[1].split("[RECEIPT] ", 1)[1])
    receipt = json.loads(Path(summary["receipt"]).read_text())
    assert c[2].flow.receipts.verify(c[1], receipt)
    assert receipt["execution_scope"] == "project_data_tool" and receipt["plan_step_id"] == "M:read"
    assert receipt["model_executed"] is False and summary["step_kind"] == "check"
    assert "M:read" in c[2].evidence()["steps_passed"], c[2].evidence()
    assert c[2].flow.approval.read(c[1])["tool_sha256"]["M:read"]["sha256"] == hashlib.sha256(Path(c[5]["tool"]).read_bytes()).hexdigest()


@pytest.mark.parametrize("change", ["source", "arguments", "cwd", "timeout", "tool", "ki", "kind", "metadata_hash"])
def test_binding_drift_refused_before_launch(tmp_path, change):
    c = case(tmp_path)
    if change in {"kind", "metadata_hash"}:
        if change == "kind": c[3]["steps"][0]["kind"] = "run"
        else: c[3]["steps"][0]["project_data_tool"]["source_sha256"] = "0"*64
        assert c[2].write_plan(c[3], c[4])
        return
    approve(c)
    extra = {}
    if change == "source": Path(c[5]["tool"]).write_text("print('drift')")
    if change == "arguments": extra["arguments"] = ["inputs/raw.csv", "outputs/other.json"]
    if change == "cwd": extra["cwd"] = "inputs"
    if change == "timeout": extra["timeout_seconds"] = 1
    if change == "tool": extra["tool_path"] = str(c[0].root / "tools/run.py")
    if change == "ki": extra["ki"] = "OTHER"
    with pytest.raises(api.ToolError): run(c, **extra)
    assert not (c[1]/"outputs").exists()


@pytest.mark.parametrize("name", ["../escape", "bad/name", "C:/outside", "reader.py", ".."])
def test_author_rejects_escape_names(tmp_path, name):
    with pytest.raises(ValueError):
        project_data_tools.write(tmp_path, "M", name, "pass", "reader")
    assert not list(tmp_path.rglob("*.py"))


@pytest.mark.parametrize("source", [
    "from pathlib import Path\nPath('inputs/raw.csv').write_text('fake')",
    "from pathlib import Path\nPath('runs/approval.json').write_text('{}')",
    "import subprocess\nsubprocess.run(['cmd','/c','echo','native'])",
    "import socket\nsocket.socket()",
    "import sqlite3\nsqlite3.connect('inputs/data.sqlite')",
])
def test_guarded_worker_denies_raw_protected_writes_native_network_and_writable_sqlite(tmp_path, source):
    c = case(tmp_path, source); approve(c)
    raw = (c[1]/"inputs/raw.csv").read_bytes()
    output = run(c)
    assert output.startswith("exit_code=1"), output
    assert "PermissionError" in output
    assert (c[1]/"inputs/raw.csv").read_bytes() == raw
    assert not (c[1]/"inputs/data.sqlite").exists()
    assert c[2].approval_status() == "OK"


def test_sqlite_reader_opens_readonly_preserves_feb29_and_flags(tmp_path):
    source = '''import sqlite3, pathlib, json, sys
p=pathlib.Path(sys.argv[1]).resolve()
with sqlite3.connect(p.as_uri()+'?mode=ro', uri=True) as con:
    con.execute('PRAGMA query_only=ON')
    columns=con.execute('PRAGMA table_info(observations)').fetchall()
    rows=con.execute('SELECT date,value,flag FROM observations ORDER BY date').fetchall()
out=pathlib.Path(sys.argv[2]);out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(json.dumps({'rows':rows, 'columns':len(columns)}))
'''
    c = case(tmp_path, source, ["inputs/data.sqlite", "outputs/inspection.json"])
    raw = c[1]/"inputs/data.sqlite"
    with sqlite3.connect(raw) as con:
        con.execute("CREATE TABLE observations(date TEXT,value REAL,flag TEXT)")
        con.executemany("INSERT INTO observations VALUES(?,?,?)", [("2020-02-28",1.0,"B"),("2020-02-29",None,"E")])
    c[4]["items"][0]["local_paths"] = [str(raw)]
    before = raw.read_bytes(); approve(c)
    output = run(c)
    assert output.startswith("exit_code=0"), output
    assert json.loads((c[1]/"outputs/inspection.json").read_text()) == {
        "rows":[["2020-02-28",1.0,"B"],["2020-02-29",None,"E"]], "columns":3}
    assert raw.read_bytes() == before


def test_output_overwrite_refused_and_provider_credentials_not_in_child(tmp_path, monkeypatch):
    source = '''import os,json,pathlib
p=pathlib.Path('outputs/env.json');p.parent.mkdir(parents=True,exist_ok=True)
p.write_text(json.dumps({k:v for k,v in os.environ.items() if 'TOKEN' in k or 'KEY' in k or 'PROXY' in k or k=='PYTHONPATH'}))
'''
    c=case(tmp_path,source);approve(c)
    monkeypatch.setenv("PRIVATE_API_KEY", "fixture-only")
    monkeypatch.setenv("HTTPS_PROXY", "http://fixture:credential@invalid")
    monkeypatch.setenv("PYTHONPATH", "fixture-path")
    assert run(c).startswith("exit_code=0")
    assert json.loads((c[1]/"outputs/env.json").read_text()) == {}
    assert run(c).startswith("exit_code=1")


def test_timeout_and_stop_use_supervised_execution(tmp_path):
    c=case(tmp_path,"while True: pass")
    c[3]["steps"][0]["project_data_tool"]["timeout_seconds"]=1
    approve(c)
    assert "timeout" in run(c).lower()
    from kiss_cli.execution import request_stop
    request_stop(c[1])
    with pytest.raises(api.ToolError, match="Stopped|stopped"):
        run(c)


def test_hardcoded_input_still_has_receipted_file_identity(tmp_path):
    source = CSV_READER.replace("sys.argv[1]", "'inputs/raw.csv'").replace("sys.argv[2]", "'outputs/inspection.json'")
    c = case(tmp_path, source)
    c[3]["steps"][0]["project_data_tool"]["arguments"] = []
    approve(c)
    output = run(c)
    assert output.startswith("exit_code=0"), output
    summary = json.loads(output.splitlines()[1].split("[RECEIPT] ", 1)[1])
    receipt = json.loads(Path(summary["receipt"]).read_text())
    assert any(f["path"] == "inputs/raw.csv" and f["sha256"] == hashlib.sha256(
        (c[1]/"inputs/raw.csv").read_bytes()).hexdigest() for f in receipt["inputs"])


def test_output_root_link_cannot_grant_external_writes(tmp_path):
    c=case(tmp_path); approve(c)
    outside=tmp_path/"external"; outside.mkdir()
    try:
        (c[1]/"outputs").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("host cannot create symbolic links")
    with pytest.raises(api.ToolError, match="escapes|links|outside"):
        run(c)
    assert not list(outside.iterdir())


@pytest.mark.parametrize("body,name", [('{broken', 'bad.json'), ('x,x\n1,2\n','bad.csv'),
                                     ('x,y\n1\n','bad.csv'), ('','empty.txt'), ('{"n":NaN}','bad.json')])
def test_data_structure_validation_rejects_malformed_outputs(tmp_path, body, name):
    output=tmp_path/"outputs"/name; output.parent.mkdir(); output.write_text(body)
    result=project_data_tools.validate_outputs(tmp_path,[output],0)
    assert result["status"] == "failed"
    assert result["model_ready"] is False and result["scientific_validation"] == "not_performed"


def test_data_evidence_projects_scope_and_containment_without_rewriting_receipt(tmp_path):
    c=case(tmp_path); approve(c)
    flow=c[2].flow
    assert flow.receipts.evidence(c[1], c[3], flow.approval.read(c[1]), enforcement="exact")["assurance"] == "containment"
    result=run(c)
    summary=json.loads(result.splitlines()[1].split("[RECEIPT] ", 1)[1])
    receipt_path=Path(summary["receipt"]); original=receipt_path.read_bytes()
    evidence=flow.receipts.evidence(c[1], c[3], flow.approval.read(c[1]), enforcement="exact", inventory=c[4])
    assert evidence["assurance"] == "containment"
    assert evidence["runs"][0]["execution_scope"] == "project_data_tool"
    assert evidence["runs"][0]["model_executed"] is False
    assert evidence["runs"][0]["step_kind"] == "check"
    assert evidence["steps_passed"] == ["M:read"]
    assert receipt_path.read_bytes() == original
    # Retained trusted-code execution does not regain a cryptographic-wall
    # label merely because a later plan no longer includes that tool.
    later=copy.deepcopy(c[3]); later["steps"] = []
    assert flow.receipts.evidence(c[1], later, flow.approval.read(c[1]), enforcement="exact")["assurance"] == "containment"
