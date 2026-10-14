"""Real isolated KI-reader children and signed receipts; no models/providers."""
from copy import deepcopy
import ast
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace

import pytest

from kiss_cli import api, cli, flowgate
from kiss_cli.catalog import KI
from .test_execution import _project, _execute, _receipt_docs


def helpers():
    flowgate.load()
    from ki_tools_common.flow import stdout_artifacts
    return stdout_artifacts


def approved(tmp_path, monkeypatch, source=None, *, contract=True, maximum=1048576, arguments=None):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    monkeypatch.setenv("GEOFORGE_FLOW_REGISTRY", str(tmp_path / "registry.json"))
    source = source or "import json,sys\nprint(json.dumps({'mean': 2.5, 'count': 2}))\nprint('reader diagnostic',file=sys.stderr)\n"
    ctx = _project(tmp_path, source=source)
    ctx.flow.request_replan("Review the explicit reader output")
    step = ctx.plan["steps"][0]
    step.update(kind="check", command=list(arguments or []), outputs=["readout"], cwd=".")
    if contract:
        step["stdout_artifact"] = {"version": 1, "output_id": "readout", "path": "outputs/check/readout.json",
                                   "format": "json_v1", "max_bytes": maximum}
    ctx.inventory["items"].append({"id": "readout", "required_by": ["M"], "status": "missing",
        "acceptable_sources": ["reviewed reader stdout"], "local_paths": ["outputs/check/readout.json"],
        "agent_resolvable": True, "needs_user": False, "decision": "Produced by the approved reader"})
    assert ctx.flow.write_plan(ctx.plan, ctx.inventory) == []
    ctx.flow.flow.approval.approve(ctx.project, by="auto")
    ctx.flow.reload_artifacts()
    ctx.flow.move("plan_written", {"plan_valid": True})
    ctx.flow.move("approved", {"approval": "OK"})
    ctx.flow.move("execution_started", {"setup_verified": True})
    return ctx


@pytest.mark.parametrize("route", ["shared", "api", "cli"])
def test_real_stdout_reader_completes_through_all_provider_seams(tmp_path, monkeypatch, capsys, route):
    ctx = approved(tmp_path, monkeypatch)
    if route == "shared":
        result = _execute(ctx)
        assert result.status == "succeeded" and result.receipt["validation"] == "passed"
    elif route == "api":
        result = api.execute_tool("run_ki_tool", {"tool_path": "tools/run.py", "ki": "M",
            "plan_step_id": "M:run", "arguments": []}, KI("M", ctx.root), ctx.cfg,
            project_mode=True, flow=ctx.flow)
        assert result.startswith("exit_code=0")
    else:
        assert cli.cmd_run_tool(SimpleNamespace(project=str(ctx.project), ki="M", tool="tools/run.py",
            step="M:run", argv=[], root=None)) == 0
        assert "mean" in capsys.readouterr().out
    path = ctx.project / "outputs/check/readout.json"
    assert json.loads(path.read_text()) == {"mean": 2.5, "count": 2}
    assert "diagnostic" not in path.read_text()
    receipt = _receipt_docs(ctx)[-1]
    assert receipt["execution_scope"] == "ki_check_stdout_artifact" and receipt["model_executed"] is False
    assert receipt["validation"]["scope"] == "ki_check_stdout_artifact"
    assert receipt["validation"]["model_execution_evidence"] is False
    evidence = ctx.flow.evidence()
    assert evidence["receipts_verified"] is True
    assert evidence["runs"][-1]["execution_scope"] == "ki_check_stdout_artifact"
    assert evidence["runs"][-1]["model_executed"] is False
    assert receipt["stdout_artifact"]["contract"] == ctx.plan["steps"][0]["stdout_artifact"]


def test_full_stdout_utf8_is_not_the_truncated_combined_ui_tail(tmp_path, monkeypatch):
    source = "import json,sys\nsys.stdout.buffer.write(json.dumps({'text':'\\u4e2d'*22000,'value':2},ensure_ascii=False).encode('utf-8'))\nsys.stderr.write('DIAGNOSTIC')\n"
    ctx = approved(tmp_path, monkeypatch, source)
    result = _execute(ctx)
    assert result.receipt["validation"] == "passed"
    path = ctx.project / "outputs/check/readout.json"
    assert json.loads(path.read_text(encoding="utf-8"))["text"] == "中" * 22000
    assert path.stat().st_size > 20_000 and "DIAGNOSTIC" not in path.read_text(encoding="utf-8")


