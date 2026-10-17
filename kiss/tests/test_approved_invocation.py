"""Real harmless dispatches bind explicit approved args/cwd across providers.

These are host contract fixtures, not scientific/native model executions.
"""
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from kiss_cli import api, cli, flowgate, ki_guard, paths, project_paths, project_verification
from kiss_cli.catalog import KI
from kiss_cli.manifest import Manifest


ABSENT = object()


def make_case(tmp_path, monkeypatch, *, command=ABSENT, cwd='.'):
    monkeypatch.setenv('GEOFORGE_FLOW_KEYS', str(tmp_path/'keys'))
    project = tmp_path/'project'; root = project/'models/M/ki'
    (root/'tools').mkdir(parents=True); (project/'runs').mkdir(); (project/'work').mkdir()
    (root/'SKILL.md').write_text('# Harmless invocation fixture\n')
    (root/'preflight_check.py').write_text("print('Harmless project preflight')\n")
    tool = root/'tools/record.py'
    tool.write_text("import json,os,sys\nfrom pathlib import Path\n"
                    "Path('launched.json').write_text(json.dumps({'argv':sys.argv[1:],'cwd':str(Path.cwd()),"
                    "'env':os.environ.get('MODEL_SETTING')}))\nprint('harmless execution complete')\n")
    ki_guard.enroll(root); ki = KI('M', root)
    cfg = project_paths.model_config(project, 'M', paths.KissConfig.default(project))
    cfg.python = sys.executable
    (root.parent/paths.CONFIG_NAME).write_text(cfg.dumps(), encoding='utf-8')
    (project/paths.CONFIG_NAME).write_text(project_paths.project_config(project, python=sys.executable).dumps(), encoding='utf-8')
    assert project_verification.verify(project, ki, Manifest(model='M'))['can_run']
    flow = flowgate.FlowSession.open(project, {'M':root}, python=sys.executable)
    flow.move('task_received'); flow.move('kis_resolved', {'selected_kis':['M']})
    step = {'id':'M:run','ki':'M','tool':str(tool),'kind':'run','inputs':[], 'outputs':[],
            'status':'planned','env':{'MODEL_SETTING':'approved'}}
    if command is not ABSENT: step['command'] = command
    if cwd is not ABSENT: step['cwd'] = cwd
    plan = {'schema_version':'1.0','goal':'Exact invocation fixture','selected_kis':['M'],
            'created_at':'test','unresolved_questions':[],'scientific_choices':[],'steps':[step]}
    inventory = {'schema_version':'1.0','items':[]}
    if command is ABSENT:
        # These fixtures explicitly exercise historical unbound-argv approval
        # compatibility; they are not newly submitted plans.
        assert flow.flow.plan.validate(plan, inventory, ['M'], {'M': root},
                                       project=project, for_execution=True) == []
        flow.flow.plan.write_artifacts(project, plan, inventory)
    else:
        assert flow.write_plan(plan, inventory) == []
    flow.flow.approval.approve(project, by='user'); flow.reload_artifacts()
    flow.move('plan_written', {'plan_valid':True}); flow.move('approved', {'approval':'OK'})
    flow.move('execution_started', {'setup_verified':True})
    return SimpleNamespace(project=project, root=root, ki=ki, cfg=cfg, tool=tool, flow=flow,
                           plan=plan, step=step, inventory=inventory)


def invoke(c, adapter, arguments, capsys, **kwargs):
    if adapter == 'api':
        return api.execute_tool('run_ki_tool', {'tool_path':'tools/record.py', 'plan_step_id':'M:run',
            'arguments':arguments, **kwargs}, c.ki, c.cfg, project_mode=True, flow=c.flow)
    result = cli.main(['run-tool','--project',str(c.project),'--step','M:run','M','tools/record.py','--',*arguments])
    output = capsys.readouterr()
    return result, output.out, output.err


def assert_denied(c, adapter, arguments, capsys, message='approved command', **kwargs):
    before = {str(p):p.read_bytes() for p in (c.project/'.geoforge/receipts/model-runs').glob('*.json')}
    if adapter == 'api':
        with pytest.raises(api.ToolError, match=message): invoke(c, adapter, arguments, capsys, **kwargs)
    else:
        result, out, error = invoke(c, adapter, arguments, capsys)
        assert result == 3 and message in error, (result,out,error)
    assert not list(c.project.rglob('launched.json'))
    after = {str(p):p.read_bytes() for p in (c.project/'.geoforge/receipts/model-runs').glob('*.json')}
    assert after == before


@pytest.mark.parametrize('adapter', ['api','cli'])
@pytest.mark.parametrize('cwd', ['.', 'work'])
def test_exact_literal_args_resolved_cwd_and_host_approved_env_reach_child(tmp_path, monkeypatch, capsys, adapter, cwd):
    args = ['--receipt','outputs/receipt.json','--case','Gainesville']
    c = make_case(tmp_path, monkeypatch, command=args, cwd=cwd)
    monkeypatch.setenv('MODEL_SETTING', 'unapproved ambient value')
    result = invoke(c,adapter,args,capsys, **({'cwd':cwd,'env':{'MODEL_SETTING':'unapproved request'}} if adapter=='api' else {}))
    assert result[0] == 0 if adapter=='cli' else result.startswith('exit_code=0')
    observed = json.loads((c.project/cwd/'launched.json').read_text())
    assert observed == {'argv':args,'cwd':str((c.project/cwd).resolve()),'env':'approved'}
    docs = [json.loads(p.read_text(encoding='utf-8')) for p in (c.project/'.geoforge/receipts/model-runs').glob('*.json')]
    assert len(docs)==1 and c.flow.flow.receipts.verify(c.project,docs[0])
    assert c.flow.flow.plan.invocation_receipt_errors(c.step,c.project,docs[0])==[]


