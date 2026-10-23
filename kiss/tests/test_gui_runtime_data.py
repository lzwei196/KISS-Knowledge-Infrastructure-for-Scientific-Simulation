"""Required runtime data is an explicit setup action, never a model/readiness pass."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import threading
from types import SimpleNamespace

import pytest
import yaml

from kiss_cli import (gui, install, install_locations, ki_guard, ki_verification,
    paths, project_paths, runtime_data, sessions, setup_jobs, software_verification)
from kiss_cli.catalog import KI
from kiss_cli.manifest import Manifest
from .test_setup_final_runtime import case, saved_status


def git(root, *args):
    return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.STDOUT)


@pytest.fixture
def data_case(case, monkeypatch, tmp_path):
    c=case
    source=tmp_path/'official';source.mkdir()
    git(source,'init','-q');git(source,'config','core.autocrlf','false')
    git(source,'config','user.email','fixture@example.invalid');git(source,'config','user.name','Fixture')
    git(source,'remote','add','origin','https://example.invalid/official/model.git')
    payload=b'! Runtime support\nA 1 2\n';(source/'TABLE.CDE').write_bytes(payload)
    git(source,'add','.');git(source,'commit','-qm','Pinned data fixture')
    contract={'version':1,'source':{'repo':'https://example.invalid/official/model.git','commit':git(source,'rev-parse','HEAD').decode().strip()},
              'target':{'role':'binaries','path':'Demo/Data'},
              'files':[{'source':'TABLE.CDE','path':'TABLE.CDE','bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}]}
    c.man=Manifest(model='Demo',runtime_data=contract);c.payload=payload
    c.target=c.cfg.roles['binaries']/'Demo/Data/TABLE.CDE'
    c.handler._manifest=lambda ki:c.man
    c.handler.catalog.get=lambda name:c.ki
    c.output=[];c.responses=[];c.fetches=[]
    c.handler._open_stream=lambda:None;c.handler._end_stream=lambda:None
    c.handler._chunk=lambda piece:c.output.append(piece) or True
    c.handler._json=lambda doc,status=200:c.responses.append((status,doc))
    def fetch(man,prefix,python,**kwargs):
        assert man.acquire.commands==[] and man.acquire.produces is None
        c.fetches.append(prefix);shutil.copytree(source,prefix)
        return install.Step('acquire',True,'Pinned fixture transport'),None
    monkeypatch.setattr(install,'acquire',fetch)
    monkeypatch.setattr(install,'run_preflight',lambda *a,**k:pytest.fail('No native preflight allowed'))
    install_locations.record(c.ki.name,c.root,c.cfg,ki_root=c.live.root,verified=False)
    return c


def invoke(c, **extra):
    c.handler._stream_required_data({'model':'Demo',**extra})


def test_data_only_prepares_pinned_bytes_once_never_claims_readiness(data_case):
    c=data_case;before=ki_verification.content_digest(c.live.root)
    config=(c.root/'kiss.toml').read_bytes()
    invoke(c)
    assert not c.responses
    assert c.target.read_bytes()==c.payload and len(c.fetches)==1
    assert setup_jobs.status(c.workroot,'Demo')['state']=='completed'
    assert not saved_status(c)['ok'] and saved_status(c)['verified_at'] is None
    assert saved_status(c)['primary_error']['name']=='verification-required'
    # Pending with no earlier pass: not a blocker, and it claims no installation.
    assert c.handler._status_for(c.ki)['label']=='Checked when it runs'
    assert 'does not establish readiness' in ''.join(c.output)
    assert ki_verification.content_digest(c.live.root)==before
    assert (c.root/'kiss.toml').read_bytes()==config
    invoke(c)
    assert len(c.fetches)==1 and not saved_status(c)['ok']


def test_get_availability_is_read_only_and_legacy_has_no_button(data_case):
    c=data_case;before=set(c.root.rglob('*'))
    state=c.handler._required_data_state(c.ki)
    assert state['declared'] and state['can_prepare'] and not state['present']
    assert set(c.root.rglob('*'))==before and not c.fetches
    c.man.runtime_data=None
    assert c.handler._required_data_state(c.ki)=={'declared':False,'can_prepare':False}


@pytest.mark.parametrize('change',['config-missing','config-malformed','unmanaged','no-contract','foreign-model'])
def test_invalid_binding_rejects_before_job_or_data(data_case,change):
    c=data_case
    if change=='config-missing':(c.root/'kiss.toml').unlink()
    elif change=='config-malformed':(c.root/'kiss.toml').write_text('[kiss\n')
    elif change=='unmanaged':c.live.root.rename(c.root/'retained-ki')
    elif change=='no-contract':c.man.runtime_data=None
    else:c.man.model='Other'
    invoke(c)
    assert c.responses[0][0]==400 and not c.fetches and not c.target.exists()
    assert setup_jobs.status(c.workroot,'Demo') is None


def test_deleted_required_data_revokes_old_green_on_read_without_acquisition(data_case):
    c=data_case;c.target.parent.mkdir(parents=True);c.target.write_bytes(c.payload)
    checked=software_verification.identity(c.ki,c.man,c.library)
    (c.root/'status.json').write_text(json.dumps({'ok':True,'ki_content_digest':ki_verification.content_digest(c.live.root),
      'runtime_identity':software_verification.runtime_identity(c.cfg),'verification_identity':checked,'steps':[]}))
    assert c.handler._status_for(c.ki)['can_run']
    c.target.unlink();before=(c.root/'status.json').read_bytes()
    state=c.handler._status_for(c.ki)
    assert not state['can_run'] and state['primary_error']['name']=='runtime-data'
    assert (c.root/'status.json').read_bytes()==before and not c.fetches


def test_no_snapshot_final_preflight_still_checks_required_data(data_case, monkeypatch):
    c=data_case;c.handler.library_root=None
    def check():return c.handler._record_agent_preflight(c.ki,c.live,c.cfg,c.root,c.output.append,
        check=install.Step('preflight',True,'Already executed harmless fixture'))
    assert not check()
    assert 'TABLE.CDE: missing' in saved_status(c)['primary_error']['detail']
    c.target.parent.mkdir(parents=True);c.target.write_bytes(c.payload)
    assert check() and saved_status(c)['verification_identity'] is None
    assert not c.fetches


def test_busy_shared_setup_rejects_data_operation(data_case):
    c=data_case;job=setup_jobs.start(c.workroot,'Demo',c.root,'fixture')
    try:
        invoke(c)
        assert c.responses[0][0]==409 and c.responses[0][1]['job']['id']==job.id
        assert not c.fetches
    finally:job.finish('cancelled')


def test_stop_and_display_disconnect_keep_owned_lifecycle(data_case, monkeypatch):
    c=data_case;started=threading.Event();release=threading.Event()
    original=runtime_data.prepare
    def waiting(*a,**kw):
        started.set();assert release.wait(5);install.check_cancelled();return original(*a,**kw)
    monkeypatch.setattr(runtime_data,'prepare',waiting)
    c.handler._chunk=lambda piece:False
    thread=threading.Thread(target=invoke,args=(c,));thread.start()
    try:
        assert started.wait(5)
        job=setup_jobs.status(c.workroot,'Demo')
        assert job['state']=='running'
        setup_jobs.stop(c.workroot,'Demo',job['id'])
    finally:release.set();thread.join(5)
    assert not thread.is_alive()
    assert setup_jobs.status(c.workroot,'Demo')['state']=='cancelled'
    assert not saved_status(c)['ok'] and not c.fetches


@pytest.mark.parametrize('change',['config','ki','manifest'])
def test_binding_drift_cannot_publish_completed(data_case,monkeypatch,change):
    c=data_case;original=runtime_data.prepare
    def changing(*a,**kw):
        result=original(*a,**kw)
        if change=='config':
            cfg=replace(c.cfg,python='changed-runtime');(c.root/'kiss.toml').write_text(cfg.dumps(),encoding="utf-8")
        elif change=='ki':(c.ki.root/'SKILL.md').write_text('Changed evidence')
        else:c.man=replace(c.man,notes='Changed effective manifest')
        return result
    monkeypatch.setattr(runtime_data,'prepare',changing)
    invoke(c)
    assert setup_jobs.status(c.workroot,'Demo')['state']=='failed'
    assert not saved_status(c)['ok']


@pytest.fixture
def project_data_case(data_case,monkeypatch,tmp_path):
    c=data_case;c.project=tmp_path/'project';c.project.mkdir()
    home=c.project/'models/Demo';live=home/'ki';live.mkdir(parents=True)
    (live/'SKILL.md').write_text('# Adopted Demo\n')
    (live/'kiss.yaml').write_text(yaml.safe_dump({'kiss_manifest_version':1,'model':'Demo','runtime_data':c.man.runtime_data}))
    ki_guard.enroll(live);c.project_ki=KI('Demo',live)
    c.project_cfg=project_paths.model_config(c.project,'Demo',c.cfg)
    (home/'kiss.toml').write_text(c.project_cfg.dumps(),encoding="utf-8")
    c.sid='d'*12
    c.session={'id':c.sid,'models':['Demo']}
    monkeypatch.setattr(sessions,'load',lambda workroot,sid:c.session if sid==c.sid else None)
    monkeypatch.setattr(sessions,'project_path',lambda workroot,session:c.project)
    c.handler._manifest=lambda ki:Manifest.load(ki.manifest)
    return c


def test_project_adopted_manifest_uses_exact_shared_runtime_without_catalogue_contract(project_data_case):
    c=project_data_case
    assert c.handler._required_data_state(c.ki)['declared'] is False
    state=c.handler._required_data_state(c.ki,session_id=c.sid)
    assert state.get('scope')=='project' and state['can_prepare'],state
    before={p.relative_to(c.project):p.read_bytes() for p in c.project.rglob('*') if p.is_file()}
    invoke(c,session=c.sid)
    assert not c.responses and c.target.read_bytes()==c.payload
    assert setup_jobs.status(c.workroot,'Demo')['state']=='completed'
    assert all((c.project/p).read_bytes()==data for p,data in before.items())
    assert not list(c.project.rglob('status.json'))
    assert c.sid not in gui._PROJECT_OPERATIONS


@pytest.mark.parametrize('change',['python','binaries','target-role','unselected','registry','ki-edit','missing-config'])
def test_project_mismatch_rejects_without_acquisition(project_data_case,change):
    c=project_data_case;cfg=c.project_cfg
    if change=='python':cfg.python='other'
    elif change=='binaries':cfg.roles['binaries']=c.project/'other-binaries'
    elif change=='target-role':
        # Both binary bindings differ here only by a lexical alias; equality must not follow it.
        cfg.roles['binaries']=Path(str(c.cfg.roles['binaries'])+'/../binaries')
    elif change=='unselected':c.session['models']=[]
    elif change=='registry':(c.root/install_locations.RECORD_FILE).write_text(json.dumps({'model':'Other','workspace':str(c.root)}))
    elif change=='ki-edit':(c.project_ki.root/'SKILL.md').write_text('Unapproved edit')
    if change=='missing-config':(c.project/'models/Demo/kiss.toml').unlink()
    elif change in {'python','binaries','target-role'}:(c.project/'models/Demo/kiss.toml').write_text(cfg.dumps(),encoding="utf-8")
    invoke(c,session=c.sid)
    assert c.responses[0][0]==400 and not c.fetches
    assert c.sid not in gui._PROJECT_OPERATIONS


def test_active_project_operation_blocks_data_without_shared_job(project_data_case):
    c=project_data_case;token=gui._claim_project_operation(c.sid,'Fixture model operation')
    try:
        invoke(c,session=c.sid)
        assert c.responses[0][0]==409 and not c.fetches
        assert setup_jobs.status(c.workroot,'Demo') is None
    finally:gui._release_project_operation(c.sid,token)
