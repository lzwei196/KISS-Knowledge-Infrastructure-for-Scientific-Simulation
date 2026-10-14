"""Execute the shipped data action UI; no network, provider or model."""
import json
from pathlib import Path
import subprocess

import pytest
from . import test_setup_verification_ui as ui


def render(*states, session='', **kwargs):
    runner=ui.RUNNER.replace("MODEL:'CRHM',STATE:","MODEL:'CRHM',DATA_SESSION:"+json.dumps(session)+",STATE:")
    runner=runner.replace("if(url!=='/api/setup-agent')", "if(url!=='/api/setup-agent'&&url!=='/api/setup-required-data')")
    runner=runner.replace("else if(action.kind==='start'){", "else if(action.kind==='start'){")
    runner=runner.replace('context.startAgent(false)', 'context.startAgent(false,true)')
    result=subprocess.run([ui.NODE,'-e',runner,str(ui.PAGE)],input=json.dumps({'states':states,**kwargs}),
      text=True,encoding='utf-8',capture_output=True,check=True,timeout=12)
    return json.loads(result.stdout)


@pytest.mark.parametrize('zh',[False,True])
def test_required_data_action_is_available_without_ai_and_never_reports_verification(zh):
    base={**ui.STALE,'required_data':{'declared':True,'can_prepare':True}}
    active={**base,'job':ui.job(provider='runtime-data')}
    done={**base,'job':ui.job('completed',provider='runtime-data'),'software':{'can_run':False,'label':'Verification required'},'log_tail':'Required data prepared; verify next.'}
    old,started,polled,finished=render(base,active,done,session='a'*12,noProvider=True,zh=zh,
       actions=[{'kind':'start'},{'kind':'poll','state':1},{'kind':'finish','state':2}])
    assert not old['#preparedata']['disabled'] and old['#preparedata']['display']==''
    post=next(row for row in started['__calls'] if row['url']=='/api/setup-required-data')
    assert post['body']=={'model':'CRHM','session':'a'*12}
    for view in (started,polled):
        assert view['#preparedata']['disabled']
        assert view['#statusbadge']['text']==('正在准备必需数据' if zh else 'Preparing required data')
        assert ('不会运行模型' if zh else 'does not run the model') in view['#verification']['html']
    assert finished['#chat']['display']=='none' and finished['#statusbadge']['className']!='badge ok'


def test_legacy_setup_has_no_required_data_action():
    view,=render(ui.STALE)
    assert view['#preparedata']['display']=='none' and view['#preparedata']['disabled']


def test_project_setup_link_preserves_current_session():
    page=(Path(ui.PAGE).parent/'app.html').read_text(encoding='utf-8')
    assert '/setup?model=${encodeURIComponent(pending[0])}&session=${encodeURIComponent(CUR.id)}' in page
