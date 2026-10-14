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
new vm.Script(page.slice(page.lastIndexOf('<script>')+8,page.lastIndexOf('</script>')));
const elements=new Map(),snapshots=[],calls=[],pendingGets=[],pollTasks=[];let finishStream,releasePost,pending;
let serverState=input.states[0],pollFails=false;
function element(key){
  if(!elements.has(key))elements.set(key,{textContent:'',innerHTML:'',className:'',disabled:false,
    value:'',style:{},scrollTop:0,scrollHeight:1,classList:{toggle(){}},setAttribute(){}});
  return elements.get(key);
}
element('#provider').value=input.noProvider?'':'api:deepseek';element('#llm').value='deepseek-chat';
class TestDate extends Date{static now(){return input.now??Date.now()}}
const context={console,Date:TestDate,TextDecoder,$:element,MODEL:'CRHM',STATE:input.states[0],busy:false,
  selectedInstallMode:'existing',rawLog:'',runStartedAt:0,lastSignalAt:0,installPathDirty:false,existingPathDirty:false,
  submitting:false,streaming:false,awaitingStatus:false,stopPending:false,stoppingJobId:'',jobNotice:'',
  statusUnavailable:false,stateMutationEpoch:0,stateLoadPromise:null,
  isZh:()=>!!input.zh,esc:s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),
  presentSetupLog:s=>s,setupPhase:()=>0,
  document:{querySelectorAll:()=>[]},
  managedWorkspacePermission:()=>false,requestSummary:r=>r.message,fmtSize:n=>n+' B',
  resumeAgent(){},chatForHelp(){},uploadFile(){},saveInstallLocation:async()=>true,
  window:{GeoForgeI18n:{language:input.zh?'zh-CN':'en'}},GeoForgeI18n:{language:input.zh?'zh-CN':'en'}};
function response(body,status=200){return {ok:status>=200&&status<300,status,json:async()=>body}}
context.fetch=async(url,options)=>{
  calls.push({url,body:options?.body?JSON.parse(options.body):null});
  if(url.startsWith('/api/setup/')){
    const captured=serverState;
    if(input.deferGet)await new Promise((resolve,reject)=>pendingGets.push({resolve,reject}));
    if(pollFails)throw new Error('Status connection lost');
    return response(captured);
  }
  if(url==='/api/setup-stop')return response(input.stopResponse?.body||{ok:true,job:serverState.job},input.stopResponse?.status||200);
  if(url==='/api/setup-resume')return response(input.resumeResponse?.body||{ok:true},input.resumeResponse?.status||200);
  if(url!=='/api/setup-agent')throw new Error('Unexpected request '+url);
  if(input.deferPost)await new Promise(resolve=>{releasePost=resolve});
  if(input.postResponse)return response(input.postResponse.body,input.postResponse.status);
  return {ok:true,status:200,body:{getReader:()=>({read:async()=>{
    await new Promise((resolve,reject)=>{finishStream=error=>error?reject(new Error('Live display disconnected')):resolve()});
    return {done:true};
  }})}};
};
vm.createContext(context);
function shipped(start,end){const a=page.indexOf(start),b=page.indexOf(end,a);
  if(a<0||b<0)throw new Error('Missing '+start);vm.runInContext(page.slice(a,b),context);}
shipped('function activeSetupJob(','function fmtSize(');
shipped('function duration(','function managedWorkspacePermission(');
shipped('function drawInstallLocation(','function chooseInstallMode(');
shipped('function setupRecheckRequired(','async function chatForHelp(');
function snapshot(){snapshots.push({...Object.fromEntries([...elements].map(([key,e])=>[key,
  {text:e.textContent,html:e.innerHTML,className:e.className,disabled:e.disabled,display:e.style.display}])),
  __calls:[...calls],__busy:context.busy,__jobState:context.STATE.job?.state});}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  context.draw();snapshot();
  const actions=input.actions||(input.start?[{kind:'start'},{kind:'poll',state:0},{kind:'finish',state:input.states.length-1}]:
    input.states.slice(1).map((s,i)=>({kind:'state',state:i+1})));
  for(const action of actions){
    if(action.state!==undefined)serverState=input.states[action.state];
    if(action.pollFails!==undefined)pollFails=action.pollFails;
    if(action.kind==='state'){context.STATE=serverState;context.draw()}
    else if(action.kind==='poll')await context.loadState();
    else if(action.kind==='begin_poll'){pollTasks.push(context.loadState());await tick()}
    else if(action.kind==='release_poll'){const get=pendingGets.shift();if(!get)throw new Error('No pending GET');action.error?get.reject(new Error('Fixture GET failed')):get.resolve();await tick()}
    else if(action.kind==='settle_polls')await Promise.all(pollTasks);
    else if(action.kind==='begin_stop'){pollTasks.push(context.stopAgent());await tick()}
    else if(action.kind==='start'){const wasBusy=context.busy,next=context.startAgent(false);if(!wasBusy)pending=next;await tick()}
    else if(action.kind==='post'){releasePost();await tick()}
    else if(action.kind==='finish'){finishStream(action.error);await pending}
    else if(action.kind==='stop')await context.stopAgent();
    else if(action.kind==='resume'){pending=context.resumeAgent();await tick()}
    else throw new Error('Unknown action '+action.kind);
    snapshot();
  }
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
    "job": None,
}
PASSED = {**STALE, "attention": None, "log_tail": "Current preflight passed",
          "software": {"state": "verified", "label": "Verified on this machine", "can_run": True,
                       "checked_at": "2026-10-06T09:00:00Z",
                       "steps": [{"name": "preflight", "ok": True}]}}


