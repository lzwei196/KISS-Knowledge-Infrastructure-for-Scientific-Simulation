"""Unit tests for ki_tools_common.flow (plan v3 A9 + codex review 2026-08-30). Run:
  /mnt/disk1/Hydrocraft_server/python_env/bin/python -m pytest tests/flow -q
Real-data tests (derive on VIC + CaMa_Flood) skip when the server's ata-kdt tree is absent.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from ki_tools_common.flow import states, resolve, plan, approval, contracts, receipts, policy
from ki_tools_common.flow.states import State, Capability, FlowContext, FlowError, transition

SERVER = Path("/mnt/disk1/Hydrocraft_server")
HAS_ATA = (SERVER / "ata-kdt" / "cards").is_dir()
VIC = SERVER / "models" / "VIC" / "knowledge_infrastructure"
CAMA = SERVER / "models" / "CaMa_Flood" / "knowledge_infrastructure"

CAT = [{"id": "VIC", "name": "VIC"}, {"id": "CaMa_Flood", "name": "CaMa-Flood"},
       {"id": "DSSAT", "name": "DSSAT"}, {"id": "SWAT+", "name": "SWAT+"}]
PAIRS = [("VIC", "CaMa_Flood"), ("VIC", "DSSAT")]


@pytest.fixture(autouse=True)
def keys(tmp_path_factory, monkeypatch):
    d = tmp_path_factory.mktemp("keys")
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(d))
    return d


# ---------------------------------------------------------------- states
def test_capability_table_denies_execution_before_approval():
    for s in (State.NEW, State.RESOLVING_KIS, State.PLANNING, State.PLAN_REVIEW,
              State.WAITING_FOR_USER, State.APPROVED):
        assert not states.allowed(s, Capability.RUN_MODEL)
        assert not states.allowed(s, Capability.DOWNLOAD)
    assert states.allowed(State.PLANNING, Capability.WRITE_PLAN_FILES)
    assert not states.allowed(State.PLANNING, Capability.WRITE_PROJECT)
    assert states.allowed(State.EXECUTING, Capability.RUN_MODEL)
    for s in State:
        assert not states.allowed(s, Capability.EDIT_SHARED_TOOLS)


def test_transitions_need_evidence():
    assert transition(State.NEW, "task_received") is State.RESOLVING_KIS
    with pytest.raises(FlowError):
        transition(State.RESOLVING_KIS, "kis_resolved", {})
    assert transition(State.RESOLVING_KIS, "kis_resolved", {"selected_kis": ["VIC"]}) is State.PLANNING
    with pytest.raises(FlowError):
        transition(State.PLANNING, "plan_written", {"plan_valid": False})
    with pytest.raises(FlowError):
        transition(State.PLAN_REVIEW, "approved", {"approval": "DRIFT"})
    with pytest.raises(FlowError):
        transition(State.PLAN_REVIEW, "approved", {"approval": "FORGED"})
    assert transition(State.PLAN_REVIEW, "approved", {"approval": "OK"}) is State.APPROVED
    with pytest.raises(FlowError):
        transition(State.APPROVED, "execution_started", {"setup_verified": False})
    with pytest.raises(FlowError):
        transition(State.VERIFYING, "validated", {"receipts_verified": True, "validation": "failed"})
    assert transition(State.VERIFYING, "validated",
                      {"receipts_verified": True, "validation": "passed"}) is State.COMPLETED
    with pytest.raises(FlowError):
        transition(State.PLANNING, "validated")
    # codex #7: a rerun goes back through APPROVED (approval + setup gates again)
    assert transition(State.FAILED_VALIDATION, "rerun", {"approval": "OK"}) is State.APPROVED
    with pytest.raises(FlowError):
        transition(State.FAILED, "rerun", {"approval": "DRIFT"})
    assert (State.FAILED, "rerun") not in {(s, e) for (s, e), (n, _) in states._MOVES.items() if n is State.EXECUTING}


def test_context_persists_agent_file_cannot_touch_it_and_corrupt_is_loud(tmp_path):
    ctx = FlowContext(project=tmp_path)
    ctx.move("task_received")
    ctx.move("kis_resolved", {"selected_kis": ["VIC"]})
    (tmp_path / "runs" / "project-agent-status.json").write_text('{"stage":"results","status":"complete"}')
    assert FlowContext.load(tmp_path).state is State.PLANNING
    (tmp_path / "runs" / "flow-state.json").write_text('{"state":"COMPLETED_BY_AGENT"}')
    with pytest.raises(FlowError):                       # codex #8: corrupt/invalid is loud
        FlowContext.load(tmp_path)
    (tmp_path / "runs" / "flow-state.json").write_text('not json')
    with pytest.raises(FlowError):
        FlowContext.load(tmp_path)
    assert FlowContext.load(tmp_path / "fresh").state is State.NEW   # missing = first run


# ---------------------------------------------------------------- resolve
@pytest.mark.parametrize("text,expect", [
    ("run VIC and CaMa-Flood", ["VIC", "CaMa_Flood"]),
    ("VIC-CaMa", ["VIC", "CaMa_Flood"]),
    ("VIC–CaMa", ["VIC", "CaMa_Flood"]),
    ("run VIC and CaMa_Flood", ["VIC", "CaMa_Flood"]),
    ("VIC, CaMa_Flood, DSSAT", ["VIC", "CaMa_Flood", "DSSAT"]),
    ("运行 VIC–CaMa-Flood 模拟洪水", ["VIC", "CaMa_Flood"]),
    ("use swat+ at Xixian", ["SWAT+"]),
])
def test_resolve_detector_cases(text, expect):
    r = resolve.resolve_kis(text, [], CAT)
    assert r.resolved == expect and not r.ambiguous and not r.unknown and r.ok


def test_resolve_reports_unknown_model_names_instead_of_dropping_them():
    # codex #3: catalogue has only VIC; the text names CaMa → unknown, not silently dropped
    r = resolve.resolve_kis("run VIC-CaMa flood at Bengbu", [], [{"id": "VIC", "name": "VIC"}])
    assert r.resolved == ["VIC"] and "CaMa" in r.unknown and not r.ok
    r = resolve.resolve_kis("run VIC and MyNewModel please", [], CAT)
    assert "MyNewModel" in r.unknown
    r = resolve.resolve_kis("run VIC at the Huai river for 2003", [], CAT)   # ordinary words: no noise
    assert r.unknown == [] and r.ok


def test_resolve_model_name_embedded_in_chinese_sentence_without_spaces():
    cat = CAT + [{"id": "CRHM", "name": "CRHM"},
                 {"id": "WRF_Hydro", "name": "WRF-Hydro"}]
    r = resolve.resolve_kis("我想要用CRHM模拟中国高寒区融雪径流", [], cat)
    assert r.resolved == ["CRHM"] and r.unknown == [] and r.ok
    r = resolve.resolve_kis("使用WRF-Hydro模拟高寒区积雪过程", [], cat)
    assert r.resolved == ["WRF_Hydro"] and r.unknown == [] and r.ok
    # A genuinely unknown ASCII model name embedded in Chinese is still surfaced.
    r = resolve.resolve_kis("我想用FooModel模拟融雪径流", [], cat)
    assert r.resolved == [] and r.unknown == ["FooModel"] and not r.ok


def test_resolve_partners_missing_and_couplings_one_end():
    r = resolve.resolve_kis("run VIC", [], CAT, couplings=PAIRS)
    assert r.resolved == ["VIC"] and r.partners_missing == ["CaMa_Flood", "DSSAT"]
    r = resolve.resolve_kis("run VIC and CaMa-Flood", [], CAT, couplings=PAIRS)
    assert r.partners_missing == ["DSSAT"]


def test_resolve_keeps_selection_first_and_flags_ambiguity():
    cat = CAT + [{"id": "VIC-classic", "name": "VIC"}]
    r = resolve.resolve_kis("run VIC please", ["DSSAT"], cat)
    assert r.resolved == ["DSSAT"]
    assert "vic" in r.ambiguous and set(r.ambiguous["vic"]) == {"VIC", "VIC-classic"}
    assert not r.ok


def test_is_scientific_task():
    assert resolve.is_scientific_task("run VIC at Bengbu 2003")
    assert resolve.is_scientific_task("模拟淮河洪水")
    assert not resolve.is_scientific_task("hello, what can you do?")


@pytest.mark.skipif(not HAS_ATA, reason="server ata-kdt tree not present")
def test_couplings_for_vic_cama_real():
    cdir = SERVER / "ata-kdt" / "couplings"
    edges = resolve.couplings_for(["VIC", "CaMa_Flood"], cdir)
    assert any(e["edge_id"] == "VIC_to_CaMa_Flood" and "surface_runoff" in e["variables"] for e in edges)
    one = resolve.couplings_for(["VIC"], cdir, one_end=True)
    assert any(e["edge_id"] == "VIC_to_CaMa_Flood" and e["partner_missing"] == "CaMa_Flood" for e in one)
    r = resolve.resolve_kis("run VIC-CaMa", [], CAT, couplings=resolve.coupling_pairs(cdir))
    assert r.resolved == ["VIC", "CaMa_Flood"] and "CaMa_Flood" not in r.partners_missing


# ---------------------------------------------------------------- plan
@pytest.mark.skipif(not HAS_ATA, reason="server ata-kdt tree not present")
def test_derive_vic_cama_from_real_data():
    roots = plan.DataRoots.server()
    full, pj, inv = plan.derive(["VIC", "CaMa_Flood"],
                                {"lat": 32.9, "lon": 117.4, "start_year": 2003, "end_year": 2005},
                                "VIC-CaMa flood", roots, {"VIC": VIC, "CaMa_Flood": CAMA})
    assert pj["schema_version"] == "1.0" and inv["schema_version"] == "1.0"
    assert pj["selected_kis"] == ["VIC", "CaMa_Flood"]
    assert any(c["edge_id"] == "VIC_to_CaMa_Flood" for c in pj["coupling"])
    cama = next(p for p in full["plans"] if p["model"] == "CaMa_Flood")
    runoff = next(i for i in cama["inputs"] if i["canonical_id"] == "surface_runoff")
    assert runoff["primary_strategy"]["kind"] == "from_upstream_model"
    assert runoff["primary_strategy"]["upstream_model"] == "VIC"
    fc = next(c for c in pj["scientific_choices"] if c["kind"] == "forcing_source")
    assert fc["picked"] == "cmfd_v1" and fc["high_impact"] is True
    st = {i["status"] for i in inv["items"]}
    assert "resolved" in st and all(i["status"] == "missing" for i in inv["items"] if i["needs_user"])
    assert plan.validate(pj, inv, ["VIC", "CaMa_Flood"], {"VIC": VIC, "CaMa_Flood": CAMA}) == []
    assert all(s["kind"] == "process" for s in pj["steps"]) and len(pj["steps"]) > 2


def _fake_ki(tmp_path, name="M", skill=True):
    ki = tmp_path / name; (ki / "tools").mkdir(parents=True, exist_ok=True)
    (ki / "tools" / "run.py").write_text("print('x')")
    if skill:
        (ki / "SKILL.md").write_text("# M\n> **MANDATORY EXECUTION POLICY**\n> run the real thing\n\n## steps\n")
    (ki / "dag.yaml").write_text("outputs:\n- var: discharge\n  validation_rank: 1\n  unit: m3/s\n")
    (ki / "preflight_check.py").write_text("print('ok')")
    return ki


def _good_plan(ki, tool=True):
    return {"schema_version": "1.0", "goal": "g", "selected_kis": ["M"], "created_at": "t",
            "unresolved_questions": [],
            "steps": [{"id": "M:run", "ki": "M", "tool": str(ki / "tools" / "run.py") if tool else None,
                       "kind": "run", "inputs": ["forcing"], "outputs": ["q"], "status": "planned"}],
            "scientific_choices": [{"id": "x", "kind": "other", "high_impact": False}]}


_INV = {"schema_version": "1.0", "items": [{"id": "forcing", "required_by": ["M"], "status": "resolved",
                                           "acceptable_sources": ["cmfd_v1"], "chosen_source": "cmfd_v1",
                                           "local_paths": [], "agent_resolvable": True, "needs_user": False}]}


def test_validate_rejects_bad_plans(tmp_path):
    ki = _fake_ki(tmp_path)
    good = _good_plan(ki)
    assert plan.validate(good, _INV, ["M"], {"M": ki}) == []
    bad = json.loads(json.dumps(good)); bad["steps"][0]["ki"] = "OTHER"
    assert any("not selected" in e for e in plan.validate(bad, _INV, ["M"], {"M": ki}))
    # codex #4: files inside the KI that are not under tools/ are NOT tools
    for notatool in (ki / "SKILL.md", ki / "dag.yaml", ki / "preflight_check.py", Path("/etc/passwd")):
        bad = json.loads(json.dumps(good)); bad["steps"][0]["tool"] = str(notatool)
        assert any("not a runnable" in e for e in plan.validate(bad, _INV, ["M"], {"M": ki})), notatool
    bad = json.loads(json.dumps(good)); bad["steps"][0]["inputs"] = ["ghost"]
    assert any("not in the data inventory" in e for e in plan.validate(bad, _INV, ["M"], {"M": ki}))
    bad = json.loads(json.dumps(good)); del bad["steps"][0]["status"]
    assert any("missing key 'status'" in e for e in plan.validate(bad, _INV, ["M"], {"M": ki}))
    inv2 = {"schema_version": "1.0", "items": [{"id": "forcing", "needs_user": True, "status": "resolved"}]}
    assert any("needs the user" in e for e in plan.validate(good, inv2, ["M"], {"M": ki}))
    inv3 = {"schema_version": "1.0", "items": [{"id": "forcing", "status": "ready", "local_paths": []}]}
    assert any("names no local file" in e for e in plan.validate(good, inv3, ["M"], {"M": ki}))
    inv4 = {"schema_version": "1.0", "items": [{"id": "forcing", "status": "downloaded"}]}
    assert any("unknown status" in e for e in plan.validate(good, inv4, ["M"], {"M": ki}))


def test_plan_step_environment_is_safe_and_expands_only_approved_roots(tmp_path):
    ki = _fake_ki(tmp_path / "catalogue")
    project = tmp_path / "project"; project.mkdir()
    good = _good_plan(ki)
    good["steps"][0]["env"] = {
        "VIC_INPUT": "${PROJECT}/inputs/forcing.txt",
        "VIC_TOOL_ROOT": "${KI_ROOT}/tools",
        "VIC_TIMESTEP": "3",
    }
    assert plan.validate(good, _INV, ["M"], {"M": ki}) == []
    expanded = plan.step_environment(good["steps"][0], project, ki)
    assert expanded["VIC_INPUT"] == str(project.resolve() / "inputs/forcing.txt")
    assert expanded["VIC_TOOL_ROOT"] == str(ki.resolve() / "tools")
    assert expanded["VIC_TIMESTEP"] == "3"

    for key in ("PATH", "PYTHONPATH", "DYLD_INSERT_LIBRARIES", "MODEL_API_TOKEN",
                "GEOFORGE_AGENT_FLOW_URL"):
        bad = json.loads(json.dumps(good)); bad["steps"][0]["env"] = {key: "x"}
        assert any("not allowed" in e for e in plan.validate(bad, _INV, ["M"], {"M": ki}))
    bad = json.loads(json.dumps(good)); bad["steps"][0]["env"] = {"VIC_INPUT": "${HOME}/x"}
    assert any("unsupported tokens" in e for e in plan.validate(bad, _INV, ["M"], {"M": ki}))
    with pytest.raises(ValueError, match="outside the project and KI"):
        plan.step_environment({"env": {"VIC_OUTPUT": "/Library/geoforge.txt"}}, project, ki)


def test_sha256_is_canonical():
    assert plan.sha256({"b": 1, "a": [1, 2]}) == plan.sha256({"a": [1, 2], "b": 1})


# ---------------------------------------------------------------- approval
def _write_plan(p: Path, ki, needs_user=False, high=False):
    pj = _good_plan(ki)
    if high:
        pj["scientific_choices"] = [{"id": "f", "kind": "forcing_source", "high_impact": True}]
    inv = json.loads(json.dumps(_INV))
    if needs_user:
        inv["items"][0].update({"needs_user": True, "status": "missing", "agent_resolvable": False})
    plan.write_artifacts(p, pj, inv)
    return pj, inv


def test_approval_ok_missing_drift_forged(tmp_path):
    ki = _fake_ki(tmp_path)
    assert approval.check(tmp_path) == "MISSING"
    _write_plan(tmp_path, ki)
    assert approval.check(tmp_path) == "MISSING"
    doc = approval.approve(tmp_path, {"forcing_source": "cmfd_v1"}, by="user")
    assert doc["approved_by"] == "user" and "signature" in doc and approval.check(tmp_path) == "OK"
    pj, inv = plan.read_artifacts(tmp_path)
    pj["goal"] = "changed"; plan.write_artifacts(tmp_path, pj, inv)
    assert approval.check(tmp_path) == "DRIFT"
    pj["goal"] = "g"; plan.write_artifacts(tmp_path, pj, inv)
    assert approval.check(tmp_path) == "OK"
    # codex #6: a hand-written approval with matching hashes is FORGED, not OK
    forged = {"schema_version": "1.0", "plan_sha256": plan.sha256(pj), "data_inventory_sha256": plan.sha256(inv),
              "approved_by": "user", "approved_at": "now", "decisions": {}, "selected_kis": ["M"],
              "signature": {"alg": "HMAC-SHA256", "key_id": "x", "value": "00" * 32}}
    (tmp_path / "runs" / "approval.json").write_text(json.dumps(forged))
    assert approval.check(tmp_path) == "FORGED"
    (tmp_path / "runs" / "approval.json").write_text(json.dumps({k: v for k, v in forged.items() if k != "signature"}))
    assert approval.check(tmp_path) == "FORGED"
    approval.approve(tmp_path, by="auto")
    approval.revoke(tmp_path, "plan changed")
    assert approval.check(tmp_path) == "MISSING"


def test_auto_approve_rule(tmp_path):
    ki = _fake_ki(tmp_path)
    pj, inv = _write_plan(tmp_path, ki)
    assert approval.may_auto_approve(pj, inv)[0] is True
    pj, inv = _write_plan(tmp_path, ki, needs_user=True)
    ok, why = approval.may_auto_approve(pj, inv); assert not ok and "needs the user" in why[0]
    pj, inv = _write_plan(tmp_path, ki, high=True)
    ok, why = approval.may_auto_approve(pj, inv); assert not ok and "high-impact" in why[0]
    with pytest.raises(ValueError):
        approval.approve(tmp_path, by="agent")


# ---------------------------------------------------------------- contracts
def test_planning_block_uses_inspect_and_execution_block_uses_execute(tmp_path):
    ki = _fake_ki(tmp_path)
    pj, inv = _write_plan(tmp_path, ki)
    pb = contracts.planning_block({"M": ki}, pj, inv, tmp_path, partners_to_ask=["N"])
    assert "INSPECT mode" in pb and "do NOT run the model pipeline" in pb
    assert "COUPLED PARTNER NOT SELECTED" in pb
    assert "Shall I proceed?" not in contracts.discipline()
    a = approval.approve(tmp_path, by="auto")
    eb = contracts.execution_block({"M": ki}, pj, a, tmp_path, "claude", {"run_tool": "kiss run-tool", "fetch": "kiss fetch"})
    assert "[STAGE GROUNDING — execute the carried plan; do not re-derive]" in eb
    assert "TOOLS (validated)" in eb and "NOT YOUR OWN JUDGE" in eb and "REPLAN_REQUIRED" in eb
    short = contracts.execution_block({"M": ki}, pj, a, tmp_path, short=True)
    assert "STAGE GROUNDING" in short and "TOOLS (validated)" not in short
    ctx = FlowContext(project=tmp_path, state=State.EXECUTING)
    line = contracts.receipt_line(ctx, ki, eb, "claude", "sess1")
    for f in ("harness_marker=", "harness_mode=execute", "ki_name=M", "skill_sha256=", "injected_at=",
              "session_id=sess1", "contract_sha256="):
        assert f in line


def test_execution_block_refuses_ki_without_protocol(tmp_path):
    ki = _fake_ki(tmp_path, skill=False)
    pj, inv = _write_plan(tmp_path, ki)
    a = approval.approve(tmp_path, by="auto")
    from ki_tools_common.harness.ki_harness import KiHarnessError
    with pytest.raises(KiHarnessError):
        contracts.execution_block({"M": ki}, pj, a, tmp_path)
    assert "nothing here is runnable" in contracts.planning_block({"M": ki}, pj, inv, tmp_path)


# ---------------------------------------------------------------- receipts
def _run(tmp_path, out, a, step="M:run", ki="M", exit_code=0, approval_sha=None):
    tool = str(tmp_path / ki / "tools" / "run.py")      # the approved step's tool (evidence binds to it)
    return receipts.record_run(tmp_path, ki=ki, executable="/usr/bin/python3", command=["/usr/bin/python3", tool],
                               cwd=str(tmp_path), started_at=1.0, finished_at=2.5, exit_code=exit_code,
                               inputs=[], outputs=[out], plan_step_id=step,
                               approval_sha256=approval_sha or approval.approval_id(a))


def test_receipts_require_binding_sign_verify_and_reject_forgery(tmp_path):
    ki = _fake_ki(tmp_path); pj, inv = _write_plan(tmp_path, ki); a = approval.approve(tmp_path, by="auto")
    out = tmp_path / "outputs" / "q.csv"; out.parent.mkdir(); out.write_text("1\n2\n3\n")
    with pytest.raises(receipts.ReceiptError):                           # codex #2: unbound
        receipts.record_run(tmp_path, ki="M", executable="/bin/true", command=[], cwd=".", started_at=1,
                            finished_at=2, exit_code=0, inputs=[], outputs=[out], plan_step_id="M:run",
                            approval_sha256="")
    rp = _run(tmp_path, out, a)
    doc = json.loads(rp.read_text())
    assert receipts.verify(tmp_path, doc) and doc["binary_actually_ran"] and doc["output_files_count"] == 1
    doc["exit_code"] = 1
    assert not receipts.verify(tmp_path, doc)
    forged = dict(doc); forged["signature"] = {"alg": "HMAC-SHA256", "key_id": receipts.project_id(tmp_path), "value": "00" * 32}
    (tmp_path / receipts.RECEIPT_DIR / receipts.RUNS_SUB / "forged.json").write_text(json.dumps(forged))
    ev = receipts.evidence(tmp_path, pj, a)
    assert ev["runs_total"] == 2 and ev["runs_bound"] == 1
    assert any(r["why"] == "signature" for r in ev["rejected_receipts"])


def test_evidence_binds_to_current_approval_steps_and_artifacts(tmp_path):
    ki = _fake_ki(tmp_path); pj, inv = _write_plan(tmp_path, ki); a = approval.approve(tmp_path, by="auto")
    good = tmp_path / "outputs" / "q.csv"; good.parent.mkdir(); good.write_text("t,q\n1,0.5\n2,1.2\n3,0.9\n")
    stray = tmp_path / "outputs" / "handmade.csv"; stray.write_text("1\n")
    rp = _run(tmp_path, good, a)
    ev = receipts.evidence(tmp_path, pj, a)
    assert "outputs/handmade.csv" in ev["unreceipted_artifacts"] and ev["validation"] == "incomplete"
    v = receipts.validate_outputs(ki, [good], run_facts={"errored": False, "output_nonempty": True})
    assert v["status"] == "passed"
    receipts.update_validation(tmp_path, rp, v)
    stray.unlink()
    ev = receipts.evidence(tmp_path, pj, a)
    assert ev["validation"] == "passed" and ev["receipts_verified"] is True and ev["steps_missing"] == []
    # a receipt for a step that is not in the plan, or for another approval, does not count
    _run(tmp_path, good, a, step="M:ghost")
    ev = receipts.evidence(tmp_path, pj, a)
    assert any("not in the approved plan" in r["why"] for r in ev["rejected_receipts"])
    _run(tmp_path, good, a, approval_sha="deadbeef")
    assert any("not bound to the current approval" in r["why"] for r in receipts.evidence(tmp_path, pj, a)["rejected_receipts"])
    # a multi-step plan needs EVERY executable step passed
    pj2 = json.loads(json.dumps(pj)); pj2["steps"].append({"id": "M:route", "ki": "M", "tool": None, "kind": "route",
                                                            "inputs": [], "outputs": [], "status": "planned"})
    ev = receipts.evidence(tmp_path, pj2, a)
    assert ev["steps_missing"] == ["M:route"] and ev["receipts_verified"] is False
    # replay of an old approval: after re-approval the old receipts no longer bind
    pj["goal"] = "v2"; plan.write_artifacts(tmp_path, pj, inv); a2 = approval.approve(tmp_path, by="auto")
    ev = receipts.evidence(tmp_path, pj, a2)
    assert ev["runs_bound"] == 0 and ev["receipts_verified"] is False


def test_validate_outputs_rank1_aliases_all_zero_and_unaffirmed(tmp_path):
    ki = _fake_ki(tmp_path)
    z = tmp_path / "q.csv"; z.write_text("t,q\n1,0\n2,0\n")
    v = receipts.validate_outputs(ki, [z], run_facts={"errored": False, "output_nonempty": True})
    assert v["status"] == "failed"
    assert any(c["check"].startswith("physically_required_positive") and not c["ok"] for c in v["checks"])
    neg = tmp_path / "n.csv"; neg.write_text("t,q\n1,-3\n2,-1\n3,-2\n")
    assert receipts.validate_outputs(ki, [neg])["status"] == "failed"
    v = receipts.validate_outputs(ki, [z], run_facts={})
    assert any(c["check"] == "run_affirmed_error_free" and not c["ok"] for c in v["checks"])
    assert receipts.validate_outputs(ki, [])["status"] == "failed"
    nan = tmp_path / "nn.csv"; nan.write_text("1\nnan\n3\n")
    assert any(c["check"].startswith("no_nan_inf") and not c["ok"] for c in receipts.validate_outputs(ki, [nan])["checks"])
    # codex #5: CaMa-Flood's rank-1 'outflw' counts as a positive-required flow
    cama = tmp_path / "C"; (cama / "tools").mkdir(parents=True)
    (cama / "dag.yaml").write_text("outputs:\n- var: outflw\n  validation_rank: 1\n  unit: m3/s\n")
    assert receipts.validate_outputs(cama, [z])["status"] == "failed"
    okf = tmp_path / "ok.csv"; okf.write_text("t,outflw\n1,12.5\n2,30.1\n3,8.0\n")
    assert receipts.validate_outputs(cama, [okf], run_facts={"errored": False, "output_nonempty": True})["status"] == "passed"


def test_validate_outputs_netcdf_uses_rank1_variable_only(tmp_path):
    xr = pytest.importorskip("xarray"); np = pytest.importorskip("numpy")
    cama = tmp_path / "C"; (cama / "tools").mkdir(parents=True)
    (cama / "dag.yaml").write_text("outputs:\n- var: outflw\n  validation_rank: 1\n  unit: m3/s\n")
    ds = xr.Dataset({"outflw": ("time", np.zeros(5)), "rivsto": ("time", np.ones(5))}, coords={"time": np.arange(5)})
    f = tmp_path / "o.nc"; ds.to_netcdf(f, engine="scipy")     # netCDF3: no HDF5 locking issues on tmpfs
    v = receipts.validate_outputs(cama, [f], expected_steps=5)
    assert v["status"] == "failed", "all-zero outflw must fail even though rivsto is positive"
    assert any("rank-1 var(s) outflw" in c["detail"] for c in v["checks"])
    ds2 = xr.Dataset({"outflw": ("time", np.array([1.0, 2.0, 3.0]))}, coords={"time": np.arange(3)})
    f2 = tmp_path / "o2.nc"; ds2.to_netcdf(f2, engine="scipy")
    v = receipts.validate_outputs(cama, [f2], expected_steps=5)
    assert any(c["check"].startswith("time_axis_complete") and not c["ok"] for c in v["checks"])


def test_netcdf4_fallback_inspects_output_without_xarray(tmp_path, monkeypatch):
    nc4 = pytest.importorskip("netCDF4"); np = pytest.importorskip("numpy")
    path = tmp_path / "fallback.nc"
    with nc4.Dataset(path, "w") as ds:
        ds.createDimension("time", 3)
        var = ds.createVariable("outflw", "f8", ("time",))
        var[:] = np.array([0.0, 1.5, 2.0])
    monkeypatch.setitem(sys.modules, "xarray", None)
    values, steps, note = receipts._load_series(path, ("outflw",))
    assert values == [0.0, 1.5, 2.0]
    assert steps == 3 and note == "netcdf rank-1 var(s) outflw"


def test_key_dir_inside_project_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    with pytest.raises(receipts.ReceiptError):
        receipts.sign(tmp_path, {"kind": "run"})


# ---------------------------------------------------------------- policy
def test_policy_claude_planning_is_read_only_plus_plan_files(tmp_path):
    ki = _fake_ki(tmp_path)
    pp = policy.for_state(State.PLANNING, "claude", tmp_path, {"M": ki}, "/py")
    tools = pp.argv_delta[1].split(",")
    assert pp.enforcement is states.Enforcement.EXACT and "--dangerously-skip-permissions" in pp.drop_flags
    bash = [t for t in tools if t.startswith("Bash(")]
    assert bash == []  # script --help/preflight may mutate; planning only reads
    writes = [t for t in tools if t.startswith(("Write(", "Edit("))]
    assert set(writes) == {f"Write(/{tmp_path}/runs/plan.json)", f"Edit(/{tmp_path}/runs/plan.json)",
                           f"Write(/{tmp_path}/runs/data-inventory.json)", f"Edit(/{tmp_path}/runs/data-inventory.json)"}


def test_policy_claude_executing_is_rebuilt_from_scratch(tmp_path):
    ki = _fake_ki(tmp_path)
    base = [f"Read({tmp_path}/**)", f"Write({tmp_path}/**)", f"Write({tmp_path}/runs/**)",
            f"Edit({ki}/tools/**)", f"Write({tmp_path}/.geoforge/**)", "Bash(git:*)", f"Bash({ki}/**)",
            "Bash(/usr/bin/python3:*)"]
    pp = policy.for_state(State.EXECUTING, "claude", tmp_path, {"M": ki}, "/py", base,
                          {"run_tool": "kiss run-tool", "fetch": "kiss fetch"})
    tools = pp.argv_delta[1].split(",")
    writes = [t for t in tools if t.startswith(("Write(", "Edit("))]
    assert all(any(f"/{sub}/" in w for sub in ("inputs", "outputs", "artifacts", "references", "calibration", "runs/logs", "runs/notes")) for w in writes), writes
    assert not any("runs/**" in w or ".geoforge" in w or "/tools/" in w or w.endswith(f"({tmp_path}/**)") for w in writes)
    assert sorted(t for t in tools if t.startswith("Bash(")) == ["Bash(kiss fetch:*)", "Bash(kiss run-tool:*)"]
    with pytest.raises(ValueError):
        policy.for_state(State.EXECUTING, "claude", tmp_path, {"M": ki}, "/py", base, None)


def test_write_allowed_rule(tmp_path):
    ki = tmp_path / "ki"
    W = lambda p, s: policy.write_allowed(p, tmp_path, [ki], s)
    assert W(tmp_path / "runs" / "plan.json", State.PLANNING)
    assert not W(tmp_path / "runs" / "plan.json", State.EXECUTING)
    assert not W(tmp_path / "runs" / "approval.json", State.PLANNING)
    assert not W(tmp_path / "runs" / "flow-state.json", State.EXECUTING)
    assert not W(tmp_path / ".geoforge" / "receipts" / "x.json", State.EXECUTING)
    assert not W(ki / "tools" / "s1.py", State.EXECUTING)
    assert W(tmp_path / "outputs" / "q.csv", State.EXECUTING)
    assert not W(tmp_path / "outputs" / "q.csv", State.PLANNING)
    assert not W(tmp_path / "runs" / "anything.txt", State.EXECUTING)
    assert W(tmp_path / "runs" / "logs" / "x.log", State.EXECUTING)


def test_policy_codex_kimi_honest_and_gemini_not_offered(tmp_path):
    pp = policy.for_state(State.PLANNING, "codex", tmp_path, {})
    assert pp.enforcement is states.Enforcement.APPROXIMATE and pp.planning_worktree
    pp = policy.for_state(State.EXECUTING, "kimi", tmp_path, {})
    assert pp.enforcement is states.Enforcement.APPROXIMATE and "receipt" in pp.note
    pp = policy.for_state(State.EXECUTING, "gemini", tmp_path, {})
    assert pp.enforcement is states.Enforcement.NONE and "not offered" in pp.note


def test_api_tools_by_state(tmp_path):
    assert "run_ki_tool" not in policy.api_tools_for(State.PLANNING)
    assert "write_plan" in policy.api_tools_for(State.PLANNING)
    assert policy.api_tool_allowed(State.EXECUTING, "run_ki_tool")
    assert not policy.api_tool_allowed(State.PLANNING, "run_ki_tool")
    assert not policy.api_tool_allowed(State.EXECUTING, "write_plan")


# ---------------------------------------------------------------- the issue's six cases (fake driver)
def _drive(tmp_path, *, needs_user=False, high=False, run_ok=True, all_zero=False,
           tamper_after_approval=False):
    """NOTE: a fake driver. It proves the state machine + artifacts + receipts + evidence
    logic, NOT desktop routing, provider argv enforcement or the API proxy (steps 2-6)."""
    ki = _fake_ki(tmp_path)
    ctx = FlowContext(project=tmp_path)
    ctx.move("task_received")
    ctx.move("kis_resolved", {"selected_kis": ["M"]})
    pj, inv = _write_plan(tmp_path, ki, needs_user=needs_user, high=high)
    assert ctx.allows(Capability.WRITE_PLAN_FILES) and not ctx.allows(Capability.RUN_MODEL)
    ctx.move("plan_written", {"plan_valid": plan.validate(pj, inv, ["M"], {"M": ki}) == []})
    ok, _ = approval.may_auto_approve(pj, inv)
    if not ok:
        ctx.move("needs_user"); return ctx
    a = approval.approve(tmp_path, by="auto")
    if tamper_after_approval:
        pj["goal"] = "changed"; plan.write_artifacts(tmp_path, pj, inv)
    verdict = approval.check(tmp_path)
    if verdict != "OK":
        ctx.move("drift"); return ctx
    ctx.move("approved", {"approval": verdict})
    ctx.move("execution_started", {"setup_verified": True})
    out = tmp_path / "outputs" / "q.csv"; out.parent.mkdir(exist_ok=True)
    out.write_text("t,q\n1,0\n2,0\n3,0\n" if all_zero else "t,q\n1,0.4\n2,1.1\n3,0.7\n")
    rp = _run(tmp_path, out, a, exit_code=0 if run_ok else 1)
    ctx.move("run_finished")
    v = receipts.validate_outputs(ki, [out], run_facts={"errored": not run_ok, "output_nonempty": True})
    receipts.update_validation(tmp_path, rp, v)
    ev = receipts.evidence(tmp_path, pj, a)
    if ev["validation"] == "passed" and ev["receipts_verified"]:
        ctx.move("validated", {"receipts_verified": True, "validation": "passed"})
    else:
        ctx.move("validation_failed")
    return ctx


def test_case1_single_ki_complete_data_auto_completes(tmp_path):
    assert _drive(tmp_path).state is State.COMPLETED


def test_case2_missing_second_ki_is_a_planning_question_not_a_run(tmp_path):
    r = resolve.resolve_kis("run VIC-CaMa flood", [], [{"id": "VIC", "name": "VIC"}], couplings=PAIRS)
    assert r.resolved == ["VIC"] and "CaMa" in r.unknown and "CaMa_Flood" in r.partners_missing and not r.ok
    pj = {"schema_version": "1.0", "selected_kis": ["VIC"], "steps": [
        {"id": "CaMa_Flood:run", "ki": "CaMa_Flood", "tool": None, "inputs": [], "outputs": [], "status": "planned", "kind": "run"}],
        "scientific_choices": [], "goal": "g", "unresolved_questions": [], "created_at": "t"}
    assert any("not selected" in e for e in plan.validate(pj, {"schema_version": "1.0", "items": []}, ["VIC"], {}))


def test_case3_user_choice_waits(tmp_path):
    assert _drive(tmp_path, high=True).state is State.WAITING_FOR_USER
    assert not FlowContext.load(tmp_path).allows(Capability.DOWNLOAD)


def test_case4_bypass_refused(tmp_path):
    ctx = FlowContext(project=tmp_path); ctx.move("task_received"); ctx.move("kis_resolved", {"selected_kis": ["M"]})
    with pytest.raises(FlowError):
        ctx.require(Capability.RUN_MODEL, "run the model")
    assert not policy.api_tool_allowed(ctx.state, "run_ki_tool")


def test_case5_exit0_but_all_zero_fails_validation(tmp_path):
    assert _drive(tmp_path, all_zero=True).state is State.FAILED_VALIDATION


def test_case6_plan_changed_after_approval_drifts(tmp_path):
    assert _drive(tmp_path, tamper_after_approval=True).state is State.REPLAN_REQUIRED


# ---------------------------------------------------------------- kimi review additions
def test_run_facts_are_required_and_netcdf_uninspectable_fails(tmp_path, monkeypatch):
    ki = _fake_ki(tmp_path)
    good = tmp_path / "q.csv"; good.write_text("t,q\n1,0.4\n2,1.1\n3,0.7\n")
    v = receipts.validate_outputs(ki, [good])                     # no run facts → fail closed
    assert v["status"] == "failed" and any(c["check"] == "run_affirmed_error_free" and not c["ok"] for c in v["checks"])
    monkeypatch.setattr(receipts, "_load_series", lambda p, prefer=(): (None, None, "NETCDF_UNINSPECTABLE: xarray not installed"))
    nc = tmp_path / "o.nc"; nc.write_bytes(b"CDF\x01junk")
    v = receipts.validate_outputs(ki, [nc], run_facts={"errored": False, "output_nonempty": True})
    assert v["status"] == "failed" and any(c["check"].startswith("readable") and c["level"] == "fail" for c in v["checks"])


def test_cumulative_column_is_not_dropped_as_time_axis(tmp_path):
    ki = _fake_ki(tmp_path)
    # first column = day index (constant step) → axis; second = cumulative discharge (increasing,
    # variable step) → data, must satisfy the positive check
    f = tmp_path / "cum.csv"; f.write_text("day,cum_q\n1,0.5\n2,1.7\n3,1.9\n4,4.0\n")
    v = receipts.validate_outputs(ki, [f], run_facts={"errored": False, "output_nonempty": True})
    assert v["status"] == "passed", v


def test_evidence_assurance_label_and_missing_key(tmp_path, monkeypatch):
    ki = _fake_ki(tmp_path); pj, inv = _write_plan(tmp_path, ki); a = approval.approve(tmp_path, by="auto")
    out = tmp_path / "outputs" / "q.csv"; out.parent.mkdir(); out.write_text("1\n2\n")
    _run(tmp_path, out, a)
    assert receipts.evidence(tmp_path, pj, a, enforcement="exact")["assurance"] == "cryptographic"
    assert receipts.evidence(tmp_path, pj, a, enforcement="approximate")["assurance"] == "containment"
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path.parent / "elsewhere"))   # key gone
    ev = receipts.evidence(tmp_path, pj, a)
    assert ev["runs_bound"] == 0 and ev["receipts_verified"] is False
    assert approval.check(tmp_path) == "FORGED"


def test_validate_for_execution_requires_tools_and_resolved_inputs(tmp_path):
    ki = _fake_ki(tmp_path)
    pj = _good_plan(ki, tool=False)
    assert plan.validate(pj, _INV, ["M"], {"M": ki}) == []                       # planning: ok
    errs = plan.validate(pj, _INV, ["M"], {"M": ki}, for_execution=True)         # approval: not ready
    assert any("has no tool" in e for e in errs)
    inv = json.loads(json.dumps(_INV)); inv["items"][0]["status"] = "missing"
    errs = plan.validate(_good_plan(ki), inv, ["M"], {"M": ki}, for_execution=True)
    assert any("still missing" in e for e in errs)
    model_run = _good_plan(ki, tool=False)
    model_run["steps"][0]["kind"] = "model_run"
    assert any("has no tool" in e for e in
               plan.validate(model_run, _INV, ["M"], {"M": ki}, for_execution=True))


def test_failed_can_replan_and_coupling_graph_keeps_agent_todo(tmp_path):
    assert transition(State.FAILED, "replan") is State.REPLAN_REQUIRED
    assert transition(State.FAILED_VALIDATION, "replan") is State.REPLAN_REQUIRED
    import yaml
    plan.emit_coupling_graph({"models": ["A"], "plans": []}, tmp_path / "g.yaml")
    g = yaml.safe_load((tmp_path / "g.yaml").read_text())
    assert "_TODO_for_agent" in g and "_TODO_for_execution" in g


# ---------------------------------------------------------------- codex R2 additions
def test_evidence_binds_receipt_to_the_approved_tool_and_download_steps(tmp_path):
    ki = _fake_ki(tmp_path); pj, inv = _write_plan(tmp_path, ki)
    pj["steps"].append({"id": "M:get_forcing", "ki": "M", "tool": None, "kind": "download",
                        "inputs": [], "outputs": ["forcing"], "status": "planned"})
    plan.write_artifacts(tmp_path, pj, inv); a = approval.approve(tmp_path, by="auto")
    out = tmp_path / "outputs" / "q.csv"; out.parent.mkdir(); out.write_text("t,q\n1,0.4\n2,1.1\n3,0.7\n")
    # a receipt whose command does NOT contain the approved tool is rejected
    wrong = receipts.record_run(tmp_path, ki="M", executable="/bin/true", command=["/bin/true", "/tmp/other.py"],
                                cwd=str(tmp_path), started_at=1.0, finished_at=2.0, exit_code=0, inputs=[],
                                outputs=[out], plan_step_id="M:run", approval_sha256=approval.approval_id(a))
    ev = receipts.evidence(tmp_path, pj, a)
    assert any("not the approved tool" in r["why"] for r in ev["rejected_receipts"]) and ev["runs_bound"] == 0
    wrong.unlink()
    right = receipts.record_run(tmp_path, ki="M", executable="/usr/bin/python3",
                                command=["/usr/bin/python3", str(ki / "tools" / "run.py")],
                                cwd=str(tmp_path), started_at=1.0, finished_at=2.0, exit_code=0, inputs=[],
                                outputs=[out], plan_step_id="M:run", approval_sha256=approval.approval_id(a))
    receipts.update_validation(tmp_path, right, receipts.validate_outputs(
        ki, [out], run_facts={"errored": False, "output_nonempty": True}))
    ev = receipts.evidence(tmp_path, pj, a)
    assert ev["runs_bound"] == 1 and ev["steps_missing"] == ["M:get_forcing"] and not ev["receipts_verified"]
    # the download step is satisfied only by a bound download receipt naming it
    raw = tmp_path / "inputs" / "raw" / "forcing" / "f.csv"; raw.parent.mkdir(parents=True); raw.write_text("1\n")
    receipts.record_download(tmp_path, item_id="forcing", source="x", request_url="https://x/f.csv",
                             http_status=200, raw_files=[raw], approval_sha256=approval.approval_id(a),
                             plan_step_id="M:get_forcing")
    ev = receipts.evidence(tmp_path, pj, a)
    assert ev["steps_missing"] == [] and ev["receipts_verified"] is True and ev["validation"] == "passed"


def test_netcdf_missing_rank1_variable_fails_physical_check(tmp_path):
    xr = pytest.importorskip("xarray"); np = pytest.importorskip("numpy")
    cama = tmp_path / "C"; (cama / "tools").mkdir(parents=True)
    (cama / "dag.yaml").write_text("outputs:\n- var: outflw\n  validation_rank: 1\n  unit: m3/s\n")
    ds = xr.Dataset({"rivsto": ("time", np.ones(4))}, coords={"time": np.arange(4)})
    f = tmp_path / "o.nc"; ds.to_netcdf(f, engine="scipy")
    v = receipts.validate_outputs(cama, [f], run_facts={"errored": False, "output_nonempty": True})
    assert v["status"] == "failed"
    assert any(c["check"].startswith("physically_required_positive") and "not in this file" in c["detail"] for c in v["checks"])
    # a preparation step (physical=False) with the same file passes the physical rule
    v = receipts.validate_outputs(cama, [f], run_facts={"errored": False, "output_nonempty": True}, physical=False)
    assert v["status"] == "passed"


# ---------------------------------------------------------------- kimi R2 additions
def test_executing_policy_has_no_bare_reads_and_key_dir_stays_unreadable(tmp_path, monkeypatch):
    ki = _fake_ki(tmp_path)
    pp = policy.for_state(State.EXECUTING, "claude", tmp_path, {"M": ki}, "/py", [f"Read({tmp_path}/**)"],
                          {"run_tool": "kiss run-tool", "fetch": "kiss fetch"})
    tools = pp.argv_delta[1].split(",")
    assert "Read" not in tools and "Glob" not in tools and "Grep" not in tools
    assert all(t.startswith(("Read(", "Glob(", "Grep(", "Write(", "Edit(", "Bash(", "TodoWrite")) for t in tools)
    # a key dir inside a granted read tree is refused loudly
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    with pytest.raises(ValueError, match="receipt key dir"):
        policy.for_state(State.EXECUTING, "claude", tmp_path, {"M": ki}, "/py", [],
                         {"run_tool": "kiss run-tool", "fetch": "kiss fetch"})
    with pytest.raises(ValueError, match="receipt key dir"):
        policy.for_state(State.PLANNING, "claude", tmp_path, {"M": ki}, "/py")


def test_temp_files_live_under_protected_tree_and_evidence_scans_all_writable_trees(tmp_path):
    ki = _fake_ki(tmp_path); pj, inv = _write_plan(tmp_path, ki)
    ctx = FlowContext(project=tmp_path); ctx.move("task_received")
    a = approval.approve(tmp_path, by="auto")
    assert not list((tmp_path / "runs").glob("*.tmp")) and (tmp_path / ".geoforge" / "tmp").is_dir()
    stray = tmp_path / "artifacts" / "handmade.png"; stray.parent.mkdir(); stray.write_bytes(b"x")
    assert "artifacts/handmade.png" in receipts.evidence(tmp_path, pj, a)["unreceipted_artifacts"]


def test_validate_accepts_extensionless_executable_tool(tmp_path):
    ki = _fake_ki(tmp_path)
    exe = ki / "tools" / "run_model"; exe.write_text("#!/bin/sh\necho hi\n"); os.chmod(exe, 0o755)
    pj = _good_plan(ki); pj["steps"][0]["tool"] = str(exe)
    assert plan.validate(pj, _INV, ["M"], {"M": ki}) == []
    os.chmod(exe, 0o644)
    assert any("not a runnable" in e for e in plan.validate(pj, _INV, ["M"], {"M": ki}))


def test_download_receipt_survives_a_replan_when_the_item_is_still_pinned(tmp_path):
    from ki_tools_common.flow import receipts
    project = tmp_path / "p"
    (project / "inputs" / "obs").mkdir(parents=True)
    raw = project / "inputs" / "obs" / "q.txt"
    raw.write_text("flow\n")
    inventory = {"items": [{"id": "obs", "dataset_id": "source-A", "requirements": {"start": "2000"}}]}
    receipts.record_download(project, item_id="obs", source="test", request_url="https://x/y",
                             http_status=200, raw_files=[raw], plan_step_id="s1",
                             approval_sha256="old-approval", inventory_item=inventory["items"][0])
    plan = {"selected_kis": ["M"], "steps": [{"id": "s1", "ki": "M", "kind": "download",
                                              "inputs": ["obs"], "outputs": []}]}
    approval = {"plan_sha256": "new-approval", "selected_kis": ["M"]}
    ev = receipts.evidence(project, plan, approval, enforcement="exact", inventory=inventory)
    assert ev["downloads_bound"] == 1 and not ev["rejected_receipts"]
    inventory["items"][0]["dataset_id"] = "source-B"
    assert receipts.evidence(project, plan, approval, inventory=inventory)["downloads_bound"] == 0
    inventory["items"][0]["dataset_id"] = "source-A"
    inventory["items"][0]["requirements"]["start"] = "2001"
    assert receipts.evidence(project, plan, approval, inventory=inventory)["downloads_bound"] == 0
    inventory["items"][0]["requirements"]["start"] = "2000"
    # a changed file, or an item no longer in the plan, breaks the binding
    raw.write_text("tampered\n")
    ev = receipts.evidence(project, plan, approval, enforcement="exact", inventory=inventory)
    assert ev["downloads_bound"] == 0


def test_legacy_receipt_cannot_reuse_same_plan_hash_with_new_inventory(tmp_path):
    from ki_tools_common.flow import receipts
    raw = tmp_path / 'raw.dat'
    raw.write_bytes(b'legacy data')
    receipts.record_download(tmp_path, item_id='forcing', source='A', request_url='https://a.test/data',
        http_status=200, raw_files=[raw], approval_sha256='unchanged-plan-hash')
    result = receipts.evidence(tmp_path, {'steps': []}, {'plan_sha256': 'unchanged-plan-hash'},
        inventory={'items': [{'id': 'forcing', 'dataset_id': 'B'}]})
    assert result['downloads_bound'] == 0


def test_declared_inputs_drive_the_data_groups(tmp_path):
    """Step 4: the KI's declaration, not the agent's status fields, decides fetch / you / run."""
    from ki_tools_common.flow import declared as D
    ki = tmp_path / "ki"; (ki / "s4_initial_conditions" / "tools").mkdir(parents=True)
    (ki / "dag.yaml").write_text("""
