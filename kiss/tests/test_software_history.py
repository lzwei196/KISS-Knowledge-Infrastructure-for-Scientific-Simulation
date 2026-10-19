"""Signed setup history records actual checks, never grants current readiness."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import gui, install, runtime_provenance, software_history as sh
from .test_setup_final_runtime import case as final_case, install_spies, finish, saved_status
from .test_setup_projection_binding import case as builtin_case


def context(build='a'):
    return {'schema_version':1,'application':{'name':'GeoForge','version':'0.6.60',
        'version_source':'source-project-metadata','build':{
            'scheme':'supervised-portable-payload-sha256-v1','sha256':build*64}},
        'backend':{'kind':'wsl','platform':'Linux','machine':'x86_64',
            'distro':'Ubuntu','user':'fixture','workspace':'/home/fixture/work','id':'1'*32,
            'guest_identity':'2'*64,'guest_path_identity':'3'*64}}


@pytest.fixture(autouse=True)
def isolated(tmp_path,monkeypatch):
    monkeypatch.setenv('GEOFORGE_FLOW_KEYS',str(tmp_path/'authority/keys'))
    monkeypatch.setenv('GEOFORGE_FLOW_REGISTRY',str(tmp_path/'authority/registry'))
    monkeypatch.setattr(runtime_provenance,'capture',lambda:context())


def record(root,**changes):
    kwargs=dict(verification_context=context(),operation_id='attempt-1',checked_at=10.0,
        outcome='passed',check_scope='full_software_verification',runtime_identity='b'*64,
        verification_identity='c'*64,ki_content_digest='d'*64,
        checks=[{'name':'preflight','ok':True,'skipped':False}])
    kwargs.update(changes)
    return sh.record(root,'M',**kwargs)


def event_path(root,ref):
    return sh._location(root,'M')[2]/(ref['event_id']+'.json')


def files(root):
    return {str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_separate_authenticated_attempts_preserve_captured_build_without_readiness(tmp_path):
    root=tmp_path/'install';root.mkdir(); before=files(root)
    first=record(root)
    first_bytes=event_path(root,first).read_bytes()
    record(root,checked_at=20,verification_context=context('e'),outcome='failed',runtime_identity=None,
           checks=[{'name':'manifest-requirements','ok':False,'skipped':False}])
    report=sh.history(root,'M')
    assert report['scope']=='historical_only' and report['invalid_count']==0
    assert [r['outcome'] for r in report['records']]==['failed','passed']
    assert report['records'][1]['verification_context']['application']['build']['sha256']=='a'*64
    assert all(r['authenticated'] and r['authentication']=='verified' and r['provenance']=='recorded'
               and 'signature' not in r and 'can_run' not in r for r in report['records'])
    assert event_path(root,first).read_bytes()==first_bytes and files(root)==before
    assert sh.history(root,'M',limit=1)['truncated'] is True


def test_writer_never_overwrites_even_reused_identifier(tmp_path,monkeypatch):
    root=tmp_path/'install';root.mkdir()
    monkeypatch.setattr(sh.uuid,'uuid4',lambda:SimpleNamespace(hex='f'*32))
    ref=record(root);before=event_path(root,ref).read_bytes()
    with pytest.raises(FileExistsError):record(root,checked_at=30)
    assert event_path(root,ref).read_bytes()==before


def test_old_unsigned_status_is_not_enrolled_and_reads_create_nothing(tmp_path):
    root=tmp_path/'install';root.mkdir()
    (root/'status.json').write_text(json.dumps({'ok':True,'verified_at':3,'runtime_identity':'b'*64}))
    before=files(tmp_path)
    assert sh.history(root,'M')['records']==[]
    assert files(tmp_path)==before and not (tmp_path/'authority').exists()


@pytest.mark.parametrize('damage',['signature','model','installation','event-id','schema','provenance','extra','oversize','hardlink','symlink'])
def test_tampered_wrong_scope_or_unsafe_records_are_never_history(tmp_path,damage):
    root=tmp_path/'install';root.mkdir();ref=record(root);p=event_path(root,ref)
    doc=json.loads(p.read_bytes());receipts=sh.flowgate.load().receipts
    if damage=='signature':doc['checked_at']=99
    elif damage=='model':doc['model']='Other'
    elif damage=='installation':doc['installation']=str(tmp_path/'other')
    elif damage=='event-id':doc['event_id']='0'*32
    elif damage=='schema':doc['schema_version']=True
    elif damage=='provenance':doc['verification_context']['backend']['nonce']='MUST-NOT-BE-ACCEPTED'
    elif damage=='extra':doc['raw_logs']='MUST-NOT-BE-ACCEPTED'
    elif damage=='oversize':p.write_bytes(b'x'*(sh.MAX_BYTES+1))
    elif damage=='hardlink':os.link(p,tmp_path/'alias')
    else:
        outside=tmp_path/'outside.json';outside.write_bytes(p.read_bytes());p.unlink()
        try:p.symlink_to(outside)
        except OSError as e:pytest.skip(str(e))
    if damage not in {'oversize','hardlink','symlink'}:
        if damage!='signature':doc=receipts.sign(root,doc)
        p.write_text(json.dumps(doc))
    before=files(tmp_path)
    history=sh.history(root,'M')
    assert history['records']==[] and history['invalid_count']==1
    assert files(tmp_path)==before


def test_history_scan_is_bounded_and_never_claims_complete(tmp_path,monkeypatch):
    root=tmp_path/'install';root.mkdir()
    for index in range(3):record(root,checked_at=index+1)
    monkeypatch.setattr(sh,'MAX_FILES',2)
    report=sh.history(root,'M')
    assert len(report['records'])==2 and report['truncated']
    assert 'not a complete timeline' in report['note']


@pytest.mark.parametrize('limit',[False,0,33,'8'])
def test_invalid_history_limit_rejected(tmp_path,limit):
    with pytest.raises(ValueError):sh.history(tmp_path,'M',limit=limit)


def test_registry_inside_installation_is_rejected(tmp_path,monkeypatch):
    root=tmp_path/'install';root.mkdir()
    monkeypatch.setenv('GEOFORGE_FLOW_REGISTRY',str(root/'registry'))
    with pytest.raises(ValueError,match='outside'):record(root)
    assert sh.history(root,'M')['unavailable'] is True


def test_record_status_excludes_diagnostics_and_keeps_real_verdict(tmp_path):
    status={'ok':False,'checked_at':7,'current_operation':{'id':'attempt'},'runtime_identity':None,
            'primary_error':{'detail':'TOKEN=secret'},'steps':[{'name':'preflight','ok':False,
                'detail':'TOKEN=secret','commands':['secret-command'],'evidence':{'secret':True}}]}
    before=deepcopy(status)
    sh.record_status(tmp_path/'install','M',status,verification_context=context(),
                     check_scope='full_software_verification')
    assert status['ok'] is False and status['primary_error']==before['primary_error']
    rows=sh.history(tmp_path/'install','M')['records']
    assert len(rows)==1 and rows[0]['checks']==[{'name':'preflight','ok':False,'skipped':False}]
    assert 'secret' not in json.dumps(rows)


@pytest.mark.parametrize('verdict',[True,False])
def test_history_persistence_failure_never_relabels_check_or_keeps_old_reference(tmp_path,monkeypatch,verdict):
    status={'ok':verdict,'checked_at':1,'verification_history':{'old':True},'steps':[]}
    monkeypatch.setattr(sh,'record',lambda *a,**k:(_ for _ in ()).throw(PermissionError('SECRET')))
    sh.record_status(tmp_path,'M',status,verification_context=context(),check_scope='full_software_verification')
    assert status['ok'] is verdict and 'verification_history' not in status
    assert 'SECRET' not in status['verification_history_error']


def test_capture_failure_stays_unknown_and_cannot_backfill_current_build(tmp_path,monkeypatch):
    monkeypatch.setattr(runtime_provenance,'capture',lambda:(_ for _ in ()).throw(ValueError('unavailable')))
    captured=sh.capture();assert captured is None
    monkeypatch.setattr(runtime_provenance,'capture',lambda:context('e'))
    status={'ok':True,'checked_at':7,'steps':[{'name':'preflight','ok':True}]}
    sh.record_status(tmp_path,'M',status,verification_context=captured,check_scope='full_software_verification')
    assert status['ok'] is True and 'verification_history' not in status
    assert sh.history(tmp_path,'M')['records']==[]


@pytest.mark.parametrize('passed',[True,False])
def test_real_agent_finalizer_records_captured_context_and_outcome(final_case,monkeypatch,passed):
    c=final_case;seen=install_spies(monkeypatch,requirements_ok=passed)
    actual=gui.software_verification.requirements
    def after_capture(*a,**kw):
        monkeypatch.setattr(runtime_provenance,'capture',lambda:context('e'))
        return actual(*a,**kw)
    monkeypatch.setattr(gui.software_verification,'requirements',after_capture)
    assert finish(c) is passed
    status=saved_status(c);rows=sh.history(c.root,c.ki.name)['records']
    assert len(rows)==1 and rows[0]['outcome']==('passed' if passed else 'failed')
    assert rows[0]['verification_context']['application']['build']['sha256']=='a'*64
    assert rows[0]['runtime_identity']==status['runtime_identity']
    assert status['verification_history']['event_id']==rows[0]['event_id']
    assert seen.requirements


def test_agent_finalizer_cancellation_remains_failed_with_cancelled_history(final_case,monkeypatch):
    install_spies(monkeypatch)
    assert finish(final_case,stop=lambda:True) is False
    row=sh.history(final_case.root,final_case.ki.name)['records'][0]
    assert row['outcome']=='cancelled' and not saved_status(final_case)['ok']


@pytest.mark.parametrize('installation_only',[False,True])
def test_builtin_final_result_uses_distinct_check_scope(builtin_case,monkeypatch,installation_only):
    c=builtin_case
    monkeypatch.setattr(gui.runnable,'check',lambda *a,**k:SimpleNamespace(usable=True,summary=lambda:'fixture'))
    gui.run_install(c.ki,c.man,c.root,lambda _:None,c.library,installation_only=installation_only)
    status=json.loads((c.root/'status.json').read_text())
    assert status['ok']
    rows=sh.history(c.root,c.ki.name)['records']
    assert len(rows)==1 and rows[0]['outcome']=='passed'
    assert rows[0]['check_scope']==('installation_only' if installation_only else 'full_software_verification')
    assert (status['verified_at'] is None) is installation_only


def test_builtin_stopped_attempt_records_only_cancellation_not_prior_pass(tmp_path,monkeypatch):
    root=tmp_path/'install';root.mkdir()
    (root/'status.json').write_text(json.dumps({'ok':True,'steps':[{'name':'old','ok':True}]}))
    monkeypatch.setattr(gui,'_run_install',lambda *a,**k:(_ for _ in ()).throw(install.InstallStopped('stopped')))
    gui.run_install(SimpleNamespace(name='M'),None,root,lambda _:None,tmp_path)
    status=json.loads((root/'status.json').read_text());rows=sh.history(root,'M')['records']
    assert not status['ok'] and rows[0]['outcome']=='cancelled'
    assert rows[0]['checks']==[{'name':'interrupted','ok':False,'skipped':False}]


def test_real_finalizer_capture_failure_preserves_verdict_without_version_backfill(final_case,monkeypatch):
    install_spies(monkeypatch)
    monkeypatch.setattr(runtime_provenance,'capture',lambda:(_ for _ in ()).throw(ValueError('SECRET')))
    assert finish(final_case) is True
    status=saved_status(final_case)
    assert status['ok'] and status['verified_at'] and 'verification_history' not in status
    assert 'SECRET' not in status['verification_history_error']
    assert sh.history(final_case.root,final_case.ki.name)['records']==[]


def test_incomplete_signed_event_is_rejected_without_repair_or_key_creation(tmp_path):
    root=tmp_path/'install';root.mkdir();ref=record(root);p=event_path(root,ref)
    p.write_bytes(p.read_bytes()[:40])
    before=files(tmp_path)
    result=sh.history(root,'M')
    assert result['records']==[] and result['invalid_count']==1
    assert files(tmp_path)==before
