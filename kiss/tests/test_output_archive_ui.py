"""Execute the shipped archive renderer/actions in Node; no server/files changed."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

PAGE = Path(__file__).parents[1]/'kiss_cli/web/app.html'
NODE = shutil.which('node')
pytestmark = pytest.mark.skipif(NODE is None, reason='Node required for real UI script tests')
ITEM = {'path':'outputs/extra.csv','sha256':'a'*64,'size':32,'eligible':True,'reason':'Not required by the plan',
        'context_sha256':'b'*64}
ARCHIVE = {'id':'c'*32,'path':'.geoforge/unreceipted-archive/item/extra.csv','sha256':'a'*64,'size':32,
           'download_url':'javascript:untrusted','audit_url':'https://untrusted.invalid'}

RUNNER = r"""
const fs=require('node:fs'),vm=require('node:vm');
const input=JSON.parse(fs.readFileSync(0,'utf8')),page=fs.readFileSync(process.argv[1],'utf8');
const start=page.indexOf('const OUTPUT_ARCHIVE_ACTIONS='),end=page.indexOf('function renderData(data){',start);
if(start<0||end<0)throw Error('Missing actual archive UI');
const nodes=new Map(),calls=[],buttons=[{dataset:{archiveOutput:'0'},disabled:false}];
const element=s=>{if(!nodes.has(s))nodes.set(s,{innerHTML:'',textContent:'',disabled:false,setAttribute(k,v){this[k]=v;}});return nodes.get(s);};
let refreshes=0,release;
const responses=input.responses||[];
const makeResponse=x=>({ok:x.ok!==false,json:async()=>{if(x.jsonError)throw Error('Malformed response');return x.body;}});
const context={CUR:{id:'session-a'},DATA_ACTIONS:new Set(),chineseUI:()=>!!input.zh,sessionBusy:()=>!!input.busy,
  esc:v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;'),
  sizeLabel:n=>`${n} B`,$:element,document:{querySelectorAll:()=>buttons},console,
  fetch:async(url,options={})=>{calls.push({url,...options});const r=responses.shift()||{};
    if(input.defer&&calls.length===1)return await new Promise(resolve=>{release=()=>resolve(makeResponse(r));});
    if(r.throw)throw Error(r.throw);return makeResponse(r);},
  refreshData:async()=>{refreshes++;if(input.refreshFail)throw Error('Status offline');},
  send:()=>{throw Error('Archive must never send or execute');}};
