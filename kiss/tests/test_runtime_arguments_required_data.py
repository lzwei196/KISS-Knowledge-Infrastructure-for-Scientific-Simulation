"""A verified runtime under home and exact support data reach both dispatchers.

The Python KI wrapper only records argv. Its native executable is a never-run
fixture, and the real preflight is harmless Python. No scientific model runs.
"""
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
import yaml

from kiss_cli import api, cli, flowgate, ki_guard, paths, project_paths, runtime_arguments
from kiss_cli import project_verification as pv
from kiss_cli.catalog import KI
from kiss_cli.manifest import Manifest


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setenv('GEOFORGE_FLOW_KEYS', str(tmp_path/'keys'))
    project=tmp_path/'project';root=project/'models/DSSAT/ki'
    (root/'tools').mkdir(parents=True);(project/'runs').mkdir()
    home=tmp_path/'saved-install';engine=home/'DSSAT/build/bin/dscsm048'
    engine.parent.mkdir(parents=True);engine.write_bytes(b'Native product fixture; never executed');engine.chmod(0o755)
    data=home/'DSSAT/Data';data.mkdir(parents=True)
    payload=b'! Official support table fixture\nA 1 2\n';(data/'TABLE.CDE').write_bytes(payload)
    contract={'version':1,'source':{'repo':'https://example.invalid/official.git','commit':'a'*40},
        'target':{'role':'home','path':'DSSAT/Data'},'files':[{'source':'Data/TABLE.CDE','path':'TABLE.CDE',
            'sha256':hashlib.sha256(payload).hexdigest(),'bytes':len(payload),'text_newlines':'lf_or_crlf'}]}
    (root/'SKILL.md').write_text('# Harmless exact runtime argument fixture\n')
    (root/'preflight_check.py').write_text("print('EXACT_PROJECT_PREFLIGHT')\n")
    (root/'kiss.yaml').write_text(yaml.safe_dump({'kiss_manifest_version':1,'model':'DSSAT','runtime_data':contract}))
    (root/'knowledge_infrastructure.yaml').write_text(yaml.safe_dump({'package':{'binary':{'path':str(engine)}}}))
    tool=root/'tools/record_args.py'
    tool.write_text("import json,sys\nfrom pathlib import Path\nPath('launched.json').write_text(json.dumps(sys.argv[1:]))\n")
    cfg=project_paths.model_config(project,'DSSAT',paths.KissConfig.default(home))
    cfg.python=sys.executable
    (root.parent/paths.CONFIG_NAME).write_text(cfg.dumps(),encoding='utf-8')
    (project/paths.CONFIG_NAME).write_text(project_paths.project_config(project,python=sys.executable).dumps(),encoding='utf-8')
    ki_guard.enroll(root);ki=KI('DSSAT',root)
    flow=flowgate.FlowSession.open(project,{'DSSAT':root},python=sys.executable)
    flow.move('task_received');flow.move('kis_resolved',{'selected_kis':['DSSAT']})
    plan={'schema_version':'1.0','goal':'Test exact verified runtime argv','created_at':'test','selected_kis':['DSSAT'],
        'unresolved_questions':[],'scientific_choices':[],'steps':[{'id':'DSSAT:run','ki':'DSSAT','tool':str(tool),
        'kind':'run','inputs':[],'outputs':[],'status':'planned'}]}
    assert flow.write_plan(plan,{'schema_version':'1.0','items':[]})==[]
    flow.flow.approval.approve(project,by='user');flow.reload_artifacts()
    flow.move('plan_written',{'plan_valid':True});flow.move('approved',{'approval':'OK'});flow.move('execution_started',{'setup_verified':True})
    result=pv.verify(project,ki,Manifest.load(root/'kiss.yaml'))
    assert result['can_run']
    assert result['receipt']['declared_runtime_bindings']=={str(engine):str(engine)}
    assert result['receipt']['runtime_data']['target_root']==str(data)
    assert not engine.is_relative_to(cfg.roles['binaries'])
    return SimpleNamespace(project=project,ki=ki,cfg=cfg,flow=flow,engine=engine,data=data,home=home,
                           receipt=result['receipt'],payload=payload,tool=tool)


def invoke(c,adapter,args,capsys):
    if adapter=='api':
        return api.execute_tool('run_ki_tool',{'tool_path':'tools/record_args.py','plan_step_id':'DSSAT:run','arguments':args},
            c.ki,c.cfg,project_mode=True,flow=c.flow)
    result=cli.main(['run-tool','--project',str(c.project),'--step','DSSAT:run','DSSAT','tools/record_args.py','--',*args])
    return result,capsys.readouterr().err


def denied(c,adapter,args,capsys):
    if adapter=='api':
        with pytest.raises(api.ToolError):invoke(c,adapter,args,capsys)
    else:
        result,error=invoke(c,adapter,args,capsys)
        assert result==3,error
    assert not (c.project/'launched.json').exists()
    assert not list((c.project/'.geoforge/receipts/model-runs').glob('*.json'))