@pytest.mark.parametrize('adapter', ['api','cli'])
@pytest.mark.parametrize('actual', [[], ['--case','Gainesville'], ['--receipt','other.json','--case','Gainesville'],
    ['--case','Gainesville','--receipt','outputs/receipt.json'],
    ['--receipt','outputs/receipt.json','--case','Gainesville','--extra'], ['--help']])
def test_missing_receipt_empty_reordered_extra_or_changed_args_never_launch(tmp_path, monkeypatch, capsys, adapter, actual):
    c=make_case(tmp_path,monkeypatch,command=['--receipt','outputs/receipt.json','--case','Gainesville'])
    assert_denied(c,adapter,actual,capsys)


@pytest.mark.parametrize('adapter',['api','cli'])
def test_explicit_empty_args_are_not_legacy(tmp_path,monkeypatch,capsys,adapter):
    c=make_case(tmp_path,monkeypatch,command=[])
    assert_denied(c,adapter,['--extra'],capsys)
    result=invoke(c,adapter,[],capsys)
    assert result[0]==0 if adapter=='cli' else result.startswith('exit_code=0')


@pytest.mark.parametrize('adapter',['api','cli'])
def test_absent_command_retains_legacy_argument_semantics(tmp_path,monkeypatch,capsys,adapter):
    c=make_case(tmp_path,monkeypatch)
    result=invoke(c,adapter,['--legacy','value'],capsys)
    assert result[0]==0 if adapter=='cli' else result.startswith('exit_code=0')


def test_api_cwd_must_match_explicit_binding_even_when_args_match(tmp_path,monkeypatch,capsys):
    c=make_case(tmp_path,monkeypatch,command=[],cwd='work')
    assert_denied(c,'api',[],capsys,message='approved cwd')


def test_cwd_only_binding_keeps_legacy_args_but_enforces_directory(tmp_path,monkeypatch,capsys):
    c=make_case(tmp_path,monkeypatch,cwd='work')
    assert_denied(c,'api',['arbitrary'],capsys,message='approved cwd')
    assert invoke(c,'api',['arbitrary'],capsys,cwd='work').startswith('exit_code=0')


@pytest.mark.parametrize('bad',[None,'', 'python run.py', {}, [None], [1], ['x\0y'], ['${PROJECT}'], ['x']*101])
def test_malformed_explicit_command_rejected_at_plan_and_dispatch_boundary(tmp_path,monkeypatch,bad):
    c=make_case(tmp_path,monkeypatch)
    st=copy.deepcopy(c.step);st['command']=bad
    plan=copy.deepcopy(c.plan);plan['steps']=[st]
    assert any('command' in x for x in c.flow.flow.plan.validate(plan,c.inventory,['M'],{'M':c.root},project=c.project))
    with pytest.raises(ValueError,match='command'):
        c.flow.flow.plan.require_step_invocation(st,c.project,[],c.project)


@pytest.mark.parametrize('bad',[None,'', '../outside','C:relative','${PROJECT}', 'x\0y'])
def test_malformed_or_unconfined_cwd_rejected(tmp_path,monkeypatch,bad):
    c=make_case(tmp_path,monkeypatch)
    st={**c.step,'command':[],'cwd':bad}
    assert c.flow.flow.plan.validate_step_invocation(st,c.project)


def test_alias_cwd_cannot_escape_project(tmp_path,monkeypatch):
    c=make_case(tmp_path,monkeypatch);outside=tmp_path/'outside';outside.mkdir()
    (c.project/'alias').symlink_to(outside,target_is_directory=True)
    assert c.flow.flow.plan.validate_step_invocation({**c.step,'cwd':'alias'},c.project)


@pytest.mark.parametrize('typed',['project_data_tool','calibration'])
def test_specialized_invocation_contracts_remain_their_own_authority(tmp_path,monkeypatch,typed):
    c=make_case(tmp_path,monkeypatch)
    assert c.flow.flow.plan.step_invocation({**c.step,typed:{},'command':None,'cwd':None},c.project)==(None,None)


@pytest.mark.parametrize('native',[False,True])
@pytest.mark.parametrize('change',['none','omitted','extra','tool','interpreter','cwd','command-type'])
def test_authentic_receipt_shape_must_match_explicit_invocation(tmp_path,monkeypatch,native,change):
    c=make_case(tmp_path,monkeypatch,command=['--receipt','receipt.json'])
    command=([str(c.tool)] if native else [sys.executable,str(c.tool)])+c.step['command']
    receipt={'command':command,'executable':str(c.tool) if native else sys.executable,'cwd':str(c.project)}
    if change=='omitted':receipt['command']=command[:-2]
    elif change=='extra':receipt['command']=[*command,'--extra']
    elif change=='tool':receipt['command'][0 if native else 1]=str(c.root/'tools/other.py')
    elif change=='interpreter':receipt['command'][0]=str(tmp_path/'other-python.exe')
    elif change=='cwd':receipt['cwd']=str(c.project/'work')
    elif change=='command-type':receipt['command']=' '.join(command)
    errors=c.flow.flow.plan.invocation_receipt_errors(c.step,c.project,receipt)
    assert bool(errors)==(change!='none'), errors


def test_command_prefix_is_not_stripped_or_substituted(tmp_path,monkeypatch,capsys):
    c=make_case(tmp_path,monkeypatch,command=['--case','test'])
    assert_denied(c,'api',[sys.executable,str(c.tool),'--case','test'],capsys)