def test_real_csv_reader_captures_result_and_consumed_input_identity(tmp_path, monkeypatch):
    source = "import csv,json,sys\nwith open(sys.argv[1],newline='') as f:\n values=[float(r['value']) for r in csv.DictReader(f)]\nprint(json.dumps({'count':len(values),'mean':sum(values)/len(values)}))\n"
    ctx = approved(tmp_path, monkeypatch, source, arguments=["inputs/series.csv"])
    path = ctx.project / "inputs/series.csv";path.parent.mkdir();path.write_text("day,value\n1,2\n2,3\n")
    result = _execute(ctx, arguments=["inputs/series.csv"])
    assert result.receipt["validation"] == "passed"
    assert json.loads((ctx.project / "outputs/check/readout.json").read_text()) == {"count":2,"mean":2.5}
    receipt = _receipt_docs(ctx)[-1]
    assert receipt["inputs"][0]["path"] == "inputs/series.csv"
    assert receipt["inputs"][0]["sha256"]


def test_no_contract_keeps_stdout_only_check_failed(tmp_path, monkeypatch):
    ctx = approved(tmp_path, monkeypatch, contract=False)
    result = _execute(ctx)
    assert result.exit_code == 0 and result.receipt["validation"] == "failed"
    assert result.receipt["outputs"] == []
    assert ctx.flow.evidence()["receipts_verified"] is False


@pytest.mark.parametrize("text", ["", "noise\n{}", "{}", "[]", "42", '{"x":NaN}', '{"x":Infinity}',
    '{"x":1e999}', '{"x":1,"x":2}', '{"x":{"y":1,"y":2}}', '{"text":"' + 'a'*300 + '"}'])
def test_real_invalid_stdout_never_publishes_or_passes(tmp_path, monkeypatch, text):
    ctx = approved(tmp_path, monkeypatch, "import sys\nsys.stdout.write(" + repr(text) + ")\n", maximum=256)
    result = _execute(ctx)
    assert result.exit_code == 0 and result.receipt["validation"] == "failed"
    assert not (ctx.project / "outputs/check/readout.json").exists()
    assert ctx.flow.evidence()["receipts_verified"] is False


@pytest.mark.parametrize("source,timeout", [
    ("import sys\nprint('{\"value\":2}')\nsys.exit(7)\n", None),
    ("import time\nprint('{\"value\":2}',flush=True)\ntime.sleep(5)\n", .1),
    ("import sys\nsys.stdout.buffer.write(b'{\"text\":\"\\xff\"}')\n", None),
])
def test_failed_timeout_and_invalid_utf8_keep_failed_receipt(tmp_path, monkeypatch, source, timeout):
    ctx = approved(tmp_path, monkeypatch, source)
    result = _execute(ctx, timeout=timeout)
    assert result.receipt["validation"] == "failed"
    if "\\xff" not in source:
        assert result.status != "succeeded"
    assert not (ctx.project / "outputs/check/readout.json").exists()
    assert ctx.flow.evidence()["receipts_verified"] is False


@pytest.mark.parametrize("change", ["args", "cwd", "existing", "child_collision"])
def test_invocation_and_fresh_destination_are_enforced(tmp_path, monkeypatch, change):
    source = None
    if change == "child_collision":
        source = "from pathlib import Path\np=Path('outputs/check/readout.json');p.parent.mkdir(parents=True);p.write_text('{\"foreign\":1}')\nprint('{\"value\":2}')\n"
    ctx = approved(tmp_path, monkeypatch, source)
    path = ctx.project / "outputs/check/readout.json"
    kwargs = {}
    if change == "args": kwargs["arguments"] = ["different.csv"]
    if change == "cwd":
        child = ctx.project / "subdir";child.mkdir();kwargs["cwd"] = child
    if change == "existing":
        path.parent.mkdir(parents=True);path.write_text('{"old":1}')
    if change == "child_collision":
        result = _execute(ctx)
        assert result.receipt["validation"] == "failed"
        assert json.loads(path.read_text()) == {"foreign":1}
    else:
        with pytest.raises(flowgate.FlowDenied, match="invocation|fresh"):
            _execute(ctx, **kwargs)
        assert not _receipt_docs(ctx)
    assert ctx.flow.evidence()["receipts_verified"] is False