def job(state="running", identifier="attempt-1", **extra):
    return {"id": identifier, "state": state, "started_at": 1791619200,
            "updated_at": 1791619205, "ended_at": None,
            "detail": "", "installation_only": False, "model": "CRHM", "root": "D:/work", **extra}


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
    waiting = {**STALE, "job": job(), "request": {"status": "waiting", "kind": "permission",
               "title": "Permission required", "message": "Allow this model workspace"}}
    _, result = render(STALE, waiting)
    assert 'id="resume"' in result["#need"]["html"]
    assert "Permission required" in result["#need"]["html"]
    assert 'id="retry"' not in result["#need"]["html"] and result["#start"]["disabled"]
    assert result["#resume"]["disabled"]


def test_genuine_current_failure_keeps_diagnostics_and_repair_action():
    failed = {**STALE, "software": {"state": "failed", "label": "Setup failed", "can_run": False,
              "steps": [{"name": "preflight", "ok": False, "detail": "Executable missing"}]}}
    result, = render(failed)
    assert 'class="step bad"' in result["#verification"]["html"]
    assert "Executable missing" in result["#verification"]["html"]
    assert 'id="retry"' in result["#need"]["html"]
    assert result["#statusbadge"]["className"] == "badge bad"


def test_running_recheck_does_not_present_previous_valid_pass_as_finished():
    _, result = render(PASSED, {**PASSED, "job": job()})
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


@pytest.mark.parametrize("zh", [False, True])
@pytest.mark.parametrize("installation_only", [False, True])
def test_reopened_page_uses_saved_running_job_and_locks_setup_choices(zh, installation_only):
    running = {**PASSED, "job": job(installation_only=installation_only), "log_tail": "Building from saved log"}
    result, = render(running, zh=zh)
    for key in ("#start", "#provider", "#llm", "#installpath", "#existingpath", "#modenew",
                "#modeexisting", "#chooseinstall", "#saveinstall", "#chooseexistingfolder",
                "#chooseexistingfile", "#saveexisting", "#findexisting"):
        assert result[key]["disabled"], key
    assert result["#stop"]["display"] == "" and not result["#stop"]["disabled"]
    assert result["#stop"]["text"] == ("停止设置" if zh else "Stop setup")
    assert result[".log"]["text"] == running["log_tail"]
    assert "✓" not in result["#verification"]["html"] and result["#chat"]["display"] == "none"
    assert ("服务器保存" if zh else "server's saved status") in result["#activitymeta"]["text"]
    assert "Command still running" not in result["#activitymeta"]["text"]


def test_pre_response_poll_cannot_unlock_start_or_provider():
    snapshots = render(PASSED, {**PASSED, "job": job("completed")}, deferPost=True, actions=[
        {"kind": "start"}, {"kind": "poll", "state": 0}, {"kind": "start"},
        {"kind": "post"}, {"kind": "finish", "state": 1}])
    for active in snapshots[1:-1]:
        assert active["#start"]["disabled"] and active["#provider"]["disabled"]
        assert active["#chat"]["display"] == "none"
    calls = snapshots[-1]["__calls"]
    assert len([c for c in calls if c["url"] == "/api/setup-agent"]) == 1
    assert not snapshots[-1]["#start"]["disabled"]


@pytest.mark.parametrize("zh", [False, True])
def test_stream_disconnect_keeps_running_job_and_recovers_saved_log(zh):
    running = {**STALE, "job": job(), "log_tail": "Compiler still writing the saved log"}
    later = {**running, "log_tail": "Next saved build output"}
    done = {**PASSED, "job": job("completed")}
    _, started, disconnected, polled, completed = render(STALE, running, later, done, zh=zh, actions=[
        {"kind": "start"}, {"kind": "finish", "state": 1, "error": True},
        {"kind": "poll", "state": 2}, {"kind": "poll", "state": 3}])
    for active in (started, disconnected, polled):
        assert active["#start"]["disabled"] and active["#chat"]["display"] == "none"
    assert disconnected[".log"]["text"] == running["log_tail"]
    assert polled[".log"]["text"] == later["log_tail"]
    assert not polled["#stop"]["disabled"]
    assert ("不会停止设置" if zh else "does not stop setup") in disconnected["#jobnotice"]["text"]
    assert completed["#statusbadge"]["className"] == "badge ok"