vm.createContext(context);vm.runInContext(page.slice(start,end),context);
(async()=>{
  let html;
  if(input.mode==='data-refresh-race'){
    const a=page.indexOf('async function refreshData(){'),b=page.indexOf('$("#opendata").onclick=',a);
    vm.runInContext(page.slice(a,b),context);
    const pending=context.refreshData();vm.runInContext('OUTPUT_ARCHIVE_ACTIONS.add("session-a")',context);
    release();await pending;
  }else if(input.mode==='render')html=context.outputArchiveCard(input.payload,'session-a',!!input.zh);
  else if(input.mode==='refresh'){
    await context.refreshUnreceiptedArtifacts('session-a');
    if(input.click)await buttons[0].onclick();
  }else if(input.mode==='stale-read'){
    const old=context.refreshUnreceiptedArtifacts('session-a');
    await context.refreshUnreceiptedArtifacts('session-a');release();await old;
  }else if(input.mode==='read-switch'){
    const old=context.refreshUnreceiptedArtifacts('session-a');context.CUR={id:'session-b'};release();await old;
  }else{
    if(input.wrongSession)context.CUR={id:'session-b'};
    const pending=context.archiveUnreceiptedArtifact('session-a',input.item,buttons[0]);
    if(input.mode==='double')await context.archiveUnreceiptedArtifact('session-a',input.item,buttons[0]);
    if(input.mode==='switch')context.CUR={id:'session-b'};
    if(release)release();await pending;
  }
  process.stdout.write(JSON.stringify({html,calls,refreshes,disabled:buttons[0].disabled,
    content:element('#unreceipted-artifacts').innerHTML,body:element('#databody').innerHTML,feedback:element('#output-archive-feedback').innerHTML,
    state:vm.runInContext('({busy:OUTPUT_ARCHIVE_ACTIONS.has("session-a"),feedback:OUTPUT_ARCHIVE_FEEDBACK.get("session-a")})',context)}));
})().catch(e=>{console.error(e);process.exitCode=1;});
"""


def evaluate(**data):
    run = subprocess.run([NODE,'-e',RUNNER,str(PAGE)],input=json.dumps(data),text=True,encoding='utf-8',
                         capture_output=True,check=True,timeout=15)
    return json.loads(run.stdout)


def success(): return {'body':{'ok':True,'archive':ARCHIVE}}


@pytest.mark.parametrize('zh',[False,True])
def test_renderer_names_exact_file_and_reversible_consequences(zh):
    result=evaluate(mode='render',zh=zh,payload={'items':[ITEM],'archives':[],'busy':False})
    html=result['html']
    assert ITEM['path'] in html and ITEM['sha256'] in html
    assert ('归档以供审查' if zh else 'Archive for review') in html
    assert ('不验证文件，也不重新运行模型' if zh else 'does not validate the file or rerun the model') in html
    assert result['calls']==[] and result['refreshes']==0


@pytest.mark.parametrize('change',[{'eligible':False},{'sha256':'bad'},{'context_sha256':None},{'size':-1},{'path':''}])
def test_no_action_for_ineligible_or_incomplete_host_preview(change):
    item={**ITEM,**change}
    assert 'data-archive-output' not in evaluate(mode='render',payload={'items':[item]})['html']
    result=evaluate(mode='archive',item=item)
    assert result['calls']==[] and result['refreshes']==0


def test_renderer_escapes_paths_reasons_and_ignores_foreign_download_urls():
    item={**ITEM,'path':'outputs/<script>.csv','reason':'<img onerror=bad>'}
    html=evaluate(mode='render',payload={'items':[item],'archives':[ARCHIVE]})['html']
    assert '<script>' not in html and '&lt;script&gt;' in html
    assert 'javascript:' not in html and 'untrusted.invalid' not in html
    assert f'/api/session/session-a/archived-unreceipted/{ARCHIVE["id"]}/audit' in html


def test_archived_history_remains_downloadable_without_an_active_extra_file():
    html=evaluate(mode='render',payload={'items':[],'archives':[ARCHIVE]})['html']
    assert ARCHIVE['path'] in html and 'Download archived file' in html and 'Download audit record' in html
    assert 'data-archive-output' not in html


def test_busy_host_preview_has_disabled_action_and_reason():
    result=evaluate(mode='refresh',click=True,responses=[{'body':{'items':[ITEM],'busy':True,'reason':'Active model worker'}}])
    assert 'disabled' in result['content'] and 'Active model worker' in result['content']
    assert len(result['calls'])==1 and result['calls'][0]['url'].endswith('/unreceipted-artifacts')


@pytest.mark.parametrize('busy',[False,True])
def test_empty_blocked_preview_keeps_host_reason_visible(busy):
    result=evaluate(mode='render',payload={'items':[],'archives':[],'busy':busy,'reason':'Project context unavailable'})
    assert 'Project context unavailable' in result['html']
    assert 'data-archive-output' not in result['html']


def test_click_posts_exact_displayed_binding_then_only_refreshes_status():
    result=evaluate(mode='refresh',click=True,responses=[{'body':{'items':[ITEM],'busy':False}},success()])
    assert len(result['calls'])==2
    post=result['calls'][1]
    assert post['method']=='POST' and post['url']=='/api/session/session-a/archive-unreceipted-artifact'
    assert json.loads(post['body'])=={'path':ITEM['path'],'expected_sha256':ITEM['sha256'],
        'expected_size':ITEM['size'],'expected_context_sha256':ITEM['context_sha256']}
    assert result['refreshes']==1 and not result['state']['busy']
    assert 'Download archived file' in result['feedback']


def test_double_click_issues_one_host_operation():
    result=evaluate(mode='double',defer=True,item=ITEM,responses=[success()])
    assert len(result['calls'])==1 and result['refreshes']==1 and not result['disabled']


@pytest.mark.parametrize('case',['busy','wrong-session'])
def test_busy_or_switched_session_does_not_issue_action(case):
    result=evaluate(mode='archive',item=ITEM,busy=case=='busy',wrongSession=case=='wrong-session')
    assert result['calls']==[] and result['refreshes']==0


def test_switch_during_operation_keeps_original_target_and_does_not_refresh_another_session():
    result=evaluate(mode='switch',defer=True,item=ITEM,responses=[success()])
    assert len(result['calls'])==1 and '/session-a/' in result['calls'][0]['url']
    assert result['refreshes']==0 and result['state']['feedback']['archive']==ARCHIVE


@pytest.mark.parametrize('response',[{'ok':False,'body':{'error':'File or plan changed'}},
    {'throw':'Network unavailable'},{'jsonError':True},{'body':{'ok':True,'archive':{'id':'bad'}}}])
def test_failed_or_unconfirmed_action_never_claims_success_or_refreshes(response):
    result=evaluate(mode='archive',item=ITEM,responses=[response])
    assert result['refreshes']==0 and result['state']['feedback']['error'] is True
    assert not result['state']['busy'] and not result['disabled']
    assert 'Download archived file' not in result['feedback']


def test_successful_archive_retains_download_and_audit_when_status_refresh_fails():
    result=evaluate(mode='archive',item=ITEM,responses=[success()],refreshFail=True)
    assert result['refreshes']==1 and 'File archived, but status refresh failed' in result['feedback']
    assert 'Download archived file' in result['feedback'] and 'Download audit record' in result['feedback']


def test_failed_preview_has_explicit_retry_without_archive_action():
    result=evaluate(mode='refresh',responses=[{'ok':False,'body':{'error':'Status <offline>'}}])
    assert 'output-archive-retry' in result['content'] and 'Status &lt;offline&gt;' in result['content']
    assert 'data-archive-output' not in result['content'] and result['refreshes']==0


def test_late_status_response_cannot_replace_newer_preview():
    result=evaluate(mode='stale-read',defer=True,responses=[{'body':{'items':[{**ITEM,'path':'outputs/old.csv'}]}},
        {'body':{'items':[{**ITEM,'path':'outputs/current.csv'}]}}])
    assert 'outputs/current.csv' in result['content'] and 'outputs/old.csv' not in result['content']


def test_late_status_response_cannot_replace_another_sessions_panel():
    result=evaluate(mode='read-switch',defer=True,responses=[{'body':{'items':[ITEM]}}])
    assert result['content']==''


def test_inflight_data_refresh_cannot_erase_active_archive_controls():
    result=evaluate(mode='data-refresh-race',defer=True,responses=[{'body':{'stale':'status'}}])
    assert len(result['calls'])==1 and 'reading project status' in result['body']
    assert result['content']==''


def test_live_renderer_and_refresh_wire_archive_panel_without_sending():
    page=PAGE.read_text(encoding='utf-8')
    start=page.index('async function refreshData(){');end=page.index('$("#opendata").onclick=',start)
    refresh=page[start:end]
    assert '<div id="unreceipted-artifacts"></div>' in page
    assert 'refreshUnreceiptedArtifacts(requestedSession);' in refresh
    assert refresh.count('OUTPUT_ARCHIVE_ACTIONS.has(requestedSession)')==2
