"""Runtime tables are versioned setup data; no fixture installs or runs a model."""
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

from kiss_cli import install, paths, runtime_data, software_verification
from kiss_cli.manifest import Acquire, Manifest, document
from tests.test_project_verification import case as project_case
from kiss_cli import project_verification as pv


def _git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.STDOUT)


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setenv('GEOFORGE_FLOW_KEYS', str(tmp_path/'host-keys'))
    source=tmp_path/'official';source.mkdir()
    _git(source,'init','-q');_git(source,'config','core.autocrlf','false')
    _git(source,'config','user.email','fixture@example.invalid');_git(source,'config','user.name','Fixture')
    _git(source,'remote','add','origin','https://example.invalid/official/model.git')
    payload=b'! Exact scientific support table\nA 1 2\nB 3 4\n'
    (source/'Data').mkdir();(source/'Data'/'TABLE.CDE').write_bytes(payload)
    _git(source,'add','Data');_git(source,'commit','-qm','Fixture support data')
    commit=_git(source,'rev-parse','HEAD').decode().strip()
    contract={'version':1,'source':{'repo':'https://example.invalid/official/model.git','commit':commit},
      'target':{'role':'home','path':'Model/Data'},'files':[{'source':'Data/TABLE.CDE','path':'TABLE.CDE',
        'sha256':hashlib.sha256(payload).hexdigest(),'bytes':len(payload),'text_newlines':'lf_or_crlf'}]}
    root=tmp_path/'setup';root.mkdir();cfg=paths.KissConfig.default(root);cfg.python=sys.executable
    cfg.roles['home']=root
    man=Manifest(model='Demo',runtime_data=contract)
    calls=[]
    def acquire(recipe,prefix,python,**kwargs):
        calls.append((recipe,prefix,python))
        assert recipe.acquire.strategy=='build' and recipe.acquire.commands==[]
        assert recipe.acquire.produces is None and recipe.acquire.ref==commit
        shutil.copytree(source,prefix)
        return install.Step('acquire[build]',True,'isolated fixture source'),None
    monkeypatch.setattr(install,'acquire',acquire)
    return SimpleNamespace(source=source,root=root,cfg=cfg,man=man,contract=contract,payload=payload,
                           target=root/'Model'/'Data'/'TABLE.CDE',calls=calls)


def _write(case,payload=None):
    case.target.parent.mkdir(parents=True,exist_ok=True)
    case.target.write_bytes(case.payload if payload is None else payload)


def test_missing_is_read_only_until_explicit_action(case):
    before=set(case.root.rglob('*'))
    assert not runtime_data.check(case.man,case.cfg).ok
    denied=runtime_data.prepare(case.man,case.cfg,allow_acquire=False)
    assert not denied.ok and not case.calls
    assert set(case.root.rglob('*'))==before


def test_pinned_acquisition_writes_only_declared_data_once_and_signs(case):
    result=runtime_data.prepare(case.man,case.cfg,allow_acquire=True)
    assert result.ok,result.detail
    assert case.target.read_bytes()==case.payload and len(case.calls)==1
    assert result.evidence['acquisition']['engine_built'] is False
    assert not result.evidence['model_executed'] and not result.evidence['scientific_validation']
    receipt=next((case.root/'.geoforge'/'runtime-data').glob('*.json'))
    from kiss_cli import flowgate
    assert flowgate.load().receipts.verify(case.root,json.loads(receipt.read_text()))
    repeat=runtime_data.prepare(case.man,case.cfg,allow_acquire=True)
    assert repeat.ok and len(case.calls)==1 and 'acquisition' not in repeat.evidence


@pytest.mark.parametrize('representation',['lf','crlf'])
def test_declared_uniform_text_representation_preserves_actual_bytes(case,representation):
    value=case.payload if representation=='lf' else case.payload.replace(b'\n',b'\r\n');_write(case,value)
    result=runtime_data.prepare(case.man,case.cfg,allow_acquire=True)
    assert result.ok and not case.calls and case.target.read_bytes()==value
    row=result.evidence['files'][0]
    assert row['sha256']==hashlib.sha256(value).hexdigest() and row['bytes']==len(value)
    assert row['canonical_sha256']==case.contract['files'][0]['sha256']
    assert row['representation']==representation


