"""Exercise the shipped project investigation UI without a provider or browser."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

WEB = Path(__file__).parents[1] / "kiss_cli/web"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node is required for UI checks")
RUNNER = r"""
const fs=require('node:fs'),vm=require('node:vm');
const input=JSON.parse(fs.readFileSync(0,'utf8')),elements=new Map(),requests=[],resumes=[],timers=new Map(),events={};
let serial=0,release,readCount=0;
function $(id){if(!elements.has(id))elements.set(id,{value:'',textContent:'',innerHTML:'',disabled:false,hidden:false,title:'',className:'',
  classes:new Set(),classList:{contains(c){return elements.get(id).classes.has(c)},add(c){elements.get(id).classes.add(c)},remove(c){elements.get(id).classes.delete(c)}},
  setAttribute(k,v){this[k]=v},addEventListener(k,v){this[k]=v}});return elements.get(id)}
const context={console,session:input.noSession?null:{id:'a',provider:'api:deepseek'},projectBusy:!!input.busy,providerReady:input.ready!==false,
  document:{hidden:false,addEventListener(k,v){events[k]=v}},
  setTimeout(fn){const id=++serial;timers.set(id,fn);return id},clearTimeout(id){timers.delete(id)},
  addEventListener(k,v){events[k]=v}};
context.window=context;
const response=(data,ok=true)=>({ok,status:ok?200:409,json:async()=>data});
context.fetch=async(url,init={})=>{
  requests.push({url,method:init.method||'GET',body:init.body?JSON.parse(init.body):null});
  if(init.method==='POST'){
    if(input.deferMutation)await new Promise(resolve=>release=resolve);
    if(input.failMutation)return response({error:'Exact KI revision changed'},false);
    return response(input.mutated||{job:{...input.job,status:'reviewing'}});
  }
  if(input.deferRead)await new Promise(resolve=>release=resolve);
  const saved=input.reads?.[Math.min(readCount++,input.reads.length-1)];
  return response(saved||{job:input.job||null,available:input.available!==false,reason:input.reason||''});
};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
const controller=context.GeoForgeInvestigation.create({$,chinese:()=>!!input.zh,session:()=>context.session,
  busy:()=>context.projectBusy,ready:()=>context.providerReady,binding:()=>({provider:'api:deepseek',llm_model:'deepseek-chat'}),
  beforeOpen(){context.opened=true},resume:async(id,message)=>{resumes.push({id,message})}});
