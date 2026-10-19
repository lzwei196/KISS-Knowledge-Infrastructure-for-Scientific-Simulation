"""An explicit, cancelable next-phase request; ordinary followups keep no action."""
import copy
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from .test_chat_send_ui import send
from .test_project_status_render import evaluate, fixture_data

PAGE = Path(__file__).parents[1] / "kiss_cli/web/app.html"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node required for shipped UI")
CAPABILITY = {"kind": "plan_next_phase", "phase": {"state": "COMPLETED",
    "approval_id": "signed-issuance", "plan_sha256": "a" * 64, "data_inventory_sha256": "b" * 64}}
RUNNER = r'''
const fs=require('fs'),vm=require('vm'),input=JSON.parse(fs.readFileSync(0,'utf8'));
const page=fs.readFileSync(process.argv[1],'utf8'),elements=new Map();
const element=id=>{if(!elements.has(id))elements.set(id,{value:'',textContent:'',hidden:false,
  style:{},scrollHeight:24,focus(){},classList:{remove(){}}});return elements.get(id);};
const context={CUR:{id:'original'},PENDING_ACTIONS:new Map(),DRAFTS:new Map(),$:element,
  chineseUI:()=>!!input.zh,sessionBusy:()=>!!input.busy,sessionUploading:()=>!!input.uploading};
vm.createContext(context);
vm.runInContext(page.slice(page.indexOf('function nextPhaseCapability('),page.indexOf('function statusEvidenceText(')),context);
element('#msg').value=input.draft||'';
const html=context.renderNextPhaseAction(input.data);
if(input.switch_before)context.CUR={id:'other'};
if(input.stage!==false)context.stageNextPhase(input.data,'original');
const staged=JSON.parse(JSON.stringify([...context.PENDING_ACTIONS]));
if(input.mutate)input.data.next_phase_action.phase.approval_id='changed-after-click';
if(input.switch_after){context.CUR={id:'other'};context.renderNextPhaseComposerNotice();}
if(input.cancel){context.renderNextPhaseComposerNotice();element('#next-phase-cancel').onclick();}
process.stdout.write(JSON.stringify({html,staged,pending:[...context.PENDING_ACTIONS],
  noticeHidden:element('#next-phase-note').hidden,notice:element('#next-phase-copy').textContent,
  draft:element('#msg').value,saved:[...context.DRAFTS]}));
'''


def probe(**kwargs):
    data = {"next_phase_action": copy.deepcopy(CAPABILITY),
            "project_status": {"progress": {"flow_state": "COMPLETED"}}}
    payload = {"data": data, **kwargs}
    result = subprocess.run([NODE, "-e", RUNNER, str(PAGE)], input=json.dumps(payload),
                            capture_output=True, text=True, encoding="utf-8", check=True, timeout=10)
    return json.loads(result.stdout)


@pytest.mark.parametrize("zh", [False, True])
def test_next_phase_click_stages_exact_capability_and_explains_no_execution_approval(zh):
    result = probe(zh=zh, mutate=True)
    assert ("规划下一阶段" if zh else "Plan next phase") in result["html"]
    assert result["pending"] == [["original", CAPABILITY]] == result["staged"]
    assert not result["noticeHidden"]
    assert ("不会批准执行" if zh else "does not approve execution") in result["notice"]
    assert result["saved"] == [["original", result["draft"]]]


def test_existing_goal_draft_is_kept_and_cancel_removes_only_staged_authority():
    result = probe(draft="Compare this run against observations", cancel=True)
    assert result["draft"] == "Compare this run against observations"
    assert result["pending"] == [] and result["noticeHidden"]


@pytest.mark.parametrize("flag", ["busy", "uploading"])
def test_busy_or_uploading_project_cannot_stage_next_phase(flag):
    result = probe(**{flag: True}, draft="Retained")
    assert "disabled" in result["html"]
    assert not result["pending"] and result["draft"] == "Retained"


def test_old_project_button_cannot_stage_on_newly_selected_chat():
    result = probe(switch_before=True)
    assert not result["pending"] and not result["saved"]


def test_pending_action_and_notice_stay_with_the_original_project():
    result = probe(switch_after=True, cancel=True)
    assert result["noticeHidden"]
    assert result["pending"] == [["original", CAPABILITY]]


@pytest.mark.parametrize("damage", ["absent", "state", "hash", "capability"])
def test_only_current_completed_host_capability_displays_action(damage):
    data = {"next_phase_action": copy.deepcopy(CAPABILITY),
            "project_status": {"progress": {"flow_state": "COMPLETED"}}}
    if damage == "absent": data.pop("next_phase_action")
    elif damage == "state": data["project_status"]["progress"]["flow_state"] = "PLANNING"
    elif damage == "hash": data["next_phase_action"]["phase"]["plan_sha256"] = ""
    else: data["next_phase_action"]["kind"] = "approve"
    result = probe(data=data)
    assert result["html"] == "" and not result["pending"]


def test_plain_followup_does_not_stage_any_planning_action():
    result = probe(stage=False, draft="Explain these completed results")
    assert not result["pending"]


def test_actual_send_posts_exact_staged_capability_with_goal_and_no_approval_choice():
    result = send(action=CAPABILITY, draft="Compare this run against observations")
    request = next(item for item in result["requests"] if item["url"].endswith("/chat"))
    assert request["body"]["action"] == CAPABILITY
    assert request["body"]["message"] == "Compare this run against observations"
    assert "option_id" not in request["body"]["action"]
    assert result["accepted"] == 1 and not result["pendingAction"]


def test_project_status_renderer_includes_the_host_action():
    data = fixture_data()
    data["next_phase_action"] = CAPABILITY
    data["project_status"]["progress"]["flow_state"] = "COMPLETED"
    assert 'id="plan-next-phase"' in evaluate(data)["html"]
