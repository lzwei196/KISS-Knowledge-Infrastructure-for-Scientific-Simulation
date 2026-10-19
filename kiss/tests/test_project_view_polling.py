"""Execute shipped view request coordination, without an app or model process."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

PAGE = Path(__file__).parents[1] / "kiss_cli/web/app.html"
NODE = shutil.which("node")
RUNNER = r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const page=fs.readFileSync(process.argv[1],'utf8').replaceAll('\r\n','\n');
function fn(name){
  let start=page.indexOf('function '+name+'(');
  assert(start>=0,'Missing function '+name);
  if(page.slice(start-6,start)==='async ')start-=6;
  const end=page.indexOf('\n}',start);assert(end>start);
  return page.slice(start,end+2);
}
let open=false,requests=[],draws=[],patches=[];
const nodes={viewpanel:{classList:{contains:()=>open}},viewbody:{innerHTML:''}};
const ctx=vm.createContext({CUR:{id:'A'},document:{hidden:false},
  $:name=>nodes[name.slice(1)],chineseUI:()=>false,esc:String,
  drawViewStatus:v=>draws.push(v),patchProjectView:v=>patches.push(v),
  fetch:url=>new Promise((resolve,reject)=>requests.push({url,resolve,reject}))});
vm.runInContext('const VIEW_REQUESTS=new Map(),VIEW_FRESH_REQUESTS=new Map();let VIEW_RENDERED_KEY="";',ctx);
for(const name of ['requestProjectView','refreshViewStatus','refreshProjectView','pollProjectView'])vm.runInContext(fn(name),ctx);
const call=text=>vm.runInContext(text,ctx);
const finish=(index,ok=true,view={revision:'1',panels:[]})=>requests[index].resolve({ok,json:async()=>view});
const drain=()=>new Promise(resolve=>setImmediate(resolve));
async function main(){
  switch(process.argv[2]){
  case 'shared': {
    const first=call('refreshViewStatus()'),second=call('refreshProjectView(false)');
    assert.equal(requests.length,1);finish(0);await Promise.all([first,second]);
    assert.equal(patches.length,1);assert.equal(call('VIEW_REQUESTS.size'),0);break;}
  case 'slow_poll': {
    open=true;const a=call('pollProjectView()'),b=call('pollProjectView()');
    assert.equal(requests.length,1);finish(0);await Promise.all([a,b]);
    assert.equal(patches.length,1);break;}
  case 'closed_hidden': {
    await call('pollProjectView()');open=true;ctx.document.hidden=true;
    await call('pollProjectView()');assert.equal(requests.length,0);
    ctx.document.hidden=false;const refresh=call('pollProjectView()');
    assert.equal(requests.length,1);finish(0);await refresh;break;}
  case 'explicit_closed': {
    const initial=call('refreshViewStatus()');assert.equal(requests.length,1);finish(0);await initial;
    const completed=call('refreshViewStatus()');assert.equal(requests.length,2);finish(1);await completed;
    open=true;const reopened=call('refreshProjectView(true)');assert.equal(requests.length,3);finish(2);await reopened;break;}
  case 'switch_session': {
    const a=call('refreshProjectView(false)');ctx.CUR={id:'B'};
    const b=call('refreshViewStatus()');assert.equal(requests.length,2);
    finish(1,true,{revision:'B',panels:[]});await b;
    finish(0,true,{revision:'A',panels:[]});await a;
    assert.deepEqual(draws.map(x=>x.revision),['B']);assert.equal(patches.length,0);break;}
  case 'reject_retry': {
    const first=call('refreshViewStatus()');requests[0].reject(Error('offline'));
    await assert.rejects(first,/offline/);assert.equal(call('VIEW_REQUESTS.size'),0);
    const retry=call('refreshViewStatus()');assert.equal(requests.length,2);finish(1);await retry;break;}
  case 'http_retry': {
    const a=call('refreshViewStatus()'),b=call('refreshProjectView(true)');
    finish(0,false,{error:'denied'});assert.equal(await a,null);await b;
    assert(nodes.viewbody.innerHTML.includes('denied'));assert.equal(draws.length,0);
    const retry=call('refreshProjectView(true)');assert.equal(requests.length,2);finish(1);await retry;break;}
  case 'completion_queue': {
    const old=call('refreshViewStatus()');
    const completed=call('refreshViewStatus("A",true)');
    const repeated=call('refreshViewStatus("A",true)');
    assert.equal(requests.length,1);
    finish(0,true,{revision:'old',panels:[]});await old;await drain();
    assert.equal(requests.length,2);
    const pending=call('refreshViewStatus("A",true)');
    finish(1,true,{revision:'new',panels:[{}]});await Promise.all([completed,repeated,pending]);
    assert.equal(requests.length,2);assert.equal(draws.at(-1).revision,'new');
    assert.equal(call('VIEW_REQUESTS.size+VIEW_FRESH_REQUESTS.size'),0);break;}
  case 'manual_queue': {
    open=true;const old=call('pollProjectView()');
    const manual=call('refreshProjectView(true,true)'),again=call('refreshProjectView(true,true)');
    assert.equal(requests.length,1);finish(0,true,{revision:'old',panels:[]});await old;await drain();
    assert.equal(requests.length,2);const poll=call('pollProjectView()');
    finish(1,true,{revision:'new',panels:[]});await Promise.all([manual,again,poll]);
    assert.equal(requests.length,2);assert.deepEqual(patches.map(x=>x.revision),['old','new']);break;}
  case 'queued_switch': {
    const old=call('refreshViewStatus()'),fresh=call('refreshProjectView(true,true)');
    ctx.CUR={id:'B'};const b=call('refreshViewStatus()');
    finish(1,true,{revision:'B',panels:[]});await b;
    finish(0,true,{revision:'A-old',panels:[]});await old;await drain();
    assert.equal(requests.length,3);assert.equal(requests[2].url,'/api/session/A/view');
    finish(2,true,{revision:'A-new',panels:[]});await fresh;
    assert.deepEqual(draws.map(x=>x.revision),['B']);assert.equal(patches.length,0);break;}
  case 'queued_old_failure': {
    const old=call('refreshViewStatus()'),fresh=call('refreshViewStatus("A",true)');
    const failed=assert.rejects(old,/old failure/);requests[0].reject(Error('old failure'));
    await failed;await drain();assert.equal(requests.length,2);
    finish(1);await fresh;assert.equal(call('VIEW_REQUESTS.size+VIEW_FRESH_REQUESTS.size'),0);break;}
  case 'queued_new_failure': {
    const old=call('refreshViewStatus()'),fresh=call('refreshProjectView(true,true)');
    finish(0);await old;await drain();
    const failed=assert.rejects(fresh,/new failure/);requests[1].reject(Error('new failure'));
    await failed;assert.equal(call('VIEW_REQUESTS.size+VIEW_FRESH_REQUESTS.size'),0);
    const retry=call('refreshProjectView(true,true)');assert.equal(requests.length,3);finish(2);await retry;break;}
  default:throw Error('unknown case');
  }
  assert(page.includes('setInterval(()=>pollProjectView().catch(()=>{}),5000)'));
  assert(page.includes('refreshViewStatus(target,true)'));
  assert(page.includes('$("#view-refresh").onclick=()=>refreshProjectView(true,true)'));
  console.log(JSON.stringify({ok:true,requests:requests.length}));
}
main().catch(e=>{console.error(e.stack);process.exit(1)});
'''


@pytest.mark.parametrize("scenario", ["shared", "slow_poll", "closed_hidden", "explicit_closed",
                                      "switch_session", "reject_retry", "http_retry", "completion_queue",
                                      "manual_queue", "queued_switch", "queued_old_failure", "queued_new_failure"])
def test_shipped_project_view_request_lifecycle(scenario):
    if NODE is None:
        pytest.skip("Node is required to execute the shipped view functions")
    result = subprocess.run([NODE, "-e", RUNNER, str(PAGE), scenario], capture_output=True,
                            text=True, encoding="utf-8", timeout=15, check=True)
    assert json.loads(result.stdout)["ok"] is True