const tick=()=>new Promise(setImmediate);
(async()=>{
  if(input.mode==='guide')await $('#guide-investigation-open').onclick();
  else await $('#openinvestigation').onclick();
  await tick();
  if(input.mode==='staleRead'){
    context.session={id:'b'};controller.close();controller.sync();release();await tick();
  }else if(input.mode==='closePoll')controller.close();
  else if(input.mode==='providerReady'){
    context.providerReady=true;controller.sync();await tick();
  }else if(input.mode==='visibility'){
    context.document.hidden=true;events.visibilitychange();
    context.timersWhileHidden=timers.size;
    context.document.hidden=false;events.visibilitychange();await tick();
  }else if(input.mode==='focus'){
    events.focus();await tick();
  }
  else if(input.mode==='switch'){
    $('#investigation-issue').value='Project A draft';$('#investigation-issue').input();
    context.session={id:'b'};controller.sync();await tick();
    $('#investigation-issue').value='Project B draft';$('#investigation-issue').input();
    context.session={id:'a'};controller.sync();await tick();
  }else if(input.action){
    $('#investigation-issue').value=input.issue??'Check the SHAW output reader';
    if(input.selected)$('#investigation-ki').value=input.selected;
    const first=$('#investigation-'+input.action).onclick();await tick();
    if(input.double)await $('#investigation-'+input.action).onclick();
    if(input.deferMutation){
      if(input.switchDuringMutation){context.session={id:'b'};controller.close();controller.sync()}
      release();
    }
    await first;await tick();
  }
  for(let n=0;n<(input.pollTicks||0);n++){
    const entry=timers.entries().next().value;if(!entry)break;
    timers.delete(entry[0]);entry[1]();await tick();
  }
  const nodes={};for(const [id,e] of elements)nodes[id]={text:e.textContent,html:e.innerHTML,disabled:e.disabled,hidden:e.hidden,value:e.value,classes:[...e.classes],inert:e.inert,ariaHidden:e['aria-hidden'],ariaExpanded:e['aria-expanded']};
  process.stdout.write(JSON.stringify({nodes,requests,resumes,timers:timers.size,timersWhileHidden:context.timersWhileHidden}));
})().catch(e=>{console.error(e);process.exitCode=1});
"""


def evaluate(**payload):
    result = subprocess.run([NODE, "-e", RUNNER, str(WEB / "investigation.js")],
        input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8",
        timeout=15, check=True)
    return json.loads(result.stdout)


def job(status="reviewed", **extra):
    return {"id": "review-1", "status": status, "selected_kis": ["SHAW", "CRHM"],
            "provider": "api:deepseek", "llm_model": "deepseek-chat", "context_digest": "abc123",
            "reviewers": [{"id": role, "status": "completed", "summary": "Read real evidence"}
                for role in ("contract_runtime", "data_science", "reproducibility_risks")],
            **extra}


def verified(**extra):
    return job("verified", repair={"ki_name": "SHAW", "kdt_job_id": "kdt-1", "status": "verified",
               "can_apply": True, "can_verify": True, "verification_id": "exact-verification", **extra})


@pytest.mark.parametrize("zh", [False, True])
def test_panel_is_bilingual_and_available_without_ready_software(zh):
    result = evaluate(zh=zh, job=job())
    nodes = result["nodes"]
    assert nodes["#investigation-label"]["text"] == ("排查 KI" if zh else "Investigate KI")
    assert not nodes["#investigation-start"]["disabled"]
    assert ("综合报告" if zh else "Combined report") not in nodes["#investigation-report"]["html"]


def test_header_click_opens_panel_and_close_removes_it_from_interaction():
    opened=evaluate(job=job("reviewing"))["nodes"]
    assert "open" in opened["#investigationpanel"]["classes"]
    assert opened["#investigationpanel"]["inert"] is False
    assert opened["#investigationpanel"]["ariaHidden"] == "false"
    assert opened["#openinvestigation"]["ariaExpanded"] == "true"
    closed=evaluate(job=job("reviewing"),mode="closePoll")
    assert "open" not in closed["nodes"]["#investigationpanel"]["classes"]
    assert closed["nodes"]["#investigationpanel"]["inert"] is True
    assert closed["nodes"]["#investigationpanel"]["ariaHidden"] == "true"
    assert closed["timers"] == 0


def test_queued_review_updates_to_saved_partial_report_without_manual_refresh():
    done=job("partial",report={"summary":"Two reviewers failed; one report retained"})
    result=evaluate(action="start",mutated={"job":job("queued")},pollTicks=2,
        reads=[{"job":None,"available":True},{"job":job("reviewing"),"available":True},
               {"job":done,"available":True}])
    assert len([r for r in result["requests"] if r["method"]=="GET"]) == 3
    assert "Two reviewers failed" in result["nodes"]["#investigation-report"]["html"]
    assert result["timers"] == 0


def test_finished_reviews_keep_polling_until_host_worker_releases_then_enable_draft():
    locked={"job":job("reviewed"),"busy":True,"available":False,
            "reason":"KI investigation is running"}
    pending=evaluate(reads=[locked])
    assert pending["nodes"]["#investigation-draft"]["disabled"]
    assert pending["timers"] == 1
    result=evaluate(reads=[locked,{"job":job("reviewed"),"busy":False,
        "available":True,"reason":""}],pollTicks=1)
    assert len(result["requests"]) == 2
    assert not result["nodes"]["#investigation-draft"]["disabled"]
    assert not result["nodes"]["#investigation-message"]["text"]
    assert result["timers"] == 0


def test_busy_without_job_keeps_polling_and_closed_panel_stops_it():
    saved={"job":None,"busy":True,"available":False,"reason":"Preparing investigation"}
    assert evaluate(reads=[saved])["timers"] == 1
    assert evaluate(reads=[saved],mode="closePoll")["timers"] == 0


def test_host_busy_prevents_applying_even_when_finished_job_is_eligible():
    result=evaluate(action="apply",reads=[{"job":verified(),"busy":True,"available":False}])
    assert result["nodes"]["#investigation-apply"]["disabled"]
    assert not result["resumes"]
    assert not [r for r in result["requests"] if r["method"]=="POST"]


def test_async_provider_discovery_refreshes_host_availability_without_manual_refresh():
    result=evaluate(ready=False,mode="providerReady",reads=[
        {"job":None,"available":False,"reason":"Provider discovery pending"},
        {"job":None,"available":True,"reason":""}])
    assert len(result["requests"]) == 2
    assert not result["nodes"]["#investigation-start"]["disabled"]
    assert not result["nodes"]["#investigation-message"]["text"]


@pytest.mark.parametrize("mode",["visibility","focus"])
def test_returning_to_visible_panel_reconciles_host_progress(mode):
    result=evaluate(mode=mode,reads=[{"job":job("queued"),"available":True},
        {"job":job("reviewed",report={"summary":"Fresh saved report"}),"available":True}])
    assert "Fresh saved report" in result["nodes"]["#investigation-report"]["html"]
    assert result["timers"] == 0
    if mode=="visibility":assert result["timersWhileHidden"] == 0


@pytest.mark.parametrize("zh",[False,True])
def test_guide_explains_independent_reviews_structural_gate_and_explicit_apply(zh):
    result=evaluate(zh=zh,mode="guide")
    nodes=result["nodes"]
    assert "open" in nodes["#investigationpanel"]["classes"]
    assert ("三方独立审查" if zh else "three independent reviews") in nodes["#guide-investigation-steps"]["text"]
    assert ("科学验证通过仍需模型测试证据" if zh else "scientific pass still requires model-test evidence") in nodes["#guide-investigation-limit"]["text"]
    assert not nodes["#guide-investigation-open"]["disabled"]
    assert evaluate(noSession=True,mode="guide")["nodes"]["#guide-investigation-open"]["disabled"]


@pytest.mark.parametrize("state", [{"noSession": True}, {"ready": False}, {"busy": True}, {"available": False, "reason": "Blocked"}])
def test_panel_keeps_explanation_when_start_unavailable(state):
    result = evaluate(**state)
    assert result["nodes"]["#investigation-start"]["disabled"]
    assert result["nodes"]["#investigation-binding"]["text"]
    assert not result["requests"] if state.get("noSession") else result["requests"]


def test_start_sends_explicit_issue_and_current_ai_binding_once():
    result = evaluate(action="start", deferMutation=True, double=True)
    writes = [r for r in result["requests"] if r["method"] == "POST"]
    assert len(writes) == 1
    assert writes[0]["url"] == "/api/session/a/investigation/start"
    assert writes[0]["body"] == {"issue": "Check the SHAW output reader", "provider": "api:deepseek", "llm_model": "deepseek-chat"}


def test_empty_issue_does_not_start_billable_reviews():
    result = evaluate(action="start", issue="   ")
    assert not [r for r in result["requests"] if r["method"] == "POST"]
    assert "Describe" in result["nodes"]["#investigation-message"]["text"]


def test_reports_coverage_errors_and_ki_names_are_escaped():
    unsafe='<script>alert("bad")</script>'
    value=job(report={"findings": [unsafe]}, coverage={"excluded": [unsafe]}, error=unsafe)
    value["reviewers"][0].update(summary=unsafe, report={"evidence": [unsafe]})
    result=evaluate(job=value)
    html=result["nodes"]["#investigation-report"]["html"]
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "3/3 reviewers completed" in html
    assert "Context coverage and exclusions" in html and "Combined report" in html


def test_partial_report_cannot_become_repair_or_completed_consensus():
    value=job("partial");value["reviewers"][2].update(status="failed", error="Provider disconnected")
    result=evaluate(job=value, action="draft")
    assert result["nodes"]["#investigation-draft"]["hidden"]
    assert "2/3 reviewers completed" in result["nodes"]["#investigation-report"]["html"]
    assert not [r for r in result["requests"] if r["method"] == "POST"]


def test_draft_uses_explicit_selected_ki():
    result=evaluate(job=job(),action="draft",selected="CRHM",mutated={"job":job("drafting")})
    assert result["requests"][-1]["body"] == {"ki_name": "CRHM"}
    assert result["requests"][-1]["url"].endswith("/review-1/draft")


@pytest.mark.parametrize("action", ["build", "verify"])
def test_draft_actions_use_saved_job_and_poll_async_work(action):
    value=job("draft",repair={"kdt_job_id":"kdt-1","ki_name":"SHAW","status":"draft","can_verify":True})
    result=evaluate(job=value,action=action,mutated={"job":job("authoring" if action=="build" else "verifying")})
    assert result["requests"][-1]["url"].endswith("/review-1/"+action)
    assert result["timers"] == 1


@pytest.mark.parametrize("repair", [{"can_apply": False}, {"verification_id": ""}])
def test_apply_requires_host_eligibility_and_exact_verification(repair):
    result=evaluate(job=verified(**repair),action="apply")
    assert result["nodes"]["#investigation-apply"]["disabled"]
    assert not result["resumes"] and len(result["requests"]) == 1


def test_apply_sends_exact_verification_and_resumes_only_after_host_success():
    result=evaluate(job=verified(),action="apply",mutated={"job":job("applied"),"resume_message":"Review the repaired KI and continue."})
    assert result["requests"][-1]["body"] == {"verification_id":"exact-verification"}
    assert result["resumes"] == [{"id":"a","message":"Review the repaired KI and continue."}]
    assert result["timers"] == 0


def test_host_rejection_preserves_report_and_never_resumes():
    result=evaluate(job=verified(),action="apply",failMutation=True)
    assert not result["resumes"]
    assert "Exact KI revision changed" in result["nodes"]["#investigation-message"]["text"]
    assert "Native and scientific tests require their own evidence" in result["nodes"]["#investigation-report"]["html"]


@pytest.mark.parametrize("zh", [False, True])
def test_failed_kdt_report_exposes_actionable_checks_without_unescaped_html(zh):
    value=verified(can_apply=False)
    value.update(status="failed")
    value["repair"].update(status="failed",retryable=True,verification={"ok":False,
        "report":{"checks":[{"detail":"Missing diagnostics/triplets.yaml <unsafe>"}]}})
    html=evaluate(job=value,zh=zh)["nodes"]["#investigation-report"]["html"]
    assert ("KDT 验证报告" if zh else "KDT verification report") in html
    assert "diagnostics/triplets.yaml &lt;unsafe&gt;" in html and "<unsafe>" not in html


@pytest.mark.parametrize("zh",[False,True])
def test_repair_review_shows_author_summary_draft_path_and_exact_changed_files_safely(zh):
    value=verified(author_report='Updated reader <script>alert("bad")</script>',
        candidate_path='C:/drafts/SHAW<unsafe>',verification={"changes":{
            "added":["tools/new_reader.py"],"modified":["SKILL.md","tools/<unsafe>.py"],
            "removed":["tools/old_reader.py"],"candidate_digest":"exact-draft-digest"}})
    html=evaluate(job=value,zh=zh)["nodes"]["#investigation-report"]["html"]
    assert ("修复 Agent 总结" if zh else "Repair agent summary") in html
    assert ("修复草稿目录" if zh else "Repair draft folder") in html
    assert ("变更文件" if zh else "Changed files") in html
    for label,count in [("新增" if zh else "Added",1),("修改" if zh else "Modified",2),("删除" if zh else "Removed",1)]:
        assert f"{label} ({count})" in html
    for path in ["tools/new_reader.py","SKILL.md","tools/old_reader.py"]:assert path in html
    assert 'data-report-key="author"' in html and 'data-report-key="changes"' in html
    assert "exact-draft-digest" in html
    assert "C:/drafts/SHAW&lt;unsafe&gt;" in html
    assert "tools/&lt;unsafe&gt;.py" in html
    assert "<script>" not in html and "<unsafe>" not in html
    assert "&lt;script&gt;" in html


def test_missing_optional_repair_summary_and_file_delta_do_not_invent_changes():
    html=evaluate(job=verified())["nodes"]["#investigation-report"]["html"]
    assert "Repair agent summary" not in html and "Changed files" not in html


@pytest.mark.parametrize("zh",[False,True])
def test_shortened_or_incomplete_repair_reports_keep_explicit_limits_and_total_counts(zh):
    value=verified(author_report="Author summary",author_report_meta={"truncated":True},
        verification={"changes":{"added":["tools/new.py"],"modified":[],"removed":[],
            "counts":{"added":501,"modified":0,"removed":0},"truncated":True,"complete":False,
            "uncompared_baseline_paths":["test_cases/<cache>"],"candidate_digest":"digest",
            "uncompared_candidate_paths":["tools/<new-cache>"]}})
    html=evaluate(job=value,zh=zh)["nodes"]["#investigation-report"]["html"]
    assert ("新增 (501)" if zh else "Added (501)") in html
    assert ("文件列表已截短" if zh else "File lists are shortened") in html
    assert ("文件比较不完整" if zh else "file comparison is incomplete") in html
    assert ("修复 Agent 总结已截短" if zh else "repair agent summary was shortened") in html
    assert "test_cases/&lt;cache&gt;" in html and "<cache>" not in html
    assert ("未比较的草稿路径" if zh else "Uncompared draft paths") in html
    assert "tools/&lt;new-cache&gt;" in html and "<new-cache>" not in html


def test_old_project_apply_response_cannot_resume_new_project():
    result=evaluate(job=verified(),action="apply",deferMutation=True,switchDuringMutation=True,
                    mutated={"job":job("applied"),"resume_message":"Continue A"})
    assert not result["resumes"]
    assert "review-1" not in result["nodes"]["#investigation-report"]["html"]


def test_old_get_response_cannot_render_new_project():
    result=evaluate(job=job(),mode="staleRead",deferRead=True)
    assert "review-1" not in result["nodes"]["#investigation-report"]["html"]
    assert result["timers"] == 0


@pytest.mark.parametrize("status,timers", [("reviewing",1),("authoring",1),("verifying",1),("applying",1),("reviewed",0),("partial",0),("failed",0)])
def test_polling_only_for_active_open_investigations(status,timers):
    assert evaluate(job=job(status))["timers"] == timers
    assert evaluate(job=job(status),mode="closePoll")["timers"] == 0


def test_session_switch_keeps_independent_issue_drafts():
    result=evaluate(mode="switch")
    assert result["nodes"]["#investigation-issue"]["value"] == "Project A draft"


@pytest.mark.parametrize("retryable", [False, True])
def test_failed_repair_can_only_rebuild_when_host_allows_retry(retryable):
    value=job("failed",error="Repair needs attention",repair={"status":"failed","kdt_job_id":"kdt-1","retryable":retryable})
    result=evaluate(job=value)
    assert result["nodes"]["#investigation-build"]["hidden"] is not retryable
    assert result["nodes"]["#investigation-verify"]["hidden"]
    assert result["nodes"]["#investigation-apply"]["disabled"]


def test_host_allows_failed_verification_retry_without_another_author_turn():
    value=job("failed",repair={"status":"failed","kdt_job_id":"kdt-1","retryable":True,
        "can_verify":True,"can_apply":False,"verification_id":"old-failed-attempt"})
    ready=evaluate(job=value)
    assert not ready["nodes"]["#investigation-verify"]["hidden"]
    assert not ready["nodes"]["#investigation-verify"]["disabled"]
    running=job("verifying",repair={"status":"verifying","kdt_job_id":"kdt-1",
        "can_verify":False,"can_apply":False})
    result=evaluate(job=value,action="verify",mutated={"job":running})
    writes=[r for r in result["requests"] if r["method"]=="POST"]
    assert len(writes)==1 and writes[0]["url"]=="/api/session/a/investigation/review-1/verify"
    assert writes[0]["body"] == {}
    assert result["nodes"]["#investigation-apply"]["disabled"]
    assert not result["resumes"] and result["timers"]==1


@pytest.mark.parametrize("state",["draft","verified","author_failed","recovery_required"])
def test_verify_requires_explicit_host_eligibility_for_every_repair_state(state):
    value=job(state,repair={"status":state,"kdt_job_id":"kdt-1","retryable":True,
        "can_verify":False,"can_apply":False})
    result=evaluate(job=value,action="verify")
    assert result["nodes"]["#investigation-verify"]["hidden"]
    assert result["nodes"]["#investigation-verify"]["disabled"]
    assert not [r for r in result["requests"] if r["method"]=="POST"]


def test_applying_transaction_cannot_be_cancelled_or_started_again():
    result=evaluate(job=job("applying"),action="cancel")
    assert result["nodes"]["#investigation-cancel"]["hidden"]
    assert result["nodes"]["#investigation-start"]["disabled"]
    assert len(result["requests"]) == 1


def test_cancel_is_available_during_review_and_does_not_resume():
    result=evaluate(job=job("reviewing"),action="cancel",mutated={"job":job("cancelled")})
    assert result["requests"][-1]["url"].endswith("/review-1/cancel")
    assert result["timers"] == 0 and not result["resumes"]


def test_header_action_and_script_are_always_present():
    page=(WEB/"app.html").read_text(encoding="utf-8")
    button=page.split('id="openinvestigation"',1)[0].rsplit('<button',1)[1]
    assert "disabled" not in button
    assert '<script src="/investigation.js"></script>' in page
    assert 'resume:resumeInvestigation' in page


RESUME_RUNNER=r"""
const fs=require('node:fs'),vm=require('node:vm'),page=fs.readFileSync(process.argv[1],'utf8');
const input=JSON.parse(fs.readFileSync(0,'utf8')),msg={value:'User draft'},sent=[];
const c={CUR:{id:'a'},DRAFTS:new Map(),$:()=>msg,chineseUI:()=>false,sessionBusy:()=>false,currentProviderReady:()=>true,
  openSession:async()=>{if(input.switchBefore)c.CUR={id:'b'}},
  send:async()=>{sent.push(msg.value);msg.value=input.typedDuring||'';if(input.switchDuring)c.CUR={id:'b'}}};
vm.createContext(c);vm.runInContext(page.slice(page.indexOf('async function resumeInvestigation('),page.indexOf('if(window.GeoForgeInvestigation)')),c);
c.resumeInvestigation('a','Resume repaired KI').then(()=>finish()).catch(error=>finish(error.message));
function finish(error){process.stdout.write(JSON.stringify({sent,draft:msg.value,saved:c.DRAFTS.get('a'),error}))}
"""


@pytest.mark.parametrize("settings,expected_sent,expected_draft", [({},True,"User draft"),({"typedDuring":"New typing"},True,"New typing"),({"switchBefore":True},False,"User draft")])
def test_apply_resume_uses_normal_send_and_preserves_composer(settings,expected_sent,expected_draft):
    result=subprocess.run([NODE,"-e",RESUME_RUNNER,str(WEB/"app.html")],input=json.dumps(settings),
        text=True,encoding="utf-8",capture_output=True,check=True,timeout=15)
    data=json.loads(result.stdout)
    assert bool(data["sent"]) is expected_sent
    assert data["draft"] == expected_draft
