"""Exercise setup rendering/start transitions without a server or agent."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

PAGE = Path(__file__).parents[1] / "kiss_cli" / "web" / "setup.html"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node is required")
RUNNER = r"""
const fs=require('node:fs'),vm=require('node:vm');
const page=fs.readFileSync(process.argv[1],'utf8'),input=JSON.parse(fs.readFileSync(0,'utf8'));
const elements=new Map(),snapshots=[];let finishStream;
function element(key){
  if(!elements.has(key))elements.set(key,{textContent:'',innerHTML:'',className:'',disabled:false,
    value:'',style:{},scrollTop:0,scrollHeight:1});
  return elements.get(key);
}
element('#provider').value=input.noProvider?'':'api:deepseek';element('#llm').value='deepseek-chat';
const context={console,Date,TextDecoder,$:element,MODEL:'CRHM',STATE:input.states[0],busy:false,
  selectedInstallMode:'existing',rawLog:'',runStartedAt:0,lastSignalAt:0,
  isZh:()=>!!input.zh,esc:s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),
  presentSetupLog:s=>s,drawInstallLocation(){},drawRunState(){},drawActivity(){},
  managedWorkspacePermission:()=>false,requestSummary:r=>r.message,fmtSize:n=>n+' B',
  resumeAgent(){},chatForHelp(){},uploadFile(){},saveInstallLocation:async()=>true,
  window:{GeoForgeI18n:{language:input.zh?'zh-CN':'en'}},GeoForgeI18n:{language:input.zh?'zh-CN':'en'}};
context.loadState=async()=>{context.STATE=input.states.at(-1);context.draw();};
context.fetch=async()=>({ok:true,body:{getReader:()=>({read:async()=>{
  await new Promise(resolve=>{finishStream=resolve;});return {done:true};
}})}});
vm.createContext(context);
function shipped(start,end){const a=page.indexOf(start),b=page.indexOf(end,a);
  if(a<0||b<0)throw new Error('Missing '+start);vm.runInContext(page.slice(a,b),context);}
shipped('function setupRecheckRequired(','async function loadState(');
shipped('async function startAgent(','async function resumeAgent(');
function snapshot(){snapshots.push(Object.fromEntries([...elements].map(([key,e])=>[key,
  {text:e.textContent,html:e.innerHTML,className:e.className,disabled:e.disabled,display:e.style.display}])));}