@pytest.mark.parametrize('payload',[b'! Exact scientific support table\r\nA 1 2\nB 3 4\n',
    b'! Exact scientific support table\nA 1 2\rB 3 4\n',b'! Exact scientific support table\nA 1 2\0B 3 4\n',
    b'! Exact scientific support table\nA 1 3\nB 3 4\n'])
def test_text_mixed_lone_cr_nul_or_content_changes_never_repaired(case,payload):
    _write(case,payload)
    result=runtime_data.prepare(case.man,case.cfg,allow_acquire=True)
    assert not result.ok and not case.calls and case.target.read_bytes()==payload


def test_omitted_text_policy_requires_exact_raw_bytes(case):
    case.contract['files'][0].pop('text_newlines');_write(case,case.payload.replace(b'\n',b'\r\n'))
    assert not runtime_data.check(case.man,case.cfg).ok
    case.target.write_bytes(case.payload)
    assert runtime_data.check(case.man,case.cfg).ok


@pytest.mark.parametrize('kind',['commit','repo','hash','size','source-path'])
def test_source_or_declaration_mismatch_creates_no_target(case,kind):
    if kind=='commit':case.contract['source']['commit']='a'*40
    elif kind=='repo':case.contract['source']['repo']='https://example.invalid/other.git'
    elif kind=='hash':case.contract['files'][0]['sha256']='b'*64
    elif kind=='size':case.contract['files'][0]['bytes']+=1
    else:case.contract['files'][0]['source']='Data/absent.CDE'
    # The test transport supplies an authentic but mismatching repository without asserting the ref.
    def transport(man,prefix,python,**kwargs):
        shutil.copytree(case.source,prefix);return install.Step('acquire',True,'fixture'),None
    from unittest.mock import patch
    with patch.object(install,'acquire',transport):result=runtime_data.prepare(case.man,case.cfg,allow_acquire=True)
    assert not result.ok and not case.target.exists()


def test_existing_data_conflict_is_preserved(case):
    _write(case,b'User calibration\n')
    result=runtime_data.prepare(case.man,case.cfg,allow_acquire=True)
    assert not result.ok and not case.calls and case.target.read_bytes()==b'User calibration\n'


def test_external_role_cannot_be_acquired(case,tmp_path):
    case.cfg.roles['home']=tmp_path/'outside'
    result=runtime_data.prepare(case.man,case.cfg,allow_acquire=True)
    assert not result.ok and not case.calls and not (tmp_path/'outside').exists()


def test_hardlinked_existing_file_cannot_be_certified_or_replaced(case,tmp_path):
    external=tmp_path/'external';external.write_bytes(case.payload)
    case.target.parent.mkdir(parents=True);os.link(external,case.target)
    result=runtime_data.prepare(case.man,case.cfg,allow_acquire=True)
    assert not result.ok and not case.calls and external.read_bytes()==case.payload


def test_aliased_target_is_rejected_without_outside_writes(case,tmp_path):
    external=tmp_path/'outside';external.mkdir();case.target.parent.parent.mkdir()
    try:case.target.parent.symlink_to(external,target_is_directory=True)
    except OSError:pytest.skip('symlink capability unavailable')
    result=runtime_data.prepare(case.man,case.cfg,allow_acquire=True)
    assert not result.ok and not case.calls and list(external.iterdir())==[]


def test_cancelled_setup_does_not_publish(case,monkeypatch):
    def stopped():raise install.InstallStopped('fixture stop')
    monkeypatch.setattr(install,'check_cancelled',stopped)
    with pytest.raises(install.InstallStopped):runtime_data.prepare(case.man,case.cfg,allow_acquire=True)
    assert not case.target.exists() and not case.calls


