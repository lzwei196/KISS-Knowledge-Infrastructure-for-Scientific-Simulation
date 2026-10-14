"""Declared scientific outputs and JSON reports remain distinct from runtime artifacts."""
import copy
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import api, cli, flowgate, ki_guard, paths, project_verification
from kiss_cli.catalog import KI
from kiss_cli.manifest import Manifest
from ki_tools_common.flow import declared_outputs as output_policy


SCRIPT = '''import json,sys
from pathlib import Path
p=Path('outputs/case');p.mkdir(parents=True,exist_ok=True)
mode=sys.argv[1] if len(sys.argv)>1 else 'ok'
(p/'Summary.OUT').write_text('day,yield\\n1,2\\n2,4\\n3,3\\n' if mode!='nan' else 'day,yield\\n1,nan\\n2,4\\n')
(p/'PlantGro.OUT').write_text('day,biomass\\n1,2\\n2,4\\n3,3\\n')
if mode!='missing':(p/'replay_receipt.json').write_text(json.dumps({'ok':True,'treatment':1}))
(p/'runtime.exe').write_bytes(b'\\x00\\xffruntime')
(p/'TABLE.CDE').write_text('NaN Inf nonnumeric supporting table')
(p/'runner_stderr.txt').write_text('')
'''


def contract(project, tool='tool.py'):
    step = {'id':'M:run','ki':'M','tool':tool,'kind':'model_run','inputs':[],
            'outputs':['summary','plantgro','report'],'status':'planned'}
    items = [{'id':i,'local_paths':['outputs/case/'+name],'status':'missing'} for i,name in
             [('summary','Summary.OUT'),('plantgro','PlantGro.OUT'),('report','replay_receipt.json')]]
    items[-1]['output_validation']='json_report_v1'
    return step, {'schema_version':'1.0','items':items}


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setenv('GEOFORGE_FLOW_KEYS',str(tmp_path/'keys'))
    project=tmp_path/'project';root=project/'models/M/ki';(root/'tools').mkdir(parents=True)
    (project/'runs').mkdir()
    (root/'SKILL.md').write_text('# Test KI\n')
    (root/'dag.yaml').write_text('outputs:\n- var: yield\n  validation_rank: 1\n  unit: kg/ha\n')
    (root/'preflight_check.py').write_text("print('Harmless fixture preflight')\n")
    tool=root/'tools/run.py';tool.write_text(SCRIPT)
    cfg=paths.KissConfig.default(project);cfg.python=sys.executable
    (project/paths.CONFIG_NAME).write_text(cfg.dumps(),encoding='utf-8')
    (root.parent/paths.CONFIG_NAME).write_text(cfg.dumps(),encoding='utf-8')
    ki_guard.enroll(root);ki=KI('M',root)
    assert project_verification.verify(project,ki,Manifest(model='M'))['ok']
    fs=flowgate.FlowSession.open(project,{'M':root},python=sys.executable)
    fs.move('task_received');fs.move('kis_resolved',{'selected_kis':['M']})
    step,inventory=contract(project,str(tool))
    plan={'schema_version':'1.0','goal':'Check genuine harmless output collection','created_at':'test',
          'selected_kis':['M'],'unresolved_questions':[],'scientific_choices':[],'steps':[step]}
    assert fs.write_plan(plan,inventory)==[]
    fs.flow.approval.approve(project,by='user');fs.reload_artifacts()
    fs.move('plan_written',{'plan_valid':True});fs.move('approved',{'approval':'OK'})
    fs.move('execution_started',{'setup_verified':True})
    return SimpleNamespace(project=project,root=root,tool=tool,ki=ki,cfg=cfg,fs=fs,step=step,inventory=inventory)


def invoke(c,adapter='api',mode='ok'):
    if adapter=='api':
        api.execute_tool('run_ki_tool',{'tool_path':'tools/run.py','plan_step_id':'M:run','arguments':[mode]},
                         c.ki,c.cfg,project_mode=True,flow=c.fs)
    else:
        cli.main(['run-tool','--project',str(c.project),'--step','M:run','M','tools/run.py','--',mode])
    paths=list((c.project/'.geoforge/receipts/model-runs').glob('*.json'))
    docs=[json.loads(p.read_text(encoding='utf-8')) for p in paths]
    assert all(c.fs.flow.receipts.verify(c.project,d) for d in docs)
    return docs