@pytest.mark.parametrize("kind", ["run", "model_run", "route", "calibrate", "prepare", "process"])
def test_contract_cannot_be_model_evidence(tmp_path, monkeypatch, kind):
    ctx = approved(tmp_path, monkeypatch)
    step = deepcopy(ctx.plan["steps"][0]);step["kind"] = kind
    assert helpers().step_errors(step, ctx.project, ctx.inventory)


@pytest.mark.parametrize("damage", ["path", "id", "inventory", "max_bool", "version_bool", "format", "adapter", "input"])
def test_contract_rejects_ambiguous_or_unsafe_bindings(tmp_path, monkeypatch, damage):
    ctx = approved(tmp_path, monkeypatch)
    step, inventory = deepcopy(ctx.plan["steps"][0]), deepcopy(ctx.inventory)
    binding = step["stdout_artifact"]
    if damage == "path": binding["path"] = "outputs/../inputs/raw.json"
    if damage == "id": binding["output_id"] = "absent"
    if damage == "inventory": inventory["items"][-1]["local_paths"] = ["outputs/wrong.json"]
    if damage == "max_bool": binding["max_bytes"] = True
    if damage == "version_bool": binding["version"] = True
    if damage == "format": binding["format"] = "text"
    if damage == "adapter": step["project_data_tool"] = {}
    if damage == "input": step["inputs"].append("readout")
    assert helpers().step_errors(step, ctx.project, inventory)


def test_current_receipt_rejects_file_contract_and_policy_drift(tmp_path, monkeypatch):
    ctx = approved(tmp_path, monkeypatch)
    assert _execute(ctx).receipt["validation"] == "passed"
    receipt = _receipt_docs(ctx)[-1]
    module = helpers()
    assert module.receipt_errors(ctx.project, ctx.plan["steps"][0], ctx.inventory, receipt) == []
    broken = deepcopy(receipt);broken.pop("stdout_artifact")
    assert module.receipt_errors(ctx.project, ctx.plan["steps"][0], ctx.inventory, broken)
    with monkeypatch.context() as patch:
        patch.setattr(module, "source_digest", lambda: "0"*64)
        assert ctx.flow.evidence()["receipts_verified"] is False
    (ctx.project / "outputs/check/readout.json").write_text('{"changed":99}')
    assert module.receipt_errors(ctx.project, ctx.plan["steps"][0], ctx.inventory, receipt)


def test_real_stop_keeps_cancelled_attempt_without_capture(tmp_path, monkeypatch):
    ctx = approved(tmp_path, monkeypatch, "import time\nprint('{\"x\":1}',flush=True)\ntime.sleep(10)\n")
    started = time.monotonic()
    result = _execute(ctx, stop=lambda: time.monotonic() - started > .3)
    assert result.status == "stopped" and result.receipt["validation"] == "stopped"
    assert not (ctx.project / "outputs/check/readout.json").exists()
    assert ctx.flow.evidence()["receipts_verified"] is False


def test_child_approval_change_cannot_publish_stdout(tmp_path, monkeypatch):
    source = "from pathlib import Path\nPath('runs/plan.json').write_text('{}')\nprint('{\"x\":1}')\n"
    ctx = approved(tmp_path, monkeypatch, source)
    result = _execute(ctx)
    assert result.receipt is None and result.receipt_error
    assert not (ctx.project / "outputs/check/readout.json").exists()


def test_child_ki_change_cannot_publish_stdout(tmp_path, monkeypatch):
    source = "from pathlib import Path\nPath(__file__).write_text('# changed')\nprint('{\"x\":1}')\n"
    ctx = approved(tmp_path, monkeypatch, source)
    result = _execute(ctx)
    assert result.status == "failed"
    assert not (ctx.project / "outputs/check/readout.json").exists()
    assert not result.receipt or result.receipt["validation"] == "failed"


def test_hardlink_output_and_inventory_input_collision_reject(tmp_path, monkeypatch):
    ctx = approved(tmp_path, monkeypatch)
    source = ctx.project / "inputs/raw.json";source.parent.mkdir();source.write_text('{"raw":1}')
    target = ctx.project / "outputs/check/readout.json";target.parent.mkdir(parents=True)
    os.link(source, target)
    assert helpers().step_errors(ctx.plan["steps"][0], ctx.project, ctx.inventory)
    target.unlink()
    inventory = deepcopy(ctx.inventory)
    inventory["items"][0]["local_paths"] = ["outputs/check/readout.json"]
    assert helpers().step_errors(ctx.plan["steps"][0], ctx.project, inventory)