@pytest.mark.parametrize('change',[
    lambda c:c.update(version=2),lambda c:c.update(unknown=True),
    lambda c:c['source'].update(repo='https://user:secret@example.invalid/repo'),
    lambda c:c['source'].update(commit='main'),lambda c:c['target'].update(path='../outside'),
    lambda c:c['target'].update(path='D:/absolute'),lambda c:c['target'].update(role='outputs'),
    lambda c:c['files'][0].update(path='A\\b'),lambda c:c['files'][0].update(path='a:$DATA'),
    lambda c:c['files'][0].update(bytes=True),lambda c:c['files'][0].update(text_newlines='auto'),
    lambda c:c['files'].append(dict(c['files'][0],path='table.cde')),
    lambda c:c['files'].append(dict(c['files'][0],source='Data/child',path='TABLE.CDE/child')),
])
def test_malformed_contract_fails_before_acquisition(case,change):
    change(case.contract)
    with pytest.raises(ValueError):runtime_data.validate_contract(case.contract)
    assert not runtime_data.prepare(case.man,case.cfg,allow_acquire=True).ok and not case.calls


def test_requirements_enforces_data_without_native_model(case):
    assert not software_verification.requirements(case.man,case.cfg).ok
    _write(case)
    assert software_verification.requirements(case.man,case.cfg).ok


def test_legacy_manifest_document_matches_prior_asdict_and_no_contract_skips(case):
    man=Manifest(model='Legacy');old=asdict(man);old.pop('runtime_data')
    assert document(man)==old
    assert 'runtime_data' not in document(man)
    assert runtime_data.check(man,case.cfg).ok and runtime_data.check(man,case.cfg).skipped
    assert runtime_data.prepare(man,case.cfg,allow_acquire=True).ok and not case.calls


def test_manifest_reads_contract_and_rejects_malformed(case,tmp_path):
    import yaml
    path=tmp_path/'kiss.yaml';raw={'kiss_manifest_version':1,'model':'Demo','runtime_data':case.contract}
    path.write_text(yaml.safe_dump(raw),encoding='utf-8')
    assert Manifest.load(path).runtime_data==case.contract
    raw['runtime_data']['files'][0]['sha256']='bad'
    path.write_text(yaml.safe_dump(raw),encoding='utf-8')
    with pytest.raises(ValueError):Manifest.load(path)


def test_current_project_receipt_binds_real_runtime_data_and_detects_deletion(project_case,case):
    project,ki,man,cfg,config=project_case
    # Runtime data roles are explicit; the project verifier does not borrow shared success.
    cfg.roles['home']=case.root;config.write_text(cfg.dumps(),encoding='utf-8')
    man.runtime_data=case.contract;_write(case)
    result=pv.verify(project,ki,man)
    assert result['ok'],result
    assert pv.status(project,ki,man)['can_run']
    receipt=pv._receipt_path(project,ki.name).read_bytes()
    case.target.unlink()
    status=pv.status(project,ki,man)
    assert not status['can_run'] and status['state']=='stale'
    assert pv._receipt_path(project,ki.name).read_bytes()==receipt
    failed=pv.verify(project,ki,man)
    assert not failed['ok'] and any(not c['ok'] for c in failed['receipt']['checks'])


def test_project_receipt_binds_actual_representation_not_only_canonical(project_case,case):
    project,ki,man,cfg,config=project_case;cfg.roles['home']=case.root
    config.write_text(cfg.dumps(),encoding='utf-8');man.runtime_data=case.contract;_write(case)
    assert pv.verify(project,ki,man)['ok']
    case.target.write_bytes(case.payload.replace(b'\n',b'\r\n'))
    assert runtime_data.check(man,cfg).ok
    assert not pv.status(project,ki,man)['can_run']



def test_legacy_signed_project_receipt_without_opt_in_key_remains_current(project_case):
    project,ki,man,cfg,config=project_case
    assert pv.verify(project,ki,man)['ok']
    path=pv._receipt_path(project,ki.name)
    doc=json.loads(path.read_text(encoding='utf-8'))
    doc.pop('runtime_data')
    # Simulate the authentic pre-feature document: same canonical effective recipe.
    assert 'runtime_data' not in doc['effective_manifest']
    path.write_text(json.dumps(pv._receipts().sign(project,doc)),encoding='utf-8')
    assert pv.status(project,ki,man)['can_run']


