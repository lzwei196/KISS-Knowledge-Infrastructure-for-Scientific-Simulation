from copy import deepcopy
from pathlib import Path
import json
import subprocess
import threading
from types import SimpleNamespace

import pytest

from kiss_cli import gui, ki_investigation as inv, ki_review_agents as review, api
from .test_gui_investigation import case, make_draft
from .test_ki_review_agents import draft, bundle, author_report
from . import test_investigation_ui as ui


@pytest.mark.parametrize('value',[None,[],{},'x'*12001,'bad\0notes'])
def test_invalid_refinement_rejected_without_author_transition(case,monkeypatch,value):
    job=make_draft(case);before=inv.get(case.project,job['id'])
    monkeypatch.setattr(gui.ki_review_agents,'author_draft',lambda *a,**k:pytest.fail('No invalid author'))
    response,status=case.handler._project_investigation(case.session['id'],action='build',job_id=job['id'],req={'author_notes':value})
    assert status==409 and '12000' in response['error']
    assert inv.get(case.project,job['id'])==before
    assert case.session['id'] not in gui._PROJECT_OPERATIONS


def test_gui_refinement_reaches_author_without_rewriting_frozen_reviews(case,monkeypatch):
    job=make_draft(case);before=inv.get(case.project,job['id']);threads=[];calls=[]
    class HeldThread:
        def __init__(self,*,target,**kw):self.target=target;threads.append(self)
        def start(self):pass
    monkeypatch.setattr(gui,'threading',SimpleNamespace(Thread=HeldThread))
    def author(*a,**kw):calls.append(kw);return {'status':'completed','raw_response':'Draft only'}
    monkeypatch.setattr(gui.ki_review_agents,'author_draft',author)
    note='Preserve the standard case and require exact supporting table bytes.'
    response,status=case.handler._project_investigation(case.session['id'],action='build',job_id=job['id'],req={'author_notes':note})
    assert status==202 and not calls
    threads[0].target()
    assert calls[0]['author_notes']==note and note in calls[0]['task_extra']
    assert 'do not change the frozen reviews' in calls[0]['task_extra']
    after=inv.get(case.project,job['id'])
    for field in ('reviewers','context','combined_report','issue'):
        assert after.get(field)==before.get(field)
    assert after['status']=='draft' and not after.get('verification')


def test_author_log_preserves_user_refinement_without_readiness(draft,monkeypatch):
    root,candidate,active,states=draft
    note='Exact required runtime tables; no acceptance-threshold changes.'
    monkeypatch.setattr(api,'_openai_turn',lambda *a,**k:(author_report(),[],{'role':'assistant','content':author_report()}))
    result=review.author_draft('fixture',provider='api:deepseek',task_extra=note,author_notes=note,
        stop_event=threading.Event(),emit=lambda _:None,managed_roots=[active])
    assert result['status']=='completed' and not result['verified'] and not result['native_execution_verified']
    text=Path(result['log']).read_text(encoding='utf-8')
    assert note in text and 'frozen reviews and KDT remain required' in text


@pytest.mark.parametrize('action',['build','verify','apply','start'])
def test_ui_sends_refinement_only_to_build(action):
    job=ui.job('draft',repair={'kdt_job_id':'draft1','status':'draft','can_verify':True,'can_apply':True,'verification_id':'verified1'})
    if action=='start':job=ui.job()
    runner=ui.RUNNER.replace("const first=$('#investigation-'+input.action).onclick();", "$('#investigation-author-notes').value='Keep strict case checks';const first=$('#investigation-'+input.action).onclick();")
    result=subprocess.run([ui.NODE,'-e',runner,str(ui.WEB/'investigation.js')],
        input=json.dumps({'job':job,'action':action}),capture_output=True,text=True,encoding='utf-8',check=True,timeout=15)
    data=json.loads(result.stdout);posts=[row for row in data['requests'] if row['method']=='POST']
    assert len(posts)==1
    assert ('author_notes' in posts[0]['body']) is (action=='build')
    if action=='build':assert posts[0]['body']['author_notes']=='Keep strict case checks'
    assert not data['nodes']['#investigation-author-row']['hidden'] or action=='start'
