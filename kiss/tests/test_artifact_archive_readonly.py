"""Informational archive previews never reserve the project's mutation lease."""
import json
import threading

import pytest

from kiss_cli import gui
from .test_artifact_archive import SID, REL, DATA, case, extra, handler, row, request


@pytest.fixture
def controller(case, monkeypatch):
    monkeypatch.setattr(gui, '_PROJECT_OPERATIONS', {})
    monkeypatch.setattr(gui, '_PROJECT_OPERATION_GENERATIONS', {})
    h=handler(case, monkeypatch)
    extra(case)
    return case, h


def _files(project):
    return {p.relative_to(project).as_posix():p.read_bytes() for p in project.rglob('*') if p.is_file()}


def test_preview_takes_no_mutation_or_setup_acquisition_guard(controller, monkeypatch):
    c,h=controller
    before=_files(c.project)
    def forbidden(*args, **kwargs):
        pytest.fail('informational preview acquired a mutation/setup guard')
    class NoIntentLock:
        def __enter__(self):forbidden()
        def __exit__(self,*args):return False
    monkeypatch.setattr(gui,'_claim_project_operation',forbidden)
    monkeypatch.setattr(gui.setup_jobs,'idle_guard',forbidden)
    monkeypatch.setattr(gui.setup_jobs,'status',forbidden)
    monkeypatch.setattr(gui.acquire,'INTENT_LOCK',NoIntentLock())
    h._project_artifact_archive(SID)
    code,result=h.responses[-1]
    assert code==200 and result['busy'] is False
    assert next(i for i in result['items'] if i['path']==REL)['eligible']
    assert _files(c.project)==before
    assert gui._PROJECT_OPERATIONS==gui._PROJECT_OPERATION_GENERATIONS=={}


def test_paused_preview_admits_chat_then_discards_its_old_snapshot(controller, monkeypatch):
    c,h=controller
    entered,release=threading.Event(),threading.Event()
    errors=[]; accepted=[]
    def preview(*args):
        entered.set()
        assert release.wait(5)
        return {'items':[{'path':REL,'eligible':True}],'archives':[],'busy':False}
    monkeypatch.setattr(gui.artifact_archive,'preview',preview)
    h._stream_session_chat_owned=lambda sid,req:accepted.append((sid,req))
    def read():
        try:h._project_artifact_archive(SID)
        except BaseException as e:errors.append(e)
    worker=threading.Thread(target=read);worker.start()
    try:
        assert entered.wait(5)
        assert SID not in gui._PROJECT_OPERATIONS
        h._stream_session_chat(SID,{'message':'Inspect existing files','action':{'kind':'inspect_existing'}})
        assert len(accepted)==1
        assert SID not in gui._PROJECT_OPERATIONS  # Short operation already finished.
        assert gui._PROJECT_OPERATION_GENERATIONS[SID]==1
    finally:
        release.set();worker.join(5)
    assert not worker.is_alive() and not errors
    code,result=h.responses[-1]
    assert code==200 and result['busy'] is True and result['items']==[]
    assert 'changed during' in result['reason']
    assert (c.project/REL).read_bytes()==DATA


@pytest.mark.parametrize('label',['Project agent','KI investigation','Artifact archive'])
def test_existing_operation_keeps_preview_non_authoritative(controller,monkeypatch,label):
    c,h=controller
    token=gui._claim_project_operation(SID,label)
    before=dict(gui._PROJECT_OPERATION_GENERATIONS)
    monkeypatch.setattr(gui.artifact_archive,'preview',lambda *a:pytest.fail('busy preview was computed'))
    try:
        h._project_artifact_archive(SID)
        assert h.responses[-1][1]['busy'] is True
        assert h.responses[-1][1]['items']==[]
        assert gui._PROJECT_OPERATIONS[SID][0]==token
        assert gui._PROJECT_OPERATION_GENERATIONS==before
    finally:gui._release_project_operation(SID,token)


