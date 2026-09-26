"""flowrun: the desktop turn under the flow — resolution, planning turn, approval card,
execution turn, evidence. No agent is spawned; the API provider path is exercised through
the same objects gui.py uses (fake catalogue, fake KI, fake cfg)."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "kiss"))

from kiss_cli import api, flowgate, flowrun, gui, obs_access, projectrun, sessions, setup as setup_flow  # noqa: E402


@pytest.fixture(autouse=True)
def _keys(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path_factory.mktemp("keys")))


def _ki(tmp_path, name):
    root = tmp_path / "kis" / name
    (root / "tools").mkdir(parents=True)
    (root / "SKILL.md").write_text(f"# {name}\n> **MANDATORY EXECUTION POLICY**\n> run the real model\n\n")
    (root / "dag.yaml").write_text("outputs:\n- var: discharge\n  validation_rank: 1\n  unit: m3/s\n"
                                   "processes:\n  modules:\n  - id: run\n    inputs: []\n    outputs: [discharge]\n")
    (root / "tools" / "run.py").write_text(
        "import sys, pathlib\nout = pathlib.Path(sys.argv[1]); out.parent.mkdir(parents=True, exist_ok=True)\n"
        "out.write_text('t,q\\n1,0.5\\n2,1.2\\n3,0.8\\n')\n")
    return SimpleNamespace(name=name, root=root)


def _project(tmp_path):
    p = tmp_path / "project"; (p / "runs").mkdir(parents=True)
    return p


def _cfg(project):
    return SimpleNamespace(root=project, python=sys.executable, roles={"binaries": project / "bin"})


def test_pre_ungated_for_small_talk_and_gated_for_science(tmp_path):
    project = _project(tmp_path); cat = [_ki(tmp_path, "VIC"), _ki(tmp_path, "CaMa_Flood")]
    r = flowrun.pre(project, "hello, what can you do?", [], cat, None, None)
    assert r.gated is False and not (project / "runs" / "flow-state.json").exists()
    r = flowrun.pre(project, "run VIC–CaMa flood at Bengbu 2003-2005", [], cat, None, None,
                    couplings_dir=None)
    assert r.gated and r.names == [] and r.message is None
    st = json.loads((project / "runs" / "flow-state.json").read_text())
    assert st["state"] == "RESOLVING_KIS"
    assert projectrun.load(project)["stage"] == "understanding"
    reply = ('<!-- GEOFORGE_INTAKE {"selected_kis":["VIC","CaMa_Flood"],'
             '"ready_for_planning":true,"understanding":"VIC-CaMa flood at Bengbu",'
             '"study_area":"Bengbu","period":"2003-2005","process":"rainfall-runoff and routing",'
             '"scenario":"baseline","requested_outputs":["discharge"],"missing":[]} -->')
    assert flowrun.promote_auto_choice(project, cat, reply) == ["VIC", "CaMa_Flood"]
    st = json.loads((project / "runs" / "flow-state.json").read_text())
    assert st["state"] == "PLANNING" and st["selected_kis"] == ["VIC", "CaMa_Flood"]
    assert projectrun.load(project)["selected_kis"] == ["VIC", "CaMa_Flood"]


def test_unknown_model_is_clarified_by_agent_intake_not_host_regex(tmp_path):
    project = _project(tmp_path); cat = [_ki(tmp_path, "VIC")]
    r = flowrun.pre(project, "run VIC-CaMa flood", [], cat, None, None)
    assert r.message is None and r.names == []
    assert json.loads((project / "runs" / "flow-state.json").read_text())["state"] == "RESOLVING_KIS"
    reply = ('I can use VIC, but CaMa is not in this library. Should I continue with VIC only? '
             '<!-- GEOFORGE_INTAKE {"selected_kis":["VIC"],"ready_for_planning":false,'
             '"understanding":"VIC-CaMa flood study","study_area":"","period":"",'
             '"process":"rainfall-runoff and routing","scenario":"",'
             '"requested_outputs":["discharge"],"missing":["whether VIC-only is acceptable"]} -->')
    assert flowrun.promote_auto_choice(project, cat, reply) == []
    assert json.loads((project / "runs" / "flow-state.json").read_text())["state"] == "RESOLVING_KIS"


def test_private_intake_marker_is_removed_from_saved_chat_text():
    reply = ('目标理解\n\n请告诉我具体流域。\n'
             '<!-- GEOFORGE_INTAKE {"selected_kis":["CRHM"],'
             '"ready_for_planning":false,"missing":["具体流域"]} -->')

    visible = flowrun.strip_intake_markers(reply)

    assert visible.strip() == "目标理解\n\n请告诉我具体流域。"
    assert "GEOFORGE_INTAKE" not in visible


def test_pre_accepts_crhm_embedded_in_chinese_scientific_request(tmp_path):
    project = _project(tmp_path)
    cat = [_ki(tmp_path, "CRHM")]
    r = flowrun.pre(project, "我想要用CRHM模拟中国高寒区融雪径流", [], cat,
                    None, None)
    assert r.gated and r.names == [] and r.message is None
    st = json.loads((project / "runs" / "flow-state.json").read_text())
    assert st["state"] == "RESOLVING_KIS"
    reply = ('我理解为使用 CRHM 研究中国高寒区融雪径流。请给出模拟时段和具体流域。 '
             '<!-- GEOFORGE_INTAKE {"selected_kis":["CRHM"],"ready_for_planning":false,'
             '"understanding":"使用 CRHM 模拟中国高寒区融雪径流",'
             '"study_area":"中国高寒区（具体流域待定）","period":"",'
             '"process":"积雪积累、融雪与径流形成","scenario":"",'
             '"requested_outputs":["融雪量","径流过程"],'
             '"missing":["具体流域或空间范围","模拟时段"]} -->')
    assert flowrun.promote_auto_choice(project, cat, reply) == []
    intake = projectrun.load(project)["intake"]
    assert intake["process"] == "积雪积累、融雪与径流形成" and not intake["ready_for_planning"]


def test_pinned_ki_does_not_treat_dataset_acronyms_as_unknown_models(tmp_path):
    project = _project(tmp_path)
    cat = [_ki(tmp_path, "AquaCrop")]

    result = flowrun.pre(
        project,
        "Run AquaCrop with NASA POWER API weather, DEM and CMFD comparison",
        ["AquaCrop"], cat, None, None,
    )

    assert result.gated and result.names == ["AquaCrop"]
    state = json.loads((project / "runs" / "flow-state.json").read_text())
    assert state["state"] == "PLANNING"
    assert state["selected_kis"] == ["AquaCrop"]


def test_pinned_ki_is_not_expanded_by_negated_models_or_alias_collisions(tmp_path):
    project = _project(tmp_path)
    cat = [_ki(tmp_path, "VIC"), _ki(tmp_path, "CaMa_Flood"),
           _ki(tmp_path, "Cell2Fire")]

    result = flowrun.pre(
        project,
        "Run a single grid cell with VIC; do not invoke CaMa-Flood",
        ["VIC"], cat, None, None,
    )

    assert result.gated and result.names == ["VIC"]
    state = json.loads((project / "runs" / "flow-state.json").read_text())
    assert state["state"] == "PLANNING"
    assert state["selected_kis"] == ["VIC"]


def test_agent_intake_can_resolve_chinese_crhm_task_into_semantic_plan(tmp_path):
    project = _project(tmp_path)
    cat = [_ki(tmp_path, "CRHM")]
    goal = "我想要用CRHM模拟中国高寒区融雪径流"
    r = flowrun.pre(project, goal, [], cat, None, None)
    assert r.names == [] and r.message is None
    reply = ('<!-- GEOFORGE_INTAKE {"selected_kis":["CRHM"],"ready_for_planning":true,'
             '"understanding":"使用 CRHM 模拟祁连山流域 2001-2010 年融雪径流",'
             '"study_area":"中国祁连山某流域","period":"2001-2010",'
             '"process":"积雪积累、能量平衡融雪与径流形成","scenario":"历史基准",'
             '"requested_outputs":["SWE","融雪量","出口径流"],"missing":[]} -->')
    assert flowrun.promote_auto_choice(project, cat, reply) == ["CRHM"]
    t = flowrun.turn(project, cat, _cfg(project), "api", "deepseek", None, goal)
    pj, _ = t.session.flow.plan.read_artifacts(project)
    assert pj["intent"]["study_area"] == "中国祁连山某流域"
    assert pj["intent"]["period"] == "2001-2010"
    assert pj["intent"]["process"] == "积雪积累、能量平衡融雪与径流形成"
    assert pj["intent"]["requested_outputs"] == ["SWE", "融雪量", "出口径流"]


def _drive_planning(tmp_path, ki, project, with_choice=False):
    resolved = [ki]
    t = flowrun.turn(project, resolved, _cfg(project), "api", "deepseek", None,
                     "run M at 32.9, 117.4 for 2003-2004")
    assert t is not None and t.execute is False and "INSPECT mode" in t.extra_prompt
    assert "PLAN DRAFT" in t.extra_prompt and (project / "runs" / "plan.json").exists()
    # the agent "corrects" the draft: fill the tool, keep everything resolved
    pj, inv = t.session.flow.plan.read_artifacts(project)
    for st in pj["steps"]:
        st["tool"] = str(ki.root / "tools" / "run.py"); st["kind"] = "run"
    if with_choice:
        pj["scientific_choices"] = [{"id": "f", "kind": "forcing_source", "options": ["cmfd_v1", "mswx_v1"],
                                     "picked": "cmfd_v1", "high_impact": True}]
    for it in inv["items"]:
        it["status"] = "resolved"; it["needs_user"] = False
    errs = t.session.write_plan(pj, inv)
    assert errs == [], errs
    return t


def _approve(project, kis, res, setup_ok=True):
    """The user's click on the approval card; nothing else approves a plan."""
    kis = kis if isinstance(kis, list) else [kis]
    assert res.request and res.request["id"].startswith(flowrun.APPROVAL_REQUEST_ID_PREFIX)
    return flowrun.pre(project, "Approved. Start the execution.", [k.name for k in kis], kis,
                       {"request_id": res.request["id"], "option_id": "approve"},
                       res.request, setup_ok=setup_ok)


def test_planning_turn_then_user_approval_then_execution_and_evidence(tmp_path):
    project = _project(tmp_path); ki = _ki(tmp_path, "M")
    flowrun.pre(project, "run M at 32.9, 117.4 for 2003-2004", ["M"], [ki], None, None)
    t = _drive_planning(tmp_path, ki, project)
    res = flowrun.after(project, t, "I wrote the plan.", setup_ok=True)
    # never auto-approved: the card waits for the user even when nothing needs deciding
    assert res.request is not None and res.continue_now is False
    assert json.loads((project / "runs" / "flow-state.json").read_text())["state"] == "WAITING_FOR_USER"
    _approve(project, ki, res)
    st = json.loads((project / "runs" / "flow-state.json").read_text())
    assert st["state"] == "EXECUTING" and (project / "runs" / "approval.json").exists()
    assert json.loads((project / "runs" / "approval.json").read_text())["approved_by"] == "user"
    # execution turn: run contract, receipts required
    t2 = flowrun.turn(project, [ki], _cfg(project), "api", "deepseek", None, "go")
    assert t2.execute is True and "STAGE GROUNDING" in t2.extra_prompt and "TOOLS (validated)" in t2.extra_prompt
    step = t2.session.plan["steps"][0]["id"]
    out = api.execute_tool("run_ki_tool", {"tool_path": "tools/run.py", "arguments": ["outputs/q.csv"],
                                           "plan_step_id": step}, ki, _cfg(project), project_mode=True,
                           flow=t2.session)
    assert "[RECEIPT]" in out
    res = flowrun.after(project, t2, "done", setup_ok=True)
    st = json.loads((project / "runs" / "flow-state.json").read_text())
    assert st["state"] == "COMPLETED", st
    ev = json.loads((project / "runs" / "evidence.json").read_text())
    assert ev["receipts_verified"] and ev["validation"] == "passed"
    assert projectrun.load(project)["stage"] == "results"