(async()=>{
  context.draw();snapshot();
  if(input.start){
    const pending=context.startAgent(false);await new Promise(resolve=>setImmediate(resolve));snapshot();
    // The state poll can still contain old attention/pass results during streaming.
    context.draw();snapshot();
    finishStream();await pending;snapshot();
  }else for(const state of input.states.slice(1)){context.STATE=state;context.busy=!!state.busy;context.draw();snapshot();}
  process.stdout.write(JSON.stringify(snapshots));
})().catch(error=>{console.error(error);process.exitCode=1;});
"""


STALE = {
    "name": "CRHM", "software": {
        "state": "setup", "label": "Recheck updated KI", "can_run": False,
        "requires_reverification": True, "checked_at": "2026-10-04T09:00:00Z",
        "primary_error": {"name": "snapshot-changed", "detail": "KI changed"},
        "steps": [{"name": "preflight", "ok": True, "detail": "Previous native check passed"}]},
    "attention": {"kind": "retry", "title": "Setup is not finished",
                  "message": "The agent stopped before verification passed."},
    "log_tail": "2026-10-04 previous setup log", "agent_ready": True,
    "install_location": {"installation_mode": "existing"},
}
PASSED = {**STALE, "attention": None, "log_tail": "Current preflight passed",
          "software": {"state": "verified", "label": "Verified on this machine", "can_run": True,
                       "checked_at": "2026-10-06T09:00:00Z",
                       "steps": [{"name": "preflight", "ok": True}]}}


def render(*states, **kwargs):
    result = subprocess.run([NODE, "-e", RUNNER, str(PAGE)],
                            input=json.dumps({"states": states, **kwargs}), capture_output=True,
                            text=True, encoding="utf-8", check=True, timeout=10)
    return json.loads(result.stdout)


@pytest.mark.parametrize("zh", [False, True])
def test_snapshot_change_explains_recheck_and_keeps_old_pass_as_neutral_history(zh):
    result, = render(STALE, zh=zh)
    need, verification = result["#need"]["html"], result["#verification"]["html"]
    assert ("shared tools changed" if not zh else "共享工具已更新") in need
    assert "stopped before" not in need and "Continue repair" not in need
    assert ("Previously recorded checks" if not zh else "以前记录的检查结果") in verification
    assert "2026-10-04T09:00:00Z" in verification
    assert 'class="step good"' not in verification and "✓" not in verification
    assert "<details" in verification and "<details open" not in verification
    assert ("not a current verification pass" if not zh else "不代表当前验证通过") in verification
    assert ("updated KI" if not zh else "更新后的 KI") in result["#logcontext"]["text"]
    assert result[".log"]["text"] == STALE["log_tail"]
    assert result["#chat"]["display"] == "none"


@pytest.mark.parametrize("zh", [False, True])
def test_start_and_state_poll_replace_old_retry_with_active_verification_then_current_pass(zh):
    old, started, polled, done = render(STALE, PASSED, start=True, zh=zh)
    for active in (started, polled):
        assert active["#start"]["disabled"]
        assert 'id="retry"' not in active["#need"]["html"]
        assert "stopped before" not in active["#need"]["html"]
        assert ("Working" if not zh else "正在处理") == active["#needbadge"]["text"]
        assert ("Verification in progress" if not zh else "正在验证") == active["#statusbadge"]["text"]
        assert ("not yet confirmed" if not zh else "尚未确认") in active["#verification"]["html"]
        assert 'class="step good"' not in active["#verification"]["html"]
        assert "✓" not in active["#verification"]["html"]
        assert ("Live log" if not zh else "实时日志") in active["#logcontext"]["text"]
        assert active["#chat"]["display"] == "none"
    assert 'class="step good"' in done["#verification"]["html"] and "✓" in done["#verification"]["html"]
    assert "Previously recorded checks" not in done["#verification"]["html"]
    assert done["#statusbadge"]["className"] == "badge ok"
    assert done["#chat"]["display"] == "" and not done["#start"]["disabled"]


def test_real_waiting_request_is_not_hidden_by_running_state():
    waiting = {**STALE, "busy": True, "request": {"status": "waiting", "kind": "permission",
               "title": "Permission required", "message": "Allow this model workspace"}}
    _, result = render(STALE, waiting)
    assert 'id="resume"' in result["#need"]["html"]
    assert "Permission required" in result["#need"]["html"]
    assert 'id="retry"' not in result["#need"]["html"] and result["#start"]["disabled"]


def test_genuine_current_failure_keeps_diagnostics_and_repair_action():
    failed = {**STALE, "software": {"state": "failed", "label": "Setup failed", "can_run": False,
              "steps": [{"name": "preflight", "ok": False, "detail": "Executable missing"}]}}
    result, = render(failed)
    assert 'class="step bad"' in result["#verification"]["html"]
    assert "Executable missing" in result["#verification"]["html"]
    assert 'id="retry"' in result["#need"]["html"]
    assert result["#statusbadge"]["className"] == "badge bad"


def test_running_recheck_does_not_present_previous_valid_pass_as_finished():
    _, result = render(PASSED, {**PASSED, "busy": True})
    assert 'class="step good"' not in result["#verification"]["html"]
    assert "not yet confirmed" in result["#verification"]["html"]
    assert "No action needed" not in result["#need"]["html"]
    assert result["#statusbadge"]["className"] == "badge warn"


def test_recheck_action_requires_a_provider():
    result, = render(STALE, noProvider=True)
    assert result["#retry"]["disabled"] and result["#start"]["disabled"]


def test_snapshot_changed_error_identifies_history_without_boolean_flag():
    sw = {k: v for k, v in STALE["software"].items() if k != "requires_reverification"}
    result, = render({**STALE, "software": sw})
    assert "Previously recorded checks" in result["#verification"]["html"]
    assert "shared tools changed" in result["#need"]["html"]


def test_new_unchecked_install_keeps_empty_verification_explanation():
    result, = render({"name": "CRHM", "software": {"state": "setup", "can_run": False}})
    assert "Not checked yet" in result["#verification"]["html"]
    assert "Previously recorded checks" not in result["#verification"]["html"]