@pytest.mark.parametrize('adapter',['api','cli'])
@pytest.mark.parametrize('form',['separate','equals'])
def test_verified_home_runtime_and_exact_data_reach_real_common_dispatch(case,adapter,form,capsys,monkeypatch):
    c=case;args=['--executable',str(c.engine),'--runtime-data',str(c.data)]
    if form=='equals':args=['--executable='+str(c.engine),'--runtime-data='+str(c.data)]
    before_engine=c.engine.read_bytes();before_data=(c.data/'TABLE.CDE').read_bytes()
    monkeypatch.setattr(pv.install,'run_preflight',lambda *a,**k:pytest.fail('Dispatch must reuse current proof'))
    result=invoke(c,adapter,args,capsys)
    assert result[0]==0 if adapter=='cli' else result.startswith('exit_code=0')
    assert json.loads((c.project/'launched.json').read_text())==args
    assert c.engine.read_bytes()==before_engine and (c.data/'TABLE.CDE').read_bytes()==before_data


@pytest.mark.parametrize('adapter',['api','cli'])
@pytest.mark.parametrize('kind',['positional-data','output-data','output-data-equals','data-parent','data-child',
    'data-file','data-wrong-flag','data-other-model','exe-directory','exe-output','undeclared-exe','declared-real-alias'])
def test_exact_capabilities_do_not_grant_external_tree_or_output_paths(case,adapter,kind,capsys):
    c=case
    sibling=c.engine.with_name('other.exe');sibling.write_bytes(b'Unverified');sibling.chmod(0o755)
    alias=c.home/'alias-data';alias.symlink_to(c.data,target_is_directory=True)
    args={'positional-data':[str(c.data)],'output-data':['--output',str(c.data)],
          'output-data-equals':['--output='+str(c.data)],'data-parent':['--runtime-data',str(c.data.parent)],
          'data-child':['--runtime-data',str(c.data/'Other')],'data-file':['--runtime-data',str(c.data/'TABLE.CDE')],
          'data-wrong-flag':['--data',str(c.data)],'data-other-model':['--vic-runtime-data',str(c.data)],
          'exe-directory':['--executable',str(c.engine.parent)],'exe-output':['--output',str(c.engine)],
          'undeclared-exe':['--executable',str(sibling)],'declared-real-alias':['--runtime-data',str(alias)]}[kind]
    denied(c,adapter,args,capsys)


@pytest.mark.parametrize('adapter',['api','cli'])
@pytest.mark.parametrize('damage',['missing-receipt','unsigned','missing-data','changed-data','new-representation',
    'data-alias','cfg-home','cfg-python','other-ki','missing-native'])
def test_current_signed_project_runtime_and_all_data_bytes_remain_mandatory(case,adapter,damage,capsys):
    c=case;receipt=pv._receipt_path(c.project,'DSSAT')
    if damage=='missing-receipt':receipt.unlink()
    elif damage=='unsigned':receipt.write_text(json.dumps({'state':'verified','ok':True}))
    elif damage=='missing-data':(c.data/'TABLE.CDE').unlink()
    elif damage=='changed-data':(c.data/'TABLE.CDE').write_bytes(c.payload.replace(b'A 1',b'A 9'))
    elif damage=='new-representation':(c.data/'TABLE.CDE').write_bytes(c.payload.replace(b'\n',b'\r\n'))
    elif damage=='data-alias':
        original=c.data.with_name('Data-original');c.data.rename(original);c.data.symlink_to(original,target_is_directory=True)
    elif damage=='cfg-home':
        c.cfg.roles['home']=c.home.parent/'another-model';(c.ki.root.parent/paths.CONFIG_NAME).write_text(c.cfg.dumps(),encoding='utf-8')
    elif damage=='cfg-python':
        c.cfg.python=str(c.home/'unverified-python.exe');(c.ki.root.parent/paths.CONFIG_NAME).write_text(c.cfg.dumps(),encoding='utf-8')
    elif damage=='other-ki':
        c.receipt['model']='VIC';receipt.write_text(json.dumps(c.flow.flow.receipts.sign(c.project,c.receipt)))
    else:c.engine.unlink()
    denied(c,adapter,['--executable',str(c.engine),'--runtime-data',str(c.data)],capsys)


@pytest.mark.parametrize('option',['--executable','--runtime-data'])
def test_project_data_tools_do_not_receive_runtime_argument_capabilities(case,option):
    c=case;target=c.engine if option=='--executable' else c.data
    with pytest.raises(ValueError,match='escapes'):
        runtime_arguments.validate(project=c.project,ki='DSSAT',ki_root=c.ki.root,cfg=c.cfg,
            arguments=[option,str(target)],cwd=c.project,allow_runtime=False)


def test_missing_runtime_data_contract_grants_no_directory_capability(case):
    c=case
    # A genuinely verified legacy KI, with its own fresh enrolment and receipt,
    # cannot borrow another model's support-data declaration.
    root=c.project/'models/Legacy/ki';root.mkdir(parents=True)
    (root/'SKILL.md').write_text('# Legacy without runtime data')
    (root/'kiss.yaml').write_text('kiss_manifest_version: 1\nmodel: Legacy\n')
    (root/'preflight_check.py').write_text("print('Legacy harmless preflight')")
    cfg=project_paths.model_config(c.project,'Legacy',paths.KissConfig.default(c.home));cfg.python=sys.executable
    (root.parent/paths.CONFIG_NAME).write_text(cfg.dumps(),encoding='utf-8');ki_guard.enroll(root)
    ki=KI('Legacy',root);assert pv.verify(c.project,ki,Manifest.load(root/'kiss.yaml'))['can_run']
    with pytest.raises(ValueError,match='escapes'):
        runtime_arguments.validate(project=c.project,ki='Legacy',ki_root=root,cfg=cfg,
            arguments=['--runtime-data',str(c.data)],cwd=c.project,allow_runtime=True)