def test_high_impact_choice_shows_the_approval_card_and_click_approves(tmp_path):
    project = _project(tmp_path); ki = _ki(tmp_path, "M")
    flowrun.pre(project, "run M for 2003", ["M"], [ki], None, None)
    t = _drive_planning(tmp_path, ki, project, with_choice=True)
    res = flowrun.after(project, t, "plan written", setup_ok=True)
    assert res.request and res.request["id"].startswith(flowrun.APPROVAL_REQUEST_ID_PREFIX)
    assert {o["id"] for o in res.request["options"]} == {"approve", "modify"}
    assert "You decide" in res.request["message"] and "forcing_source" in res.request["message"]
    assert json.loads((project / "runs" / "flow-state.json").read_text())["state"] == "WAITING_FOR_USER"
    assert projectrun.load(project)["status"] == "waiting_for_user"
    pending = setup_flow.request(project)
    assert pending and pending["id"] == res.request["id"]
    # the user clicks approve
    r = flowrun.pre(project, "Approved. Start the execution.", ["M"], [ki],
                    {"request_id": pending["id"], "option_id": "approve", "note": "use cmfd"}, pending,
                    note="use cmfd", setup_ok=True)
    st = json.loads((project / "runs" / "flow-state.json").read_text())
    assert st["state"] == "EXECUTING" and r.message is None
    a = json.loads((project / "runs" / "approval.json").read_text())
    assert a["approved_by"] == "user"
    # the signed approval now carries WHO decided each input (flow.decisions), the note included
    assert a["decisions"]["note"]["value"] == "use cmfd" and a["decisions"]["note"]["source"] == "user"
    assert a["decisions"]["choice:f"]["source"] == "ki_default"   # the planner pick, accepted by approving
    assert setup_flow.request(project) is None


def test_modify_click_goes_back_to_planning_with_the_note(tmp_path):
    project = _project(tmp_path); ki = _ki(tmp_path, "M")
    flowrun.pre(project, "run M for 2003", ["M"], [ki], None, None)
    t = _drive_planning(tmp_path, ki, project, with_choice=True)
    res = flowrun.after(project, t, "plan written", setup_ok=True)
    pending = setup_flow.request(project)
    r = flowrun.pre(project, "Please revise the plan.", ["M"], [ki],
                    {"request_id": pending["id"], "option_id": "modify", "note": "use MSWX"}, pending, note="use MSWX")
    assert r.replan_reason == "use MSWX"
    assert json.loads((project / "runs" / "flow-state.json").read_text())["state"] == "PLANNING"
    t = flowrun.turn(project, [ki], _cfg(project), "api", "deepseek", None, "revise", replan_reason="use MSWX")
    assert "[RE-PLAN]" in t.extra_prompt and "use MSWX" in t.extra_prompt


def test_approval_without_verified_software_goes_to_setup(tmp_path):
    project = _project(tmp_path); ki = _ki(tmp_path, "M")
    flowrun.pre(project, "run M for 2003", ["M"], [ki], None, None)
    t = _drive_planning(tmp_path, ki, project)
    res = flowrun.after(project, t, "plan written", setup_ok=False)
    assert res.continue_now is False
    _approve(project, ki, res, setup_ok=False)
    assert json.loads((project / "runs" / "flow-state.json").read_text())["state"] == "SETUP_REQUIRED"
    st = flowrun.setup_turn(project, [ki], _cfg(project), "cli", "claude")
    assert json.loads((project / "runs" / "flow-state.json").read_text())["state"] == "SETUP_RUNNING"
    flowrun.setup_verified(project, [ki], _cfg(project))
    # codex R2 #2: verification resumes straight into EXECUTING (APPROVED is passed through)
    assert json.loads((project / "runs" / "flow-state.json").read_text())["state"] == "EXECUTING"


def test_executing_turn_detects_drift_and_replan_marker(tmp_path):
    project = _project(tmp_path); ki = _ki(tmp_path, "M")
    flowrun.pre(project, "run M for 2003", ["M"], [ki], None, None)
    t = _drive_planning(tmp_path, ki, project)
    _approve(project, ki, flowrun.after(project, t, "plan written", setup_ok=True))
    # the agent says it needs another model → re-plan
    t2 = flowrun.turn(project, [ki], _cfg(project), "api", "deepseek", None, "go")
    flowrun.after(project, t2, "I cannot do this: REPLAN_REQUIRED: routing needs CaMa_Flood", setup_ok=True)
    assert json.loads((project / "runs" / "flow-state.json").read_text())["state"] == "REPLAN_REQUIRED"
    assert not (project / "runs" / "approval.json").exists()


def test_cli_policy_and_worktree_for_codex(tmp_path):
    project = _project(tmp_path); ki = _ki(tmp_path, "M")
    flowrun.pre(project, "run M for 2003", ["M"], [ki], None, None)
    (project / "outputs").mkdir(); (project / "outputs" / "old.csv").write_text("1")
    t = flowrun.turn(project, [ki], _cfg(project), "cli", "codex", None, "run M for 2003")
    assert t.planning_worktree is not None and t.planning_worktree.is_dir()
    assert not (t.planning_worktree / "outputs").exists()          # outputs never copied
    assert (t.planning_worktree / "runs" / "plan.json").exists()
    assert t.policy.enforcement.value == "approximate" and t.policy.planning_worktree
    tc = flowrun.turn(project, [ki], _cfg(project), "cli", "claude", None, "run M for 2003")
    assert tc.planning_worktree is None and tc.policy.argv_delta[0] == "--allowedTools"
    assert "--dangerously-skip-permissions" in tc.policy.drop_flags


def test_database_access_modes_choose_one_planning_surface(tmp_path):
    direct_project = _project(tmp_path / "direct")
    direct_ki = _ki(tmp_path / "direct", "M")
    flowrun.pre(direct_project, "run M for 2003", ["M"], [direct_ki], None, None)
    direct = flowrun.turn(
        direct_project, [direct_ki], _cfg(direct_project), "cli", "kimi", None,
        "run M for 2003", database_access_mode="direct")
    assert "query the live GeoForge Database" in direct.extra_prompt
    assert direct.wrappers["obs_search"] in direct.extra_prompt
    assert "CACHED CATALOGUE MODE" not in direct.extra_prompt

    snapshot_project = _project(tmp_path / "snapshot")
    snapshot_ki = _ki(tmp_path / "snapshot", "M")
    flowrun.pre(snapshot_project, "run M for 2003", ["M"], [snapshot_ki], None, None)
    snapshot = flowrun.turn(
        snapshot_project, [snapshot_ki], _cfg(snapshot_project), "cli", "kimi", None,
        "run M for 2003", database_access_mode="snapshot")
    assert "CACHED CATALOGUE MODE" in snapshot.extra_prompt
    assert "obs_search" not in snapshot.wrappers
    assert "query the live GeoForge Database" not in snapshot.extra_prompt

    off_project = _project(tmp_path / "off")
    off_ki = _ki(tmp_path / "off", "M")
    flowrun.pre(off_project, "run M for 2003", ["M"], [off_ki], None, None)
    off = flowrun.turn(
        off_project, [off_ki], _cfg(off_project), "api", "deepseek", None,
        "run M for 2003", database_access_mode="off")
    assert "GEOFORGE DATABASE: DISABLED" in off.extra_prompt
    assert "search_observation_data" not in off.session.api_tools()


def test_project_view_labels_unvalidated_artifacts_under_the_flow(tmp_path):
    from kiss_cli import projectview
    project = _project(tmp_path); ki = _ki(tmp_path, "M")
    (project / "artifacts").mkdir()
    (project / "artifacts" / "handmade.svg").write_text("<svg/>")
    # no flow yet: no labels
    assert "evidence" not in projectview._automatic(project)["panels"][0]
    flowrun.pre(project, "run M for 2003", ["M"], [ki], None, None)
    view = projectview._automatic(project)
    assert view["panels"][0]["evidence"] == "unvalidated" and "unvalidated" in view["panels"][0]["title"]
    # a verified run output is labelled verified
    t = _drive_planning(tmp_path, ki, project)
    _approve(project, ki, flowrun.after(project, t, "planned", setup_ok=True))
    t2 = flowrun.turn(project, [ki], _cfg(project), "api", "deepseek", None, "go")
    step = t2.session.plan["steps"][0]["id"]
    api.execute_tool("run_ki_tool", {"tool_path": "tools/run.py", "arguments": ["artifacts/q.csv"],
                                     "plan_step_id": step}, ki, _cfg(project), project_mode=True, flow=t2.session)
    view = projectview._automatic(project)
    by = {p["path"]: p["evidence"] for p in view["panels"]}
    assert by["artifacts/q.csv"] == "verified" and by["artifacts/handmade.svg"] == "unvalidated"


