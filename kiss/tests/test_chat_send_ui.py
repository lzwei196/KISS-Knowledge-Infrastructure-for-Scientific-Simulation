"""Execute the shipped send path with a fake transport, never a live provider."""
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
const page=fs.readFileSync(process.argv[1],'utf8'),input=JSON.parse(fs.readFileSync(0,'utf8'));
const elements=new Map(),requests=[],turns=[],timers=new Set();
function element(key){
  if(!elements.has(key))elements.set(key,{value:'',textContent:'',innerHTML:'',style:{},
    events:new Map(),addEventListener(name,fn){this.events.set(name,fn);}});
  return elements.get(key);
}
const session={id:'case',provider:'api:deepseek',binding_locked:true,messages:[{role:'user'}],
  title:'Crowsnest',models:['CRHM'],...input.session};
const draft=input.draft??'  Continue checking the KI.\n';
element('#msg').value=draft;
element('#prov').value=input.provider||session.provider;
element('#llm').value=input.model??session.llm_model??'deepseek-chat';
const files=input.files?[{path:'inputs/test.csv'}]:[];
let accepted=0,releaseChat;
const context={console,Date,TextDecoder,window:{},$:element,CUR:session,
  PROV:{providers:[{name:'api:deepseek',kind:'api',default_model:'deepseek-chat',usable:input.ready!==false},
    {name:'api:other',kind:'api',default_model:'other-model',usable:true}]},
  SESSIONS:[{...session}],SKILLS:[],DRAFTS:new Map([['case',draft]]),INFLIGHT:new Map(),
  PENDING_ACTIONS:new Map([['case',{id:'continue'}]]),PENDING_ATTACHMENTS:new Map([['case',files]]),
  ensureSession:async()=>session,pendingFor:()=>files,sessionUploading:()=>false,
  sessionBusy:id=>context.INFLIGHT.has(id),chineseUI:()=>!!input.zh,
  drawSessions(){},setControls(){},drawSlash(){},renderAttachments(){},
  renderLiveTurn(){},updateLiveActivity(){},chatFollow(){},
  addTurn(who,role){const turn={who,role,innerHTML:''};turns.push(turn);return turn;},
  messageHtml:m=>m.text,liveBubble:()=>element('.bubble'),md:text=>text,
  document:{querySelector:()=>null},
  setInterval:()=>{timers.add(1);return 1;},clearInterval:id=>timers.delete(id),
  refreshRun:async()=>{},refreshAgentStatus:async()=>{},refreshMachineStatus:async()=>{},
  refreshViewStatus:async()=>{},maybeShowAction:async()=>{},
};
context.fetch=async(url,options)=>{
  const body=options?.body?JSON.parse(options.body):null;
  requests.push({url,method:options?.method||'GET',body});
  if(url.endsWith('/update')){
    if(input.updateError)return {ok:false,status:400,json:async()=>({error:'Invalid binding'})};
    // Match the real locked-conversation equality guard, including a missing model.
    if(session.binding_locked&&Object.entries(body).some(([k,v])=>v!==(session[k]??null)))
      return {ok:false,status:409,json:async()=>({error:'The agent and model are fixed'})};
    return {ok:true,json:async()=>session};
  }
  if(url.endsWith('/chat')){
    if(input.defer)await new Promise(resolve=>{releaseChat=resolve;});
    if(input.networkError)throw new TypeError('Failed to fetch');
    if(input.chatError)return {ok:false,status:409,json:async()=>({error:'Chat already running'})};
    accepted++;
    let read=0;
    return {ok:true,body:{getReader:()=>({read:async()=>{
      if(input.streamError)throw new TypeError('Failed to fetch');
      return read++?{done:true}:{done:false,value:new TextEncoder().encode('Saved reply')};
    }})}};
  }
  if(input.networkError)throw new TypeError('Failed to fetch');
  return {ok:true,json:async()=>({...session,message_count:1+accepted*2})};
};
vm.createContext(context);
vm.runInContext(page.slice(page.indexOf('function currentProviderReady(){'),page.indexOf('function drawProviders(){')),context);
vm.runInContext(page.slice(page.indexOf('function chatBindingUpdate('),page.indexOf('function setControls(')),context);
const original=context.send;
let pending;
context.send=()=>{pending=original();return pending;};
vm.runInContext(page.slice(page.indexOf('$("#send").onclick=send;'),page.indexOf('$("#attach").onclick=')),context);
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  if(input.enter){
    element('#msg').events.get('keydown')({key:'Enter',shiftKey:false,isComposing:input.enter==='ime',
      keyCode:input.enter==='legacy-ime'?229:13,preventDefault(){}});
  }else pending=element('#send').onclick();
  await flush();
  let whilePending=element('#msg').value;
  if(input.defer){
    if(input.newDraft!==undefined){element('#msg').value=input.newDraft;context.DRAFTS.set('case',input.newDraft);}
    if(input.switchChat){context.CUR={id:'other',messages:[]};element('#msg').value='Other chat draft';}
    releaseChat();
  }
  await pending;
  process.stdout.write(JSON.stringify({requests,accepted,turns,whilePending,
    composer:element('#msg').value,draft:context.DRAFTS.get('case')??null,
    hint:element('#hint').textContent,bubble:element('.bubble').innerHTML,
    pendingFiles:context.PENDING_ATTACHMENTS.has('case'),pendingAction:context.PENDING_ACTIONS.has('case'),
    inflight:context.INFLIGHT.size,timers:timers.size,selectedSession:context.CUR.id}));
})().catch(error=>{console.error(error);process.exitCode=1;});
"""


def send(**kwargs):
    result = subprocess.run([NODE, "-e", RUNNER, str(PAGE)], input=json.dumps(kwargs),
                            capture_output=True, text=True, encoding="utf-8", check=True, timeout=10)
    return json.loads(result.stdout)


@pytest.mark.parametrize("model", ["absent", None, "", "deepseek-chat", "deepseek-reasoner"])
def test_locked_chat_preserves_the_existing_binding_and_reaches_chat(model):
    session = {} if model == "absent" else {"llm_model": model}
    result = send(session=session, model=model or "deepseek-chat" if model != "absent" else "deepseek-chat")
    assert not any(r["url"].endswith("/update") for r in result["requests"])
    assert result["accepted"] == 1
    assert result["composer"] == "" and result["draft"] is None
    assert result["inflight"] == 0 and result["timers"] == 0


@pytest.mark.parametrize("change", [{"provider": "api:other"}, {"model": "deepseek-reasoner"}])
def test_genuine_locked_binding_change_is_rejected_without_sending(change):
    result = send(**change)
    assert result["accepted"] == 0
    assert not any(r["method"] == "POST" for r in result["requests"])
    assert "fixed for this chat" in result["hint"]
    assert result["composer"] == result["draft"] == "  Continue checking the KI.\n"


def test_new_chat_still_sets_its_selected_binding():
    result = send(session={"binding_locked": False, "messages": []})
    posts = [r for r in result["requests"] if r["method"] == "POST"]
    assert posts[0]["url"].endswith("/update")
    assert posts[0]["body"] == {"provider": "api:deepseek", "llm_model": "deepseek-chat"}
    assert result["accepted"] == 1


@pytest.mark.parametrize("failure", ["updateError", "chatError", "networkError"])
@pytest.mark.parametrize("zh", [False, True])
def test_unaccepted_request_keeps_draft_files_action_and_reports_actual_error(failure, zh):
    result = send(**{failure: True}, session={"binding_locked": False, "messages": []}, files=True, zh=zh)
    assert result["accepted"] == 0 and result["turns"] == []
    assert result["composer"] == result["draft"] == "  Continue checking the KI.\n"
    assert result["pendingFiles"] and result["pendingAction"]
    assert ("草稿已保留" if zh else "Your draft is kept") in result["hint"]
    expected = {"updateError": "Invalid binding", "chatError": "Chat already running", "networkError": "Failed to fetch"}
    assert expected[failure] in result["hint"]
    assert "实时连接已停止" not in result["hint"] and "connection stopped" not in result["hint"]
    assert result["inflight"] == 0 and result["timers"] == 0


def test_stream_failure_after_acceptance_does_not_restore_a_duplicate_draft():
    result = send(streamError=True, files=True)
    assert result["accepted"] == 1 and len(result["turns"]) == 1
    assert result["composer"] == "" and result["draft"] is None
    assert not result["pendingFiles"] and not result["pendingAction"]
    assert "response connection stopped" in result["hint"]


def test_draft_stays_until_acceptance_and_a_new_draft_is_not_erased():
    result = send(defer=True, newDraft="Next question")
    assert result["whilePending"] == "  Continue checking the KI.\n"
    assert result["composer"] == result["draft"] == "Next question"
    assert result["accepted"] == 1


def test_switching_chat_during_send_does_not_erase_the_other_composer():
    result = send(defer=True, switchChat=True)
    assert result["selectedSession"] == "other"
    assert result["composer"] == "Other chat draft" and result["draft"] is None
    assert result["turns"] == []


def test_enter_uses_the_same_provider_readiness_guard_as_send():
    result = send(enter="normal", ready=False)
    assert result["requests"] == [] and result["accepted"] == 0
    assert result["composer"] == result["draft"]
    assert "Connect this chat's AI" in result["hint"]


@pytest.mark.parametrize("enter", ["ime", "legacy-ime"])
def test_composition_enter_does_not_send(enter):
    result = send(enter=enter)
    assert result["requests"] == [] and result["composer"] == result["draft"]
