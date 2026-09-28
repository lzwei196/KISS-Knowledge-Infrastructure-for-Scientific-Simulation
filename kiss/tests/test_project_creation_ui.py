"""Exercise the shipped new-project dialog, without a live agent or app state."""
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
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const page=fs.readFileSync(process.argv[1],'utf8');
const elements=new Map(),requests=[],timers=new Map(),pending=[];
let timerID=0;
function element(key){
  if(!elements.has(key)){
    const classes=new Set(),events=new Map();
    elements.set(key,{value:'',textContent:'',disabled:false,events,focus(){},select(){},
      classList:{add:v=>classes.add(v),remove:v=>classes.delete(v),contains:v=>classes.has(v)},
      addEventListener:(event,fn)=>events.set(event,fn),
      click(){if(!this.disabled&&this.onclick)return this.onclick();}});
  }
  return elements.get(key);
}
element('#msg').value=input.draft||'';
element('#prov').value='api:deepseek';
const context={console,$:element,URLSearchParams,Date,
  CUR:input.existing?{id:'existing'}:null,SESSIONS:[],DRAFTS:new Map(),
  PROJECT_LOCATION:{default_parent:'/test/projects'},window:{},
  chineseUI:()=>Boolean(input.zh),drawSessions(){},renderAttachments(){},
  openSession:async()=>{},refreshAgentStatus(){},
  setTimeout:fn=>{timers.set(++timerID,fn);return timerID;},clearTimeout:id=>timers.delete(id),
};
const flush=()=>new Promise(resolve=>setImmediate(resolve));
async function tick(){const queued=[...timers.values()];timers.clear();for(const fn of queued)await fn();await flush();}
context.fetch=async(url,options)=>{
  requests.push({url,method:options?.method||'GET',body:options?JSON.parse(options.body):null});
  if(options?.method==='POST'){
    if(input.failCreate)throw new Error('Connection interrupted');
    if(input.rejectCreate)return {ok:false,status:400,json:async()=>({error:'Location unavailable'})};
    const body=JSON.parse(options.body);
    return {ok:true,json:async()=>({id:'123456abcdef',title:body.project_name,
      project_path:'/actual/server/path',created:1})};
  }
  const query=new URLSearchParams(url.split('?')[1]);
  const response={ok:!input.failPreview,json:async()=>input.failPreview?{error:'Invalid folder'}:
    {project_path_preview:`${query.get('project_parent')}/SERVER-${query.get('project_name')}--{id}`}};
  if(input.deferPreview)return new Promise(resolve=>pending.push(()=>resolve(response)));
  return response;
};
vm.createContext(context);
vm.runInContext(page.slice(page.indexOf('let PROJECT_PICK_RESOLVE='),page.indexOf('function pendingFor(')),context);
vm.runInContext(page.slice(page.indexOf('$("#newsess").onclick='),page.indexOf('$("#action-later").onclick=')),context);
const snapshot=()=>({name:element('#project-name').value,parent:element('#project-parent').value,
  preview:element('#project-path-preview').textContent,error:element('#project-location-error').textContent,
  disabled:element('#project-create').disabled,open:element('#sessionpick').classList.contains('open')});
