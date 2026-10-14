"""Harmless real API dispatches exercise current evidence, not model validity."""
import json
import sys
from types import SimpleNamespace

import pytest

from kiss_cli import api, execution, flowgate, flowrun, ki_guard, paths, project_verification
from kiss_cli.catalog import KI
from kiss_cli.manifest import Manifest


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    monkeypatch.setenv("GEOFORGE_FLOW_REGISTRY", str(tmp_path / "registry"))
    project = tmp_path / "project"
    root = project / "models/M/ki"
    (root / "tools").mkdir(parents=True)
    (project / "inputs").mkdir()
    (project / "runs").mkdir()
    (project / "inputs/source.csv").write_text("day,value\n1,2\n2,4\n", encoding="utf-8")
    (root / "SKILL.md").write_text("# Harmless evidence fixture\n", encoding="utf-8")
    (root / "dag.yaml").write_text("outputs: []\n", encoding="utf-8")
    (root / "preflight_check.py").write_text("print('Harmless preflight')\n", encoding="utf-8")
    tool = root / "tools/derive.py"
    tool.write_text(
        "import csv,sys\nfrom pathlib import Path\n"
        "source=Path('inputs/default/source.csv') if sys.argv[1]=='--default' else Path(sys.argv[1])\n"
        "with source.open(encoding='utf-8') as f: rows=list(csv.DictReader(f))\n"
        "if '--mutate-source' in sys.argv: source.write_text('day,value\\n1,9\\n2,4\\n',encoding='utf-8')\n"
        "for row in rows: row['value']=float(row['value'])*2\n"
        "dest=Path(sys.argv[2]);dest.parent.mkdir(parents=True,exist_ok=True)\n"
        "with dest.open('w',newline='',encoding='utf-8') as f:\n"
        " w=csv.DictWriter(f,fieldnames=['day','value']);w.writeheader();w.writerows(rows)\n",
        encoding="utf-8")
    cfg = paths.KissConfig.default(project)
    cfg.python = sys.executable
    for config in (project / paths.CONFIG_NAME, root.parent / paths.CONFIG_NAME):
        config.write_text(cfg.dumps(), encoding="utf-8")
    ki_guard.enroll(root)
    ki = KI("M", root)
    assert project_verification.verify(project, ki, Manifest(model="M"))["ok"]
    fs = flowgate.FlowSession.open(project, {"M": root}, python=sys.executable)
    fs.move("task_received")
    fs.move("kis_resolved", {"selected_kis": ["M"]})
    steps = [{"id": sid, "ki": "M", "kind": "process", "tool": str(tool),
              "command": args, "cwd": ".", "inputs": [inp], "outputs": [out], "status": "planned"}
             for sid, inp, out, args in (
                 ("produce", "source", "middle", ["inputs/source.csv", "outputs/middle.csv"]),
                 ("consume", "middle", "result", ["outputs/middle.csv", "outputs/result.csv"]))]
    plan = {"schema_version": "1.0", "goal": "Derive and inspect fixture data", "created_at": "test",
            "selected_kis": ["M"], "scientific_choices": [], "unresolved_questions": [], "steps": steps}
    inv = {"schema_version": "1.0", "items": [
        {"id": ident, "status": "ready" if ident == "source" else "missing", "local_paths": [path]}
        for ident, path in (("source", "inputs/source.csv"), ("middle", "outputs/middle.csv"),
                            ("result", "outputs/result.csv"))]}
    assert fs.write_plan(plan, inv) == []
    fs.flow.approval.approve(project, by="user")
    fs.reload_artifacts()
    fs.move("plan_written", {"plan_valid": True})
    fs.move("approved", {"approval": "OK"})
    fs.move("execution_started", {"setup_verified": True})
    execution.begin_turn(project)
    turn = flowrun.Turn(fs, True, "", True, SimpleNamespace(provider="api"), "fixture",
                        kind="execution", provider_succeeded=True, started_at=1)
    return SimpleNamespace(project=project, root=root, cfg=cfg, ki=ki, fs=fs, turn=turn)


