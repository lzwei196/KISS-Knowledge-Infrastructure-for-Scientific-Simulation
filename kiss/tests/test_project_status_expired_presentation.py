"""Presentation does not confuse expired authority with missing existing bytes."""
from copy import deepcopy
import os
from pathlib import Path
import pytest
from kiss_cli import project_status, flowgate
from .test_project_status_preflight import progress
from .test_project_status_render import fixture_data, evaluate


def test_completed_phase_with_expired_preflight_is_not_reported_as_new_failure():
    result=progress([{'name':'M','state':'stale','can_run':False}])
    assert result['status']=='failed'  # existing needs-attention UI, never ready
    assert result['saved_flow_completed'] is True
    assert result['preflight_currentness']=='stale'
    assert 'no longer current' in result['summary']
    assert 'earlier completion record' in result['summary']
    assert 'Latest project preflight did not pass' not in result['summary']
    assert not result['execution_complete'] and not result['science_complete']
    assert not result['ready_to_start'] and result['completion_scope'] is None


@pytest.mark.parametrize('state',['failed','cancelled'])
def test_real_latest_preflight_failure_keeps_failure_wording(state):
    result=progress([{'name':'M','state':state,'can_run':False}])
    assert result['preflight_currentness']=='failed'
    assert 'Latest project preflight did not pass' in result['summary']
    assert not result['execution_complete']


def test_runtime_staleness_does_not_override_unreadable_or_pending_user_request():
    rows=[{'name':'M','state':'stale','can_run':False}]
    assert 'unreadable' in progress(rows,errors=['fixture'])['summary']
    result=progress(rows,request={'title':'Choose inputs'})
    assert result['summary']=='Choose inputs' and not result['execution_complete']


@pytest.mark.parametrize('state',['EXECUTING','FAILED','COMPLETED'])
def test_raw_completion_record_never_confers_current_readiness(state):
    result=progress([{'name':'M','state':'stale','can_run':False}],state=state)
    assert result['saved_flow_completed']==(state=='COMPLETED')
    assert not result['execution_complete'] and not result['ready_to_start']


@pytest.mark.parametrize('mode',['file','missing','partial','empty','directory','absolute','escape','symlink','hardlink'])
def test_generated_item_presence_is_bounded_and_never_a_producer_receipt(tmp_path,monkeypatch,mode):
    monkeypatch.setenv('GEOFORGE_FLOW_KEYS',str(tmp_path/'keys'))
    p=tmp_path/'project';(p/'outputs').mkdir(parents=True)
    target=p/'outputs/result.json';target.write_bytes(b'{"retained":true}')
    outside=tmp_path/'private.json';outside.write_bytes(b'{"outside":true}')
    paths=['outputs/result.json']
    if mode=='missing':target.unlink()
    elif mode=='partial':paths.append('outputs/missing.json')
    elif mode=='empty':target.write_bytes(b'')
    elif mode=='directory':target.unlink();target.mkdir();(target/'child').write_text('data')
    elif mode=='absolute':paths=[str(outside)]
    elif mode=='escape':paths=['outputs/../../private.json']
    elif mode in {'symlink','hardlink'}:
        target.unlink()
        try:
            if mode=='symlink':target.symlink_to(outside)
            else:os.link(outside,target)
        except OSError as e:pytest.skip(str(e))
    plan={'selected_kis':['M'],'steps':[{'id':'run','ki':'M','kind':'run','tool':'tools/run.py','inputs':[],'outputs':['result']}]}
    inventory={'items':[{'id':'result','status':'resolved','required_by':['M'],'local_paths':paths,'agent_resolvable':True,'needs_user':False}]}
    proof={'steps_passed':[],'stale_steps':['run'],'receipts_verified':False,'validation':'failed'}
    before=deepcopy((plan,inventory,proof))
    data=project_status._plan_data(p,flowgate.load(),plan,inventory,proof,None,{},[])
    row=data['items'][0]
    assert row['status']==('present_unverified' if mode=='file' else 'pending')
    assert row['evidence_source']==('local_files' if mode=='file' else 'project_inventory')
    assert row['scientific_validation']=='pending'
    assert (plan,inventory,proof)==before
    assert outside.read_bytes()==b'{"outside":true}'


@pytest.mark.parametrize('zh',[False,True])
def test_real_renderer_shows_existing_unverified_files_and_stale_summary(zh):
    data=fixture_data();data['project_status']['progress']=progress([{'name':'M','state':'stale','can_run':False}])
    data['plan_data']={'total':1,'counts':{'present_unverified':1},'items':[{'id':'native_output','group':'run','how':'generated','status':'present_unverified'}]}
    data['project_status']['data_summary']=project_status._data_summary(data['plan_data'])
    html=evaluate(data,zh=zh)['html']
    assert ('文件存在，尚未核实' if zh else 'Present; not verified') in html
    assert 'no longer current' in html and 'earlier completion record' in html
    assert 'Latest project preflight did not pass' not in html
    assert 'Ready to continue' not in html


@pytest.mark.parametrize('state',['FAILED','FAILED_VALIDATION'])
def test_expired_preflight_preserves_explicit_failed_flow_headline(state):
    result=progress([{'name':'M','state':'stale','can_run':False}],state=state,
                    proof={'validation':'failed','receipts_verified':False})
    assert result['summary'].startswith('Flow records a failed attempt; inspect its details.')
    assert 'no longer current' in result['summary']
    assert result['preflight_currentness']=='stale'
    assert not result['execution_complete'] and not result['ready_to_start']


def test_expired_proof_failure_does_not_invent_a_failed_execution():
    result=progress([{'name':'M','state':'stale','can_run':False}],
                    proof={'validation':'failed','receipts_verified':False,
                           'stale_steps':['native_run']})
    assert 'earlier completion record' in result['summary']
    assert not result['summary'].startswith('Flow records a failed attempt')
    assert 'An execution attempt failed' not in result['summary']
    assert not result['execution_complete'] and not result['ready_to_start']