@pytest.mark.parametrize('adapter',['api','cli'])
def test_real_dispatch_checks_declared_results_and_retains_all_support_hashes(case,adapter):
    c=case;doc=invoke(c,adapter)[0]
    assert doc['exit_code']==0 and doc['validation']['status']=='passed'
    assert len(doc['outputs'])==6 and all(row['sha256'] for row in doc['outputs'])
    roles={row['path']:row['output_role'] for row in doc['outputs']}
    assert roles['outputs/case/Summary.OUT']=='declared_scientific_result'
    assert roles['outputs/case/replay_receipt.json']=='declared_json_report'
    assert roles['outputs/case/runtime.exe']=='supporting_execution_artifact'
    assert roles['outputs/case/runner_stderr.txt']=='supporting_execution_artifact'
    names=[c['check'] for c in doc['validation']['checks']]
    assert not any('TABLE.CDE' in n or 'runtime.exe' in n or 'runner_stderr' in n for n in names)
    assert any('physically_required_positive:Summary.OUT'==n for n in names)
    assert c.fs.evidence()['receipts_verified']


@pytest.mark.parametrize('adapter',['api','cli'])
@pytest.mark.parametrize('mode',['missing','nan'])
def test_missing_report_or_nonfinite_scientific_result_still_fails(case,adapter,mode):
    c=case;doc=invoke(c,adapter,mode)[0]
    assert doc['exit_code']==0 and doc['validation']['status']=='failed'
    assert not c.fs.evidence()['receipts_verified']
    if mode=='missing':assert not (c.project/'outputs/case/replay_receipt.json').exists()


@pytest.mark.parametrize('file',['Summary.OUT','TABLE.CDE','runtime.exe','runner_stderr.txt','replay_receipt.json'])
def test_current_completion_rechecks_scientific_and_supporting_file_hashes(case,file):
    c=case;invoke(c)
    target=c.project/'outputs/case'/file;target.write_bytes(target.read_bytes()+b'changed')
    evidence=c.fs.evidence()
    assert not evidence['receipts_verified'] and evidence['validation']=='incomplete'
    assert evidence['stale_steps'] == ['M:run']
    assert evidence['runs'][0]['validation'] == 'passed'


@pytest.mark.parametrize('damage',['missing-item','duplicate-id','duplicate-path','directory','outside','parent','alias','unknown-policy','malformed-policy','report-only'])
def test_ambiguous_or_unsafe_declared_output_contract_fails_closed(tmp_path,damage):
    project=tmp_path/'project';(project/'outputs/case').mkdir(parents=True)
    step,inv=contract(project)
    if damage=='missing-item':inv['items'].pop(0)
    elif damage=='duplicate-id':inv['items'].append(copy.deepcopy(inv['items'][0]))
    elif damage=='duplicate-path':inv['items'][1]['local_paths']=inv['items'][0]['local_paths']
    elif damage=='directory':inv['items'][0]['local_paths']=['outputs/case']
    elif damage=='outside':inv['items'][0]['local_paths']=[str(tmp_path/'elsewhere.csv')]
    elif damage=='parent':inv['items'][0]['local_paths']=['outputs/../case.csv']
    elif damage=='alias':
        target=tmp_path/'external';target.write_text('1,2');(project/'outputs/case/Summary.OUT').symlink_to(target)
    elif damage=='unknown-policy':inv['items'][0]['output_validation']='skip'
    elif damage=='malformed-policy':inv['items'][0]['output_validation']={'role':'report'}
    else:
        for item in inv['items']:item['output_validation']='json_report_v1'
    assert output_policy.plan_errors({'steps':[step]},inv,project)
    validation,_=output_policy.validate(project,tmp_path,step,inv,[],run_facts={'errored':False},physical=True)
    assert validation['status']=='failed'