def test_status_failure_after_disconnect_does_not_reenable_until_authoritative_poll():
    running = {**STALE, "job": job()}
    done = {**PASSED, "job": job("completed")}
    _, _, disconnected, recovered, completed = render(STALE, running, done, actions=[
        {"kind": "start"}, {"kind": "finish", "error": True, "pollFails": True},
        {"kind": "poll", "state": 1, "pollFails": False}, {"kind": "poll", "state": 2}])
    assert disconnected["#start"]["disabled"] and disconnected["#provider"]["disabled"]
    assert "Cannot read server status" in disconnected["#jobnotice"]["text"]
    assert recovered["#start"]["disabled"] and not recovered["#stop"]["disabled"]
    assert not completed["#start"]["disabled"]


@pytest.mark.parametrize("zh", [False, True])
def test_stop_targets_exact_attempt_and_stays_stopping_until_terminal(zh):
    running = {**STALE, "job": job()}
    stopping = {**running, "job": job("stopping")}
    cancelled = {**running, "job": job("cancelled", detail="Stopped by the user")}
    _, stopped, old_poll, terminal = render(running, stopping, cancelled, zh=zh, actions=[
        {"kind": "stop", "state": 1}, {"kind": "poll", "state": 0}, {"kind": "poll", "state": 2}])
    stop_calls = [c for c in stopped["__calls"] if c["url"] == "/api/setup-stop"]
    assert [c["body"] for c in stop_calls] == [{"model": "CRHM", "job_id": "attempt-1"}]
    for active in (stopped, old_poll):
        assert active["#stop"]["disabled"] and active["#start"]["disabled"]
        assert active["#stop"]["text"] == ("正在停止…" if zh else "Stopping…")
    assert terminal["#stop"]["display"] == "none" and not terminal["#start"]["disabled"]
    assert terminal["#statusbadge"]["text"] == ("设置已取消" if zh else "Setup cancelled")


def test_stale_stop_adopts_replacement_job_without_cancelling_it():
    running = {**STALE, "job": job()}
    replacement = {**running, "job": job(identifier="attempt-2")}
    _, result = render(running, replacement, stopResponse={"status": 409, "body": {
        "error": "The setup attempt changed", "job": replacement["job"]}}, actions=[{"kind": "stop", "state": 1}])
    stop_calls = [c for c in result["__calls"] if c["url"] == "/api/setup-stop"]
    assert len(stop_calls) == 1 and stop_calls[0]["body"]["job_id"] == "attempt-1"
    assert result["#start"]["disabled"] and not result["#stop"]["disabled"]
    assert "attempt changed" in result["#jobnotice"]["text"]


def test_duplicate_start_uses_conflict_job_and_does_not_retry():
    running = {**STALE, "job": job(identifier="already-running")}
    _, result = render(STALE, running, postResponse={"status": 409, "body": {
        "error": "Setup is already running", "job": running["job"]}}, actions=[{"kind": "start", "state": 1}])
    assert result["#start"]["disabled"] and not result["#stop"]["disabled"]
    assert "already running" in result["#jobnotice"]["text"]
    assert len([c for c in result["__calls"] if c["url"] == "/api/setup-agent"]) == 1


@pytest.mark.parametrize("zh", [False, True])
@pytest.mark.parametrize("state", ["cancelled", "interrupted", "waiting_for_user"])
def test_unfinished_job_does_not_reuse_previous_green_software_result(zh, state):
    result, = render({**PASSED, "job": job(state, detail="Attempt not verified")}, zh=zh)
    assert result["#statusbadge"]["className"] == "badge warn"
    assert result["#chat"]["display"] == "none" and result["#stop"]["display"] == "none"
    assert "✓" not in result["#verification"]["html"]
    assert 'id="retry"' in result["#need"]["html"] and not result["#retry"]["disabled"]
    assert "Attempt not verified" in result["#need"]["html"]


def test_waiting_job_allows_explicit_resume_after_worker_has_stopped():
    result, = render({**STALE, "job": job("waiting_for_user"), "request": {
        "status": "waiting", "kind": "permission", "title": "Permission required", "message": "Allow this command"}})
    assert not result["#resume"]["disabled"] and not result["#provider"]["disabled"]
    assert result["#start"]["disabled"] and result["#stop"]["display"] == "none"