def test_policy_or_contract_change_invalidates_project_receipt(project_case,case,monkeypatch):
    project,ki,man,cfg,config=project_case;cfg.roles['home']=case.root
    config.write_text(cfg.dumps(),encoding='utf-8');man.runtime_data=case.contract;_write(case)
    assert pv.verify(project,ki,man)['ok']
    monkeypatch.setattr(runtime_data,'POLICY','different-policy')
    assert not pv.status(project,ki,man)['can_run']


from tests.test_setup_preflight_cli import prepared as cli_prepared


def test_cli_diagnostic_rejects_missing_data_without_acquiring(case,cli_prepared,monkeypatch,capsys):
    from kiss_cli import cli
    args,cfg=cli_prepared
    man=Manifest(model=args.model,runtime_data=case.contract)
    monkeypatch.setattr(cli,'_manifest_for',lambda *_:man)
    assert cli.cmd_preflight(args)==1
    report=json.loads(capsys.readouterr().out)
    assert not report['ok'] and 'missing' in report['detail']
    assert not case.calls and not (cfg.root/'Model'/'Data').exists()


def test_cli_diagnostic_accepts_existing_data_without_ready_claim(case,cli_prepared,monkeypatch,capsys):
    from kiss_cli import cli
    args,cfg=cli_prepared
    target=cfg.roles['home']/'Model'/'Data'/'TABLE.CDE';target.parent.mkdir(parents=True)
    target.write_bytes(case.payload)
    man=Manifest(model=args.model,runtime_data=case.contract)
    monkeypatch.setattr(cli,'_manifest_for',lambda *_:man)
    assert cli.cmd_preflight(args)==0
    report=json.loads(capsys.readouterr().out)
    assert report['ok'] and report['evidence']['runtime_data']['ok']
    assert not case.calls and not (cfg.root/'status.json').exists()


from tests.test_setup_projection_binding import case as projection_case


def test_cli_new_setup_prepares_declared_data_before_preflight(case,projection_case,monkeypatch):
    from kiss_cli import cli
    c=projection_case;c.man.runtime_data=case.contract
    monkeypatch.setattr(cli,'_manifest_for',lambda *_:c.man)
    calls=[]
    def prepare(man,cfg,*,allow_acquire,env=None):
        calls.append((man,cfg,allow_acquire))
        return install.Step('runtime-data',False,'fixture required table acquisition failed')
    monkeypatch.setattr(runtime_data,'prepare',prepare)
    monkeypatch.setattr(install,'run_preflight',lambda *a,**kw:pytest.fail('preflight ran despite missing runtime tables'))
    args=SimpleNamespace(models=c.library/'models',model='Demo',workdir=str(c.root),python=None,relocation='none')
    assert cli.cmd_init(args)==2
    assert len(calls)==1 and calls[0][0] is c.man and calls[0][2] is True
    assert calls[0][1].python==str(c.selected)


from tests.test_setup_existing_placement import case as existing_case


def test_cli_existing_setup_checks_tables_without_acquiring(case,existing_case,monkeypatch,capsys):
    from kiss_cli import cli,gui
    c=existing_case;man=c.handler._manifest(c.ki);man.runtime_data=case.contract
    gui._place_selected_existing_install(c.live,man,c.cfg,str(c.distribution))
    monkeypatch.setattr(cli,'_manifest_for',lambda *_:man)
    monkeypatch.setattr(install,'needs_shared_tools',lambda *a:False)
    monkeypatch.setattr(install,'check_system_deps',lambda *a:install.Step('system-deps',True))
    monkeypatch.setattr(install,'install_python_deps',lambda *a,**kw:install.Step('python-deps',True))
    monkeypatch.setattr(install,'acquire',lambda *a,**kw:pytest.fail('Existing discovery fetched software'))
    monkeypatch.setattr(runtime_data,'prepare',lambda *a,**kw:pytest.fail('Existing discovery acquired support data'))
    monkeypatch.setattr(install,'run_preflight',lambda *a,**kw:pytest.fail('Missing runtime tables reached preflight'))
    args=SimpleNamespace(models=c.handler.catalog.models_dir,model='DSSAT',workdir=str(c.root),python=None,relocation='none')
    assert cli.cmd_init(args)==2
    output=capsys.readouterr().out
    assert 'required runtime data: FAILED' in output and 'TABLE.CDE: missing' in output
    assert not (c.root/'status.json').exists()
