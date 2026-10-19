"""Node exercises the real setup-page functions; no browser/server/model run."""
import copy
from pathlib import Path

import pytest

from . import test_setup_verification_ui as ui

pytestmark = pytest.mark.skipif(ui.NODE is None, reason="Node is required")
SID = "abcdef123456"


@pytest.fixture(autouse=True)
def page(monkeypatch):
    monkeypatch.setattr(ui, "PAGE", Path(__file__).parents[1] / "kiss_cli/web/setup.html")
    runner = ui.RUNNER.replace("window:{GeoForgeI18n", "CASE_SESSION:input.caseSession||'',DATA_SESSION:input.projectSession||'',window:{GeoForgeI18n")
    runner = runner.replace("__calls:[...calls]", "__calls:[...calls]")
    runner = runner.replace("if(action.kind==='state')", "if(action.kind==='case_start'){element('#casegoal').value=action.goal||'';pending=context.startAgent(false,false,true);await tick()}\n    else if(action.kind==='state')")
    monkeypatch.setattr(ui, "RUNNER", runner)


@pytest.mark.parametrize("zh", [False, True])
def test_project_check_has_explicit_case_repair_navigation_but_no_automatic_setup(zh):
    state = {**copy.deepcopy(ui.PASSED), "project_preflight":{"can_check":True,"detail":"Current case"}}
    result, = ui.render(state, projectSession=SID, zh=zh)
    assert "case_session=" + SID in result["#need"]["html"]
    assert ("Repair software for this project" if not zh else "为此项目修复软件") in result["#need"]["html"]
    assert result["__calls"] == []


@pytest.mark.parametrize("zh", [False, True])
def test_goal_page_displays_limits_and_submits_bound_goal_only_on_explicit_action(zh):
    state = copy.deepcopy(ui.PASSED)
    state["install_location"]["installation_mode"] = "new"
    initial, sent, finished = ui.render(state, caseSession=SID, zh=zh,
        actions=[{"kind":"case_start","goal":"Build the official case feature"},{"kind":"finish","state":0}])
    assert initial["__calls"] == []
    assert initial["#repaircase"]["disabled"]
    explain = initial["#caserepairexplain"]["text"]
    assert ("does not establish case compatibility" if not zh else "不代表案例兼容") in explain
    post = next(call for call in sent["__calls"] if call["url"] == "/api/setup-agent")
    assert post["body"]["session"] == SID
    assert post["body"]["setup_intent"] == {"kind":"case_repair","session":SID,"goal":"Build the official case feature"}
    assert not any(call["url"] == "/api/setup-location" for call in finished["__calls"])
    assert any("case_session=" + SID in call["url"] for call in finished["__calls"])


@pytest.mark.parametrize("goal", ["", " ", "x"*4001])
def test_invalid_goal_cannot_start_or_fall_back_to_plain_setup(goal):
    result, after = ui.render(ui.PASSED, caseSession=SID, actions=[{"kind":"case_start","goal":goal}])
    assert after["__calls"] == []


def test_regular_recheck_does_not_silently_replay_saved_case_goal():
    state = {**copy.deepcopy(ui.PASSED), "setup_intent":{"session":SID,"goal":"old requested goal",
             "state":"completed","case_outcome":"unverified","detail":"Software verified only"}}
    initial, sent, _polled, finished = ui.render(state, caseSession=SID, start=True)
    assert "Case requirement remains unverified" in initial["#caseoutcome"]["text"]
    post = next(call for call in sent["__calls"] if call["url"] == "/api/setup-agent")
    assert post["body"]["session"] == SID
    assert "setup_intent" not in post["body"]


def test_foreign_case_record_is_not_presented_or_replayed():
    state = {**copy.deepcopy(ui.PASSED), "setup_intent":{"session":"f"*12,"goal":"foreign case",
             "state":"completed","case_outcome":"unverified","detail":"foreign evidence"}}
    result, = ui.render(state, caseSession=SID)
    assert not result["#caseoutcome"]["text"]
    assert result["#repaircase"]["disabled"]