(async()=>{
  const selection=context.chooseProjectLocation();await flush();
  const initial=snapshot();
  if(input.name!==undefined){element('#project-name').value=input.name;element('#project-name').events.get('input')();}
  if(input.parent!==undefined){element('#project-parent').value=input.parent;element('#project-parent').events.get('input')();}
  if(input.defaultLocation)element('#project-default').onclick();
  if(input.browse){context.window.pywebview={api:{choose_project_parent:async()=>input.browse}};await element('#project-browse').onclick();}
  if(input.deferPreview){
    // Input invalidates an old response before its debounce fires.
    pending.shift()();await flush();
    const afterStale=snapshot();
    const scheduled=tick();await flush();
    pending.shift()();await scheduled;
    const afterLatest=snapshot();
    element('#project-cancel').onclick();await selection;
    process.stdout.write(JSON.stringify({initial,afterStale,afterLatest,requests}));return;
  }
  await tick();
  const edited=snapshot();let choice=null,created=null,retry=null,afterEnter=null;
  if(input.enter){
    element('#project-name').events.get('keydown')({key:'Enter',isComposing:input.enter==='composing',
      keyCode:input.enter==='legacy-ime'?229:13,preventDefault(){}});
    afterEnter=snapshot();
  }
  if(input.cancel){element('#project-cancel').onclick();choice=await selection;}
  else {
    element('#project-create').onclick();
    if(!snapshot().open){
      choice=await selection;
      if(input.create){
        created=await context.createSessionAt(choice);
        if(!created){const again=context.chooseProjectLocation(choice);await flush();retry=snapshot();element('#project-cancel').onclick();await again;}
      }
    }else{element('#project-cancel').onclick();await selection;}
  }
  process.stdout.write(JSON.stringify({initial,edited,choice,created,retry,requests,
    final:snapshot(),afterEnter,sessions:context.SESSIONS,draft:element('#msg').value}));
})().catch(error=>{console.error(error);process.exitCode=1;});
"""


def dialog(**kwargs):
    result = subprocess.run([NODE, "-e", RUNNER, str(PAGE)], input=json.dumps(kwargs),
                            capture_output=True, text=True, check=True, timeout=10)
    return json.loads(result.stdout)


@pytest.mark.parametrize("zh,prefix", [(False, "Project "), (True, "新项目 ")])
def test_blank_chat_has_editable_default_name_and_server_path(zh, prefix):
    result = dialog(zh=zh, create=True)
    assert result["initial"]["name"].startswith(prefix)
    assert result["initial"]["parent"] == "/test/projects"
    assert "/SERVER-" in result["initial"]["preview"]
    assert result["created"]["title"] == result["initial"]["name"]
    assert result["sessions"][0]["project_path"] == "/actual/server/path"
    assert not result["final"]["open"]


def test_unsent_request_suggests_name_without_sending_or_changing_draft():
    draft = "哈尔滨大豆生长模拟\nThese are my input requirements."
    result = dialog(draft=draft, cancel=True)
    assert result["initial"]["name"] == "哈尔滨大豆生长模拟"
    assert result["draft"] == draft
    assert result["choice"] is None
    assert all(request["method"] == "GET" for request in result["requests"])


def test_new_chat_does_not_borrow_existing_chats_draft():
    result = dialog(existing=True, draft="Continue old model", cancel=True)
    assert result["initial"]["name"].startswith("Project ")
    assert result["draft"] == "Continue old model"


@pytest.mark.parametrize("draft", ["VIC\t华北平原测试", "👩‍🔬 VIC test", "🌧️", "---", "\x00"])
def test_auto_suggestion_is_accepted_by_server_without_changing_request(tmp_path, draft):
    from kiss_cli import sessions

    result = dialog(draft=draft, cancel=True)
    name = result["initial"]["name"]
    assert sessions.project_location(tmp_path, project_name=name)["project_name"] == name
    assert result["draft"] == draft


def test_editing_name_and_missing_parent_updates_preview_and_create_payload():
    result = dialog(name="华北 VIC + CaMa", parent="/new/nested/projects", create=True)
    assert result["edited"]["preview"] == "/new/nested/projects/SERVER-华北 VIC + CaMa--{id}"
    post = next(request for request in result["requests"] if request["method"] == "POST")
    assert post["body"] == {"provider": "api:deepseek", "project_name": "华北 VIC + CaMa",
                            "project_parent": "/new/nested/projects"}


@pytest.mark.parametrize("option,parent", [("defaultLocation", "/test/projects"), ("browse", "/chosen/parent")])
def test_location_controls_preserve_name_and_refresh_preview(option, parent):
    result = dialog(name="My project", parent="/typed/parent", **{option: parent if option == "browse" else True})
    assert result["edited"]["name"] == "My project"
    assert result["edited"]["parent"] == parent
    assert result["edited"]["preview"].startswith(parent + "/SERVER-My project")


@pytest.mark.parametrize("field", ["name", "parent"])
def test_empty_required_field_keeps_dialog_open_without_creating(field):
    result = dialog(create=True, **{field: "  "})
    assert result["edited"]["disabled"]
    assert result["created"] is None
    assert not any(request["method"] == "POST" for request in result["requests"])


@pytest.mark.parametrize("failure", ["failCreate", "rejectCreate"])
def test_creation_failure_keeps_both_inputs_for_retry(failure):
    result = dialog(name="My custom project", parent="/chosen/new/parent", create=True, **{failure: True})
    assert result["created"] is None
    assert result["retry"]["name"] == "My custom project"
    assert result["retry"]["parent"] == "/chosen/new/parent"
    assert result["retry"]["error"]
    assert result["sessions"] == []


def test_stale_preview_response_cannot_replace_new_name():
    result = dialog(name="The latest name", deferPreview=True)
    assert "/SERVER-" not in result["afterStale"]["preview"]
    assert result["afterLatest"]["preview"] == "/test/projects/SERVER-The latest name--{id}"


def test_preview_error_is_visible_and_cancellation_never_creates_a_project():
    result = dialog(failPreview=True, cancel=True)
    assert "Invalid folder" in result["initial"]["preview"]
    assert all(request["method"] == "GET" for request in result["requests"])


@pytest.mark.parametrize("enter", ["composing", "legacy-ime", "normal"])
def test_enter_committing_chinese_name_does_not_submit(enter):
    result = dialog(name="哈尔滨大豆", enter=enter, cancel=True)
    assert result["afterEnter"]["open"] is (enter != "normal")
