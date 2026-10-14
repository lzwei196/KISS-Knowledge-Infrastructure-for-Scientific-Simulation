"""A checked preflight final continues only still-approved missing work once."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import api, cli, execution, execution_continuation as ec, flowgate, flowrun
from kiss_cli import ki_guard, paths, project_verification, setup
from kiss_cli.catalog import KI
from kiss_cli.manifest import Manifest

PROV = api.ApiProvider(name='fixture', label='Fixture', wire='openai',
    base_url='https://invalid.example', env_key='FIXTURE_API_KEY', models={'x': 'x'}, default_model='x')


@pytest.fixture
def c(tmp_path, monkeypatch):
    monkeypatch.setenv('GEOFORGE_FLOW_KEYS', str(tmp_path / 'keys'))
    monkeypatch.setenv('GEOFORGE_FLOW_REGISTRY', str(tmp_path / 'registry'))
    monkeypatch.setenv('FIXTURE_API_KEY', 'fixture-only')
    project = tmp_path / 'project'; root = project / 'models/M/ki'
    (root / 'tools').mkdir(parents=True); (project / 'runs').mkdir()
    (root / 'SKILL.md').write_text('# Harmless test KI\n')
    (root / 'dag.yaml').write_text('outputs: []\n')
    (root / 'preflight_check.py').write_text("print('HARMLESS PREFLIGHT PASS')\n")
    for n in (1, 2):
        (root / f'tools/step{n}.py').write_text(
            "from pathlib import Path\nPath('outputs').mkdir(exist_ok=True)\n" +
            ("assert Path('outputs/one.csv').is_file()\n" if n == 2 else '') +
            f"Path('outputs/{'one' if n == 1 else 'two'}.csv').write_text('day,value\\n1,{n}\\n2,{n+2}\\n')\n")
    ki_guard.enroll(root); ki = KI('M', root)
    cfg = paths.KissConfig.default(project); cfg.python = sys.executable
    (project / paths.CONFIG_NAME).write_text(cfg.dumps(), encoding='utf-8')
    (root.parent / paths.CONFIG_NAME).write_text(cfg.dumps(), encoding='utf-8')
    assert project_verification.verify(project, ki, Manifest(model='M'))['ok']
    fs = flowgate.FlowSession.open(project, {'M': root}, python=sys.executable)
    fs.move('task_received'); fs.move('kis_resolved', {'selected_kis': ['M']})
    plan = {'schema_version': '1.0', 'goal': 'Run two harmless approved steps', 'created_at': 'fixture',
        'selected_kis': ['M'], 'unresolved_questions': [], 'scientific_choices': [],
        'steps': [{'id': 's1', 'ki': 'M', 'kind': 'model_run', 'tool': str(root / 'tools/step1.py'),
                   'command': [], 'cwd': '.', 'inputs': [], 'outputs': ['one'], 'status': 'planned'},
                  {'id': 's2', 'ki': 'M', 'kind': 'process', 'tool': str(root / 'tools/step2.py'),
                   'command': [], 'cwd': '.', 'inputs': ['one'], 'outputs': ['two'], 'status': 'planned'}]}
    inv = {'schema_version': '1.0', 'items': [
        {'id': n, 'local_paths': [f'outputs/{n}.csv'], 'status': 'missing'} for n in ('one', 'two')]}
    assert fs.write_plan(plan, inv) == []
    fs.flow.approval.approve(project, by='user'); fs.reload_artifacts()
    fs.move('plan_written', {'plan_valid': True}); fs.move('approved', {'approval': 'OK'})
    fs.move('execution_started', {'setup_verified': True})
    turn_id = execution.begin_turn(project)
    turn = flowrun.Turn(fs, True, '', True, SimpleNamespace(provider='api'), 'fixture',
                        kind='execution', provider_succeeded=True, started_at=1)
    return SimpleNamespace(project=project, root=root, cfg=cfg, ki=ki, fs=fs, turn=turn, turn_id=turn_id)


def run_step(c, step, provider='api'):
    if provider == 'api':
        return api.execute_tool('run_ki_tool', {'tool_path': f'tools/step{step}.py',
            'plan_step_id': f's{step}', 'arguments': []}, c.ki, c.cfg,
            project_mode=True, flow=c.fs)
    return cli.main(['run-tool', '--project', str(c.project), '--step', f's{step}',
        'M', f'tools/step{step}.py', '--'])


def scope(c, ticket=None, stopped=lambda: False):
    return ec.scoped(c.turn, ticket or ec.offer(c.turn), stopped=stopped, turn_id=c.turn_id)


def prose(text):
    return text, [], {'role': 'assistant', 'content': text}


def call(name, args):
    return '', [('call', name, args)], {'role': 'assistant', 'content': '', 'tool_calls': []}


@pytest.mark.parametrize('wire', ['openai', 'anthropic'])
def test_actual_provider_loop_preflight_final_then_bounded_native_chain(c, monkeypatch, wire):
    prov = api.ApiProvider(**{**PROV.__dict__, 'wire': wire})
    initial = iter([call('run_preflight', {}), prose('Preflight passed. Next I will run the case.')])
    method = '_anthropic_turn' if wire == 'anthropic' else '_openai_turn'
    monkeypatch.setattr(api, method, lambda *a, **k: next(initial))
    reply = ''.join(api.run(prov, c.ki, c.cfg, 'Approved project test', 'Run the approved case',
                          flow=c.fs, project_mode=True))
    assert 'Preflight passed' in reply
    assert not list((c.project / '.geoforge/receipts/model-runs').glob('*.json'))
    result = flowrun.after(c.project, c.turn, reply)
    assert result.execution_continuation['pending_ids'] == ['s1', 's2']
    guidance = ec.prompt(result.execution_continuation)
    assert 'additional numeric' in guidance and 'step1.py' in guidance
    turns = iter([call('run_ki_tool', {'tool_path': 'tools/step1.py', 'plan_step_id': 's1', 'arguments': []}),
                  call('run_ki_tool', {'tool_path': 'tools/step2.py', 'plan_step_id': 's2', 'arguments': []}),
                  prose('Both approved steps are complete.')])
    seen = []
    def provider(*args, **kwargs):
        seen.append(args[3][-1]); return next(turns)
    monkeypatch.setattr(api, method, provider)
    before = (c.project / 'runs/approval.json').read_bytes()
    with scope(c, result.execution_continuation):
        final = ''.join(api.run(prov, c.ki, c.cfg, 'Approved project test', guidance,
                             flow=c.fs, project_mode=True))
        assert c.fs.evidence()['receipts_verified']
        finished = flowrun.after(c.project, c.turn, final)
        assert finished.execution_continuation is None
    assert c.fs.state.value == 'COMPLETED' and len(seen) == 3
    assert before == (c.project / 'runs/approval.json').read_bytes()
    assert len(list((c.project / '.geoforge/receipts/model-runs').glob('*.json'))) == 2


@pytest.mark.parametrize('provider', ['api', 'cli'])
def test_current_pass_cannot_repeat_but_pending_step_runs_and_new_user_can_rerun(c, provider):
    run_step(c, 1, provider)
    ticket = ec.offer(c.turn)
    assert ticket['pending_ids'] == ['s2'] and ticket['passed_ids'] == ['s1']
    with scope(c, ticket):
        # Check admission twice like CLI; no one-use token is consumed here.
        for _ in range(2): c.fs.check_step_tool('s2', 'M', c.root / 'tools/step2.py')
        with pytest.raises(flowgate.FlowDenied, match='passed steps'):
            c.fs.check_step_tool('s1', 'M', c.root / 'tools/step1.py')
        assert run_step(c, 2, provider) != 3
        with pytest.raises(flowgate.FlowDenied, match='passed steps'):
            c.fs.check_step_tool('s2', 'M', c.root / 'tools/step2.py')
    with pytest.raises(flowgate.FlowDenied, match='already used'):
        c.fs.check_step_tool('s1', 'M', c.root / 'tools/step1.py')
    assert ec.offer(c.turn) is None
    execution.begin_turn(c.project)
    # Normal explicit new user turns keep the previous approved rerun semantics.
    assert c.fs.check_step_tool('s1', 'M', c.root / 'tools/step1.py')['id'] == 's1'


@pytest.mark.parametrize('kind', ['setup', 'auto', 'planning', 'readonly'])
def test_no_offer_outside_approved_execution(c, kind):
    c.turn.kind = kind
    assert ec.offer(c.turn) is None
    assert not (c.project / ec.MARKER).exists()


@pytest.mark.parametrize('failure', ['provider', 'limit', 'cancel', 'tool-error', 'question',
    'stop', 'revoked', 'runtime', 'ki', 'unreceipted', 'stale-output', 'failed-latest', 'missing-external'])
def test_blockers_never_offer_auto_continuation(c, failure):
    if failure == 'provider': c.turn.provider_succeeded = False
    elif failure in {'limit', 'cancel'}: c.fs.provider_succeeded = False
    elif failure == 'tool-error': c.fs.continuation_blocked = True
    elif failure == 'question':
        p = c.project / setup.REQUEST_FILE;p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({'status': 'waiting', 'kind': 'choice', 'title': 'Need a choice'}))
    elif failure == 'stop': execution.request_stop(c.project)
    elif failure == 'revoked': c.fs.flow.approval.revoke(c.project, 'fixture')
    elif failure == 'runtime':
        (c.root.parent / paths.CONFIG_NAME).write_text('invalid toml [[')
    elif failure == 'ki': (c.root / 'SKILL.md').write_text('Changed')
    elif failure == 'unreceipted':
        (c.project / 'outputs').mkdir();(c.project / 'outputs/extra.csv').write_text('1,2\n')
    elif failure in {'stale-output', 'failed-latest'}:
        run_step(c, 1)
        if failure == 'stale-output': (c.project / 'outputs/one.csv').write_text('TAMPER')
        else:
            path = next((c.project / '.geoforge/receipts/model-runs').glob('*.json'))
            doc = json.loads(path.read_text());doc['validation']['status'] = 'failed'
            path.write_text(json.dumps(c.fs.flow.receipts.sign(c.project, doc)))
    else:
        c.fs.plan['steps'][0]['inputs'] = ['external']
        c.fs.inventory['items'].append({'id': 'external', 'local_paths': ['inputs/missing.csv']})
        c.fs.flow.plan.write_artifacts(c.project, c.fs.plan, c.fs.inventory)
        c.fs.flow.approval.approve(c.project, by='user')
    assert ec.offer(c.turn) is None
    assert not (c.project / ec.MARKER).exists()


@pytest.mark.parametrize('change', ['approval', 'plan', 'runtime', 'question', 'new-input', 'stop'])
def test_ticket_revalidated_immediately_before_resume(c, change):
    ticket = ec.offer(c.turn)
    if change == 'approval': c.fs.flow.approval.revoke(c.project, 'fixture')
    elif change == 'plan':
        c.fs.plan['goal'] = 'Changed';c.fs.flow.plan.write_artifacts(c.project, c.fs.plan, c.fs.inventory)
    elif change == 'runtime': (c.root.parent / paths.CONFIG_NAME).write_text('invalid [[')
    elif change == 'question':
        p = c.project / setup.REQUEST_FILE;p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({'status': 'waiting', 'kind': 'other', 'title': 'Need input'}))
    elif change == 'new-input': execution.begin_turn(c.project)
    else: execution.request_stop(c.project)
    with pytest.raises(ValueError):
        with scope(c, ticket): pytest.fail('Changed context must not resume provider')


@pytest.mark.parametrize('damage', ['forged', 'linked', 'too-big'])
def test_invalid_marker_fails_closed(c, tmp_path, damage):
    path = c.project / ec.MARKER
    if damage == 'forged': path.write_text(json.dumps({'policy': ec.POLICY, 'state': 'active'}))
    elif damage == 'too-big': path.write_bytes(b' ' * (256 * 1024 + 1))
    else:
        outside = tmp_path / 'outside.json';outside.write_text('{}');path.symlink_to(outside)
    assert ec.offer(c.turn) is None
    with pytest.raises(flowgate.FlowDenied): c.fs.check_step_tool('s1', 'M', c.root / 'tools/step1.py')


def test_one_empty_continuation_final_cannot_create_second_scope(c):
    ticket = ec.offer(c.turn)
    with scope(c, ticket):
        assert ec.offer(c.turn) is None
    assert ec.offer(c.turn) is None
    with pytest.raises(ValueError):
        with scope(c, ticket): pytest.fail('Cannot reuse an already closed scope')


def test_exception_closes_only_its_owned_scope(c):
    with pytest.raises(RuntimeError):
        with scope(c): raise RuntimeError('provider failure')
    assert ec._read(c.project)['state'] == 'closed'


@pytest.mark.parametrize('drift', ['runtime', 'approval', 'question', 'passed-output'])
def test_current_scope_rechecks_each_launch(c, drift):
    with scope(c):
        if drift == 'runtime': (c.root.parent / paths.CONFIG_NAME).write_text('invalid [[')
        elif drift == 'approval': c.fs.flow.approval.revoke(c.project, 'fixture drift')
        elif drift == 'question':
            p = c.project / setup.REQUEST_FILE;p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({'status': 'waiting', 'kind': 'other', 'title': 'Need input'}))
        else:
            run_step(c, 1)
            (c.project / 'outputs/one.csv').write_text('tampered')
        with pytest.raises(flowgate.FlowDenied):
            c.fs.check_step_tool('s2' if drift == 'passed-output' else 's1', 'M',
                                 c.root / ('tools/step2.py' if drift == 'passed-output' else 'tools/step1.py'))


def test_cli_partial_root_view_rechecks_full_selected_scope(c):
    import shutil
    root2 = c.project / 'models/N/ki'
    shutil.copytree(c.root, root2)
    ki_guard.enroll(root2)
    (root2.parent / paths.CONFIG_NAME).write_text(c.cfg.dumps(), encoding='utf-8')
    assert project_verification.verify(c.project, KI('N', root2), Manifest(model='N'))['ok']
    c.fs.ki_roots['N'] = root2
    c.fs.ctx.selected_kis.append('N'); c.fs.ctx.save()
    c.fs.plan['selected_kis'].append('N')
    c.fs.flow.plan.write_artifacts(c.project, c.fs.plan, c.fs.inventory)
    c.fs.flow.approval.approve(c.project, by='user'); c.fs.reload_artifacts()
    with scope(c):
        assert run_step(c, 1, 'cli') == 0
        (root2 / 'SKILL.md').write_text('Changed second selected KI')
        assert run_step(c, 2, 'cli') == 3


@pytest.mark.parametrize('event', ['preflight-fail', 'tool-denial', 'tool-error', 'limit', 'stopped'])
def test_real_api_loop_failure_or_limit_cannot_request_continuation(c, monkeypatch, event):
    calls = [call('run_preflight' if event == 'preflight-fail' else 'read_ki_file', {})]
    if event != 'limit': calls.append(prose('I have finished checking.'))
    turns = iter(calls)
    monkeypatch.setattr(api, '_openai_turn', lambda *a, **k: next(turns))
    monkeypatch.setattr(api, 'execute_tool', lambda *a, **k: 'FAIL\nnot ready' if event == 'preflight-fail' else 'ERROR: fixture')
    handle = api.TurnHandle()
    if event == 'stopped': handle.stopped.set()
    ''.join(api.run(PROV, c.ki, c.cfg, 'system', 'task', flow=c.fs, project_mode=True,
        max_steps=1 if event == 'limit' else None, handle=handle,
        approve=(lambda *a: False) if event == 'tool-denial' else None))
    assert ec.offer(c.turn) is None


def test_real_cli_wrapper_refusal_blocks_vendor_success_final(c, monkeypatch):
    monkeypatch.setenv(execution.TURN_ID_ENV, c.turn_id)
    monkeypatch.setenv(execution.TURN_PROJECT_ENV, str(c.project))
    assert cli.main(['run-tool', '--project', str(c.project), '--step', 's1', 'M',
                     'tools/step1.py', '--', '--unapproved-argument']) == 3
    c.turn.policy.provider = 'codex'; c.turn.provider_succeeded = True
    result = flowrun.after(c.project, c.turn, 'I could not execute that command.')
    assert result.execution_continuation is None
    blocker = ec._read(c.project, blocker=True)
    assert blocker['exit_code'] == 3 and c.fs.flow.receipts.verify(c.project, blocker)
    assert not list((c.project / '.geoforge/receipts/model-runs').glob('*.json'))
    monkeypatch.delenv(execution.TURN_ID_ENV)
    monkeypatch.delenv(execution.TURN_PROJECT_ENV)
    c.turn_id = execution.begin_turn(c.project)
    assert ec.offer(c.turn) is not None


@pytest.mark.parametrize('owner', ['none', 'old-turn', 'other-project'])
def test_unrelated_cli_refusal_does_not_poison_current_turn(c, monkeypatch, owner):
    monkeypatch.delenv(execution.TURN_ID_ENV, raising=False)
    monkeypatch.delenv(execution.TURN_PROJECT_ENV, raising=False)
    if owner != 'none':
        monkeypatch.setenv(execution.TURN_ID_ENV, c.turn_id if owner == 'other-project' else 'old')
        monkeypatch.setenv(execution.TURN_PROJECT_ENV, str(c.project.parent if owner == 'other-project' else c.project))
    assert cli.main(['run-tool', '--project', str(c.project), '--step', 's1', 'M',
                     'tools/step1.py', '--', '--unapproved-argument']) == 3
    assert not (c.project / ec.BLOCKER).exists()
    monkeypatch.delenv(execution.TURN_ID_ENV, raising=False)
    monkeypatch.delenv(execution.TURN_PROJECT_ENV, raising=False)
    assert ec.offer(c.turn) is not None