def test_auto_turn_is_read_only_and_refuses_ungateable_providers(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    project = _project(tmp_path)
    flowrun.pre(project, "simulate the flood at Bengbu", [], [], None, None)   # nothing resolved
    assert json.loads((project / "runs" / "flow-state.json").read_text())["state"] == "RESOLVING_KIS"
    t = flowrun.auto_turn(project, "api", "deepseek")
    assert "run_ki_tool" not in t.session.api_tools() and "write_plan" not in t.session.api_tools()
    assert "report_project_progress" in t.session.api_tools()
    tc = flowrun.auto_turn(project, "cli", "claude")
    assert tc.policy.argv_delta[0] == "--allowedTools" and "Write(" not in tc.policy.argv_delta[1]
    assert Path(tc.wrappers["obs_search"]).name in {"geoforge-db", "geoforge-db.cmd"}
    assert f"Bash({tc.wrappers['obs_search']}:*)" in tc.policy.argv_delta[1]
    assert "run-tool" not in tc.policy.argv_delta[1]
    assert not tc.planning_worktree and not tc.policy.planning_worktree
    with pytest.raises(Exception, match="cannot be held to the planning gate"):
        flowrun.auto_turn(project, "cli", "gemini")

    disabled = flowrun.auto_turn(
        project, "api", "deepseek", database_access_mode="off")
    assert "search_observation_data" not in disabled.session.api_tools()
    disabled_cli = flowrun.auto_turn(
        project, "cli", "kimi", database_access_mode="off")
    assert disabled_cli.wrappers == {}


def test_gated_auto_api_receives_only_the_task_intake_contract(monkeypatch, tmp_path):
    """The API path used to drop the appended intake prompt and retain conflicting
    execution rules.  Exercise the actual Handler seam so this cannot regress silently."""
    project = _project(tmp_path)
    ki = _ki(tmp_path, "CRHM")
    ki.meta = {"reference": "Cold Regions Hydrological Model"}

    class Catalogue(list):
        models_dir = tmp_path / "kis"

    catalog = Catalogue([ki])
    pre = flowrun.pre(project, "我想要用CRHM模拟中国高寒区融雪径流", [], catalog,
                      None, None)
    handler = object.__new__(gui.Handler)
    handler.catalog = catalog
    handler.workroot = tmp_path
    handler._status_for = lambda _ki: {"label": "Verified", "can_run": True}
    captured = {}

    def fake_run(_provider, _ki, _cfg, system, task, **kwargs):
        captured.update(system=system, task=task, flow=kwargs.get("flow"))
        yield "请提供具体流域和模拟时段。"

    monkeypatch.setattr(api, "run", fake_run)
    pieces = []
    handler._chat_auto(
        "api:deepseek", "USER: 我想要用CRHM模拟中国高寒区融雪径流",
        lambda piece: pieces.append(piece) or True, project,
        bare_task="我想要用CRHM模拟中国高寒区融雪径流", flow_pre=pre,
    )
    assert captured["task"] == "我想要用CRHM模拟中国高寒区融雪径流"
    assert "[TASK UNDERSTANDING — NO EXECUTION]" in captured["system"]
    assert "The user's message is a scientific goal" in captured["system"]
    assert "search_catalogue tool" in captured["system"]
    assert "Search only: do not download during intake" in captured["system"]
    assert "[AGENT-FIRST PROJECT PREPARATION]" not in captured["system"]
    assert "[KI CHOICE IS YOURS]" not in captured["system"]
    assert captured["flow"] is not None


def test_gated_auto_kimi_receives_live_database_command_and_narrow_grant(monkeypatch, tmp_path):
    project = _project(tmp_path)
    ki = _ki(tmp_path, "VIC")
    ki.meta = {"reference": "VIC"}

    class Catalogue(list):
        models_dir = tmp_path / "kis"

    catalogue = Catalogue([ki])
    pre = flowrun.pre(project, "simulate Bengbu runoff with real data", [], catalogue,
                      None, None)
    handler = object.__new__(gui.Handler)
    handler.catalog = catalogue
    handler.workroot = tmp_path
    handler._status_for = lambda _ki: {"label": "Verified", "can_run": True}

    launcher = tmp_path / ".kiss" / "bin" / "geoforge-flow"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\n")
    obs_command = f"{launcher} obs-search"
    monkeypatch.setattr(flowrun, "wrapper_commands", lambda: {
        "run_tool": f"{launcher} run-tool",
        "fetch": f"{launcher} fetch",
        "obs_search": obs_command,
        "obs_download": f"{launcher} obs-download",
    })
    monkeypatch.setattr(gui.settings, "database_access_mode", lambda: "direct")
    fake_provider = SimpleNamespace(name="kimi")
    monkeypatch.setattr(gui.providers, "available", lambda: [fake_provider])
    monkeypatch.setattr(gui.providers, "get", lambda _name: fake_provider)
    monkeypatch.setattr(gui.skilllib, "roots", lambda: [])
    monkeypatch.setattr(gui.calibration, "framework_root", lambda: None)
    captured = {}

    def fake_cli_turn(_provider, **kwargs):
        captured.update(kwargs)

    handler._cli_turn = fake_cli_turn
    handler._chat_auto(
        "cli:kimi", "USER: simulate Bengbu runoff with real data",
        lambda _piece: True, project,
        bare_task="simulate Bengbu runoff with real data", flow_pre=pre,
    )

    assert obs_command in captured["replay_prompt"]
    assert "Do not hunt for an MCP connector" in captured["replay_prompt"]
    assert str(launcher.parent.resolve()) in captured["extra_dirs"]
    assert "run-tool" not in captured["flow_policy"].argv_delta


def test_pinned_planning_receives_host_database_snapshot_in_snapshot_mode(monkeypatch, tmp_path):
    project = _project(tmp_path)
    ki = _ki(tmp_path, "VIC")
    ki.meta = {}

    class Catalogue(list):
        models_dir = tmp_path / "kis"

        def get(self, name):
            return next(item for item in self if item.name == name)

    catalog = Catalogue([ki])
    pre = flowrun.pre(project, "run VIC at Bengbu for 2003", ["VIC"], catalog,
                      None, None)
    handler = object.__new__(gui.Handler)
    handler.catalog = catalog
    handler.workroot = tmp_path
    handler.repo_root = None
    handler._status_for = lambda _ki: {"label": "Verified", "can_run": True}
    handler._session_workspace = lambda _project, model: (model, _cfg(project))
    handler._software_status_prompt = lambda _kis, _cfg: "Software is verified."
    captured = {}

    snapshot = project / obs_access.CATALOGUE_SNAPSHOT
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text(json.dumps({
        "schema_version": obs_access.CATALOGUE_SNAPSHOT_SCHEMA,
        "ok": True,
        "service": "GeoForge Database",
        "datasets": [{"id": "cmfd-bengbu", "variables": ["prec"]}],
    }))
    monkeypatch.setattr(obs_access, "prepare_catalogue_snapshot",
                        lambda _project: snapshot)
    monkeypatch.setattr(gui.settings, "database_access_mode", lambda: "snapshot")
    monkeypatch.setattr(gui.prompt, "compose_multi",
                        lambda *_args, **_kwargs: "KI contract")

    def fake_run(_provider, _ki, _cfg, system, task, **kwargs):
        captured.update(system=system, task=task, flow=kwargs.get("flow"))
        yield "I will compare cmfd-bengbu with the VIC input contract."

    monkeypatch.setattr(api, "run", fake_run)
    pieces = []
    handler._chat_with_models(
        ["VIC"], "api:deepseek", "run VIC at Bengbu for 2003",
        lambda piece: pieces.append(piece) or True, project,
        bare_task="run VIC at Bengbu for 2003", flow_pre=pre,
    )

    assert "[GEOFORGE DATABASE — HOST-OWNED DATA SERVICE]" in captured["system"]
    assert str(snapshot) in captured["system"]
    assert "no KI or Agent receives its token" in captured["system"]
    assert captured["flow"] is not None


def test_setup_is_deferred_until_approval(tmp_path):
    project = _project(tmp_path); ki = _ki(tmp_path, "M")
    assert flowrun.setup_allowed(project)                        # no flow yet: old behaviour
    flowrun.pre(project, "run M for 2003", ["M"], [ki], None, None)
    assert not flowrun.setup_allowed(project)                    # PLANNING: no compile grants
    t = _drive_planning(tmp_path, ki, project)
    res = flowrun.after(project, t, "planned", setup_ok=False)
    _approve(project, ki, res, setup_ok=False)                   # approved, software missing
    assert flowrun.setup_allowed(project)                        # SETUP_REQUIRED


def test_wrapper_commands_have_no_spaces_in_the_executable_path(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "GeoForge Desktop"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    w = flowrun.wrapper_commands()
    base = w["run_tool"].rsplit(" run-tool", 1)[0]
    assert " " not in base or base.startswith("'"), w
    if " " not in base:
        assert Path(base).is_file()
        assert "GeoForge Desktop.app" not in Path(base).read_text()
        assert "GEOFORGE_AGENT_FLOW_URL" in Path(base).read_text()


def test_provider_refusal_for_gemini_and_qwen():
    assert flowrun.provider_refusal("cli", "gemini") and flowrun.provider_refusal("cli", "qwen")
    assert flowrun.provider_refusal("cli", "claude") is None and flowrun.provider_refusal("api", "deepseek") is None


def test_setup_verified_resumes_into_executing_and_continues(tmp_path):
    project = _project(tmp_path); ki = _ki(tmp_path, "M")
    flowrun.pre(project, "run M for 2003", ["M"], [ki], None, None)
    t = _drive_planning(tmp_path, ki, project)
    res = flowrun.after(project, t, "planned", setup_ok=False)
    _approve(project, ki, res, setup_ok=False)                          # SETUP_REQUIRED
    st = flowrun.setup_turn(project, [ki], _cfg(project), "cli", "claude")
    flowrun.setup_verified(project, [ki], _cfg(project))
    assert json.loads((project / "runs" / "flow-state.json").read_text())["state"] == "EXECUTING"
    assert flowrun.after(project, st, "installed", setup_ok=True).continue_now is True


def test_auto_choice_is_promoted_into_the_flow(tmp_path):
    project = _project(tmp_path); cat = [_ki(tmp_path, "VIC"), _ki(tmp_path, "DSSAT")]
    flowrun.pre(project, "simulate the flood at Bengbu", [], cat, None, None)   # RESOLVING_KIS
    projectrun.report(project, {"status": "working", "summary": "picked", "selected_kis": ["VIC", "Nope"],
                                "intake": {"ready_for_planning": True,
                                           "understanding": "VIC flood simulation at Bengbu",
                                           "study_area": "Bengbu", "period": "2003-2005",
                                           "process": "rainfall-runoff", "scenario": "baseline",
                                           "requested_outputs": ["discharge"], "missing": []}})
    assert flowrun.promote_auto_choice(project, cat) == ["VIC"]
    st = json.loads((project / "runs" / "flow-state.json").read_text())
    assert st["state"] == "PLANNING" and st["selected_kis"] == ["VIC"]
    assert flowrun.promote_auto_choice(project, cat) == ["VIC"]           # idempotent


def test_run_ki_tool_checks_step_ki_and_tool_before_running(tmp_path):
    project = _project(tmp_path); a, b = _ki(tmp_path, "A"), _ki(tmp_path, "B")
    (a.root / "tools" / "other.py").write_text("print('x')")
    flowrun.pre(project, "run A and B for 2003", ["A", "B"], [a, b], None, None)
    t = flowrun.turn(project, [a, b], _cfg(project), "api", "deepseek", None, "run A and B")
    pj, inv = t.session.flow.plan.read_artifacts(project)
    pj["steps"] = [{"id": "A:run", "ki": "A", "tool": str(a.root / "tools" / "run.py"), "kind": "run",
                    "inputs": [], "outputs": [], "status": "planned"}]
    for it in inv["items"]:
        it["status"] = "resolved"; it["needs_user"] = False
    assert t.session.write_plan(pj, inv) == []
    _approve(project, [a, b], flowrun.after(project, t, "planned", setup_ok=True))
    t2 = flowrun.turn(project, [a, b], _cfg(project), "api", "deepseek", None, "go")
    with pytest.raises(api.ToolError, match="belongs to KI 'A'"):
        api.execute_tool("run_ki_tool", {"tool_path": "tools/run.py", "ki": "B", "plan_step_id": "A:run",
                                         "arguments": ["outputs/b.csv"]}, a, _cfg(project), project_mode=True, flow=t2.session)
    with pytest.raises(api.ToolError, match="approved for tool"):
        api.execute_tool("run_ki_tool", {"tool_path": "tools/other.py", "plan_step_id": "A:run",
                                         "arguments": ["outputs/o.csv"]}, a, _cfg(project), project_mode=True, flow=t2.session)
    assert not (project / "outputs").exists()                              # nothing ran
    names = {t["name"]: t for t in api.tool_schemas(a, project_mode=True, flow=t2.session)}
    assert "stage" not in names["report_project_progress"]["input_schema"]["properties"]


def test_setup_turn_keeps_the_desktop_setup_grants_on_cli(tmp_path):
    project = _project(tmp_path); ki = _ki(tmp_path, "M")
    flowrun.pre(project, "run M for 2003", ["M"], [ki], None, None)
    t = _drive_planning(tmp_path, ki, project)
    flowrun.after(project, t, "planned", setup_ok=False)                  # SETUP_REQUIRED
    st = flowrun.setup_turn(project, [ki], _cfg(project), "cli", "claude")
    assert st.kind == "setup" and flowrun.policy_for_cli(st, "claude", None) is None


def test_launcher_never_embeds_the_frozen_executable(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(sys, "executable", str(tmp_path / "GeoForge Desktop v1"))
    w1 = flowrun.wrapper_commands()["run_tool"].rsplit(" run-tool", 1)[0]
    monkeypatch.setattr(sys, "executable", str(tmp_path / "GeoForge Desktop v2"))
    w2 = flowrun.wrapper_commands()["run_tool"].rsplit(" run-tool", 1)[0]
    body = Path(w2).read_text()
    assert w1 == w2 and str(tmp_path / "GeoForge Desktop v2") not in body
    assert "GEOFORGE_AGENT_FLOW_URL" in body
    assert Path(w2).is_relative_to(tmp_path / "home")          # user-owned dir, never $TMPDIR


def test_wrapper_access_root_is_only_the_narrow_launcher_directory(tmp_path):
    launcher = tmp_path / ".kiss" / "bin" / "geoforge-flow"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\n")
    roots = flowrun.wrapper_access_roots({
        "obs_search": f"{launcher} obs-search",
        "unrelated": f"{sys.executable} -m kiss_cli",
    })
    assert roots == [str(launcher.parent.resolve())]


def test_database_ki_helper_uses_only_process_local_desktop_capability(
        monkeypatch, tmp_path):
    """The helper must not exec the app bundle or read a persistent DB token."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    token = "one-process-capability"
    gui.Handler.agent_database_token = token
    expected = {"ok": True, "datasets": [{"id": "bengbu_51080"}]}
    monkeypatch.setattr(obs_access, "search_catalogue", lambda **_kwargs: expected)
    server = gui.GeoForgeHTTPServer(("127.0.0.1", 0), gui.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        endpoint = (f"http://127.0.0.1:{server.server_port}"
                    "/api/agent/obs/catalogue")
        gui.Handler.agent_database_url = endpoint
        helper = flowrun._database_launcher_path()
        assert helper and helper.is_file()
        body = helper.read_text(encoding="utf-8")
        assert "GeoForge Desktop.app" not in body
        assert "GEOFORGE_OBS_TOKEN" not in body

        env = {"PATH": str(Path(sys.executable).parent),
               "GEOFORGE_AGENT_DATABASE_URL": endpoint,
               "GEOFORGE_AGENT_DATABASE_TOKEN": token}
        result = subprocess.run(
            [str(helper), "--query", "Bengbu 51080", "--limit", "5"],
            capture_output=True, text=True, env=env, timeout=10)
        assert result.returncode == 0
        assert json.loads(result.stdout) == expected

        projects = tmp_path / "projects"
        project = projects / "session-1"
        project.mkdir(parents=True)
        gui.Handler.workroot = projects
        flow_endpoint = (f"http://127.0.0.1:{server.server_port}"
                         "/api/agent/flow-command")
        gui.Handler.agent_flow_url = flow_endpoint
        launched = {}

        def fake_run(command, **kwargs):
            launched.update(command=command, kwargs=kwargs)
            return SimpleNamespace(returncode=0, stdout="[RECEIPT] {}\n", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        flow_request = urllib.request.Request(
            flow_endpoint,
            data=json.dumps({
                "argv": ["fetch", "https://example.test/data", "--item", "forcing"],
                "cwd": str(project),
            }).encode(),
            method="POST",
            headers={"X-GeoForge-Agent-Token": token,
                     "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(flow_request, timeout=5) as response:
            flow_result = json.load(response)
        assert flow_result["returncode"] == 0
        assert launched["command"][-4:] == [
            "fetch", "https://example.test/data", "--item", "forcing"]
        assert launched["kwargs"]["cwd"] == str(project)

        # A project chosen outside the default workroot is accepted only when
        # the Desktop's local session pointer binds that exact --<id> folder.
        sid = "abcdef012345"
        external = tmp_path / "external" / f"2026-test--{sid}"
        external.mkdir(parents=True)
        pointer = projects / "sessions" / f"{sid}.json"
        pointer.parent.mkdir(parents=True)
        pointer.write_text(json.dumps({
            "kind": "geoforge-project-pointer-v1", "id": sid,
            "project_root": str(external),
        }))
        assert sessions.registered_project_for_path(projects, external) == external.resolve()
        external_request = urllib.request.Request(
            flow_endpoint,
            data=json.dumps({
                "argv": ["fetch", "https://example.test/external", "--item", "forcing"],
                "cwd": str(external),
            }).encode(),
            method="POST",
            headers={"X-GeoForge-Agent-Token": token,
                     "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(external_request, timeout=5) as response:
            external_result = json.load(response)
        assert external_result["returncode"] == 0
        assert launched["kwargs"]["cwd"] == str(external)

        unregistered = tmp_path / "external" / "not-a-project"
        unregistered.mkdir()
        denied_external = urllib.request.Request(
            flow_endpoint,
            data=json.dumps({"argv": ["fetch", "https://example.test/x", "--item", "x"],
                             "cwd": str(unregistered)}).encode(),
            method="POST",
            headers={"X-GeoForge-Agent-Token": token,
                     "Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as denied:
            urllib.request.urlopen(denied_external, timeout=5)
        assert denied.value.code == 400

        request = urllib.request.Request(
            endpoint + "?q=Bengbu", headers={"X-GeoForge-Agent-Token": "wrong"})
        with pytest.raises(urllib.error.HTTPError) as denied:
            urllib.request.urlopen(request, timeout=5)
        assert denied.value.code == 401
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("provider", ["codex", "kimi", "claude"])
def test_untouched_draft_never_becomes_an_approval(tmp_path, provider):
    project = _project(tmp_path); ki = _ki(tmp_path, "M")
    flowrun.pre(project, "run M for 2003", ["M"], [ki], None, None)
    t = flowrun.turn(project, [ki], _cfg(project), "cli", provider, None, "run M for 2003")
    result = flowrun.after(project, t, "could not save")
    assert result.message and not result.request and not result.continue_now
    assert t.session.state.value == "PLANNING"
    assert not (project / "runs/approval.json").exists()


def test_failed_cli_with_saved_files_cannot_offer_approval(tmp_path):
    """A CLI that saved the plan files and then crashed: the files are unvalidated, so no card.
    (An API write_plan is validated by the host before it is written; see the test below.)"""
    project = _project(tmp_path); ki = _ki(tmp_path, "M")
    flowrun.pre(project, "run M for 2003", ["M"], [ki], None, None)
    t = flowrun.turn(project, [ki], _cfg(project), "api", "deepseek", None, "run M for 2003")
    pj, inv = t.session.flow.plan.read_artifacts(project)
    for st in pj["steps"]:
        st["tool"] = str(ki.root / "tools" / "run.py"); st["kind"] = "run"
    t.session.flow.plan.write_artifacts(project, pj, inv)     # saved by the CLI, never submitted
    t.provider_succeeded = False
    result = flowrun.after(project, t, "CLI exited 2")
    assert "failed" in result.message and result.request is None
    assert t.session.state.value == "PLANNING"


@pytest.mark.parametrize("changed", [True, False])
def test_worktree_handoff_preserves_reviewed_plan_even_if_unchanged(tmp_path, changed):
    project = _project(tmp_path); ki = _ki(tmp_path, "M")
    flowrun.pre(project, "run M for 2003", ["M"], [ki], None, None)
    t = flowrun.turn(project, [ki], _cfg(project), "cli", "kimi", None, "run M for 2003")
    wt = t.planning_worktree
    assert str(wt / "runs/plan.json") in t.extra_prompt
    pj, inv = t.session.flow.plan.read_artifacts(wt)
    if changed:
        pj["goal"] = "Reviewed by the agent"
    t.session.flow.plan.write_artifacts(wt, pj, inv)
    result = flowrun.after(project, t, "saved both")
    assert result.request and result.message == ""
    assert json.loads((project / "runs/plan.json").read_text()) == pj
    assert wt.is_dir()  # preserve submitted evidence


def test_concurrent_original_edit_is_not_overwritten(tmp_path):
    project = _project(tmp_path); ki = _ki(tmp_path, "M")
    flowrun.pre(project, "run M for 2003", ["M"], [ki], None, None)
    t = flowrun.turn(project, [ki], _cfg(project), "cli", "codex", None, "run M for 2003")
    pj, inv = t.session.flow.plan.read_artifacts(t.planning_worktree)
    t.session.flow.plan.write_artifacts(t.planning_worktree, pj, inv)
    pj["goal"] = "user concurrent edit"
    t.session.flow.plan.write_artifacts(project, pj, inv)
    result = flowrun.after(project, t, "saved")
    assert "original plan changed" in result.message and not result.request
    assert json.loads((project / "runs/plan.json").read_text())["goal"] == "user concurrent edit"


def test_review_card_cannot_approve_a_changed_inventory(tmp_path):
    project = _project(tmp_path); ki = _ki(tmp_path, "M")
    flowrun.pre(project, "run M for 2003", ["M"], [ki], None, None)
    t = _drive_planning(tmp_path, ki, project, with_choice=True)
    result = flowrun.after(project, t, "saved")
    pending = setup_flow.request(project)
    (project / "runs/data-inventory.json").write_text('{"schema_version":"1.0","items":[],"changed":true}')
    pre = flowrun.pre(project, "approve", ["M"], [ki],
                      {"request_id": pending["id"], "option_id": "approve"}, pending)
    assert pre.replan_reason and not (project / "runs/approval.json").exists()


@pytest.mark.parametrize("text", ["准备蚌埠站 VIC-CaMa，输入数据", "Prepare VIC-CaMa, input data"])
def test_preparation_intent_and_punctuation_select_both_models(tmp_path, text):
    project = _project(tmp_path); cat = [_ki(tmp_path, "VIC"), _ki(tmp_path, "CaMa_Flood")]
    pre = flowrun.pre(project, text, ["VIC"], cat, None, None)
    assert pre.gated and pre.names == ["VIC", "CaMa_Flood"]


def test_argv_replacement_removes_variadic_grants_and_equals_flags():
    from kiss_cli import providers
    args = ["--allowedTools", "Read(//x/**)", "Write(//x/**)", "--sandbox=workspace-write",
            "--sandbox", "danger-full-access", "--permission-mode", "bypassPermissions", "--verbose"]
    assert providers._strip_flags(args, ("--allowedTools", "--sandbox", "--permission-mode")) == ["--verbose"]


def test_claude_planning_paths_and_tool_surface(tmp_path):
    p = flowrun._flow().policy
    project = tmp_path / "带 空格的项目"; ki = _ki(tmp_path, "M")
    policy = p.for_state(flowrun._flow().states.State.PLANNING, "claude", project, {"M": ki.root})
    grants = policy.argv_delta[1]
    assert f"Write(/{project}/runs/plan.json)" in grants
    assert "Bash(" not in grants and "bypassPermissions" not in policy.argv_delta
    assert "dontAsk" not in policy.argv_delta and "dontAsk" in policy.argv_extra   # wall vs launcher flags
    assert p.claude_path(r"C:\Users\User Name\项目") == "//c/Users/User Name/项目"


def test_declared_legacy_stage_tool_is_not_arbitrary_code(tmp_path):
    from ki_tools_common.flow.tools import is_ki_tool
    ki = _ki(tmp_path, "M")
    stage = ki.root / "s1_grid"; stage.mkdir()
    tool = stage / "prepare.py"; tool.write_text("pass")
    assert not is_ki_tool(ki.root, tool)
    (ki.root / "SKILL.md").write_text("Run `s1_grid/prepare.py`.")
    assert is_ki_tool(ki.root, tool)
    outside = tmp_path / "outside.py"; outside.write_text("pass")
    (ki.root / "tools/escape.py").symlink_to(outside)
    assert not is_ki_tool(ki.root, ki.root / "tools/escape.py")
    assert not is_ki_tool(ki.root, ki.root / "SKILL.md")


def test_rejected_worktree_is_reused_then_validated_without_resetting_agent_work(tmp_path):
    project = _project(tmp_path); ki = _ki(tmp_path, "M")
    flowrun.pre(project, "run M for 2003", ["M"], [ki], None, None)
    t = flowrun.turn(project, [ki], _cfg(project), "cli", "kimi", None, "planning only")
    pj, inv = t.session.flow.plan.read_artifacts(t.planning_worktree)
    pj["goal"] = "Agent's carefully reviewed draft"
    pj["steps"][0]["inputs"] = ["missing-reference"]
    t.session.flow.plan.write_artifacts(t.planning_worktree, pj, inv)
    t.provider_succeeded = True
    rejected = flowrun.after(project, t, "saved")
    assert rejected.retry_planning and "missing-reference" in rejected.message
    t2 = flowrun.turn(project, [ki], _cfg(project), "cli", "kimi", None,
                      "planning only", replan_reason=rejected.message)
    recovered, recovered_inv = t2.session.flow.plan.read_artifacts(t2.planning_worktree)
    assert recovered == pj and recovered_inv == inv
    assert "missing-reference" in t2.extra_prompt
    recovered["steps"][0]["inputs"] = []
    t2.session.flow.plan.write_artifacts(t2.planning_worktree, recovered, recovered_inv)
    t2.provider_succeeded = True
    result = flowrun.after(project, t2, "repaired")
    assert result.request and not result.continue_now
    assert json.loads((project / "runs/plan.json").read_text())["goal"] == pj["goal"]
    assert not (project / ".geoforge/planning-last.json").exists()


def test_planning_only_never_auto_approves_even_a_fully_resolved_plan(tmp_path):
    project = _project(tmp_path); ki = _ki(tmp_path, "M")
    flowrun.pre(project, "run M for 2003", ["M"], [ki], None, None)
    t = _drive_planning(tmp_path, ki, project)
    t.confirmation_required = True
    result = flowrun.after(project, t, "saved")
    assert result.request and not result.continue_now
    assert not (project / "runs/approval.json").exists()


def test_partial_save_returns_to_agent_but_identical_failure_stops_repair(tmp_path):
    project = _project(tmp_path); ki = _ki(tmp_path, "M")
    flowrun.pre(project, "run M for 2003", ["M"], [ki], None, None)
    rejected_revisions = set()
    for attempt in range(2):
        t = flowrun.turn(project, [ki], _cfg(project), "cli", "kimi", None, "planning only")
        p = t.planning_worktree / "runs/plan.json"
        p.write_text(p.read_text())
        t.provider_succeeded = True
        result = flowrun.after(project, t, "I saved both (but actually only one)")
        assert result.retry_planning and "data-inventory.json" in result.message
        assert flowrun.claim_planning_repair(result, rejected_revisions) is (attempt == 0)
        assert not result.request and not (project / "runs/approval.json").exists()


def test_failed_provider_is_not_automatically_retried(tmp_path):
    project = _project(tmp_path); ki = _ki(tmp_path, "M")
    flowrun.pre(project, "run M for 2003", ["M"], [ki], None, None)
    t = flowrun.turn(project, [ki], _cfg(project), "cli", "codex", None, "planning only")
    t.provider_succeeded = False
    result = flowrun.after(project, t, "network failed")
    assert not flowrun.claim_planning_repair(result, set())


def test_approval_card_groups_inputs_by_what_happens_to_them():
    plan = {"steps": [{"id": "s1", "outputs": ["grid"]}]}
    inv = {"items": [
        {"id": "obs", "status": "resolved", "required_by": ["VIC"], "delivery": "served",
         "dataset_id": "bengbu_51080", "catalogue": {"size": 566225}},
        {"id": "forcing", "status": "resolved", "required_by": ["VIC"], "delivery": "manual",
         "dataset_id": "cmfd_huai_3hr_025", "catalogue": {"size": 7892006694}},
        {"id": "grid", "status": "missing", "required_by": ["VIC"]},
        {"id": "veglib", "status": "missing", "required_by": ["VIC"]},
        {"id": "local", "status": "ready", "required_by": ["VIC"]},
    ]}
    text = flowrun._data_summary(plan, inv)
    assert "Data: 5 inputs" in text
    assert "GeoForge fetches after approval (1)" in text and "bengbu_51080 (553 KB)" in text
    assert "you (1)" in text and "7.35 GB" in text and "Baidu link" in text
    # the host decides what the run prepares itself; the agent's "missing" is not a group
    assert "the run prepares itself (1 made by a step, 1 prepared during the run, 1 already on disk)" in text
    assert "missing" not in text


def test_desktop_draft_drops_server_era_sources():
    plan = {"scientific_choices": [
        {"id": "forcing_source:air_temperature", "kind": "forcing_source",
         "options": ["cmfd_v1", "mswx_v1"], "picked": "mswx_v1", "high_impact": True},
        {"id": "calibration_target", "kind": "calibration_target", "high_impact": True}]}
    inv = {"items": [
        {"id": "air_temperature", "status": "resolved", "strategy": "from_forcing_provider",
         "chosen_source": "mswx_v1", "acceptable_sources": ["cmfd_v1", "mswx_v1"],
         "needs_user": False, "agent_resolvable": True},
        {"id": "dem", "status": "resolved", "strategy": "from_dataset_lookup",
         "chosen_source": "china_dem_90m_server", "acceptable_sources": ["china_dem_90m_server"]},
        {"id": "obs_flow", "status": "missing", "strategy": "from_user", "chosen_source": None,
         "acceptable_sources": [], "needs_user": True, "agent_resolvable": False},
    ]}
    flowrun._localize_draft(plan, inv)
    temp, dem, obs = inv["items"]
    assert temp["status"] == "missing" and temp["chosen_source"] is None and temp["needs_user"] is False
    assert "GeoForge Database" in temp["acceptable_sources"][0]
    assert dem["chosen_source"] is None
    assert obs["needs_user"] is True                      # untouched
    assert [c["kind"] for c in plan["scientific_choices"]] == ["calibration_target"]


def test_answered_intake_question_promotes_without_a_second_report(tmp_path, monkeypatch):
    from kiss_cli import projectrun, setup as setup_flow
    project = tmp_path / "p"
    (project / "runs").mkdir(parents=True)
    flow = flowgate.load()
    flow.states.FlowContext.load(project).move("task_received")
    cat = [SimpleNamespace(name="VIC")]
    projectrun.report(project, {
        "status": "waiting_for_user", "summary": "understood",
        "selected_kis": ["VIC"],
        "intake": {"ready_for_planning": False, "understanding": "VIC at Bengbu",
                   "missing": ["single grid or full basin?"]},
    }, source="agent")
    doc = setup_flow.request_user(project, {"kind": "choice", "title": "scale?", "message": "A or B",
                                             "options": [{"id": "a", "label": "A", "response": "A"}]})
    assert flowrun.promote_auto_choice(project, cat, "prose without a marker") == []   # still waiting
    setup_flow.resume(project, "A")
    assert flowrun.promote_auto_choice(project, cat, "prose without a marker") == ["VIC"]
    assert flow.states.FlowContext.load(project).state is flow.states.State.PLANNING


def test_approval_card_carries_a_structured_plan_review(tmp_path):
    project = _project(tmp_path); ki = _ki(tmp_path, "M")
    flowrun.pre(project, "run M at 32.9, 117.4 for 2003-2004", ["M"], [ki], None, None)
    t = _drive_planning(tmp_path, ki, project, with_choice=True)
    res = flowrun.after(project, t, "planned", setup_ok=True)
    review = res.request["plan_review"]
    assert review["kis"] == ["M"] and review["goal"]
    assert [s["tool"] for s in review["steps"]] == ["run.py"] * len(review["steps"])
    assert set(review["data"]) == {"total", "fetch", "you", "run"}
    assert review["decisions"][0]["kind"] == "forcing_source" and review["decisions"][0]["decided"] is False
    assert review["blockers"]                      # the undecided high-impact choice
    saved = json.loads((project / "setup-request.json").read_text())
    assert saved["plan_review"]["steps"] == review["steps"]


def test_failed_validation_resumes_as_an_execution_turn(tmp_path):
    project = _project(tmp_path); ki = _ki(tmp_path, "M")
    flowrun.pre(project, "run M for 2003", ["M"], [ki], None, None)
    t = _drive_planning(tmp_path, ki, project)
    _approve(project, ki, flowrun.after(project, t, "planned", setup_ok=True))
    t2 = flowrun.turn(project, [ki], _cfg(project), "api", "deepseek", None, "go")
    t2.session.move("run_finished"); t2.session.move("validation_failed")   # a step's output failed checks
    assert json.loads((project / "runs" / "flow-state.json").read_text())["state"] == "FAILED_VALIDATION"
    # the user's next message reruns under the same approval (pre → rerun → ACQUIRING → EXECUTING)
    pre = flowrun.pre(project, "fix S1 and continue", ["M"], [ki], None, None)
    assert pre.message is None
    assert json.loads((project / "runs" / "flow-state.json").read_text())["state"] == "EXECUTING"
    t3 = flowrun.turn(project, [ki], _cfg(project), "api", "deepseek", None, "fix S1 and continue")
    assert t3.kind == "execution" and t3.execute is True


def test_replan_reason_and_state_helpers(tmp_path):
    assert flowrun.replan_reason_from("I cannot do this: REPLAN_REQUIRED: S1 needs a site polygon\nmore") == "S1 needs a site polygon"
    assert flowrun.replan_reason_from("REPLAN_REQUIRED：需要流域边界") == "需要流域边界"
    assert flowrun.replan_reason_from("all good") == ""
    assert flowrun.current_state(tmp_path / "nope") == "NEW"      # no flow yet
    project = _project(tmp_path); ki = _ki(tmp_path, "M")
    flowrun.pre(project, "run M for 2003", ["M"], [ki], None, None)
    assert flowrun.current_state(project) == "PLANNING"


def test_execution_turn_without_receipts_is_contradicted_in_chat(tmp_path):
    project = _project(tmp_path); ki = _ki(tmp_path, "M")
    flowrun.pre(project, "run M for 2003", ["M"], [ki], None, None)
    t = _drive_planning(tmp_path, ki, project)
    _approve(project, ki, flowrun.after(project, t, "planned", setup_ok=True))
    t2 = flowrun.turn(project, [ki], _cfg(project), "api", "deepseek", None, "go")
    assert t2.kind == "execution" and t2.started_at > 0
    res = flowrun.after(project, t2, "S1 done, outputs written to outputs/x.nc", setup_ok=True)
    assert "ran no receipted step" in res.message and "0 of" in res.message


def test_plan_data_status_reports_each_input_from_receipts_not_prose(tmp_path, monkeypatch):
    from kiss_cli import setup as setup_flow
    monkeypatch.setattr(obs_access, "refresh_catalogue", lambda: {"datasets": [
        {"id": "cmfd_x", "delivery": "manual"}]})
    project = _project(tmp_path); ki = _ki(tmp_path, "M")
    assert flowrun.plan_data_status(project) is None                 # no plan yet
    flowrun.pre(project, "run M for 2003", ["M"], [ki], None, None)
    t = _drive_planning(tmp_path, ki, project)
    # the agent pins a manual-delivery dataset before submitting the plan
    pj, inv = t.session.flow.plan.read_artifacts(project)
    inv["items"].append({"id": "cmfd_x", "required_by": ["M"], "status": "resolved", "dataset_id": "cmfd_x",
                         "delivery": "manual", "acceptable_sources": [], "chosen_source": "cmfd_x",
                         "local_paths": [], "agent_resolvable": True, "needs_user": False})
    pj["steps"][0]["inputs"] = list(pj["steps"][0].get("inputs") or []) + ["cmfd_x"]
    assert t.session.write_plan(pj, inv) == []
    from kiss_cli import acquire
    monkeypatch.setattr(acquire, "run", lambda project, client=None:      # no network in this test
                        {"status": "waiting", "items": {"cmfd_x": {"status": "waiting"}}})
    _approve(project, ki, flowrun.after(project, t, "planned", setup_ok=True))
    pd = flowrun.plan_data_status(project)
    assert pd is not None and pd["total"] == len(pd["items"])
    assert [i["status"] for i in pd["items"] if i["id"] == "cmfd_x"] == ["pending"]
    # GeoForge asks the user for the manual download: the item is attributed, the chat points there
    setup_flow.request_user(project, {"kind": "download", "title": "Download cmfd_x",
                                      "message": "m", "expected_path": str(project / "inputs/raw/cmfd")})
    pd = flowrun.plan_data_status(project)
    assert [i["status"] for i in pd["items"] if i["id"] == "cmfd_x"] == ["waiting_for_you"]
    # while the host waits for the files the project is in ACQUIRING: no agent turn, and any
    # message answers with the reminder that points to Project status (never the link itself)
    assert json.loads((project / "runs" / "flow-state.json").read_text())["state"] == "ACQUIRING"
    assert flowrun.turn(project, [ki], _cfg(project), "api", "deepseek", None, "go") is None
    monkeypatch.setattr(acquire, "run", lambda project, client=None:
                        {"status": "waiting", "items": {"cmfd_x": {"status": "waiting", "expected_path": str(project / "inputs/raw/cmfd")}}})
    pre = flowrun.pre(project, "which step are we at?", ["M"], [ki], None, None)
    assert "GeoForge needs you" in pre.message and "Project status" in pre.message
    assert "pan.baidu" not in pre.message


def test_plan_data_status_rejects_forged_deleted_and_changed_downloads(tmp_path, monkeypatch):
    project = _project(tmp_path)
    flow = flowrun._flow()
    payload = project / "inputs" / "forcing.nc"
    payload.parent.mkdir()
    payload.write_bytes(b"real downloaded bytes")
    inv = {"items": [{"id": "forcing", "dataset_id": "source-A", "status": "ready", "delivery": "served",
                       "required_by": [], "local_paths": [str(payload)]}]}
    plan = {"steps": [{"id": "M:run", "inputs": ["forcing"], "outputs": []}]}
    monkeypatch.setattr(flow.plan, "read_artifacts", lambda _p: (plan, inv))
    def status():
        return flowrun.plan_data_status(project)["items"][0]["status"]
    assert status() == "pending"  # existing bytes alone are not a served-download receipt
    receipt = flow.receipts.record_download(
        project, item_id="forcing", source="test", request_url="https://example.test/data",
        http_status=200, raw_files=[payload], approval_sha256="approved", inventory_item=inv["items"][0])
    assert status() == "done"
    inv["items"][0]["dataset_id"] = "source-B"
    assert status() == "pending"
    inv["items"][0]["dataset_id"] = "source-A"
    inv["items"][0]["requirements"] = {"start": "2000", "end": "2001"}
    assert status() == "pending"
    inv["items"][0].pop("requirements")
    assert status() == "done"
    original = receipt.read_text()
    forged = json.loads(original)
    forged["source"] = "tampered"
    receipt.write_text(json.dumps(forged))
    assert status() == "pending"
    receipt.write_text(original)
    payload.write_bytes(b"different bytes")
    assert status() == "pending"
    payload.unlink()
    assert status() == "pending"


def test_plan_data_status_does_not_mark_empty_local_directory_ready(tmp_path, monkeypatch):
    project = _project(tmp_path)
    directory = project / "inputs"
    directory.mkdir()
    inv = {"items": [{"id": "local", "status": "ready", "required_by": [],
                       "local_paths": [str(directory)]}]}
    monkeypatch.setattr(flowrun._flow().plan, "read_artifacts", lambda _p: ({"steps": []}, inv))
    assert flowrun.plan_data_status(project)["items"][0]["status"] == "pending"
    (directory / "data.nc").write_bytes(b"local data")
    assert flowrun.plan_data_status(project)["items"][0]["status"] == "done"


def test_provided_input_is_done_once_files_sit_at_its_target_path(tmp_path, monkeypatch):
    """2026-09-19: "Add source data" put files in inputs/uploads while the card said
    inputs/user/<id>; the row never changed. Now the per-row upload lands there and counts."""
    project = _project(tmp_path)
    inv = {"items": [{"id": "site_geometry", "status": "missing", "required_by": ["M"],
                      "decision": "user", "needs_user": True}]}
    plan = {"steps": [{"id": "s1", "inputs": ["site_geometry"], "outputs": []}]}
    monkeypatch.setattr(flowrun._flow().plan, "read_artifacts", lambda _p: (plan, inv))
    row = flowrun.plan_data_status(project)["items"][0]
    assert (row["how"], row["status"], row["target_path"]) == ("provide", "waiting_for_you", "inputs/user/site_geometry")
    (project / "inputs/user/site_geometry").mkdir(parents=True)
    (project / "inputs/user/site_geometry/.DS_Store").write_bytes(b"")
    assert flowrun.plan_data_status(project)["items"][0]["status"] == "waiting_for_you"
    (project / "inputs/user/site_geometry/site.csv").write_text("lat,lon\n")
    assert flowrun.plan_data_status(project)["items"][0]["status"] == "done"


def test_data_actions_distinguish_manual_agent_and_coverage_gap(tmp_path, monkeypatch):
    project = _project(tmp_path)
    requirements = {"bbox": [117, 32, 118, 33], "start": "1989", "end": "1990"}
    record = {"bbox": [110, 30, 120, 35], "start_date": "1980", "end_date": "2000"}
    items = [{"id": delivery, "status": "resolved", "required_by": [],
              "delivery": delivery, "requirements": requirements, "catalogue": record}
             for delivery in ("served", "manual")]
    items.append({**items[0], "id": "short", "catalogue": {**record, "end_date": "1989"}})
    items.append({**items[0], "id": "unspecified", "requirements": {}})
    monkeypatch.setattr(flowrun._flow().plan, "read_artifacts", lambda _p: ({"steps": []}, {"items": items}))
    rows = {r["id"]: r for r in flowrun.plan_data_status(project)["items"]}
    assert rows["served"]["action"] == "agent_download"
    assert rows["manual"]["action"] == "manual_download"
    assert rows["short"]["action"] == "choose_data"
    assert rows["unspecified"]["action"] == "check_coverage"


# ---------------------------------------------------------------------------
# Step 2 (FLOW-TARGET-2026-09-17): one card approves the plan and its server clips.


def _clip_client(*responses):
    from .test_obs_access import Opener, json_response
    from kiss_cli.obs_access import Client
    return Client(opener=Opener(*[json_response(r) for r in responses]), token_getter=lambda: "tok")


_EST = {"subsettable": True, "estimated_output_bytes": 4096, "over_output_cap": False,
        "coverage_complete": True, "missing": [], "transformations": [], "n_parts": 2,
        "snapped_output_bounds": [115, 37, 117, 39], "variables": ["prec"],
        "processing_version": "obs_subset/3", "source_version": "v1"}


def _plan_with_clip(tmp_path, ki, project, monkeypatch, *refresh_responses):
    from kiss_cli import obs_subset, obs_access
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    # the catalogue lookup for non-clip items must not touch the network
    monkeypatch.setattr(obs_access, "refresh_catalogue", lambda *a, **k: {"datasets": []})
    flowrun.pre(project, "run M at 32.9, 117.4 for 2003-2004", ["M"], [ki], None, None)
    t = flowrun.turn(project, [ki], _cfg(project), "api", "deepseek", None, "run M at 32.9, 117.4 for 2003-2004")
    body = {"dataset_id": "cmfd_china_daily_010", "bbox": [115, 37, 117, 39],
            "variables": ["prec"], "start": "1989-01-01", "end": "1989-12-31"}
    est = obs_subset.estimate(project, body, client=_clip_client(_EST))
    pj, inv = t.session.flow.plan.read_artifacts(project)
    for st in pj["steps"]:
        st["tool"] = str(ki.root / "tools" / "run.py"); st["kind"] = "run"
    for it in inv["items"]:
        it["status"] = "resolved"; it["needs_user"] = False
    # The agent names the dataset and the study scope; it never copies the estimate id.
    inv["items"].append({"id": "forcing", "required_by": ["M"], "status": "resolved",
                         "acceptable_sources": [], "chosen_source": "cmfd_china_daily_010", "local_paths": [],
                         "agent_resolvable": True, "needs_user": False,
                         "dataset_id": "cmfd_china_daily_010", "delivery": "subset",
                         "requirements": {"bbox": "115,37,117,39", "start": "1989-01-01",
                                          "end": "1989-12-31", "variable": "prec"}})
    pj["steps"][0]["inputs"] = list(pj["steps"][0].get("inputs") or []) + ["forcing"]
    errs = t.session.write_plan(pj, inv)
    assert errs == [], errs
    calls = iter(refresh_responses)
    monkeypatch.setattr(obs_subset, "_estimate_attempt",
                        lambda project, state, client=None: _fake_refresh(project, state, next(calls)))
    return t, est


def _fake_refresh(project, state, raw):
    from kiss_cli import obs_subset, data_contract
    state["estimate"] = raw
    state["offer"] = data_contract.normalize_estimate(state["request"], raw, obs_subset.MAX_OUTPUT)
    state["status"] = "awaiting_approval"
    return obs_subset._save(project, state)


def test_card_shows_clip_and_approval_starts_the_job(tmp_path, monkeypatch):
    from kiss_cli import obs_subset
    project = _project(tmp_path); ki = _ki(tmp_path, "M")
    t, est = _plan_with_clip(tmp_path, ki, project, monkeypatch, _EST, _EST)
    res = flowrun.after(project, t, "plan written", setup_ok=True)
    assert res.request and "forcing ← cmfd_china_daily_010 (server clip, 4 KB, 2 files)" in res.request["message"]
    inv = json.loads((project / "runs" / "data-inventory.json").read_text())
    item = next(i for i in inv["items"] if i["id"] == "forcing")
    assert item["acquisition_id"] == est["id"]
    assert item["estimate_summary"]["processing_version"] == "obs_subset/3"
    created = []
    monkeypatch.setattr(obs_subset, "approve",
                        lambda project, ident, client=None, inspection=False, expected=None:
                        created.append((ident, inspection)) or {"status": "queued"})
    from kiss_cli import acquire
    monkeypatch.setattr(acquire, "run", lambda project, client=None: {"status": "done", "items": {}})
    pre = _approve(project, ki, res)
    assert pre.message is None and created == [(est["id"], False)]
    st = json.loads((project / "runs" / "flow-state.json").read_text())
    assert st["state"] == "EXECUTING"


def test_changed_clip_at_approval_reissues_the_card_unsigned(tmp_path, monkeypatch):
    project = _project(tmp_path); ki = _ki(tmp_path, "M")
    grown = {**_EST, "estimated_output_bytes": 40 * 1024**2, "source_version": "v2"}
    t, est = _plan_with_clip(tmp_path, ki, project, monkeypatch, _EST, grown)
    res = flowrun.after(project, t, "plan written", setup_ok=True)
    pre = _approve(project, ki, res)
    assert pre.message and "changed since you reviewed" in pre.message and "source_version v1 -> v2" in pre.message
    st = json.loads((project / "runs" / "flow-state.json").read_text())
    assert st["state"] == "WAITING_FOR_USER"
    assert not (project / "runs" / "approval.json").exists()
    card = json.loads((project / "setup-request.json").read_text())
    assert card["id"].startswith(flowrun.APPROVAL_REQUEST_ID_PREFIX) and "40 MB" in card["message"]
    inv = json.loads((project / "runs" / "data-inventory.json").read_text())
    item = next(i for i in inv["items"] if i["id"] == "forcing")
    assert item["estimate_summary"]["bytes"] == 40 * 1024**2


# ---------------------------------------------------------------------------
# Step 3 (FLOW-TARGET-2026-09-17): ACQUIRING is host work between approval and execution.


def _state(project):
    return json.loads((project / "runs" / "flow-state.json").read_text())["state"]


def _approved_plan(tmp_path, monkeypatch):
    project = _project(tmp_path); ki = _ki(tmp_path, "M")
    flowrun.pre(project, "run M for 2003", ["M"], [ki], None, None)
    t = _drive_planning(tmp_path, ki, project)
    res = flowrun.after(project, t, "planned", setup_ok=True)
    return project, ki, res


def test_pending_clip_holds_the_project_in_acquiring_until_the_poll_finishes_it(tmp_path, monkeypatch):
    from kiss_cli import acquire
    project, ki, res = _approved_plan(tmp_path, monkeypatch)
    passes = iter([{"status": "pending", "items": {"forcing": {"status": "pending", "job_status": "running"}}},
                   {"status": "done", "items": {"forcing": {"status": "done", "receipt": "r"}}}])
    monkeypatch.setattr(acquire, "run", lambda project, client=None: next(passes))
    pre = _approve(project, ki, res)
    assert _state(project) == "ACQUIRING" and "fetching the approved data" in pre.message
    # no agent turn while acquiring
    assert flowrun.turn(project, [ki], _cfg(project), "api", "deepseek", None, "hi") is None
    # the panel poll advances it (rate limit bypassed for the test)
    flowrun._ACQ_POLL.clear()
    assert flowrun.poll_acquisition(project, setup_ok=True) == "done"
    assert _state(project) == "EXECUTING"
    assert flowrun.poll_acquisition(project, setup_ok=True) is None   # nothing to do once past ACQUIRING


def test_manual_wait_then_files_in_place_message_continues(tmp_path, monkeypatch):
    from kiss_cli import acquire
    project, ki, res = _approved_plan(tmp_path, monkeypatch)
    passes = iter([{"status": "waiting", "items": {"forcing": {"status": "waiting", "expected_path": "/p/inputs/x"}}},
                   {"status": "done", "items": {"forcing": {"status": "done", "receipt": "r"}}}])
    monkeypatch.setattr(acquire, "run", lambda project, client=None: next(passes))
    pre = _approve(project, ki, res)
    assert _state(project) == "ACQUIRING" and "GeoForge needs you" in pre.message and "/p/inputs/x" in pre.message
    # the user's "files are in place" message re-runs the pass and the run starts
    pre = flowrun.pre(project, "I placed the files. Please continue.", ["M"], [ki], None, None)
    assert pre.message is None and _state(project) == "EXECUTING"


def test_failed_acquisition_blocks_with_retry_and_modify(tmp_path, monkeypatch):
    from kiss_cli import acquire, setup as setup_flow
    project, ki, res = _approved_plan(tmp_path, monkeypatch)
    passes = iter([{"status": "failed", "items": {"forcing": {"status": "failed", "error": "HTTP 503"}}},
                   {"status": "done", "items": {"forcing": {"status": "done", "receipt": "r"}}}])
    monkeypatch.setattr(acquire, "run", lambda project, client=None: next(passes))
    pre = _approve(project, ki, res)
    assert _state(project) == "BLOCKED" and "could not be fetched" in pre.message
    card = setup_flow.request(project)
    assert card["id"] == flowrun.BLOCKED_REQUEST_ID and "HTTP 503" in card["message"]
    assert flowrun.turn(project, [ki], _cfg(project), "api", "deepseek", None, "hi") is None
    # retry: the second pass succeeds and execution starts under the same approval
    pre = flowrun.pre(project, "Retry the data acquisition.", ["M"], [ki],
                      {"request_id": card["id"], "option_id": "retry"}, card)
    assert pre.message is None and _state(project) == "EXECUTING"
    assert (project / "runs" / "approval.json").exists()


def test_failed_acquisition_modify_revokes_and_replans(tmp_path, monkeypatch):
    from kiss_cli import acquire, setup as setup_flow
    project, ki, res = _approved_plan(tmp_path, monkeypatch)
    monkeypatch.setattr(acquire, "run", lambda project, client=None:
                        {"status": "failed", "items": {"forcing": {"status": "failed", "error": "gone"}}})
    _approve(project, ki, res)
    card = setup_flow.request(project)
    pre = flowrun.pre(project, "Please revise the plan.", ["M"], [ki],
                      {"request_id": card["id"], "option_id": "modify"}, card, note="use the served subset")
    assert pre.replan_reason == "use the served subset" and _state(project) == "PLANNING"
    assert not (project / "runs" / "approval.json").exists()


def test_manual_card_modify_replans_while_acquiring(tmp_path, monkeypatch):
    """Montreal 2026-09-19: hwsd waiting as a Baidu download; the user wants a server clip instead.
    The manual card's "change the plan" leaves ACQUIRING for PLANNING with the user's words."""
    from kiss_cli import acquire, setup as setup_flow
    project, ki, res = _approved_plan(tmp_path, monkeypatch)
    monkeypatch.setattr(acquire, "run", lambda project, client=None:
                        {"status": "waiting", "items": {"forcing": {"status": "waiting"}}})
    _approve(project, ki, res)
    assert _state(project) == "ACQUIRING"
    pre = flowrun.pre(project, "请修改计划：hwsd 用服务器裁剪", ["M"], [ki],
                      {"request_id": acquire.MANUAL_REQUEST_ID, "option_id": "modify", "note": ""}, None)
    assert pre.replan_reason == "请修改计划：hwsd 用服务器裁剪" and _state(project) == "PLANNING"
    assert not (project / "runs" / "approval.json").exists()
    assert not setup_flow.request(project) or setup_flow.request(project).get("status") != "waiting"


def test_message_while_blocked_reissues_the_card(tmp_path, monkeypatch):
    from kiss_cli import acquire, setup as setup_flow
    project, ki, res = _approved_plan(tmp_path, monkeypatch)
    monkeypatch.setattr(acquire, "run", lambda project, client=None:
                        {"status": "failed", "items": {"forcing": {"status": "failed", "error": "gone"}}})
    _approve(project, ki, res)
    setup_flow.resume(project, "dismissed")           # the generic handler marked it answered
    assert setup_flow.request(project)["status"] != "waiting"
    pre = flowrun.pre(project, "what now?", ["M"], [ki], None, None)
    assert "could not be fetched" in pre.message
    card = setup_flow.request(project)
    assert card["status"] == "waiting" and card["id"] == flowrun.BLOCKED_REQUEST_ID


def test_plan_submitted_before_a_dropped_connection_still_reaches_the_card(tmp_path, monkeypatch):
    """Montreal 2026-09-18: write_plan succeeded, the next API call hit an SSL EOF, and the
    valid plan was reported as 'provider failed'."""
    project = _project(tmp_path); ki = _ki(tmp_path, "M")
    flowrun.pre(project, "run M for 2003", ["M"], [ki], None, None)
    t = _drive_planning(tmp_path, ki, project)          # sets session.plan_submission
    t.provider_succeeded = False                         # the turn ended in a transport error afterwards
    res = flowrun.after(project, t, "", setup_ok=True)
    assert res.request and res.request["id"].startswith(flowrun.APPROVAL_REQUEST_ID_PREFIX)
    assert json.loads((project / "runs" / "flow-state.json").read_text())["state"] == "WAITING_FOR_USER"


def test_card_offers_the_catalogue_candidates_and_a_different_pick_repins(tmp_path, monkeypatch):
    """The missing step: what the database holds for each input is shown before approval,
    and the user's pick, not the agent's, is what gets pinned."""
    from kiss_cli import obs_access, acquire
    store = obs_access.catalogue_store_path(); store.parent.mkdir(parents=True, exist_ok=True)
    obs_access._atomic_json(store, {"schema": obs_access.CATALOGUE_SNAPSHOT_SCHEMA, "ok": True, "datasets": [
        {"id": "agrometeo_quebec", "name": "Agrometeo Quebec", "delivery": "manual", "size": 344_000_000,
         "start_date": "2012-01-01", "end_date": "2023-12-31"},
        {"id": "risma_on2", "name": "RISMA ON2", "delivery": "served", "size": 47_000},
    ]})
    monkeypatch.setattr(obs_access, "refresh_catalogue", lambda *a, **k: obs_access.load_catalogue())
    monkeypatch.setattr(acquire, "run", lambda project, client=None: {"status": "done", "items": {}})
    project = _project(tmp_path); ki = _ki(tmp_path, "M")
    flowrun.pre(project, "run M for 2003", ["M"], [ki], None, None)
    t = flowrun.turn(project, [ki], _cfg(project), "api", "deepseek", None, "run M for 2003")
    pj, inv = t.session.flow.plan.read_artifacts(project)
    for st in pj["steps"]:
        st["tool"] = str(ki.root / "tools" / "run.py"); st["kind"] = "run"
    for it in inv["items"]:
        it["status"] = "resolved"; it["needs_user"] = False
    inv["items"].append({"id": "forcing", "required_by": ["M"], "status": "resolved", "acceptable_sources": [],
                         "chosen_source": "agrometeo_quebec", "dataset_id": "agrometeo_quebec", "local_paths": [],
                         "agent_resolvable": True, "needs_user": False})
    pj["steps"][0]["inputs"] = list(pj["steps"][0].get("inputs") or []) + ["forcing"]
    pj["scientific_choices"] = [{"id": "data:forcing", "kind": "data_source", "item": "forcing",
                                 "options": ["agrometeo_quebec", "risma_on2", "made_up_id"],
                                 "picked": "agrometeo_quebec", "rationale": "local stations", "high_impact": True}]
    assert t.session.write_plan(pj, inv) == []
    res = flowrun.after(project, t, "planned", setup_ok=True)
    choices = res.request["plan_review"]["data_choices"]
    assert len(choices) == 1 and choices[0]["picked"] == "agrometeo_quebec"
    assert [o["dataset_id"] for o in choices[0]["options"]] == ["agrometeo_quebec", "risma_on2"]   # invented id dropped
    assert choices[0]["options"][0]["delivery"] == "manual" and choices[0]["options"][1]["size_label"] == "46 KB"
    # the user picks the served candidate instead: re-pin, card comes back unsigned
    pre = flowrun.pre(project, "Approved.", ["M"], [ki],
                      {"request_id": res.request["id"], "option_id": "approve", "choices": {"data:forcing": "risma_on2"}},
                      res.request)
    assert "re-pinned to your choice: forcing" in pre.message
    assert not (project / "runs" / "approval.json").exists()
    inv2 = json.loads((project / "runs" / "data-inventory.json").read_text())
    item = next(i for i in inv2["items"] if i["id"] == "forcing")
    assert item["dataset_id"] == "risma_on2" and item["delivery"] == "served"
    card = json.loads((project / "setup-request.json").read_text())
    assert card["plan_review"]["data_choices"][0]["picked"] == "risma_on2"
    # approving the re-issued card with the same pick signs and moves on
    pre = flowrun.pre(project, "Approved.", ["M"], [ki],
                      {"request_id": card["id"], "option_id": "approve", "choices": {"data:forcing": "risma_on2"}}, card)
    assert pre.message is None and (project / "runs" / "approval.json").exists()


# ── who decided what (flow.decisions on the desktop) ──────────────────────────

def test_approval_records_who_decided_each_input_and_the_plan_carries_the_revision(tmp_path):
    project = _project(tmp_path); ki = _ki(tmp_path, "M")
    flowrun.pre(project, "run M at 32.9, 117.4 for 2003-2004", ["M"], [ki], None, None)
    t = _drive_planning(tmp_path, ki, project, with_choice=True)
    res = flowrun.after(project, t, "planned", setup_ok=True)
    pre = _approve(project, ki, res)
    assert pre.message is None
    approval = json.loads((project / "runs" / "approval.json").read_text())
    plan = json.loads((project / "runs" / "plan.json").read_text())
    recs = approval["decisions"]
    assert plan["decision_revision"] and len(plan["decision_revision"]) == 16
    # the planner's recommendation is disclosed, never recorded as the user's own choice
    assert recs["choice:f"]["source"] == "ki_default" and recs["choice:f"]["value"] == "cmfd_v1"
    assert recs["choice:f"]["rationale"] == flowrun._SUGGESTION_WHY
    assert all(r["source"] in ("user", "ki_default") for r in recs.values())
    assert all(k.split(":")[0] in ("item", "choice", "question", "note") for k in recs)


def test_a_high_impact_choice_with_no_candidate_refuses_to_start_and_is_named(tmp_path):
    """Approving accepts a recommendation; it cannot answer a question that has none."""
    project = _project(tmp_path); ki = _ki(tmp_path, "M")
    flowrun.pre(project, "run M at 32.9, 117.4 for 2003-2004", ["M"], [ki], None, None)
    t = _drive_planning(tmp_path, ki, project)
    pj, inv = t.session.flow.plan.read_artifacts(project)
    pj["scientific_choices"] = [{"id": "routing", "kind": "routing_scheme",
                                 "options": ["lohmann", "cama"], "high_impact": True}]   # nothing picked
    assert t.session.write_plan(pj, inv) == []
    res = flowrun.after(project, t, "planned", setup_ok=True)
    pre = _approve(project, ki, res)
    assert "routing" in (pre.message or "") and "need your decision" in (pre.message or "")
    assert not (project / "runs" / "approval.json").exists()
    # the user picks on the re-issued card: it signs, and the pick is recorded as THEIRS
    card = json.loads((project / "setup-request.json").read_text())
    pre = flowrun.pre(project, "Approved.", ["M"], [ki],
                      {"request_id": card["id"], "option_id": "approve", "choices": {"routing": "cama"}}, card)
    assert pre.message is None
    recs = json.loads((project / "runs" / "approval.json").read_text())["decisions"]
    assert recs["choice:routing"]["source"] == "user" and recs["choice:routing"]["value"] == "cama"
    # the user's answer is host-written, outside anything the agent may edit
    assert json.loads((project / ".geoforge" / "user-answers.json").read_text())["answers"]["choice:routing"]["value"] == "cama"


def test_an_input_with_nothing_to_fall_back_on_is_recorded_open(tmp_path):
    """Unit rule: an item needing the user with no decision and no data behind it is open."""
    ki = _ki(tmp_path, "M"); project = _project(tmp_path)
    fs = flowgate.FlowSession.open(project, {"M": Path(ki.root)}, database_access_mode="direct")
    inv = {"items": [
        {"id": "gauge", "needs_user": True, "category": "observations"},
        {"id": "gauge_ok", "needs_user": True, "decision": "51080 Bengbu"},
        {"id": "forcing", "needs_user": False, "ki_default": {"default_source": "CMFD"}},
        {"id": "planted", "needs_user": True, "decision_source": "user", "decision": "agent's pick"},
        {"id": "picked_by_user", "needs_user": True, "dataset_id": "risma_on2"}]}
    recs, invalid = flowrun.decision_records(fs.flow, {}, inv,
                                             {"item:picked_by_user": {"value": "risma_on2"}})
    assert invalid == []
    assert fs.flow.decisions.open_inputs(recs) == ["item:gauge"]
    assert recs["item:gauge_ok"]["source"] == "ki_default" and recs["item:forcing"]["value"] == "CMFD"
    # a provenance marker the AGENT wrote into the plan is not evidence of a user decision
    assert recs["item:planted"]["source"] == "ki_default"
    assert recs["item:picked_by_user"]["source"] == "user"

def test_the_execution_turn_names_the_inputs_the_ki_decided(tmp_path):
    project = _project(tmp_path); ki = _ki(tmp_path, "M")
    flowrun.pre(project, "run M at 32.9, 117.4 for 2003-2004", ["M"], [ki], None, None)
    t = _drive_planning(tmp_path, ki, project, with_choice=True)
    res = flowrun.after(project, t, "planned", setup_ok=True)
    _approve(project, ki, res)
    nxt = flowrun.turn(project, [ki], _cfg(project), "api", "deepseek", None, "go")
    # a planner suggestion is disclosed as one, not as a KI protocol default
    assert "[RECOMMENDATIONS THE USER ACCEPTED]" in nxt.extra_prompt and "f: cmfd_v1" in nxt.extra_prompt
    assert "[INPUTS ON KI PROTOCOL DEFAULTS]" not in nxt.extra_prompt    # this KI derives no inputs
    # the namespaced id belongs to the signed record (grounding line); what the agent reads out
    # to the user is the plain name
    block = nxt.extra_prompt.split("[RECOMMENDATIONS THE USER ACCEPTED]", 1)[1]
    assert "choice:f" not in block


def test_an_untouched_recommendation_coming_back_from_the_card_is_not_a_user_decision(tmp_path):
    """The card pre-selects the suggestion and the UI submits every checked radio, so a pick
    equal to the suggestion proves nothing (codex review, 2026-09-25)."""
    project = _project(tmp_path)
    card = {"plan_review": {"data_choices": [{"id": "data:forcing", "picked": "cmfd_v1"}],
                            "decisions": [{"id": "routing", "picked": "lohmann"}]}}
    answers = flowrun.record_user_answers(project, card, {"data:forcing": "cmfd_v1",
                                                          "routing": "cama"})
    assert "choice:data:forcing" not in answers          # unchanged suggestion: not an answer
    assert answers["choice:routing"]["value"] == "cama"  # a real change is


def test_a_repinned_data_choice_survives_the_reissued_card(tmp_path):
    """Pick A, approve, change to B: the re-issued card pre-selects B, so the next click alone
    cannot prove the user chose B. The re-pin path records it against the card the user saw."""
    project = _project(tmp_path)
    old_card = {"plan_review": {"data_choices": [{"id": "data:forcing", "item": "forcing", "picked": "cmfd_v1"}]}}
    flowrun.record_user_answers(project, old_card, {"data:forcing": "mswx_v1"})
    new_card = {"plan_review": {"data_choices": [{"id": "data:forcing", "item": "forcing", "picked": "mswx_v1"}]}}
    answers = flowrun.record_user_answers(project, new_card, {"data:forcing": "mswx_v1"})
    assert answers["choice:data:forcing"]["value"] == "mswx_v1"
    assert answers["item:forcing"]["value"] == "mswx_v1"          # the item it answers, explicitly


def test_a_repin_alone_is_not_a_user_choice(tmp_path):
    """The card can pre-select a suggestion that differs from the pinned dataset; leaving it
    untouched still re-pins. That must not become a user decision (codex review A #1)."""
    project = _project(tmp_path)
    card = {"plan_review": {"data_choices": [{"id": "data:forcing", "item": "forcing", "picked": "mswx_v1"}]}}
    answers = flowrun.record_user_answers(project, card, {"data:forcing": "mswx_v1"})
    assert answers == {}


def test_a_legacy_store_answers_the_item_the_card_binds_it_to(tmp_path):
    """Stores from before 2026-09-26 hold only `choice:<id>`. The item is taken from the card
    row's `item`, never from the id's `data:` prefix — a choice `data:forcing` may be bound to
    the item `temperature` (codex review A2 #1)."""
    project = _project(tmp_path)
    p = project / ".geoforge" / flowrun.ANSWERS_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"schema": 1, "answers": {"choice:data:forcing": {"value": "mswx_v1"}}}), encoding="utf-8")
    assert "item:forcing" not in flowrun.load_user_answers(project)          # no guessing at load
    card = {"plan_review": {"data_choices": [{"id": "data:forcing", "item": "temperature", "picked": "cmfd_v1"}]}}
    answers = flowrun.record_user_answers(project, card, {})
    assert answers["item:temperature"]["value"] == "mswx_v1"
    assert "item:forcing" not in answers


def test_a_saved_answer_that_the_plan_no_longer_uses_is_not_signed_as_user(tmp_path):
    """User chose B; a replan re-pinned the item to A. Signing "user chose B" while A runs would
    be false (codex review A #3): the saved answer counts only while it is what will run."""
    plan = {"scientific_choices": [{"id": "data:forcing", "kind": "data_source", "item": "forcing",
                                    "options": ["a", "b"], "decision": "a"}]}
    inv = {"items": [{"id": "forcing", "dataset_id": "a"}]}
    recs, _ = flowrun.decision_records(flowrun._flow(), plan, inv,
                                       {"item:forcing": {"value": "b"}, "choice:data:forcing": {"value": "b"}})
    assert recs["item:forcing"]["source"] == "ki_default" and recs["item:forcing"]["value"] == "a"
    assert recs["choice:data:forcing"]["source"] == "ki_default"
    recs, _ = flowrun.decision_records(flowrun._flow(), plan, inv,
                                       {"item:forcing": {"value": "a"}, "choice:data:forcing": {"value": "a"}})
    assert recs["item:forcing"]["source"] == "user"


def test_an_item_is_answered_only_in_its_own_namespace(tmp_path):
    """A planner-authored choice id that happens to equal an item id must not answer the item
    (kimi review, 2026-09-26): the mapping is explicit, never a fallback across namespaces."""
    plan = {"scientific_choices": [{"id": "forcing", "kind": "routing", "options": ["a", "b"], "decision": "a"}]}
    inv = {"items": [{"id": "forcing", "needs_user": True}]}
    recs, invalid = flowrun.decision_records(flowrun._flow(), plan, inv, {"choice:forcing": {"value": "a"}})
    assert recs["item:forcing"]["source"] == "open"               # still open: not answered
    assert recs["choice:forcing"]["source"] == "user"
    inv2 = {"items": [{"id": "forcing", "dataset_id": "cmfd_v1"}]}
    recs, _ = flowrun.decision_records(flowrun._flow(), plan, inv2, {"item:forcing": {"value": "cmfd_v1"}})
    assert recs["item:forcing"]["source"] == "user"


def test_a_corrupt_answer_store_is_loud_not_silent(tmp_path):
    """A missing store is "nothing answered yet"; an unreadable one must refuse, not quietly
    turn every earlier user decision into a KI default (kimi review, 2026-09-26)."""
    project = _project(tmp_path)
    assert flowrun.load_user_answers(project) == {}
    p = project / ".geoforge" / flowrun.ANSWERS_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    for bad in ("{not json", b"\xff\xfe{}", '{"schema": 1}', '{"schema": 1, "answers": {"item:x": null}}',
                '{"schema": 1, "answers": {"item:x": {"value": []}}}'):
        if isinstance(bad, bytes):
            p.write_bytes(bad)
        else:
            p.write_text(bad, encoding="utf-8")
        with pytest.raises(flowrun.AnswersUnreadable):
            flowrun.load_user_answers(project)
    p.write_text('{"schema": 1, "answers": {}}', encoding="utf-8")
    assert flowrun.load_user_answers(project) == {}                # valid and empty is fine


def test_a_changed_pick_survives_a_clip_refresh_reissue(tmp_path, monkeypatch):
    """Card recommends A, the inventory already pins B, the user picks B: no re-pin, but a
    changed clip estimate re-issues a card pre-selecting B. The pick must already be recorded
    against the card the user saw (codex review A2 #2)."""
    project = _project(tmp_path)
    card = {"plan_review": {"data_choices": [{"id": "data:forcing", "item": "forcing", "picked": "cmfd_v1"}]}}
    answers = flowrun.record_user_answers(project, card, {"data:forcing": "mswx_v1"})
    assert answers["item:forcing"]["value"] == "mswx_v1"
    # the re-issued card now pre-selects B; the untouched click keeps the earlier record
    card2 = {"plan_review": {"data_choices": [{"id": "data:forcing", "item": "forcing", "picked": "mswx_v1"}]}}
    answers = flowrun.record_user_answers(project, card2, {"data:forcing": "mswx_v1"})
    assert answers["item:forcing"]["value"] == "mswx_v1"


def test_a_non_data_pick_made_with_a_repin_is_recorded_at_that_click(tmp_path):
    """Routing changed in the same click as a data re-pin: the re-issued card keeps the routing
    decision, so it must be recorded against the card the user saw, or the next approval
    signs it as a KI default (codex review A3 #1)."""
    project = _project(tmp_path)
    card = {"plan_review": {"data_choices": [{"id": "data:forcing", "item": "forcing", "picked": "cmfd_v1"}],
                            "decisions": [{"id": "routing", "picked": "lohmann"}]}}
    picks = {"data:forcing": "mswx_v1", "routing": "cama"}
    shown = {ch["id"] for key in ("data_choices", "decisions") for ch in card["plan_review"][key]}
    answers = flowrun.record_user_answers(project, card, {k: v for k, v in picks.items() if k in shown})
    assert answers["choice:routing"]["value"] == "cama"
    plan = {"scientific_choices": [{"id": "routing", "kind": "routing", "options": ["lohmann", "cama"],
                                    "decision": "cama", "picked": "lohmann"}]}
    recs, _ = flowrun.decision_records(flowrun._flow(), plan, {"items": []}, answers)
    assert recs["choice:routing"]["source"] == "user"


def test_a_rebound_choice_id_does_not_carry_the_old_answer_to_the_new_item(tmp_path):
    """User chose B for `forcing`. A replan binds the same choice id to `temperature` (already
    pinned to B). Approving untouched must not sign "user chose B for temperature": only
    records without an `item` stamp are legacy (codex review A4 #1)."""
    project = _project(tmp_path)
    card = {"plan_review": {"data_choices": [{"id": "data:forcing", "item": "forcing", "picked": "cmfd_v1"}]}}
    flowrun.record_user_answers(project, card, {"data:forcing": "mswx_v1"})
    rebound = {"plan_review": {"data_choices": [{"id": "data:forcing", "item": "temperature", "picked": "mswx_v1"}]}}
    answers = flowrun.record_user_answers(project, rebound, {"data:forcing": "mswx_v1"})
    assert "item:temperature" not in answers
    assert answers["item:forcing"]["value"] == "mswx_v1"
    # and the choice record itself is not the user's for the rebound item either (codex A5 #1)
    plan = {"scientific_choices": [{"id": "data:forcing", "kind": "data_source", "item": "temperature",
                                    "options": ["mswx_v1"], "decision": "mswx_v1"}]}
    inv = {"items": [{"id": "temperature", "dataset_id": "mswx_v1"}]}
    recs, _ = flowrun.decision_records(flowrun._flow(), plan, inv, answers)
    assert recs["choice:data:forcing"]["source"] == "ki_default"
    assert recs["item:temperature"]["source"] == "ki_default"


def test_a_migrated_legacy_record_is_stamped_and_never_migrates_again(tmp_path):
    """Legacy `choice:data:forcing` migrates once to the item the card binds it to; a later
    rebinding of the same choice id must not migrate it again (codex review A5 #2)."""
    project = _project(tmp_path)
    p = project / ".geoforge" / flowrun.ANSWERS_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"schema": 1, "answers": {"choice:data:forcing": {"value": "mswx_v1"}}}), encoding="utf-8")
    card = {"plan_review": {"data_choices": [{"id": "data:forcing", "item": "forcing", "picked": "cmfd_v1"}]}}
    answers = flowrun.record_user_answers(project, card, {})
    assert answers["item:forcing"]["value"] == "mswx_v1"
    assert answers["choice:data:forcing"]["item"] == "forcing"
    rebound = {"plan_review": {"data_choices": [{"id": "data:forcing", "item": "temperature", "picked": "mswx_v1"}]}}
    answers = flowrun.record_user_answers(project, rebound, {"data:forcing": "mswx_v1"})
    assert "item:temperature" not in answers


