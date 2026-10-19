"""Host stdin contract fixtures, including real harmless child processes.

The declared fixture executable is replaced at the transport seam by a Python
byte echo child. No scientific model or provider is invoked.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

import pytest

from kiss_cli import api, cli, execution, flowgate, ki_guard, native_stdin, paths, project_verification
from kiss_cli.catalog import KI
from kiss_cli.manifest import Manifest


def case(tmp_path, monkeypatch, text="Trial.inp\r\n\r\n", *, approve=True, dependent=False):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    monkeypatch.setenv("GEOFORGE_FLOW_REGISTRY", str(tmp_path / "registry.json"))
    project = tmp_path / "project"
    root = project / "models/M/ki"
    (root / "tools").mkdir(parents=True)
    (project / "runs").mkdir()
    (project / "work").mkdir()
    control = project / "work/Trial.inp"
    control.write_bytes(b"unchanged native control\n")
    binary = project / "fixture_engine.exe"
    binary.write_bytes(b"MZ harmless fixture; transport replaced in tests")
    binary.chmod(0o755)
    (root / "SKILL.md").write_text("# Synthetic native fixture\n")
    (root / "knowledge_infrastructure.yaml").write_text(
        "model:\n  binary:\n    path: " + json.dumps(str(binary)) + "\n")
    (root / "preflight_check.py").write_text("print('harmless preflight')\n")
    reader = root / "tools/read.py"
    reader.write_text("print('harmless downstream reader')\n")
    cfg = paths.KissConfig.default(project)
    cfg.python = sys.executable
    (project / paths.CONFIG_NAME).write_text(cfg.dumps(), encoding="utf-8")
    (root.parent / paths.CONFIG_NAME).write_text(cfg.dumps(), encoding="utf-8")
    ki_guard.enroll(root)
    ki = KI("M", root)
    assert project_verification.verify(project, ki, Manifest(model="M"))["ok"]
    flow = flowgate.FlowSession.open(project, {"M": root}, python=sys.executable)
    flow.move("task_received")
    flow.move("kis_resolved", {"selected_kis": ["M"]})
    step = {"id": "M:run", "ki": "M", "tool": str(binary), "kind": "check", "command": [],
            "cwd": "work", "inputs": ["control"], "outputs": ["report"], "status": "planned"}
    if text is not None:
        step["stdin"] = {"text": text}
    plan = {"schema_version": "1.0", "goal": "Harmless native stdin fixture", "selected_kis": ["M"],
            "created_at": "fixture", "unresolved_questions": [], "scientific_choices": [], "steps": [step]}
    def item(ident, location, status):
        return {"id": ident, "required_by": ["M"], "local_paths": [location], "status": status,
                "acceptable_sources": ["fixture"], "chosen_source": "fixture",
                "needs_user": False, "agent_resolvable": True}
    inventory = {"schema_version": "1.0", "items": [item("control", "work/Trial.inp", "resolved"),
        {**item("report", "outputs/result.json", "missing"), "output_validation": "json_report_v1"}]}
    if dependent:
        plan["steps"].append({"id": "M:read", "ki": "M", "tool": str(reader), "kind": "check",
            "command": [], "cwd": ".", "inputs": ["report"], "outputs": [], "status": "planned"})
    if approve:
        assert flow.write_plan(plan, inventory) == []
        flow.flow.approval.approve(project, by="user")
        flow.reload_artifacts()
        flow.move("plan_written", {"plan_valid": True})
        flow.move("approved", {"approval": "OK"})
        flow.move("execution_started", {"setup_verified": True})
    return SimpleNamespace(project=project, root=root, binary=binary, cfg=cfg, ki=ki,
                           flow=flow, step=step, plan=plan, inventory=inventory, control=control)


def transport(c, monkeypatch, *, code=0, delay=0, long_log=False):
    original = execution.run_process
    script = ("import sys,time,json\nfrom pathlib import Path\n"
              "data=sys.stdin.buffer.read()\n"
              "p=Path('../outputs');p.mkdir(exist_ok=True)\n"
              "(p/'result.json').write_text(json.dumps({'ok':True,'stdin_hex':data.hex()}))\n"
              f"print({'x' * 24000!r} if {long_log!r} else 'child stdout')\n"
              "print('child stderr',file=sys.stderr)\n"
              f"time.sleep({delay!r})\nsys.exit({code!r})\n")
    def run(command, **kwargs):
        assert command == [str(c.binary)]
        return original([sys.executable, "-c", script], **kwargs)
    monkeypatch.setattr(execution, "run_process", run)


def invoke(c, route="shared", **overrides):
    if route == "api":
        return api.execute_tool("run_ki_tool", {"tool_path": str(c.binary), "ki": "M",
            "plan_step_id": "M:run", "arguments": [], "cwd": "work", **overrides},
            c.ki, c.cfg, project_mode=True, flow=c.flow)
    if route == "cli":
        return cli.cmd_run_tool(SimpleNamespace(project=str(c.project), ki="M", tool=str(c.binary),
            step="M:run", argv=[], root=None))
    return execution.execute_ki_tool(flow=c.flow, cfg=c.cfg, project=c.project, ki="M", ki_root=c.root,
        tool=c.binary, arguments=[], cwd=c.project / "work", plan_step_id="M:run", python_tool=False,
        **overrides)


def receipts(c):
    return [(p, json.loads(p.read_text(encoding="utf-8")))
            for p in (c.project / ".geoforge/receipts/model-runs").glob("*.json")]


@pytest.mark.parametrize("route", ["shared", "api", "cli"])
def test_real_child_exact_stdin_shared_api_cli_and_full_signed_logs(tmp_path, monkeypatch, route):
    c = case(tmp_path, monkeypatch)
    transport(c, monkeypatch, long_log=True)
    invoke(c, route)
    assert json.loads((c.project / "outputs/result.json").read_text())["stdin_hex"] == c.step["stdin"]["text"].encode().hex()
    _, doc = receipts(c)[0]
    assert c.flow.flow.receipts.verify(c.project, doc)
    assert doc["input_coverage"]["native_stdin"]["sha256"] == hashlib.sha256(b"Trial.inp\r\n\r\n").hexdigest()
    assert doc["input_coverage"]["native_stdin"]["input_files"] == ["work/Trial.inp"]
    assert Path(doc["stdout_log"]).read_text() == "x" * 24000 + "\n"
    assert Path(doc["stderr_log"]).read_text() == "child stderr\n"
    assert native_stdin.receipt_errors(c.project, c.step, c.inventory, doc) == []
    proof = c.flow.evidence()
    assert proof["receipts_verified"] and proof["steps_passed"] == ["M:run"], proof


@pytest.mark.parametrize("text", ["", "1\nY\n\n", "-1.25D+2\r\n", "Trial.inp\n"])
def test_empty_numeric_menu_and_lf_are_exact(tmp_path, monkeypatch, text):
    c = case(tmp_path, monkeypatch, text)
    transport(c, monkeypatch)
    invoke(c)
    assert json.loads((c.project / "outputs/result.json").read_text())["stdin_hex"] == text.encode().hex()


@pytest.mark.parametrize("payload", [None, {}, {"text": 2}, {"text": "x", "extra": 1},
    {"text": "x" * 4097}, {"text": "\ud800"}, {"text": "x\0"}, {"text": "\t"},
    {"text": "${PROJECT}/case"}, {"text": "../outside.inp\n"}, {"text": "C:/secret\n"},
    {"text": "/secret\n"}, {"text": "Trial.inp other\n"}, {"text": "missing.inp\n"}])
def test_invalid_binding_rejected_before_review_and_dispatch(tmp_path, monkeypatch, payload):
    c = case(tmp_path, monkeypatch, approve=False)
    c.step["stdin"] = payload
    assert native_stdin.plan_errors(c.plan, c.inventory, c.project, {"M": c.root})
    assert c.flow.write_plan(c.plan, c.inventory)
    assert not (c.project / "runs/plan.json").exists()


@pytest.mark.parametrize("change", ["python", "adapter", "calibration", "no_command", "no_cwd", "no_tool", "interpreter"])
def test_only_explicit_declared_native_steps(tmp_path, monkeypatch, change):
    c = case(tmp_path, monkeypatch, approve=False)
    if change == "python": c.step["tool"] = str(c.root / "preflight_check.py")
    elif change == "adapter": c.step["project_data_tool"] = {}
    elif change == "calibration": c.step["calibration"] = {}
    elif change == "interpreter": c.step["tool"] = sys.executable
    else: c.step.pop({"no_command": "command", "no_cwd": "cwd", "no_tool": "tool"}[change])
    assert native_stdin.plan_errors(c.plan, c.inventory, c.project, {"M": c.root})


def test_future_inventoried_file_reviewable_but_missing_dispatch_refused(tmp_path, monkeypatch):
    c = case(tmp_path, monkeypatch)
    c.control.unlink()
    assert native_stdin.plan_errors(c.plan, c.inventory, c.project, {"M": c.root}) == []
    monkeypatch.setattr(execution, "run_process", lambda *a, **k: pytest.fail("must not launch"))
    with pytest.raises(flowgate.FlowDenied, match="does not exist"):
        invoke(c)


def test_unicode_filename_exact_utf8_and_input_hash(tmp_path, monkeypatch):
    c = case(tmp_path, monkeypatch, approve=False)
    target = c.control.with_name("输入.inp")
    c.control.rename(target)
    c.inventory["items"][0]["local_paths"] = ["work/输入.inp"]
    c.step["stdin"] = {"text": "输入.inp\r\n"}
    bound = native_stdin.binding(c.step, c.project, c.root, c.inventory, for_execution=True)
    assert bound["bytes"] == len("输入.inp\r\n".encode())
    with tempfile.TemporaryFile(mode="w+b") as stream:
        stream.write(bound["text"].encode()); stream.seek(0)
        result = execution.run_process([sys.executable, "-c", "import sys;print(sys.stdin.buffer.read().hex())"],
            cwd=c.project, env=os.environ.copy(), timeout=10, stdin=stream)
    assert result.stdout.strip() == bound["text"].encode().hex()


@pytest.mark.parametrize("change", ["missing", "hash", "text", "input_files", "log", "log_bytes"])
def test_authentic_missing_or_changed_binding_never_completes(tmp_path, monkeypatch, change):
    c = case(tmp_path, monkeypatch)
    transport(c, monkeypatch)
    invoke(c)
    path, doc = receipts(c)[0]
    if change == "missing": doc["input_coverage"].pop("native_stdin")
    elif change == "hash": doc["input_coverage"]["native_stdin"]["sha256"] = "0" * 64
    elif change == "text": doc["input_coverage"]["native_stdin"]["text"] = "N\n"
    elif change == "input_files": doc["input_coverage"]["native_stdin"]["input_files"] = []
    elif change == "log": doc["input_coverage"].pop("native_stdio_logs")
    elif change == "log_bytes": Path(doc["stdout_log"]).write_text("changed")
    path.write_text(json.dumps(c.flow.flow.receipts.sign(c.project, doc)), encoding="utf-8")
    proof = c.flow.evidence()
    assert not proof["receipts_verified"] and "M:run" not in proof["steps_passed"]
    assert proof["runs"][0]["validation"] == "failed"
    assert proof["current_failures"]


@pytest.mark.parametrize("code,delay,timeout,expected", [(7, 0, 10, "failed"), (0, 2, .1, "timed_out")])
def test_real_child_nonzero_and_timeout_keep_stdin_and_failure_receipts(tmp_path, monkeypatch, code, delay, timeout, expected):
    c = case(tmp_path, monkeypatch)
    transport(c, monkeypatch, code=code, delay=delay)
    result = invoke(c, timeout=timeout)
    assert result.status == expected
    doc = receipts(c)[0][1]
    assert doc["input_coverage"]["native_stdin"]["text"] == c.step["stdin"]["text"]
    assert not c.flow.evidence()["receipts_verified"]


def test_no_stdin_keeps_existing_closed_input_default(tmp_path, monkeypatch):
    c = case(tmp_path, monkeypatch, text=None)
    transport(c, monkeypatch)
    invoke(c)
    assert json.loads((c.project / "outputs/result.json").read_text())["stdin_hex"] == ""
    assert "native_stdin" not in receipts(c)[0][1]["input_coverage"]


def test_stdin_write_failure_cannot_launch_or_sign(tmp_path, monkeypatch):
    c = case(tmp_path, monkeypatch)
    monkeypatch.setattr(execution.tempfile, "TemporaryFile", lambda **k: (_ for _ in ()).throw(OSError("disk failure")))
    monkeypatch.setattr(execution, "run_process", lambda *a, **k: pytest.fail("must not launch"))
    with pytest.raises(flowgate.FlowDenied, match="no process was launched"):
        invoke(c)
    assert receipts(c) == []


def test_api_cannot_override_plan_stdin(tmp_path, monkeypatch):
    c = case(tmp_path, monkeypatch)
    monkeypatch.setattr(execution, "run_process", lambda *a, **k: pytest.fail("must not launch"))
    with pytest.raises(api.ToolError, match="stdin"):
        invoke(c, "api", stdin={"text": "different.inp\n"}, stdin_text="different.inp\n")
    assert receipts(c) == []


def test_changed_approved_stdin_invalidates_approval_before_launch(tmp_path, monkeypatch):
    c = case(tmp_path, monkeypatch)
    changed = copy.deepcopy(c.plan)
    changed["steps"][0]["stdin"]["text"] = "N\n"
    c.flow.flow.plan.write_artifacts(c.project, changed, c.inventory)
    c.flow.reload_artifacts()
    monkeypatch.setattr(execution, "run_process", lambda *a, **k: pytest.fail("must not launch"))
    with pytest.raises(flowgate.FlowDenied, match="approval"):
        invoke(c)
    assert receipts(c) == []


@pytest.mark.parametrize("mode", ["hardlink", "undeclared", "directory", "shell"])
def test_filename_and_executable_authority_is_narrow(tmp_path, monkeypatch, mode):
    c = case(tmp_path, monkeypatch, approve=False)
    if mode == "hardlink":
        alias = c.control.with_name("alias.inp")
        alias.hardlink_to(c.control)
    elif mode == "undeclared":
        c.step["inputs"] = []
    elif mode == "directory":
        c.inventory["items"][0]["local_paths"] = ["work"]
    else:
        shell = c.project / "script.sh"
        shell.write_text("#!/bin/sh\nexit 0\n")
        shell.chmod(0o755)
        (c.root / "knowledge_infrastructure.yaml").write_text("binary:\n  path: " + json.dumps(str(shell)))
        c.step["tool"] = str(shell)
    assert native_stdin.plan_errors(c.plan, c.inventory, c.project, {"M": c.root})


def test_stdin_failure_invalidates_downstream_pass_without_resurrecting_old_receipt(tmp_path, monkeypatch):
    c = case(tmp_path, monkeypatch)
    transport(c, monkeypatch)
    invoke(c)
    path, doc = receipts(c)[0]
    doc["input_coverage"].pop("native_stdin")
    path.write_text(json.dumps(c.flow.flow.receipts.sign(c.project, doc)), encoding="utf-8")
    # Keep the actual signed upstream receipt; isolate only the existing shared
    # summary to demonstrate that the Desktop extension revokes a dependent pass.
    plan = copy.deepcopy(c.plan)
    plan["steps"].append({"id": "M:read", "ki": "M", "inputs": ["report"], "outputs": [], "tool": "reader.py"})
    original = c.flow.flow.receipts.evidence
    def summary(*args, **kwargs):
        result = original(*args, **kwargs)
        result["steps_passed"] = ["M:run", "M:read"]
        result["receipts_verified"] = True
        return result
    monkeypatch.setattr(c.flow.flow.receipts, "evidence", summary)
    proof = native_stdin.evidence(c.flow.flow, c.project, plan, c.flow.approval_doc, inventory=c.inventory)
    assert not proof["steps_passed"] and set(proof["steps_missing"]) == {"M:run", "M:read"}
    assert not proof["receipts_verified"]


def test_stop_before_stdin_launch_creates_no_receipt(tmp_path, monkeypatch):
    c = case(tmp_path, monkeypatch)
    monkeypatch.setattr(execution, "run_process", lambda *a, **k: pytest.fail("must not launch"))
    with pytest.raises(flowgate.FlowDenied, match="stopped"):
        invoke(c, stop=lambda: True)
    assert receipts(c) == []


def test_exact_inventoried_filename_with_spaces_is_literal(tmp_path, monkeypatch):
    c = case(tmp_path, monkeypatch, approve=False)
    target = c.control.with_name("My Trial.inp")
    c.control.rename(target)
    c.inventory["items"][0]["local_paths"] = ["work/My Trial.inp"]
    c.step["stdin"] = {"text": "My Trial.inp\r\n\n"}
    bound = native_stdin.binding(c.step, c.project, c.root, c.inventory, for_execution=True)
    assert bound["input_files"] == ["work/My Trial.inp"]
    with tempfile.TemporaryFile(mode="w+b") as stream:
        stream.write(bound["text"].encode()); stream.seek(0)
        result = execution.run_process([sys.executable, "-c", "import sys;print(sys.stdin.buffer.read().hex())"],
            cwd=c.project, env=os.environ.copy(), timeout=10, stdin=stream)
    assert result.stdout.strip() == bound["text"].encode().hex()


def test_actual_dependency_admission_refuses_missing_stdin_receipt(tmp_path, monkeypatch):
    c = case(tmp_path, monkeypatch, dependent=True)
    transport(c, monkeypatch)
    invoke(c)
    reader = c.root / "tools/read.py"
    assert c.flow.check_step_tool("M:read", "M", reader)["id"] == "M:read"
    path, doc = receipts(c)[0]
    doc["input_coverage"].pop("native_stdin")
    path.write_text(json.dumps(c.flow.flow.receipts.sign(c.project, doc)), encoding="utf-8")
    monkeypatch.setattr(execution, "run_process", lambda *a, **k: pytest.fail("must not launch dependent"))
    with pytest.raises(flowgate.FlowDenied, match="without current passed receipts"):
        execution.execute_ki_tool(flow=c.flow, cfg=c.cfg, project=c.project, ki="M", ki_root=c.root,
            tool=reader, arguments=[], cwd=c.project, plan_step_id="M:read", python_tool=True)


def test_trusted_legacy_ki_root_can_be_supplied_for_evidence(tmp_path, monkeypatch):
    c = case(tmp_path, monkeypatch)
    transport(c, monkeypatch)
    invoke(c)
    doc = receipts(c)[0][1]
    other = tmp_path / "legacy-ki"
    import shutil
    shutil.copytree(c.root, other)
    assert native_stdin.receipt_errors(c.project, c.step, c.inventory, doc, ki_root=other) == []
