"""Run the shipped project-upload JavaScript with isolated browser/network fixtures."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


PAGE = Path(__file__).parents[1] / "kiss_cli" / "web" / "app.html"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node is required")
RUNNER = r"""
const fs=require('node:fs'),vm=require('node:vm');
const page=fs.readFileSync(process.argv[1],'utf8');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const elements=new Map(),listeners=new Map(),requests=[],renders=[],refreshes=[];
let sendCalls=0;
function element(key){
  if(!elements.has(key))elements.set(key,{textContent:'',value:'',disabled:false,
    style:{},scrollHeight:20,click(){},classList:{remove(){},toggle(){}},
    querySelectorAll(){return [];}});
  return elements.get(key);
}
element('#msg').value=input.draft||'Existing project question.';
// The full page declares this optional controller before setControls().
const context={CUR:{id:'original'},INVESTIGATION:null,PENDING_ATTACHMENTS:new Map(),UPLOADING:new Map(),
  DRAFTS:new Map(),INFLIGHT:new Map(),console,$:element,
  chineseUI:()=>Boolean(input.zh),currentProviderReady:()=>true,updateActivityUI(){},
  renderAttachments(){renders.push(context.CUR?.id);},
  async refreshData(){refreshes.push(context.CUR?.id);},
  send(){sendCalls++;throw new Error('Uploads must never send automatically');},
  document:{addEventListener:(name,callback)=>listeners.set(name,callback),querySelectorAll:()=>[]},
};
context.sessionBusy=(id=context.CUR?.id)=>context.INFLIGHT.has(id);
context.sessionUploading=(id=context.CUR?.id)=>(context.UPLOADING.get(id)||0)>0;
function switchSession(){
  context.DRAFTS.set(context.CUR.id,element('#msg').value);
  context.CUR={id:'other'};element('#msg').value='Other session draft.';
  element('#data-msg').textContent='Other session status.';
  context.setControls(true);
}
context.fetch=async(url,options)=>{
  const index=requests.length;
  requests.push({url,file:options.body.name,sendDisabled:element('#send').disabled,
    uploading:[...context.UPLOADING.entries()]});
  if(input.switch_after_first&&index===0)switchSession();
  const response=(input.responses||[])[index]||{relative_path:`inputs/uploads/saved-${index}.csv`};
  if(response.network_error)throw new Error(response.network_error);
  return {ok:!response.error,status:response.error?400:200,json:async()=>response};
};
vm.createContext(context);
vm.runInContext(page.slice(page.indexOf('function setControls(on){'),page.indexOf('$("#send").onclick=send;')),context);
vm.runInContext(page.slice(page.indexOf('let UPLOAD_ITEM='),page.indexOf('$("#paperfile").onchange=')),context);
(async()=>{
  if(input.item){listeners.get('click')({target:{closest:()=>({dataset:{item:input.item}})}});}
  else element('#data-upload').onclick();
  if(input.switch_before_selection)switchSession();
  const picker={files:(input.files||['weather.csv']).map(name=>({name,size:8})),value:'chosen'};
  await element('#datafile').onchange({target:picker});
  process.stdout.write(JSON.stringify({requests,pending:[...context.PENDING_ATTACHMENTS.entries()],
    drafts:[...context.DRAFTS.entries()],uploading:[...context.UPLOADING.entries()],
    current:context.CUR.id,message:element('#msg').value,status:element('#data-msg').textContent,
    renders,refreshes,sendCalls,sendDisabled:element('#send').disabled,pickerValue:picker.value}));
})().catch(e=>{console.error(e);process.exitCode=1;});
"""


def upload(**kwargs):
    # Node always writes UTF-8; the locale default (GBK on Chinese Windows) cannot decode it.
    result = subprocess.run([NODE, "-e", RUNNER, str(PAGE)], input=json.dumps(kwargs),
                            capture_output=True, text=True, encoding="utf-8", check=True, timeout=10)
    parsed = json.loads(result.stdout)
    assert parsed["sendCalls"] == 0, "An upload must not send a message or continue a run"
    return parsed


def test_targeted_upload_queues_actual_renamed_path_without_sending_or_approval():
    path = "inputs/user/site_geometry/site-actual-unique.csv"
    result = upload(item="../site_geometry", files=["site.csv"], responses=[{"relative_path": path}])
    attached = dict(result["pending"])["original"]
    assert attached == [{"name": "site-actual-unique.csv", "path": path, "size": 8}]
    assert result["message"].startswith("Existing project question.")
    assert "../site_geometry" in result["message"]
    assert path in result["message"] and path in result["status"]
    assert "unverified" in result["message"].lower()
    assert "not approval" in result["message"].lower()
    assert dict(result["drafts"])["original"] == result["message"]
    assert result["requests"][0]["sendDisabled"]
    assert result["uploading"] == [] and not result["sendDisabled"]


@pytest.mark.parametrize("when", ["switch_after_first", "switch_before_selection"])
def test_batch_remains_attached_to_original_session_after_navigation(when):
    result = upload(item="soil", files=["one.csv", "two.csv"], **{when: True})
    assert len(result["requests"]) == 2
    assert all("/original/upload?" in request["url"] for request in result["requests"])
    assert len(dict(result["pending"])["original"]) == 2
    assert "other" not in dict(result["pending"])
    assert "soil" in dict(result["drafts"])["original"]
    assert result["message"] == "Other session draft."
    assert result["status"] == "Other session status."
    assert "other" not in result["renders"] and "other" not in result["refreshes"]
    assert result["uploading"] == []


@pytest.mark.parametrize("failure", [{"error": "file larger than 300 MB"},
                                      {"network_error": "Network unavailable"}])
def test_partial_failure_keeps_saved_files_and_actual_paths(failure):
    path = "inputs/user/forcing/first-renamed.csv"
    result = upload(item="forcing", files=["first.csv", "second.csv", "third.csv"],
                    responses=[{"relative_path": path}, failure])
    assert len(result["requests"]) == 2
    assert [file["path"] for file in dict(result["pending"])["original"]] == [path]
    assert path in result["message"] and path in result["status"]
    assert next(iter(failure.values())) in result["status"]
    assert result["uploading"] == [] and not result["sendDisabled"]
    assert result["pickerValue"] == ""


def test_generic_upload_queues_server_name_and_path():
    result = upload(responses=[{"relative_path": "inputs/uploads/actual.csv", "name": "actual.csv"}])
    assert dict(result["pending"])["original"][0]["name"] == "actual.csv"
    assert "inputs/uploads/actual.csv" in result["status"]
    assert "inputs/uploads/actual.csv" in result["message"]


def test_missing_server_path_is_reported_not_guessed_or_attached():
    result = upload(responses=[{"ok": True}])
    assert result["pending"] == []
    assert "path" in result["status"].lower()
    assert result["message"] == "Existing project question."
    assert result["uploading"] == []


def test_chinese_disclosure_preserves_draft_and_does_not_claim_binding():
    path = "inputs/user/soil/土壤.csv"
    result = upload(zh=True, item="soil", draft="我的研究区是哈尔滨。", responses=[{"relative_path": path}])
    assert result["message"].startswith("我的研究区是哈尔滨。")
    assert path in result["message"] and path in result["status"]
    assert "尚未验证" in result["message"]
    assert "不是计划批准" in result["message"]
    assert "不代表已经完成输入绑定" in result["message"]
