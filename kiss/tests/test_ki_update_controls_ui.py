"""Execute the shipped KI updater controls with a fake transport and clock."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

PAGE = Path(__file__).parents[1] / "kiss_cli" / "web" / "library.html"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node is required")

RUNNER = r"""
const fs=require('node:fs'),vm=require('node:vm');
const page=fs.readFileSync(process.argv[1],'utf8'),input=JSON.parse(fs.readFileSync(0,'utf8'));
const elements=new Map(),requests=[],timers=new Map(),gates=new Map(),frames={};
let timerId=0;
const language=input.zh?'zh-CN':'en';
function element(key){
  if(!elements.has(key)){
    const el={textContent:'',innerHTML:'',disabled:false,title:'',open:false};
    el.classList={add(n){if(n==='open')el.open=true;}};
    elements.set(key,el);
  }
  return elements.get(key);
}
const context={console,URL,$:element,KIUPDATE:input.report||null,KIUPDATE_TIMER:null,
  KIUPDATE_REVISION:input.revision||'',MODELS:[],STATUS:{},SEL:new Set(),
  window:{GeoForgeI18n:{language}},GeoForgeI18n:{language},
  draws:[],drawList(){context.draws.push('list');},drawDetails(){context.draws.push('details');},
  drawSetup(){context.draws.push('setup');},
  clearTimeout:id=>timers.delete(id),setTimeout:(fn,ms)=>{const id=++timerId;timers.set(id,{fn,ms});return id;},
  fetch:async(url,options)=>{
    requests.push({url,method:options?.method||'GET',body:options?.body});
    const reply=input.replies?.[url]?.shift();
    if(!reply)throw new Error('Unexpected request '+url);
    if(reply.defer)await new Promise(resolve=>gates.set(reply.defer,resolve));
    if(reply.error)throw new Error(reply.error);
    return {ok:reply.status===undefined||reply.status<400,status:reply.status||200,
      json:async()=>{if(reply.invalidJSON)throw new Error('invalid JSON');return reply.data;}};
  },
};
vm.createContext(context);
function shipped(start,end){
  const a=page.indexOf(start),b=page.indexOf(end,a);
  if(a<0||b<0)throw new Error('Missing shipped JavaScript '+start);
  vm.runInContext(page.slice(a,b),context);
}
shipped('function esc(s){','\n');
shipped('function safeUrl(s){','function drawList(){');
shipped('$("#updateretry").onclick=','\n');
context.flush=()=>new Promise(resolve=>setImmediate(resolve));
context.release=name=>{const resolve=gates.get(name);if(!resolve)throw new Error('Missing gate '+name);gates.delete(name);resolve();};
context.tick=async()=>{const item=timers.entries().next().value;if(!item)throw new Error('No timer');timers.delete(item[0]);await item[1].fn();};
context.snapshot=name=>{
  frames[name]={elements:Object.fromEntries([...elements].map(([k,e])=>[k,{text:e.textContent,html:e.innerHTML,disabled:e.disabled,title:e.title,open:e.open,href:e.href}])),
    report:context.KIUPDATE,revision:context.KIUPDATE_REVISION,requests:[...requests],
    timers:[...timers.values()].map(t=>t.ms),draws:[...context.draws],models:context.MODELS,
    state:vm.runInContext('({starting:KIUPDATE_STARTING,statusError:KIUPDATE_STATUS_ERROR,actionError:KIUPDATE_ACTION_ERROR,viewError:KIUPDATE_VIEW_ERROR})',context)};
};
(async()=>{
  await vm.runInContext('(async()=>{'+input.script+'})()',context);
  context.snapshot('final');process.stdout.write(JSON.stringify(frames));
})().catch(error=>{console.error(error);process.exitCode=1;});
"""


def render(script, *, report=None, replies=None, zh=False, revision=""):
    result = subprocess.run(
        [NODE, "-e", RUNNER, str(PAGE)],
        input=json.dumps(dict(script=script, report=report, replies=replies, zh=zh,
                             revision=revision)),
        capture_output=True, text=True, encoding="utf-8", timeout=10, check=True,
    )
    return json.loads(result.stdout)


def reply(data, **kwargs):
    return dict(data=data, **kwargs)


def node(frame, key):
    return frame["elements"][key]


@pytest.mark.parametrize("zh", [False, True])
def test_disabled_state_explains_reason_and_cannot_start_check(zh):
    f = render('await loadKiUpdate(true); await $("#updateretry").onclick();', zh=zh,
               replies={"/api/ki-updates": [reply(dict(state="disabled", branch="main",
                    summary="Automatic KI updates run in the Desktop app."))]})["final"]
    assert len(f["requests"]) == 1
    assert node(f, "#updateretry")["disabled"]
    assert node(f, "#updatemodal")["open"]
    assert "Automatic KI updates" in node(f, "#updatedetails")["html"]
    assert node(f, "#kiupdatelabel")["text"] == ("更新不可用" if zh else "Updates unavailable")
    assert f["timers"] == []


@pytest.mark.parametrize("next_state", ["idle", "disabled"])
def test_rejected_check_shows_server_error_even_after_successful_status_refresh(next_state):
    f = render('await $("#updateretry").onclick();', report={"state": "idle"}, replies={
        "/api/ki-updates/check": [reply({"error": "Desktop updater is disabled"}, status=400)],
        "/api/ki-updates": [reply({"state": next_state})],
    })["final"]
    assert f["state"]["actionError"] == "Desktop updater is disabled"
    assert "Desktop updater is disabled" in node(f, "#updatesummary")["html"]
    assert node(f, "#updateretry")["disabled"] == (next_state == "disabled")


def test_start_button_is_disabled_until_post_finishes_and_duplicate_click_is_ignored():
    f = render('const p=$("#updateretry").onclick(); await flush(); snapshot("waiting"); '
               'await $("#updateretry").onclick(); release("post"); await p;',
               report={"state": "idle"}, replies={
        "/api/ki-updates/check": [reply({"state": "checking", "started": True}, defer="post")],
        "/api/ki-updates": [reply({"state": "checking"})],
    })
    assert node(f["waiting"], "#updateretry")["disabled"]
    assert node(f["waiting"], "#updateretry")["text"] == "Starting…"
    assert len([r for r in f["final"]["requests"] if r["method"] == "POST"]) == 1
    assert f["final"]["timers"] == [1000]


def test_already_running_reply_still_polls_and_refreshes_new_active_catalogue_once():
    updated = {"state": "updated", "active_revision": "new", "summary": "Library updated"}
    f = render('await $("#updateretry").onclick(); snapshot("running"); await tick(); '
               'snapshot("finished"); await loadKiUpdate();', report={"state": "idle"}, replies={
        "/api/ki-updates/check": [reply({"state": "checking", "started": False})],
        "/api/ki-updates": [reply({"state": "checking"}), reply(updated), reply(updated)],
        "/api/models": [reply([{"name": "CRHM"}])],
        "/api/status": [reply({"CRHM": {"state": "verified"}})],
    })
    assert f["running"]["timers"] == [1000]
    assert f["finished"]["timers"] == []
    assert f["final"]["revision"] == "new"
    assert f["final"]["models"] == [{"name": "CRHM"}]
    assert f["final"]["draws"] == ["list", "details", "setup"]


def test_stale_get_cannot_overwrite_a_newer_check():
    f = render('const old=loadKiUpdate(); await flush(); await $("#updateretry").onclick(); '
               'release("old"); await old;', report={"state": "idle"}, replies={
        "/api/ki-updates": [reply({"state": "disabled"}, defer="old"), reply({"state": "checking"})],
        "/api/ki-updates/check": [reply({"state": "checking"})],
    })["final"]
    assert f["report"]["state"] == "checking"
    assert f["timers"] == [1000]
    assert node(f, "#updateretry")["text"] == "Checking…"


def test_status_network_failure_preserves_last_record_then_recovers_by_poll():
    f = render('await loadKiUpdate(); snapshot("offline"); await tick();',
               report={"state": "up_to_date", "source_commit": "old"}, replies={
        "/api/ki-updates": [{"error": "Network connection lost"}, reply({"state": "up_to_date"})],
    })
    assert f["offline"]["report"]["source_commit"] == "old"
    assert "last recorded status" in node(f["offline"], "#updatesummary")["html"]
    assert f["offline"]["timers"] == [3000]
    assert f["final"]["state"]["statusError"] == ""
    assert f["final"]["timers"] == []


def test_catalogue_refresh_failure_retries_without_marking_revision_loaded():
    updated = {"state": "updated", "active_revision": "new"}
    f = render('await loadKiUpdate(); snapshot("failed"); await tick();', revision="old", replies={
        "/api/ki-updates": [reply(updated), reply(updated)],
        "/api/models": [reply({"error": "Catalogue temporarily unavailable"}, status=503), reply([])],
        "/api/status": [reply({}), reply({})],
    })
    assert f["failed"]["revision"] == "old"
    assert "Catalogue temporarily unavailable" in node(f["failed"], "#updatesummary")["html"]
    assert f["failed"]["timers"] == [3000]
    assert f["final"]["revision"] == "new"
    assert f["final"]["state"]["viewError"] == ""


@pytest.mark.parametrize("bad,expected", [
    (dict(status=502, invalidJSON=True), "Request failed (502)"),
    (reply({"summary": "missing state"}), "Missing KI update state"),
    (reply(None), "Invalid update response"),
])
def test_malformed_or_http_failure_is_visible_and_retryable(bad, expected):
    f = render('await loadKiUpdate();', replies={"/api/ki-updates": [bad]})["final"]
    assert f["state"]["statusError"] == expected
    assert expected in node(f, "#updatesummary")["html"]
    assert not node(f, "#updateretry")["disabled"]
    assert f["timers"] == [3000]


@pytest.mark.parametrize("zh", [False, True])
def test_checking_hides_previous_result_details_and_labels_previous_snapshot(zh):
    f = render('drawKiUpdate();', zh=zh, report={"state": "checking", "branch": "main",
        "summary": "Checking for KI updates", "checked_at": 1700000000,
        "source_commit": "0123456789abcdef", "error": "Previous Windows refusal",
        "updated": ["Old KI"], "warning_count": 3})["final"]
    summary, details = node(f, "#updatesummary")["html"], node(f, "#updatedetails")["html"]
    assert ("上次检查：" if zh else "Previous check: ") in summary
    assert ("上次检查的提交：" if zh else "Previous checked commit: ") in summary
    assert "Previous Windows refusal" not in details
    assert "Old KI" not in details
    assert "blocking checks" not in details


@pytest.mark.parametrize("zh", [False, True])
def test_component_sources_distinguish_fallback_and_escape_recorded_values(zh):
    f = render('drawKiUpdate();', zh=zh, report={"state": "updated", "components": {
        "models": {"state": "snapshot", "source_commit": "a" * 40, "tree_sha": "b" * 40},
        "manifests": {"state": "snapshot", "source_commit": "<script>bad"},
        "shared_tools": {"state": "snapshot", "tree_sha": "c" * 40},
        "data_kis": {"state": "bundled_fallback"},
    }})["final"]
    html = node(f, "#updatedetails")["html"]
    assert ("应用内置回退（未更新）" if zh else "Bundled fallback (not updated)") in html
    assert ("仓库快照" if zh else "Repository snapshot") in html
    assert "aaaaaaaaaaaa" in html and "aaaaaaaaaaaaa" not in html
    assert "bbbbbbbbbbbb" in html
    assert "&lt;script&gt;bad" in html and "<script>" not in html
    assert ("共享工具" if zh else "shared tools") in node(f, "#updatescope")["text"]


def test_server_error_is_escaped_and_unsafe_source_link_is_rejected():
    f = render('drawKiUpdate();', report={"state": "error", "error": '<img src=x onerror="bad()">',
                                       "source_url": "javascript:bad()"})["final"]
    assert "<img" not in node(f, "#updatedetails")["html"]
    assert "&lt;img" in node(f, "#updatedetails")["html"]
    assert node(f, "#updatesource")["href"] == "#"


@pytest.mark.parametrize("zh", [False, True])
def test_active_windows_overlay_shows_counts_provenance_and_reverification(zh):
    f = render('drawKiUpdate();', zh=zh, report={"state": "checking", "windows_overlay": {
        "platform": "windows", "source_identity": '<source "local">',
        "upstream_commit": "d" * 40, "overlay_id": "e" * 64,
        "files": [dict(mode=mode) for mode in ["retained_windows_notes", "retained_windows_notes",
                  "retained_windows_recipe", "three_way_rebase", "platform_contract_overlay"]],
        "setup_reverification_required": True,
    }})["final"]
    html = node(f, "#updatedetails")["html"]
    assert ("2 份保留的说明" if zh else "2 retained documents") in html
    assert ("1 份保留的安装配方" if zh else "1 retained recipes") in html
    assert ("2 份组合生成的安装配方" if zh else "2 composed recipes") in html
    assert ("需要重新验证安装" if zh else "Setup must be verified again") in html
    assert ("本次库更新不代表模型安装或科学结果已通过验证" if zh else
            "does not verify model installation or scientific results") in html
    assert "dddddddddddd" in html and "eeeeeeeeeeee" in html
    assert "eeeeeeeeeeeee" not in html
    assert "&lt;source &quot;local&quot;&gt;" in html and '<source "local">' not in html


def test_absent_or_empty_overlay_does_not_claim_windows_composition():
    for overlay in (None, {}, {"files": []}):
        f = render('drawKiUpdate();', report={"state": "updated", "windows_overlay": overlay})["final"]
        assert "Active Windows support" not in node(f, "#updatedetails")["html"]


@pytest.mark.parametrize("zh", [False, True])
def test_quarantined_candidate_full_findings_are_separate_from_active_sources(zh):
    failure = {
        "activated": False, "stage": "package-validation", "source_commit": "candidate-full-commit",
        "quarantine_path": "D:/updates/quarantine/abc", "report_path": "D:/updates/quarantine/abc/validation-report.json",
        "archive_sha256": "a" * 64, "source_content_sha256": "b" * 64, "candidate_content_sha256": "c" * 64,
        "error": "Package failed static checks", "findings": [
            {"severity": "BLOCK", "ki": "SHAW", "check": "hardcoded-paths", "detail": "2 paths in a Python comment", "count": 2},
            {"severity": "WARN", "ki": "VIC", "check": "dag-version", "detail": "Old schema", "count": 1},
            {"severity": "INFO", "ki": "CRHM", "check": "dependency", "detail": "Shared helpers required", "count": 1},
        ], "portability_files": [
            {"ki": "SHAW", "path": "models/SHAW/tools/run_shaw.py", "sha256": "d" * 64,
             "matches": [{"line": 17, "path": "/home/server/forcing", "role": "forcing"},
                         {"line": 18, "path": "/home/server/outputs", "role": "outputs"}]},
        ],
    }
    f = render('drawKiUpdate();', zh=zh, report={"state": "error", "validation_failure": failure,
        "components": {"models": {"state": "snapshot", "source_commit": "active-commit"}}})["final"]
    html = node(f, "#updatedetails")["html"]
    assert ("1 项阻塞性软件包检查结果" if zh else "1 blocking package findings") in html
    assert ("未启用候选版本的诊断" if zh else "Inactive candidate diagnostics") in html
    assert ("不代表模型运行失败" if zh else "do not establish that model execution failed") in html
    assert ("全部软件包检查结果 (3)" if zh else "All package findings (3)") in html
    assert "candidate-full-commit" in html and "active-commi" in html
    assert html.index("active-commi") < html.index("candidate-full-commit")
    for text in [failure["quarantine_path"], failure["report_path"], "a" * 64, "b" * 64, "c" * 64,
                 "d" * 64, "run_shaw.py", "/home/server/forcing", "/home/server/outputs",
                 "Old schema", "Shared helpers required", "2 paths in a Python comment"]:
        assert text in html
    assert ("行 17" if zh else "Line 17") in html
    assert "<code>forcing</code>" in html and "<code>outputs</code>" in html
    assert "<details" in html and "<summary" in html


def test_validation_diagnostics_escape_paths_roles_and_details_without_file_links():
    payload = '<script>alert("x")</script>'
    failure = {"activated": False, "error": payload, "report_path": "javascript:bad()",
        "quarantine_path": payload, "findings": [{"severity": "BLOCK", "ki": payload,
            "check": payload, "detail": payload}], "portability_files": [{"ki": payload,
            "path": payload, "sha256": payload, "matches": [{"line": payload, "path": payload, "role": payload}]}]}
    html = node(render('drawKiUpdate();', report={"state": "error", "validation_failure": failure})["final"],
                "#updatedetails")["html"]
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert 'href="javascript:' not in html
    assert "javascript:bad()" in html


def test_old_candidate_failure_is_hidden_during_a_new_check():
    html = node(render('drawKiUpdate();', report={"state": "checking", "validation_failure": {
        "activated": False, "error": "old-candidate-failure", "source_commit": "old-failed-commit"}})["final"],
        "#updatedetails")["html"]
    assert "old-candidate-failure" not in html and "old-failed-commit" not in html


def test_non_validator_failure_preserves_stage_and_report_without_inventing_findings():
    html = node(render('drawKiUpdate();', report={"state": "error", "validation_failure": {
        "activated": False, "stage": "windows-overlay", "error": "Conflicting recipe field",
        "report_path": "D:/quarantine/report.json", "findings": [], "portability_files": []}})["final"],
        "#updatedetails")["html"]
    assert "windows-overlay" in html and "Conflicting recipe field" in html
    assert "D:/quarantine/report.json" in html
    assert "No structured findings were recorded" in html


def test_evidence_retention_error_remains_visible_when_report_could_not_be_saved():
    html = node(render('drawKiUpdate();', report={"state": "error", "validation_failure": {
        "activated": False, "stage": "validation", "error": "Invalid package",
        "evidence_error": "Unable to move candidate: access denied"}})["final"],
        "#updatedetails")["html"]
    assert "Evidence retention issue" in html
    assert "Unable to move candidate: access denied" in html


@pytest.mark.parametrize("zh", [False, True])
def test_reference_case_classification_does_not_claim_native_verification(zh):
    html = node(render('drawKiUpdate();', zh=zh, report={"state": "updated", "reference_cases": {
        "native_verification": "not_performed", "configurable_path_count": 2,
        "historical_path_count": 30, "runtime_binding_metadata_count": 5,
        "affected_kis": ["CRHM", "SHAW"], "warnings": [{"ki": "CRHM", "check": "configurable-reference-path",
            "severity": "WARN", "detail": "Pass --crhm-bin explicitly; <unsafe>"}],
    }})["final"], "#updatedetails")["html"]
    for text in (["2 项可配置路径", "30 项历史记录路径", "5 项运行绑定元数据", "本次更新尚未执行本机参考案例"]
                 if zh else ["2 configurable paths", "30 historical paths", "5 runtime-binding metadata entries",
                             "Native reference runs: not performed by this update"]):
        assert text in html
    assert ("实际运行参考案例后" if zh else "reference cases must be run") in html
    assert "CRHM" in html and "SHAW" in html
    assert "&lt;unsafe&gt;" in html and "<unsafe>" not in html
    assert "<details>" in html


def test_reference_case_card_is_absent_without_recorded_classified_paths():
    for cases in (None, {}, {"configurable_path_count": 0, "historical_path_count": 0,
                            "runtime_binding_metadata_count": 0}):
        html = node(render('drawKiUpdate();', report={"state": "updated", "reference_cases": cases})["final"],
                    "#updatedetails")["html"]
        assert "Active reference-case portability" not in html