inputs:
  forcing:
    - {name: air_temperature, unit: degC, source_kind: forcing, model_input_format: ".wea"}
  initial_conditions:
    - {name: soil_moisture_profile, unit: fraction, source_kind: user_provided, model_input_format: ".moi", notes: ">=2 profiles"}
    - {name: measured_snow_course, unit: m, source_kind: user_provided, model_input_format: ".snw"}
  parameters:
    - {name: soil_texture (sand/silt/clay), unit: percent, source_kind: dataset_lookup, model_input_format: ".sit"}
""")
    (ki / "s4_initial_conditions" / "tools" / "set_initial_conditions.py").write_text('OUT = "trial.moi"\n')
    decl = D.declared_inputs(str(ki))
    assert [d["default_tool"] for d in decl] == [None, "s4_initial_conditions/tools/set_initial_conditions.py", None, None]
    produced = {"made_by_step"}
    cases = {
        # agent said needs_user, KI says user_provided with a default tool -> run/default
        "initial_profiles_ic": ({"id": "initial_profiles_ic", "status": "missing", "needs_user": True}, "run", "default"),
        # user_provided, no tool writes .snw -> you/provide with instructions
        "measured_snow_course": ({"id": "measured_snow_course", "status": "missing"}, "you", "provide"),
        # forcing declared, nothing pinned -> you/choose
        "meteorology_daily": ({"id": "meteorology_daily", "status": "missing", "needs_user": True}, "you", "choose"),
        # lookup -> run/prepared regardless of agent fields
        "soil_texture_hwsd": ({"id": "soil_texture_hwsd", "status": "missing", "needs_user": True}, "run", "prepared"),
        # catalogue delivery wins
        "obs": ({"id": "obs", "delivery": "served", "dataset_id": "x"}, "fetch", "served"),
        "baidu": ({"id": "baidu", "delivery": "manual", "dataset_id": "y"}, "you", "manual"),
        # step output wins over everything else
        "made_by_step": ({"id": "made_by_step", "status": "missing", "needs_user": True}, "run", "generated"),
        # unknown to the KI, nothing pinned, no step -> prepared during the run (not "missing")
        "shaw_input_bundle": ({"id": "shaw_input_bundle", "status": "missing"}, "run", "prepared"),
    }
    for iid, (item, group, how) in cases.items():
        v = D.classify(item, decl, produced)
        assert (v["group"], v["how"]) == (group, how), (iid, v)
    v = D.classify(cases["measured_snow_course"][0], decl, produced)
    text = D.instructions(cases["measured_snow_course"][0], v)
    assert "format .snw" in text and "inputs/user/measured_snow_course" in text
    v = D.classify(cases["initial_profiles_ic"][0], decl, produced)
    assert "set_initial_conditions.py" in D.instructions(cases["initial_profiles_ic"][0], v)
    # the agent may still hand an item to the user explicitly
    v = D.classify({"id": "initial_profiles_ic", "decision": "user"}, decl, produced)
    assert (v["group"], v["how"]) == ("you", "provide")