def approve(c):
    c.fs.flow.plan.write_artifacts(c.project, c.fs.plan, c.fs.inventory)
    c.fs.flow.approval.approve(c.project, by="user")
    c.fs.reload_artifacts()


def run(c, sid):
    step = next(s for s in c.fs.plan["steps"] if s["id"] == sid)
    answer = api.execute_tool("run_ki_tool", {"tool_path": "tools/derive.py", "plan_step_id": sid,
        "arguments": step["command"]}, c.ki, c.cfg, project_mode=True, flow=c.fs)
    assert '"validation": "passed"' in answer, answer


def receipt_bytes(c):
    return {p: p.read_bytes() for p in (c.project / ".geoforge/receipts/model-runs").glob("*.json")}


@pytest.mark.parametrize("kind", ["read", "analysis", "", None, 0, [], {}])
def test_unknown_or_malformed_kind_is_rejected_and_old_approval_cannot_complete(case, kind):
    c = case
    c.fs.plan["steps"][1]["kind"] = kind
    for flags in ({"for_review": True}, {"for_execution": True}):
        errors = c.fs.flow.plan.validate(c.fs.plan, c.fs.inventory, ["M"], {"M": c.root},
                                         project=c.project, **flags)
        assert any("unknown step kind" in error for error in errors), errors
    # Reconstruct a pre-fix approval: the current evidence gate must also reject it.
    approve(c)
    run(c, "produce")
    evidence = c.fs.evidence()
    assert evidence["plan_errors"] and "consume" in evidence["steps_missing"]
    assert evidence["validation"] == "failed" and not evidence["receipts_verified"]
    with pytest.raises(api.ToolError, match="unknown step kind"):
        run(c, "consume")
    flowrun.after(c.project, c.turn, "Only the first step ran.")
    assert c.fs.state.value != "COMPLETED"
    assert not (c.project / "outputs/result.csv").exists()


@pytest.mark.parametrize("damage", ["changed", "missing"])
def test_changed_or_missing_external_input_stales_real_derived_results_transitively(case, damage):
    c = case
    run(c, "produce")
    run(c, "consume")
    assert "16.0" in (c.project / "outputs/result.csv").read_text(encoding="utf-8")
    assert c.fs.evidence()["receipts_verified"]
    before = receipt_bytes(c)
    source = c.project / "inputs/source.csv"
    original = source.read_bytes()
    if damage == "changed":
        source.write_bytes(original.replace(b"1,2", b"1,9"))  # same length
    else:
        source.unlink()
    evidence = c.fs.evidence()
    assert evidence["stale_steps"] == ["consume", "produce"]
    assert damage in evidence["stale_step_reasons"]["produce"][0]
    assert "Upstream" in evidence["stale_step_reasons"]["consume"][0]
    assert evidence["validation"] == "incomplete" and not evidence["receipts_verified"]
    assert all(r["validation"] == "passed" for r in evidence["runs"])
    assert before == receipt_bytes(c)
    source.write_bytes(original)
    assert c.fs.evidence()["receipts_verified"]  # restored exact bytes support the original run


@pytest.mark.parametrize("damage", ["changed", "missing"])
def test_legacy_symbolic_current_output_must_still_exist_and_match(case, damage):
    c = case
    c.fs.plan["steps"] = c.fs.plan["steps"][:1]
    c.fs.inventory["items"] = c.fs.inventory["items"][:1]
    approve(c)
    run(c, "produce")
    assert c.fs.evidence()["receipts_verified"]
    before = receipt_bytes(c)
    output = c.project / "outputs/middle.csv"
    if damage == "missing":
        output.unlink()
    else:
        output.write_bytes(output.read_bytes().replace(b"4.0", b"9.0"))
    evidence = c.fs.evidence()
    assert evidence["validation"] == "incomplete" and not evidence["receipts_verified"]
    assert evidence["stale_steps"] == ["produce"]
    assert evidence["invalid_output_files"] == [
        {"path": "outputs/middle.csv", "plan_step_id": "produce", "reason": damage}]
    assert before == receipt_bytes(c)


