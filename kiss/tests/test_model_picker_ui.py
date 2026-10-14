"""The shipped picker retains the chat and exposes rejected selection errors."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

NODE=shutil.which("node")
pytestmark=pytest.mark.skipif(NODE is None,reason="Node is needed for shipped UI checks")
PAGE=Path(__file__).parents[1]/"kiss_cli/web/app.html"
RUNNER=r'''
const fs=require('node:fs'),vm=require('node:vm');
const input=JSON.parse(fs.readFileSync(0,'utf8')),html=fs.readFileSync(process.argv[1],'utf8'),nodes=new Map(),requests=[];
function $(id){if(!nodes.has(id))nodes.set(id,{value:'',disabled:false,textContent:'',classes:new Set(id==='#mpick'?['open']:[]),classList:{contains(c){return nodes.get(id).classes.has(c)},remove(c){nodes.get(id).classes.delete(c)}}});return nodes.get(id)}
const original={id:'session',models:['SHAW']};
const context={$,CUR:original,PICK:new Set(['VIC']),chineseUI:()=>false,ensureSession:async()=>true,
  SESSIONS:[],rememberSessionSummary(){},invalidateProjectStatus(){},mergeSessionSummaries:rows=>rows,refreshRun:async()=>{},
  drawModelLabel(){},drawSessions(){},refreshData(){},fetch:async(url,init)=>{
    requests.push({url,body:JSON.parse(init.body)});
    if(input.network)throw new Error('Network failed');
    return {ok:!input.failure,status:input.failure?400:200,json:async()=>input.failure?{error:'Exact KI problem <unsafe>'}:input.malformed?{error:'bad'}:{id:'session',models:['VIC']}};
  }};
vm.createContext(context);
const start=html.indexOf('$("#m-apply").onclick=async()=>{'),end=html.indexOf('/* skills: chat-composer',start);
vm.runInContext(html.slice(start,end),context);
(async()=>{await $('#m-apply').onclick();process.stdout.write(JSON.stringify({requests,session:context.CUR,
  error:$('#m-error').textContent,open:$('#mpick').classes.has('open'),disabled:$('#m-apply').disabled}));})().catch(e=>{console.error(e);process.exitCode=1});
'''


def evaluate(**kwargs):
    result=subprocess.run([NODE,"-e",RUNNER,str(PAGE)],input=json.dumps(kwargs),capture_output=True,
                          encoding="utf-8",check=True,timeout=10)
    return json.loads(result.stdout)


@pytest.mark.parametrize("failure",["failure","network","malformed"])
def test_picker_failure_shows_error_keeps_original_chat_and_modal(failure):
    result=evaluate(**{failure:True})
    assert result["session"] == {"id":"session","models":["SHAW"]}
    assert result["error"] and result["open"] and not result["disabled"]
    if failure=="failure":assert result["error"]=="Exact KI problem <unsafe>"


def test_picker_success_saves_selection_and_closes_modal():
    result=evaluate()
    assert result["session"]["models"] == ["VIC"]
    assert not result["open"] and not result["error"] and not result["disabled"]