def test_a_legacy_choice_is_stamped_even_when_its_item_record_already_exists(tmp_path):
    """Two legacy choices bound to the same item: the second finds `item:forcing` already
    present and must still be stamped, or a later rebinding migrates it (codex review A6)."""
    project = _project(tmp_path)
    p = project / ".geoforge" / flowrun.ANSWERS_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"schema": 1, "answers": {"choice:data:forcing": {"value": "mswx_v1"},
                                                       "choice:select-forcing": {"value": "mswx_v1"}}}), encoding="utf-8")
    card = {"plan_review": {"data_choices": [{"id": "data:forcing", "item": "forcing", "picked": "cmfd_v1"},
                                             {"id": "select-forcing", "item": "forcing", "picked": "cmfd_v1"}]}}
    answers = flowrun.record_user_answers(project, card, {})
    assert answers["choice:data:forcing"]["item"] == "forcing"
    assert answers["choice:select-forcing"]["item"] == "forcing"
    rebound = {"plan_review": {"data_choices": [{"id": "select-forcing", "item": "temperature", "picked": "mswx_v1"}]}}
    answers = flowrun.record_user_answers(project, rebound, {"select-forcing": "mswx_v1"})
    assert "item:temperature" not in answers


def test_a_reissued_card_shows_the_non_data_pick_the_user_made(tmp_path):
    """Whichever branch re-issues the card (re-pin or clip refresh), the plan must already carry
    the non-data picks from that click, or the card shows the old suggestion and the next click
    demotes the recorded answer (codex A3 #1, kimi A7 #1)."""
    plan = {"goal": "g", "selected_kis": ["VIC"],
            "scientific_choices": [{"id": "routing", "kind": "routing", "options": ["lohmann", "cama"],
                                    "picked": "lohmann", "high_impact": True}]}
    assert flowrun.apply_choice_picks(plan, {"routing": "cama"}) == ["routing"]
    assert plan["scientific_choices"][0]["decision"] == "cama"

    class _FS:
        project = tmp_path
        flow = flowrun._flow()
    card = flowrun._card(flowrun._flow(), _FS(), plan, {"items": []}, "note")
    assert card["plan_review"]["decisions"][0]["picked"] == "cama"