@pytest.mark.parametrize('body',['{}','[]','null','true','{"a":1,"a":2}','{"a":NaN}','{"a":Infinity}','{"a":1e999}','{broken'])
def test_explicit_json_report_is_strict_and_never_numeric_proof(tmp_path,body):
    project=tmp_path/'project';p=project/'outputs/case';p.mkdir(parents=True)
    step,inv=contract(project)
    for name in ['Summary.OUT','PlantGro.OUT']:(p/name).write_text('day,value\n1,1\n2,4\n3,2\n')
    (p/'replay_receipt.json').write_text(body)
    result,_=output_policy.validate(project,tmp_path,step,inv,list(p.iterdir()),run_facts={'errored':False},physical=True)
    assert result['status']=='failed'


def test_unchanged_declared_file_is_not_fresh_even_when_other_results_are_new(tmp_path):
    project=tmp_path/'project';p=project/'outputs/case';p.mkdir(parents=True)
    step,inv=contract(project)
    for name in ['Summary.OUT','PlantGro.OUT']:(p/name).write_text('day,value\n1,1\n2,4\n3,2\n')
    (p/'replay_receipt.json').write_text('{"ok":true}')
    result,_=output_policy.validate(project,tmp_path,step,inv,[p/'Summary.OUT',p/'PlantGro.OUT'],
        run_facts={'errored':False},physical=True)
    assert result['status']=='failed'
    assert any(not c['ok'] and c['check'].endswith('replay_receipt.json') for c in result['checks'])


def test_input_only_output_policy_and_specialized_tool_policy_are_rejected(tmp_path):
    step,inv=contract(tmp_path)
    inv['items'].append({'id':'input','output_validation':'json_report_v1'})
    assert output_policy.plan_errors({'steps':[step]},inv,tmp_path)
    inv['items'].pop();step['project_data_tool']={'version':1}
    assert output_policy.plan_errors({'steps':[step]},inv,tmp_path)


def test_legacy_no_outputs_and_specialized_binding_are_unchanged(tmp_path):
    step,inv=contract(tmp_path);step['outputs']=[]
    assert output_policy.binding(tmp_path,step,inv) is None
    step['outputs']=['summary'];step['stdout_artifact']={'version':1}
    assert output_policy.binding(tmp_path,step,inv) is None


def test_legacy_symbolic_outputs_keep_all_changed_validation_without_support_exemptions(tmp_path):
    project=tmp_path/'project';p=project/'outputs';p.mkdir(parents=True)
    step={'id':'M:legacy','ki':'M','tool':'tool.py','kind':'run','inputs':[],'outputs':['symbolic']}
    inv={'items':[]}
    (p/'numeric.csv').write_text('time,value\n1,2\n2,4\n3,3\n')
    (p/'empty.txt').write_text('')
    assert output_policy.binding(project,step,inv) is None
    assert output_policy.plan_errors({'steps':[step]},inv,project)==[]
    result,bound=output_policy.validate(project,tmp_path,step,inv,list(p.iterdir()),
        run_facts={'errored':False},physical=True)
    assert bound is None and result['status']=='failed'
    assert any(c['check']=='non_empty:empty.txt' and not c['ok'] for c in result['checks'])


def test_missing_contract_cannot_promote_a_historical_signed_pass(case):
    c=case;doc=invoke(c)[0];doc.pop('declared_outputs')
    errors=output_policy.receipt_errors(c.project,c.step,c.inventory,doc)
    assert errors and 'differ' in errors[0]


def test_support_role_cannot_be_changed_to_hide_a_declared_result(case):
    c=case;doc=invoke(c)[0]
    next(row for row in doc['outputs'] if row['path'].endswith('Summary.OUT'))['output_role']='supporting_execution_artifact'
    assert output_policy.receipt_errors(c.project,c.step,c.inventory,doc)


def test_later_missing_output_attempt_does_not_resurrect_earlier_pass(case):
    c=case;invoke(c)
    assert c.fs.evidence()['receipts_verified']
    docs=invoke(c,mode='missing')
    assert len(docs)==2
    evidence=c.fs.evidence()
    assert not evidence['receipts_verified'] and evidence['validation']=='failed'
    assert 'M:run' not in evidence['steps_passed']


