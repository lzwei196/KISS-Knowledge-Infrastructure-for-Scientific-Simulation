"""After data-only preparation, real project checks use the retained KI, not old setup."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from kiss_cli import gui, install, install_locations, ki_guard, paths, project_verification, sessions, setup_jobs
from kiss_cli.catalog import KI
from .test_project_readiness_shared_provenance import build_case, chat


@pytest.fixture
def prepared_project(tmp_path,monkeypatch,request):
    c=build_case(tmp_path,monkeypatch)
    # Restore the old shared KI's authentic baseline: this specifically avoids
    # the older ki-edit exception hiding the new data-only handoff problem.
    (c.shared.root/'ki/preflight_check.py').write_bytes((c.source/'preflight_check.py').read_bytes())
    ki_guard.require_intact(c.shared.root/'ki')
    install_locations.record('Demo',c.shared.root,c.shared,ki_root=c.shared.root/'ki',verified=True)
    cfg=c.handler._session_config(c.project,c.ki)
    home=c.project/'models/Demo';live=home/'ki';live.mkdir(parents=True)
    payload=b'! Required native table\nA 1 2\n';c.payload=payload
    upstream=tmp_path/'official';upstream.mkdir();(upstream/'TABLE.CDE').write_bytes(payload)
    def git(*args):return subprocess.check_output(['git','-C',str(upstream),*args],stderr=subprocess.STDOUT)
    git('init','-q');git('config','core.autocrlf','false');git('config','user.email','fixture@example.invalid');git('config','user.name','Fixture')
    git('remote','add','origin','https://example.invalid/official.git');git('add','.');git('commit','-qm','Immutable table')
    contract={'version':1,'source':{'repo':'https://example.invalid/official.git','commit':git('rev-parse','HEAD').decode().strip()},
      'target':{'role':'binaries','path':'Demo/Data'},'files':[{'source':'TABLE.CDE','path':'TABLE.CDE','bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}]}
    (live/'SKILL.md').write_text('# Independently enrolled project repair fixture\n',encoding='utf-8')
    manifest={'kiss_manifest_version':1,'model':'Demo','runtime_data':contract}
    if getattr(request,'param',None)=='coupled':manifest['depends_on']=['MissingDependency']
    (live/'kiss.yaml').write_text(yaml.safe_dump(manifest),encoding='utf-8')
    (live/'preflight_check.py').write_text("print('UPDATED_PROJECT_DATA_KI_CHECK_EXECUTED')\n"+
        ("raise SystemExit('Project check still fails')\n" if getattr(request,'param',None)=='preflight' else ''),encoding='utf-8')
    (home/'kiss.toml').write_text(cfg.dumps(),encoding='utf-8');ki_guard.enroll(live)
    c.working=KI('Demo',live);c.sid='e'*12;c.fetches=[]
    monkeypatch.setattr(sessions,'load',lambda workroot,sid:{'id':sid,'models':['Demo']} if sid==c.sid else None)
    monkeypatch.setattr(sessions,'project_path',lambda *args:c.project)
    def fetch(man,prefix,python,**kwargs):
        assert man.acquire.commands==[] and man.acquire.produces is None
        c.fetches.append(prefix);shutil.copytree(upstream,prefix)
        return install.Step('acquire',True,'Pinned fixture source'),None
    monkeypatch.setattr(install,'acquire',fetch)
    c.responses=[];c.handler._json=lambda data,status=200:c.responses.append((status,data))
    c.handler._open_stream=lambda:None;c.handler._end_stream=lambda:None
    c.handler._chunk=lambda piece:c.messages.append(piece) or True
    c.before_shared=(c.shared.root/'ki/preflight_check.py').read_bytes()
    c.handler._stream_required_data({'model':'Demo','session':c.sid})
    assert not c.responses
    assert setup_jobs.status(c.handler.workroot,'Demo')['state']=='completed'
    c.target=c.shared.roles['binaries']/'Demo/Data/TABLE.CDE'
    assert c.target.read_bytes()==payload and len(c.fetches)==1
    assert c.handler._status_for(c.ki)['primary_error']['name']=='verification-required'
    assert not c.handler._project_setup_ok(c.project,['Demo'])
    return c


@pytest.mark.parametrize('provider',['api:deepseek','cli:claude'])
def test_data_action_then_retry_runs_exact_updated_project_preflight(prepared_project,provider,monkeypatch):
    c=prepared_project
    assert gui._project_check_allowed_by_shared_status(c.handler._status_for(c.ki),shared_root=c.shared.root)
    assert chat(c,provider) is c.turn and c.transitions==['verified']
    report=project_verification.status(c.project,c.working)
    assert report['can_run']
    check=report['receipt']['checks'][0]
    assert check['evidence']['source_root']==str(c.working.root)
    assert 'UPDATED_PROJECT_DATA_KI_CHECK_EXECUTED' in check['detail']
    assert 'EXACT_PROJECT_PREFLIGHT_EXECUTED' not in check['detail']
    assert (c.shared.root/'ki/preflight_check.py').read_bytes()==c.before_shared
    ki_guard.require_intact(c.shared.root/'ki')
    assert not c.handler._status_for(c.ki)['can_run']
    monkeypatch.setattr(install,'run_preflight',lambda *a,**k:pytest.fail('Read-only status cannot rerun'))
    assert c.handler._project_setup_ok(c.project,['Demo'])
    c.target.unlink()
    assert not c.handler._project_setup_ok(c.project,['Demo'])


@pytest.mark.parametrize('damage',['missing-data','changed-data'])
def test_data_drift_after_preparation_blocks_project_receipt(prepared_project,damage):
    c=prepared_project
    if damage=='missing-data':c.target.unlink()
    else:c.target.write_bytes(b'Changed support values\n')
    assert chat(c) is c.turn and c.transitions==['failed']
    assert not project_verification.status(c.project,c.working)['can_run']
    assert not c.handler._project_setup_ok(c.project,['Demo'])
    assert len(c.fetches)==1


@pytest.mark.parametrize('damage',['missing-runtime','bad-config','active-setup','project-edit','helper-edit'])
def test_data_only_marker_does_not_bypass_current_runtime_or_project_guards(prepared_project,monkeypatch,damage):
    c=prepared_project
    if damage=='missing-runtime':
        c.shared.python=str(c.shared.root/'absent/python.exe')
        (c.shared.root/'kiss.toml').write_text(c.shared.dumps(),encoding='utf-8')
    elif damage=='bad-config':(c.shared.root/'kiss.toml').write_text('[kiss\n',encoding='utf-8')
    elif damage=='project-edit':(c.working.root/'preflight_check.py').write_text("print('Unapproved edit')\n")
    elif damage=='helper-edit':
        cfg=paths.KissConfig.load(c.working.root.parent)
        (cfg.roles['ki_tools_common']/'ki_tools_common/__init__.py').write_text('Changed helper')
    job=setup_jobs.start(c.handler.workroot,'Demo',c.shared.root,'fixture') if damage=='active-setup' else None
    try:
        monkeypatch.setattr(install,'run_preflight',lambda *a,**k:pytest.fail('Damaged runtime must not execute'))
        monkeypatch.setattr(gui.setup_flow,'prepare',lambda *a,**k:(_ for _ in ()).throw(ValueError('Existing setup remains required')))
        assert chat(c) is None
        assert not c.transitions and not c.handler._project_setup_ok(c.project,['Demo'])
    finally:
        if job:job.finish('cancelled')


@pytest.mark.parametrize('prepared_project',['coupled','preflight'],indirect=True)
def test_data_preparation_cannot_replace_real_checks_or_coupled_readiness(prepared_project):
    c=prepared_project
    assert chat(c) is c.turn and c.transitions==['failed']
    report=project_verification.status(c.project,c.working)
    assert not report['can_run'] and report['receipt']['checks'][0]['evidence']['launch_attempted']
    assert not c.handler._project_setup_ok(c.project,['Demo'])
    assert len(c.fetches)==1