def test_approved_in_place_transform_keeps_prior_step_and_propagates_source_staleness(case):
    c = case
    c.fs.plan["steps"][1]["command"][1] = "outputs/middle.csv"
    c.fs.inventory["items"][2]["local_paths"] = ["outputs/middle.csv"]
    approve(c)
    run(c, "produce")
    run(c, "consume")
    evidence = c.fs.evidence()
    assert evidence["receipts_verified"] and evidence["stale_steps"] == [], evidence
    assert "16.0" in (c.project / "outputs/middle.csv").read_text(encoding="utf-8")
    before = receipt_bytes(c)
    (c.project / "inputs/source.csv").unlink()
    assert c.fs.evidence()["stale_steps"] == ["consume", "produce"]
    assert before == receipt_bytes(c)


def test_one_evidence_query_hashes_shared_recorded_files_once(case, monkeypatch):
    c = case
    run(c, "produce")
    run(c, "consume")
    receipts = c.fs.flow.receipts
    original = receipts.sha256_file
    calls = []
    def count(path):
        calls.append(str(path))
        return original(path)
    monkeypatch.setattr(receipts, "sha256_file", count)
    assert c.fs.evidence()["receipts_verified"]
    assert len(calls) == 3 and len(set(calls)) == 3, calls


def test_omitted_legacy_kind_remains_a_required_process_step(case):
    c = case
    c.fs.plan["steps"][1].pop("kind")
    approve(c)
    run(c, "produce")
    assert c.fs.evidence()["steps_missing"] == ["consume"]
    run(c, "consume")
    assert c.fs.evidence()["receipts_verified"]


def test_download_kind_cannot_hide_an_executable_tool(case):
    c = case
    c.fs.plan["steps"][1]["kind"] = "download"
    errors = c.fs.flow.plan.validate(c.fs.plan, c.fs.inventory, ["M"], {"M": c.root},
                                     project=c.project, for_review=True)
    assert any("download steps cannot name" in error for error in errors)
    approve(c)
    run(c, "produce")
    evidence = c.fs.evidence()
    assert evidence["plan_errors"] and not evidence["receipts_verified"]
    assert "consume" in evidence["steps_missing"]


@pytest.mark.parametrize("scope,damage", [("file", "changed"), ("file", "missing"),
    ("directory", "changed"), ("directory", "missing"), ("directory", "new-member")])
def test_declared_default_inputs_and_directory_members_have_current_coverage(case, scope, damage):
    c = case
    directory = c.project / "inputs/default"
    (directory / "nested").mkdir(parents=True)
    source = directory / "source.csv"
    (c.project / "inputs/source.csv").replace(source)
    c.fs.plan["steps"][0]["command"][0] = "--default"
    c.fs.inventory["items"][0]["local_paths"] = [
        "inputs/default/source.csv" if scope == "file" else "inputs/default"]
    approve(c)
    original_hash = c.fs.flow.receipts.sha256_file(source)
    run(c, "produce")
    run(c, "consume")
    assert c.fs.evidence()["receipts_verified"]
    docs = [json.loads(data) for data in receipt_bytes(c).values()]
    doc = next(d for d in docs if d["plan_step_id"] == "produce")
    assert next(i for i in doc["inputs"] if i["path"] == "inputs/default/source.csv")["sha256"] == original_hash
    assert doc["input_coverage"]["inventory_bindings"] == [
        {"id": "source", "local_paths": c.fs.inventory["items"][0]["local_paths"]}]
    before = receipt_bytes(c)
    if damage == "missing":
        source.unlink()
    elif damage == "changed":
        source.write_bytes(source.read_bytes().replace(b"1,2", b"1,9"))
    else:
        (directory / "nested/extra.csv").write_text("day,value\n1,9\n", encoding="utf-8")
    evidence = c.fs.evidence()
    assert not evidence["receipts_verified"] and evidence["stale_steps"] == ["consume", "produce"]
    assert before == receipt_bytes(c)