@pytest.mark.parametrize('change',['step','inventory','policy','missing-file','missing-entry','hardlink'])
def test_receipt_binding_freshness_and_output_identity_remain_mandatory(case,change):
    c=case;doc=invoke(c)[0];step=copy.deepcopy(c.step);inv=copy.deepcopy(c.inventory)
    if change=='step':step['kind']='prepare'
    elif change=='inventory':inv['items'][0]['local_paths']=['outputs/case/other.OUT']
    elif change=='policy':doc['declared_outputs']['policy']='old-policy'
    elif change=='missing-file':(c.project/'outputs/case/Summary.OUT').unlink()
    elif change=='missing-entry':doc['outputs']=[r for r in doc['outputs'] if not r['path'].endswith('replay_receipt.json')]
    else:
        (c.project/'external-link').hardlink_to(c.project/'outputs/case/TABLE.CDE')
    assert output_policy.receipt_errors(c.project,step,inv,doc)


def test_enlarged_support_file_is_rejected_before_replacement_is_opened(case,monkeypatch):
    c=case;doc=invoke(c)[0];target=c.project/'outputs/case/runtime.exe'
    target.write_bytes(target.read_bytes()+b'x')
    original=Path.open
    def checked(path,*args,**kwargs):
        if path==target:pytest.fail('Size drift must be rejected before hashing replacement')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'open',checked)
    assert output_policy.receipt_errors(c.project,c.step,c.inventory,doc)


def test_report_size_limit_is_checked_before_open(tmp_path,monkeypatch):
    path=tmp_path/'huge.json';path.write_bytes(b'x'*100)
    monkeypatch.setattr(output_policy,'MAX_REPORT_BYTES',50)
    original=Path.open
    def checked(target,*args,**kwargs):
        if target==path:pytest.fail('Oversized JSON must not be opened')
        return original(target,*args,**kwargs)
    monkeypatch.setattr(Path,'open',checked)
    with pytest.raises(ValueError,match='4 MiB'):output_policy._json_report(path)


def test_newer_authentic_wrong_invocation_is_failed_without_resurrecting_old_pass(case):
    """A synthetic historical host receipt exercises the combined A+B evidence seam."""
    c=case
    step=c.fs.plan['steps'][0]
    step['command']=['ok','--receipt','outputs/case/replay_receipt.json'];step['cwd']='.'
    c.fs.flow.plan.write_artifacts(c.project,c.fs.plan,c.fs.inventory)
    c.fs.flow.approval.approve(c.project,by='user');c.fs.reload_artifacts()
    api.execute_tool('run_ki_tool',{'tool_path':'tools/run.py','plan_step_id':'M:run','arguments':step['command']},
                     c.ki,c.cfg,project_mode=True,flow=c.fs)
    assert c.fs.evidence()['receipts_verified']
    path=next((c.project/'.geoforge/receipts/model-runs').glob('*.json'))
    previous=json.loads(path.read_text(encoding='utf-8'))
    now=time.time()+2
    c.fs.flow.receipts.record_run(c.project,ki='M',executable=sys.executable,
        command=[sys.executable,str(c.tool),'ok'],cwd=str(c.project),started_at=now,finished_at=now,
        exit_code=0,inputs=[],outputs=[c.project/row['path'] for row in previous['outputs']],
        approval_sha256=c.fs.approval_id,plan_step_id='M:run',validation=previous['validation'],
        declared_outputs=previous['declared_outputs'],execution_status='succeeded',process_started=True)
    evidence=c.fs.evidence()
    assert evidence['runs_bound']==2 and evidence['validation']=='failed'
    assert not evidence['receipts_verified'] and 'M:run' not in evidence['steps_passed']
    assert any('invocation' in row.get('validation_reason','').lower() or
               'argument' in row.get('validation_reason','').lower() for row in evidence['runs'])


def test_api_two_part_plan_write_preserves_explicit_json_report_policy(case):
    c=case;c.fs.request_replan('Fixture: review an explicit report policy')
    first=api.execute_tool('write_plan',{'plan':c.fs.plan},c.ki,c.cfg,project_mode=True,flow=c.fs)
    assert 'Received plan' in first
    second=api.execute_tool('write_plan',{'data_inventory':c.inventory},c.ki,c.cfg,project_mode=True,flow=c.fs)
    assert 'Plan files written' in second
    saved=json.loads((c.project/'runs/data-inventory.json').read_text(encoding='utf-8'))
    assert next(i for i in saved['items'] if i['id']=='report')['output_validation']=='json_report_v1'