@pytest.mark.parametrize('change',['live-agent','acquisition','selection','operation-active','operation-finished'])
def test_concurrent_work_or_selection_discards_preview(controller,monkeypatch,change):
    c,h=controller
    busy={'agent':False,'acquisition':False}; tokens=[]
    monkeypatch.setattr(gui,'_agent_run_snapshot',lambda sid:{'state':'running' if busy['agent'] else 'idle'})
    monkeypatch.setattr(gui.project_status,'snapshot',lambda *a,**k:{'progress':{'acquisition':{'active':busy['acquisition']}}})
    def preview(*args):
        if change=='live-agent':busy['agent']=True
        elif change=='acquisition':busy['acquisition']=True
        elif change=='selection':
            (c.project/'session.json').write_text(json.dumps({'id':SID,'models':['Changed']}))
        else:
            token=gui._claim_project_operation(SID,'Other work');tokens.append(token)
            if change=='operation-finished':gui._release_project_operation(SID,token)
        return {'items':[{'path':REL,'eligible':True}],'archives':[],'busy':False}
    monkeypatch.setattr(gui.artifact_archive,'preview',preview)
    try:
        h._project_artifact_archive(SID)
        assert h.responses[-1][1]['busy'] is True
        assert h.responses[-1][1]['items']==[]
        assert (c.project/REL).read_bytes()==DATA
    finally:
        for token in tokens:gui._release_project_operation(SID,token)


def test_preview_error_does_not_leave_lease_or_increment_generation(controller,monkeypatch):
    c,h=controller
    monkeypatch.setattr(gui.artifact_archive,'preview',lambda *a:(_ for _ in ()).throw(ValueError('changed fixture')))
    h._project_artifact_archive(SID)
    assert h.responses[-1][1]['busy'] is True
    assert gui._PROJECT_OPERATIONS==gui._PROJECT_OPERATION_GENERATIONS=={}
    accepted=[];h._stream_session_chat_owned=lambda *a:accepted.append(True)
    h._stream_session_chat(SID,{'message':'Inspect'})
    assert accepted==[True]


def test_archive_post_still_excludes_chat_and_uses_guards(controller,monkeypatch):
    c,h=controller;r=row(c)
    guarded=[];original=gui.setup_jobs.idle_guard
    def guard(*args,**kwargs):
        guarded.append(True)
        return original(*args,**kwargs)
    monkeypatch.setattr(gui.setup_jobs,'idle_guard',guard)
    accepted=[];h._stream_session_chat_owned=lambda *a:accepted.append(True)
    def archive(*args,**kwargs):
        assert gui._PROJECT_OPERATIONS[SID][1]=='Artifact archive'
        h._stream_session_chat(SID,{'message':'Inspect','action':{'kind':'inspect_existing'}})
        assert h.responses[-1][0]==409 and not accepted
        kwargs['check_idle']()
        return {'id':'a'*32,'path':REL,'sha256':r['sha256'],'size':r['size']}
    monkeypatch.setattr(gui.artifact_archive,'archive',archive)
    h._project_artifact_archive(SID,req=request(r),action=True)
    assert h.responses[-1][0]==200 and h.responses[-1][1]['ok'] is True
    assert guarded and not gui._PROJECT_OPERATIONS
    assert gui._PROJECT_OPERATION_GENERATIONS[SID]==1
    assert (c.project/REL).read_bytes()==DATA


def test_archive_post_during_agent_is_still_rejected(controller):
    c,h=controller;r=row(c)
    token=gui._claim_project_operation(SID,'Project agent')
    try:
        h._project_artifact_archive(SID,req=request(r),action=True)
        assert h.responses[-1][0]==409
        assert (c.project/REL).read_bytes()==DATA
        assert gui._PROJECT_OPERATIONS[SID][0]==token
    finally:gui._release_project_operation(SID,token)