def test_rejected_start_does_not_claim_an_agent_continues_in_background():
    _, result = render(STALE, postResponse={"status": 400, "body": {"error": "Provider unavailable"}},
                       actions=[{"kind": "start"}])
    assert result["#jobnotice"]["text"] == "Provider unavailable"
    assert not result["#start"]["disabled"] and result["#stop"]["display"] == "none"
    assert "background" not in result[".log"]["text"]


def test_failed_resume_does_not_launch_an_agent():
    waiting = {**STALE, "job": job("waiting_for_user"), "request": {
        "status": "waiting", "kind": "permission", "title": "Permission required", "message": "Allow this command"}}
    _, result = render(waiting, resumeResponse={"status": 409, "body": {"error": "Request changed"}},
                       actions=[{"kind": "resume"}])
    assert result["#jobnotice"]["text"] == "Request changed"
    assert not any(c["url"] == "/api/setup-agent" for c in result["__calls"])


def test_reopened_job_elapsed_time_uses_server_epoch_seconds():
    result, = render({**STALE, "job": job()}, now=1791619207000)
    assert result["#activitytime"]["text"] == "00:07"


def test_recovery_pending_job_cannot_stop_an_unowned_process():
    running = {**STALE, "job": job(can_stop=False, recovery_pending=True)}
    initial, result = render(running, actions=[{"kind": "stop"}])
    assert initial["#stop"]["disabled"] and result["#start"]["disabled"]
    assert not any(c["url"] == "/api/setup-stop" for c in result["__calls"])


def test_successful_resume_waits_for_saved_state_before_starting():
    waiting = {**STALE, "job": job("waiting_for_user"), "request": {
        "status": "waiting", "kind": "permission", "title": "Permission required", "message": "Allow this command"}}
    _, result = render(waiting, actions=[{"kind": "resume", "pollFails": True}])
    assert result["#resume"]["disabled"] and result["#provider"]["disabled"]
    assert not any(c["url"] == "/api/setup-agent" for c in result["__calls"])


def test_slow_status_requests_are_shared_and_each_response_updates_the_page():
    running = {**STALE, "job": job()}
    completed = {**PASSED, "job": job("completed")}
    interrupted = {**STALE, "job": job("interrupted")}
    snapshots = render(running, completed, interrupted, deferGet=True, actions=[
        *[{"kind": "begin_poll", "state": 1} for _ in range(6)],
        {"kind": "release_poll"}, {"kind": "settle_polls"},
        {"kind": "begin_poll", "state": 2}, {"kind": "release_poll"}, {"kind": "settle_polls"}])
    for waiting in snapshots[1:7]:
        assert waiting["#start"]["disabled"]
        assert len([c for c in waiting["__calls"] if c["url"].startswith("/api/setup/")]) == 1
    assert snapshots[7]["__jobState"] == "completed"
    assert snapshots[7]["#statusbadge"]["className"] == "badge ok"
    assert snapshots[-1]["__jobState"] == "interrupted"
    assert len([c for c in snapshots[-1]["__calls"] if c["url"].startswith("/api/setup/")]) == 2


@pytest.mark.parametrize("old_read_fails", [False, True])
def test_stop_mutation_invalidates_older_get_and_coalesces_one_fresh_read(old_read_fails):
    running = {**STALE, "job": job()}
    stopping = {**running, "job": job("stopping")}
    cancelled = {**running, "job": job("cancelled")}
    snapshots = render(running, stopping, cancelled, deferGet=True, actions=[
        {"kind": "begin_poll"}, {"kind": "begin_stop", "state": 1},
        {"kind": "begin_poll"},
        {"kind": "release_poll", "state": 2, "error": old_read_fails},
        {"kind": "release_poll"}, {"kind": "settle_polls"}])
    for stopped in snapshots[2:5]:
        assert stopped["__jobState"] == "stopping"
        assert stopped["#start"]["disabled"] and stopped["#stop"]["disabled"]
        assert "Cannot read server status" not in stopped["#jobnotice"]["text"]
    assert snapshots[-1]["__jobState"] == "cancelled"
    assert not snapshots[-1]["#start"]["disabled"]
    assert len([c for c in snapshots[-1]["__calls"] if c["url"].startswith("/api/setup/")]) == 2


@pytest.mark.parametrize("zh", [False, True])
def test_compact_activity_reports_setup_state_without_inferring_agent_work(zh):
    running = {**STALE, "job": job()}
    initial, disconnected = render(running, zh=zh, actions=[{"kind": "poll", "pollFails": True}])
    assert ("正在设置" if zh else "Setup running") in initial["#runstate"]["html"]
    assert ("正在确认设置状态" if zh else "Checking setup status") in disconnected["#runstate"]["html"]
    for result in (initial, disconnected):
        assert "Agent working" not in result["#runstate"]["html"]
        assert "Agent 正在处理" not in result["#runstate"]["html"]