def test_unapproved_input_mutation_during_execution_cannot_sign_replacement_bytes(case):
    c = case
    c.fs.plan["steps"] = c.fs.plan["steps"][:1]
    c.fs.plan["steps"][0]["command"].append("--mutate-source")
    approve(c)
    source = c.project / "inputs/source.csv"
    original_hash = c.fs.flow.receipts.sha256_file(source)
    run(c, "produce")
    doc = json.loads(next(iter(receipt_bytes(c).values())))
    assert next(i for i in doc["inputs"] if i["path"] == "inputs/source.csv")["sha256"] == original_hash
    assert c.fs.flow.receipts.sha256_file(source) != original_hash
    assert c.fs.evidence()["stale_steps"] == ["produce"]


def test_directory_can_receive_exact_approved_nested_output_without_hiding_new_inputs(case):
    c = case
    c.fs.plan["steps"] = c.fs.plan["steps"][:1]
    (c.project / "inputs/case").mkdir()
    (c.project / "inputs/source.csv").replace(c.project / "inputs/case/source.csv")
    c.fs.plan["steps"][0]["command"] = ["inputs/case/source.csv", "inputs/case/results/nested/middle.csv"]
    c.fs.inventory["items"][0]["local_paths"] = ["inputs/case"]
    c.fs.inventory["items"][1]["local_paths"] = ["inputs/case/results/nested/middle.csv"]
    approve(c)
    run(c, "produce")
    assert c.fs.evidence()["receipts_verified"]
    (c.project / "inputs/case/results/nested/unapproved.csv").write_text("1,2\n", encoding="utf-8")
    assert c.fs.evidence()["stale_steps"] == ["produce"]


def test_arbitrary_argument_directories_are_not_scanned_and_descriptive_items_need_no_fake_file(case):
    c = case
    c.fs.plan["steps"] = c.fs.plan["steps"][:1]
    c.fs.plan["steps"][0]["command"].extend(["--project-root", "."])
    c.fs.plan["steps"][0]["inputs"].append("runtime")
    c.fs.inventory["items"].append({"id": "runtime", "status": "resolved", "local_paths": []})
    approve(c)
    run(c, "produce")
    doc = json.loads(next(iter(receipt_bytes(c).values())))
    assert doc["input_coverage"]["directories"] == []
    assert {i["path"] for i in doc["inputs"]} == {"inputs/source.csv"}
    assert c.fs.evidence()["receipts_verified"]


@pytest.mark.parametrize("legacy_scope", ["complete-files", "missing-file", "directory"])
def test_legacy_receipts_require_authentic_file_coverage_and_cannot_invent_directory_membership(case, legacy_scope):
    c = case
    c.fs.plan["steps"] = c.fs.plan["steps"][:1]
    if legacy_scope == "directory":
        (c.project / "inputs/case").mkdir()
        (c.project / "inputs/source.csv").replace(c.project / "inputs/case/source.csv")
        c.fs.plan["steps"][0]["command"][0] = "inputs/case/source.csv"
        c.fs.inventory["items"][0]["local_paths"] = ["inputs/case"]
    approve(c)
    run(c, "produce")
    assert c.fs.evidence()["receipts_verified"]
    path, data = next(iter(receipt_bytes(c).items()))
    doc = json.loads(data)
    # A synthetic legacy signed shape around the real harmless dispatch result.
    # Old receipts never had the directory/binding coverage field.
    doc.pop("input_coverage")
    if legacy_scope == "missing-file":
        doc["inputs"] = []
    path.write_text(json.dumps(c.fs.flow.receipts.sign(c.project, doc)), encoding="utf-8")
    before = receipt_bytes(c)
    evidence = c.fs.evidence()
    assert evidence["receipts_verified"] is (legacy_scope == "complete-files")
    if legacy_scope != "complete-files":
        assert evidence["stale_steps"] == ["produce"]
        assert any("Legacy receipt lacks" in reason for reason in evidence["stale_step_reasons"]["produce"])
    assert receipt_bytes(c) == before