def test_alias_parent_destination_rejects(tmp_path, monkeypatch):
    ctx = approved(tmp_path, monkeypatch)
    (ctx.project / "outputs").mkdir()
    elsewhere = tmp_path / "elsewhere";elsewhere.mkdir()
    try:
        (ctx.project / "outputs/check").symlink_to(elsewhere, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"OS does not permit fixture symlinks: {error}")
    with pytest.raises(flowgate.FlowDenied, match="aliases"):
        _execute(ctx)
    assert not list(elsewhere.iterdir())


def test_new_failed_attempt_cannot_fall_back_to_earlier_pass(tmp_path, monkeypatch):
    source = "from pathlib import Path\nprint('not JSON' if Path('inputs/fail').exists() else '{\"x\":1}')\n"
    ctx = approved(tmp_path, monkeypatch, source)
    assert _execute(ctx).receipt["validation"] == "passed"
    (ctx.project / "outputs/check/readout.json").unlink()
    (ctx.project / "inputs").mkdir();(ctx.project / "inputs/fail").touch()
    assert _execute(ctx).receipt["validation"] == "failed"
    proof = ctx.flow.evidence()
    assert proof["validation"] == "failed" and not proof["receipts_verified"]


def test_receipt_invocation_and_legacy_missing_proof_reject(tmp_path, monkeypatch):
    ctx = approved(tmp_path, monkeypatch)
    assert _execute(ctx).receipt["validation"] == "passed"
    original = _receipt_docs(ctx)[-1]
    for field, value in (("command", [str(ctx.cfg.python),str(ctx.tool),'other.csv']),
                         ("cwd", str(tmp_path)), ("stdout_artifact", None),
                         ("execution_scope", "model_run"), ("model_executed", True)):
        receipt = deepcopy(original);receipt[field] = value
        assert helpers().receipt_errors(ctx.project, ctx.plan["steps"][0], ctx.inventory, receipt)


@pytest.mark.parametrize("change", ["step", "input_inventory", "output_inventory"])
def test_full_reviewed_binding_drift_rejects_current_stdout_receipt(tmp_path, monkeypatch, change):
    ctx = approved(tmp_path, monkeypatch)
    assert _execute(ctx).receipt["validation"] == "passed"
    receipt = _receipt_docs(ctx)[-1]
    step, inventory = deepcopy(ctx.plan["steps"][0]), deepcopy(ctx.inventory)
    if change == "step": step["note"] = "Different reviewed requirement"
    elif change == "input_inventory": inventory["items"][0]["decision"] = "Different reviewed forcing source"
    else: inventory["items"][-1]["decision"] = "Different reviewed output"
    assert helpers().receipt_errors(ctx.project, step, inventory, receipt)


def test_stdout_module_is_required_by_bundled_startup(monkeypatch):
    original = flowgate.importlib.import_module
    def importing(name, *args, **kwargs):
        if name == "ki_tools_common.flow.stdout_artifacts":
            raise ImportError("stdout artifact validator missing")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(flowgate.importlib, "import_module", importing)
    with pytest.raises(flowgate.FlowUnavailable, match="stdout artifact validator missing"):
        flowgate.load()


@pytest.mark.parametrize("name", ["KISS.spec", "GeoForgeDesktop.spec", "GeoForgeDesktopWindows.spec"])
def test_all_desktop_specs_include_stdout_validator_in_analysis(name):
    source = Path(__file__).resolve().parents[1]
    tree = ast.parse((source / name).read_text(encoding="utf-8"))
    hidden = next(ast.literal_eval(node.value) for node in tree.body
                  if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "harness_hidden" for target in node.targets))
    assert "ki_tools_common.flow.stdout_artifacts" in hidden
    analysis = next(node for node in ast.walk(tree) if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name) and node.func.id == "Analysis")
    hidden_imports = next(kw.value for kw in analysis.keywords if kw.arg == "hiddenimports")
    assert any(isinstance(node, ast.Name) and node.id == "harness_hidden" for node in ast.walk(hidden_imports))
