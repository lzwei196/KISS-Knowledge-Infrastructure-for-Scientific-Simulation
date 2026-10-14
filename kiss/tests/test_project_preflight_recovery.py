"""Recovery is an explicit, authenticated choice after a real failed host check."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import (catalog, flowgate, flowrun, ki_guard, obs_access, paths,
                      project_paths, project_verification, setup as setup_flow)
from kiss_cli.manifest import Manifest


@pytest.fixture
def failed_case(tmp_path, monkeypatch):
    monkeypatch.setenv('GEOFORGE_FLOW_KEYS', str(tmp_path / 'keys'))
    project = tmp_path / 'project--0123456789ab'
    root = project / 'models/M/ki'
    (root / 'tools').mkdir(parents=True)
    (project / 'inputs').mkdir()
    passing_flag = project / 'inputs/runtime-ready.flag'
    (root / 'SKILL.md').write_text('# M\nA tiny real host preflight fixture.\n', encoding='utf-8')
    (root / 'dag.yaml').write_text('outputs:\n- var: result\n  validation_rank: 1\n  unit: 1\n', encoding='utf-8')
    (root / 'tools/run.py').write_text("raise RuntimeError('scientific execution must not occur in recovery tests')\n", encoding='utf-8')
    (root / 'preflight_check.py').write_text(
        'import json\nfrom pathlib import Path\n'
        f'ready = Path({str(passing_flag)!r}).is_file()\n'
        "print('PREFLIGHT_REPORT=' + json.dumps({'model_id': 'M', 'checks': ["
        "{'kind': 'data', 'subject': 'fixture runtime readiness flag', 'critical': True, "
        "'status': 'pass' if ready else 'fail', 'fix': 'Place the runtime readiness flag'}]}))\n"
        'raise SystemExit(0 if ready else 1)\n', encoding='utf-8')
    ki_guard.enroll(root)
    shared = paths.KissConfig.default(tmp_path / 'shared/M')
    shared.python = sys.executable
    cfg = project_paths.model_config(project, 'M', shared)
    (root.parent / paths.CONFIG_NAME).write_text(cfg.dumps(), encoding='utf-8')
    ki = catalog.KI('M', root)
    manifest = Manifest.stub_for(ki)
    flow = flowgate.load()
    plan = {'schema_version': '1.0', 'goal': 'Run fixture M only after host verification',
            'selected_kis': ['M'], 'created_at': 'fixture', 'unresolved_questions': [],
            'coupling': [], 'scientific_choices': [],
            'steps': [{'id': 'M:run', 'ki': 'M', 'kind': 'run',
                       'tool': str(root / 'tools/run.py'), 'inputs': [],
                       'outputs': [], 'status': 'planned'}]}
    inventory = {'schema_version': '1.0', 'items': []}
    assert flow.plan.validate(plan, inventory, ['M'], {'M': root}) == []
    flow.plan.write_artifacts(project, plan, inventory)
    approval = flow.approval.approve(project, by='user')
    ctx = flow.states.FlowContext.load(project)
    ctx.selected_kis = ['M']
    ctx.state = flow.states.State.SETUP_RUNNING
    ctx.save()
    result = project_verification.verify(project, ki, manifest)
    assert result['state'] == 'failed'
    assert result['receipt']['checks'][0]['evidence']['launch_attempted'] is True
    assert result['receipt']['checks'][0]['evidence']['returncode'] == 1
    monkeypatch.setattr(obs_access.Client, 'download', lambda *a, **kw: pytest.fail('recovery must not download'))
    monkeypatch.setattr(flowrun, 'wrapper_commands', lambda: {})
    flowrun.project_setup_failed(project, [ki], 'Fixture runtime readiness flag is absent')
    return SimpleNamespace(project=project, ki=ki, cfg=cfg, manifest=manifest, flow=flow,
                           plan=plan, inventory=inventory, passing_flag=passing_flag,
                           approval_id=flow.approval.approval_id(approval))


def _pre(c, *, action=None, pending=None, text='continue'):
    return flowrun.pre(c.project, text, ['M'], [c.ki], action, pending, setup_ok=False)


def _attempts(c):
    return sorted((c.project / '.geoforge/preflight').glob('*/execution.json'))


def _card(c):
    card = setup_flow.request(c.project, archive_obsolete=False)
    assert card and card['id'].startswith(flowrun.PROJECT_PREFLIGHT_REQUEST_ID_PREFIX)
    return card


def _choice(c, option='revise', *, pending=None):
    card = _card(c)
    return _pre(c, action={'request_id': card['id'], 'option_id': option},
                pending=card if pending is None else pending)


def _no_scientific_evidence(c):
    assert not list((c.project / '.geoforge/receipts/model-runs').glob('*.json'))
    assert not list((c.project / '.geoforge/receipts/data-receipts').glob('*.json'))


def test_real_failed_preflight_issues_signed_explicit_recovery_card(failed_case):
    c = failed_case
    card = _card(c)
    assert [row['id'] for row in card['options']] == ['revise', 'retry']
    assert card['status'] == 'waiting'
    assert flowrun.current_state(c.project) == 'SETUP_REQUIRED'
    record = json.loads((c.project / '.geoforge/project-preflight-recovery.json').read_text(encoding='utf-8'))
    assert c.flow.receipts.verify(c.project, record)
    assert record['request_id'] == card['id']
    assert record['context']['approval_id'] == c.approval_id
    assert record['context']['failed_checks'][0]['attempt_id'] == project_verification.status(c.project, c.ki)['receipt']['attempt_id']
    assert len(_attempts(c)) == 1
    assert not project_verification.status(c.project, c.ki)['can_run']
    _no_scientific_evidence(c)


def test_repeated_text_and_lazy_card_recovery_never_retry_checks(failed_case, monkeypatch):
    c = failed_case
    before = _attempts(c)
    monkeypatch.setattr(project_verification, 'verify', lambda *a, **kw: pytest.fail('text must not rerun preflight'))
    (c.project / setup_flow.REQUEST_FILE).unlink()
    (c.project / '.geoforge/project-preflight-recovery.json').unlink()
    first = _pre(c)
    assert first.message and not first.replan_reason
    card = _card(c)
    for text in ('continue', 'find the missing input', 'retry', 'revise'):
        reply = _pre(c, text=text)
        assert reply.message and not reply.replan_reason
        assert _card(c)['id'] == card['id']
    assert _attempts(c) == before
    assert c.flow.approval.approval_id(c.flow.approval.read(c.project)) == c.approval_id
    _no_scientific_evidence(c)


@pytest.mark.parametrize('kind,provider', [('api', 'deepseek'), ('cli', 'claude'),
                                          ('cli', 'codex'), ('cli', 'kimi')])
def test_revise_enters_restricted_planning_and_requires_new_approval(failed_case, kind, provider):
    c = failed_case
    initial_attempts = _attempts(c)
    pre = _choice(c)
    assert pre.message is None and pre.replan_reason
    assert flowrun.current_state(c.project) == 'REPLAN_REQUIRED'
    assert c.flow.approval.check(c.project) == 'MISSING'
    assert setup_flow.request(c.project, archive_obsolete=False) is None
    turn = flowrun.turn(c.project, [c.ki], c.cfg, kind, provider, None,
                        c.plan['goal'], pre.replan_reason, database_access_mode='off')
    assert turn.kind == 'planning' and turn.execute is False
    assert turn.policy.state is c.flow.states.State.REPLAN_REQUIRED
    for capability in ('DOWNLOAD', 'RUN_MODEL', 'RUN_SETUP', 'COMPILE', 'WRITE_PROJECT'):
        assert not c.flow.states.allowed(turn.policy.state, getattr(c.flow.states.Capability, capability))
    assert c.flow.states.allowed(turn.policy.state, c.flow.states.Capability.WRITE_PLAN_FILES)
    if kind == 'api':
        for tool in ('fetch_data', 'run_preflight', 'run_ki_tool', 'run_setup_command'):
            assert not c.flow.policy.api_tool_allowed(turn.policy.state, tool)
    if provider in ('codex', 'kimi'):
        assert turn.planning_worktree and turn.planning_worktree != c.project
        assert not (turn.planning_worktree / 'runs/approval.json').exists()
    assert c.flow.approval.check(c.project) == 'MISSING'
    assert not project_verification.status(c.project, c.ki)['can_run']
    assert _attempts(c) == initial_attempts
    assert not (c.project / '.geoforge/acquisition.json').exists()
    _no_scientific_evidence(c)


def test_explicit_retry_performs_new_real_check_then_resumes_original_approval(failed_case):
    c = failed_case
    first_attempt = project_verification.status(c.project, c.ki)['receipt']['attempt_id']
    pre = _choice(c, 'retry')
    assert pre.message is None and not pre.replan_reason
    assert flowrun.current_state(c.project) == 'SETUP_REQUIRED'
    assert c.flow.approval.check(c.project) == 'OK'
    assert c.flow.approval.approval_id(c.flow.approval.read(c.project)) == c.approval_id
    assert len(_attempts(c)) == 1, 'the choice itself cannot claim a successful probe'
    turn = flowrun.setup_turn(c.project, [c.ki], c.cfg, 'api', 'deepseek', database_access_mode='off')
    assert turn.kind == 'setup'
    c.passing_flag.write_text('fixture runtime dependency now present', encoding='utf-8')
    result = project_verification.verify(c.project, c.ki, c.manifest)
    assert result['can_run'] and result['receipt']['attempt_id'] != first_attempt
    assert result['receipt']['checks'][0]['evidence']['returncode'] == 0
    assert len(_attempts(c)) == 2
    flowrun.setup_verified(c.project, [c.ki], c.cfg)
    assert flowrun.current_state(c.project) == 'EXECUTING'
    assert c.flow.approval.approval_id(c.flow.approval.read(c.project)) == c.approval_id
    assert c.flow.approval.check(c.project) == 'OK'
    _no_scientific_evidence(c)


@pytest.mark.parametrize('mutation', ['wrong_request', 'wrong_option', 'missing_option', 'wrong_pending'])
def test_malformed_or_stale_action_preserves_current_choice(failed_case, mutation):
    c = failed_case
    card = _card(c)
    action, pending = {'request_id': card['id'], 'option_id': 'revise'}, dict(card)
    if mutation == 'wrong_request':
        action['request_id'] += '-old'
    elif mutation == 'wrong_option':
        action['option_id'] = 'approve'
    elif mutation == 'missing_option':
        action.pop('option_id')
    else:
        pending['id'] += '-old'
    reply = _pre(c, action=action, pending=pending)
    assert reply.message and not reply.replan_reason
    assert _card(c)['id'] == card['id']
    assert flowrun.current_state(c.project) == 'SETUP_REQUIRED'
    assert c.flow.approval.check(c.project) == 'OK'
    assert len(_attempts(c)) == 1


@pytest.mark.parametrize('mutation', ['new_attempt', 'new_approval', 'revoked_approval', 'forged_receipt',
    'cancelled_receipt', 'pending_receipt', 'missing_receipt', 'empty_checks',
    'changed_ki', 'changed_config', 'forged_recovery'])
def test_stale_or_unauthentic_context_cannot_accept_old_choice(failed_case, mutation):
    c = failed_case
    card = _card(c)
    if mutation == 'new_attempt':
        assert project_verification.verify(c.project, c.ki, c.manifest)['state'] == 'failed'
    elif mutation == 'new_approval':
        c.flow.approval.approve(c.project, by='user')
    elif mutation == 'revoked_approval':
        c.flow.approval.revoke(c.project, 'fixture revocation')
    elif mutation == 'changed_ki':
        (c.ki.root / 'SKILL.md').write_text('# changed KI', encoding='utf-8')
    elif mutation == 'changed_config':
        c.cfg.python = str(c.project / 'different-python.exe')
        (c.ki.root.parent / paths.CONFIG_NAME).write_text(c.cfg.dumps(), encoding='utf-8')
    elif mutation == 'forged_recovery':
        path = c.project / '.geoforge/project-preflight-recovery.json'
        doc = json.loads(path.read_text(encoding='utf-8'))
        doc['context']['approval_id'] = 'forged'
        path.write_text(json.dumps(doc), encoding='utf-8')
    else:
        path = project_verification._receipt_path(c.project, 'M')
        doc = json.loads(path.read_text(encoding='utf-8'))
        if mutation == 'missing_receipt':
            path.unlink()
        elif mutation == 'forged_receipt':
            doc['attempt_id'] = 'forged'
            path.write_text(json.dumps(doc), encoding='utf-8')
        else:
            if mutation == 'empty_checks':
                doc['checks'] = []
            else:
                doc['state'] = mutation.removesuffix('_receipt')
            project_verification._write(c.project, 'M', doc)
    attempts = _attempts(c)
    reply = _pre(c, action={'request_id': card['id'], 'option_id': 'revise'}, pending=card)
    assert reply.message and not reply.replan_reason
    assert flowrun.current_state(c.project) == 'SETUP_REQUIRED'
    assert _card(c)['id'] == card['id']
    assert _attempts(c) == attempts
    _no_scientific_evidence(c)


@pytest.mark.parametrize('state', ['SETUP_RUNNING', 'EXECUTING', 'ACQUIRING'])
def test_busy_state_rejects_old_recovery_action(failed_case, state):
    c = failed_case
    card = _card(c)
    ctx = c.flow.states.FlowContext.load(c.project)
    ctx.state = c.flow.states.State(state)
    ctx.save()
    reply = _pre(c, action={'request_id': card['id'], 'option_id': 'retry'}, pending=card)
    assert reply.message and not reply.replan_reason
    assert flowrun.current_state(c.project) == state
    assert _card(c)['id'] == card['id']
    assert len(_attempts(c)) == 1


def test_unrelated_pending_request_is_not_overwritten(failed_case):
    c = failed_case
    unrelated = setup_flow.request_user(c.project, {'kind': 'choice', 'title': 'License choice',
        'message': 'An unrelated pending choice', 'options': [{'id': 'accept', 'label': 'Accept'}]})
    raw = (c.project / setup_flow.REQUEST_FILE).read_bytes()
    reply = _pre(c)
    assert reply.message and not reply.replan_reason
    assert (c.project / setup_flow.REQUEST_FILE).read_bytes() == raw
    assert setup_flow.request(c.project)['id'] == unrelated['id']
    assert c.flow.approval.check(c.project) == 'OK'
    assert len(_attempts(c)) == 1


def test_recreated_card_replaces_hardlink_without_modifying_external_file(failed_case, tmp_path):
    c = failed_case
    request_path = c.project / setup_flow.REQUEST_FILE
    request_path.unlink()
    external = tmp_path / 'unrelated-request.json'
    original = b'{"id":"old","status":"ready"}\n'
    external.write_bytes(original)
    os.link(external, request_path)
    assert os.path.samefile(external, request_path)
    reply = _pre(c)
    assert reply.message and _card(c)['status'] == 'waiting'
    assert external.read_bytes() == original
    assert not os.path.samefile(external, request_path)
    assert len(_attempts(c)) == 1


def test_revise_revokes_approval_before_state_transition_failure(failed_case, monkeypatch):
    c = failed_case
    card = _card(c)
    original_move = c.flow.states.FlowContext.move

    def fail_replan(self, event, *args, **kwargs):
        if event == 'replan':
            raise OSError('simulated state persistence failure')
        return original_move(self, event, *args, **kwargs)

    monkeypatch.setattr(c.flow.states.FlowContext, 'move', fail_replan)
    with pytest.raises(OSError, match='state persistence failure'):
        _choice(c, 'revise')
    assert c.flow.approval.check(c.project) == 'MISSING'
    assert flowrun.current_state(c.project) == 'SETUP_REQUIRED'
    assert _card(c)['id'] == card['id']
    assert not project_verification.status(c.project, c.ki)['can_run']
    assert len(_attempts(c)) == 1
    _no_scientific_evidence(c)
