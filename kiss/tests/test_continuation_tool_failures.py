"""Inspection failures cannot poison one otherwise-safe host continuation."""
import json

import pytest

from kiss_cli import api, execution, execution_continuation as ec, provider_diagnostics, setup
from .test_execution_continuation import PROV, c, call, prose, scope


@pytest.mark.parametrize('tool', [
    'read_ki_file', 'list_ki_files', 'search_diagnostics', 'list_skills', 'read_skill',
    'list_project_files', 'read_project_file', 'list_work_files', 'read_work_file',
    'search_catalogue', 'describe_dataset',
])
def test_explicit_inspection_errors_are_not_execution_failures(tool):
    assert ec.tool_result_blocker(tool, 'ERROR: unavailable inspection') is None
    assert ec.tool_result_blocker(tool, 'DENIED by the user') == 'tool_denied'
    assert ec.tool_result_blocker(tool, 'ordinary result', user_denied=True) == 'user_denied'


@pytest.mark.parametrize('tool', ['run_ki_tool', 'run_project_data_tool', 'run_calibration',
    'run_setup_command', 'run_builtin_setup', 'fetch_data', 'write_project_file',
    'write_project_data_tool', 'request_user_action', 'estimate_clip', 'estimate_preparation',
    'read_future_mutating_tool', 'unknown_tool'])
def test_other_failed_tools_stay_blocking(tool):
    assert ec.tool_result_blocker(tool, 'ERROR: failed') == 'tool_error'


def test_failed_preflight_and_unrecognized_name_fail_closed():
    assert ec.tool_result_blocker('run_preflight', 'FAIL\nnot ready') == 'preflight_failed'
    assert ec.tool_result_blocker('run_preflight', 'ERROR: not ready') == 'tool_error'
    assert ec.tool_result_blocker(['read_ki_file'], 'ERROR: bad name') == 'tool_error'


def provider_turns(c, monkeypatch, turns, *, wire='openai', approve=None):
    replies = iter(turns)
    method = '_anthropic_turn' if wire == 'anthropic' else '_openai_turn'
    monkeypatch.setattr(api, method, lambda *a, **k: next(replies))
    provider = api.ApiProvider(**{**PROV.__dict__, 'wire': wire})
    return ''.join(api.run(provider, c.ki, c.cfg, 'Harmless fixture', 'Approved work',
        flow=c.fs, project_mode=True, approve=approve))


def diagnostics(c):
    return [json.loads(row) for row in (c.project / provider_diagnostics.LOG).read_text(
        encoding='utf-8').splitlines()]


@pytest.mark.parametrize('wire', ['openai', 'anthropic'])
def test_real_read_error_then_final_gets_only_one_bounded_continuation(c, monkeypatch, wire):
    # The real dispatcher raises ToolError for this absent optional KI file.
    provider_turns(c, monkeypatch, [
        call('read_ki_file', {'path': 'tools/optional_missing.py'}),
        call('read_ki_file', {'path': 'SKILL.md'}),
        prose('Inspection ended before running the approved steps.')], wire=wire)
    assert c.fs.continuation_blocked is False
    ticket = ec.offer(c.turn)
    assert ticket['pending_ids'] == ['s1', 's2']
    assert any(r.get('event') == 'tool_result' and r.get('tool') == 'read_ki_file'
               and r.get('error', '').startswith('ERROR:') and not r['blocked']
               for r in diagnostics(c))
    with scope(c, ticket):
        provider_turns(c, monkeypatch, [prose('Still no execution.')], wire=wire)
        assert ec.offer(c.turn) is None
    assert ec.offer(c.turn) is None
    assert ec._read(c.project)['state'] == 'closed'
    assert not list((c.project / '.geoforge/receipts/model-runs').glob('*.json'))
    assert diagnostics(c)[-1]['reason'] == 'continuation_already_used'


def test_read_error_continuation_can_run_only_the_existing_approved_dummy_steps(c, monkeypatch):
    provider_turns(c, monkeypatch, [call('read_project_file', {'path': 'inputs/optional.txt'}),
                                  prose('No work done yet.')])
    ticket = ec.offer(c.turn)
    approval = (c.project / 'runs/approval.json').read_bytes()
    with scope(c, ticket):
        provider_turns(c, monkeypatch, [
            call('run_ki_tool', {'tool_path': 'tools/step1.py', 'plan_step_id': 's1', 'arguments': []}),
            call('run_ki_tool', {'tool_path': 'tools/step2.py', 'plan_step_id': 's2', 'arguments': []}),
            prose('The two harmless fixture steps ran.')])
        assert c.fs.evidence()['steps_missing'] == []
        assert c.fs.evidence()['receipts_verified']
        assert ec.offer(c.turn) is None
    assert (c.project / 'runs/approval.json').read_bytes() == approval
    assert len(list((c.project / '.geoforge/receipts/model-runs').glob('*.json'))) == 2
    assert diagnostics(c)[-1]['reason'] == 'no_pending_steps'


def test_real_dispatch_denial_remains_sticky_after_successful_and_failed_reads(c, monkeypatch):
    provider_turns(c, monkeypatch, [
        call('run_ki_tool', {'tool_path': 'tools/step1.py', 'plan_step_id': 's1',
                             'arguments': ['--unapproved']}),
        call('read_ki_file', {'path': 'tools/optional_missing.py'}),
        call('read_ki_file', {'path': 'SKILL.md'}),
        prose('An execution attempt was refused.')])
    assert c.fs.continuation_blocked is True
    assert ec.offer(c.turn) is None
    assert not list((c.project / '.geoforge/receipts/model-runs').glob('*.json'))
    assert diagnostics(c)[-1]['reason'] == 'snapshot_rejected'


def test_explicit_user_denied_read_still_blocks(c, monkeypatch):
    provider_turns(c, monkeypatch, [call('read_ki_file', {'path': 'SKILL.md'}),
                                  prose('The user refused this read.')], approve=lambda *a: False)
    assert c.fs.continuation_blocked is True
    assert ec.offer(c.turn) is None


@pytest.mark.parametrize('blocker', ['question', 'stop', 'revoked', 'preflight', 'missing_input'])
def test_nonblocking_read_error_never_overrides_current_authority(c, monkeypatch, blocker):
    provider_turns(c, monkeypatch, [call('read_ki_file', {'path': 'tools/optional_missing.py'}),
                                  prose('Waiting.')])
    assert c.fs.continuation_blocked is False
    if blocker == 'question':
        (c.project / setup.REQUEST_FILE).write_text(json.dumps({'status': 'waiting',
            'kind': 'choice', 'title': 'A required user decision'}), encoding='utf-8')
    elif blocker == 'stop':
        execution.request_stop(c.project)
    elif blocker == 'revoked':
        c.fs.flow.approval.revoke(c.project, 'User revised the plan')
    elif blocker == 'preflight':
        (c.root / 'SKILL.md').write_text('A changed KI makes preflight stale', encoding='utf-8')
    else:
        c.fs.plan['steps'][0]['inputs'] = ['required']
        c.fs.inventory['items'].append({'id': 'required', 'local_paths': ['inputs/required.csv']})
        c.fs.flow.plan.write_artifacts(c.project, c.fs.plan, c.fs.inventory)
        c.fs.flow.approval.approve(c.project, by='user')
    assert ec.offer(c.turn) is None
    assert diagnostics(c)[-1]['reason'] == 'snapshot_rejected'


def test_failed_execution_receipt_blocks_even_without_error_text(c, monkeypatch):
    monkeypatch.setattr(execution, 'run_process', lambda *a, **k:
        execution.ProcessRun('failed', 1, stderr='Dummy execution failed', process_started=True))
    provider_turns(c, monkeypatch, [
        call('run_ki_tool', {'tool_path': 'tools/step1.py', 'plan_step_id': 's1', 'arguments': []}),
        call('read_ki_file', {'path': 'tools/optional_missing.py'}),
        prose('Execution failed.')])
    receipts = list((c.project / '.geoforge/receipts/model-runs').glob('*.json'))
    assert len(receipts) == 1
    assert json.loads(receipts[0].read_text())['validation']['status'] == 'failed'
    assert ec.offer(c.turn) is None


def test_offer_logging_failure_never_changes_authority(c, monkeypatch):
    monkeypatch.setattr(provider_diagnostics, 'record', lambda *a, **k: (_ for _ in ()).throw(OSError('disk full')))
    assert ec.offer(c.turn)['pending_ids'] == ['s1', 's2']
    execution.request_stop(c.project)
    assert ec.offer(c.turn) is None


@pytest.mark.parametrize('kind,success,expected', [
    ('planning', True, 'not_execution_turn'),
    ('execution', False, 'provider_failed'),
    ('execution', None, 'provider_not_succeeded'),
])
def test_offer_records_bounded_suppression_codes(c, kind, success, expected):
    c.turn.kind = kind
    c.turn.provider_succeeded = success
    assert ec.offer(c.turn) is None
    assert diagnostics(c)[-1]['reason'] == expected
    assert diagnostics(c)[-1]['blocked'] is True


def test_snapshot_rejection_records_redacted_diagnostic_not_raw_authority_data(c, monkeypatch):
    secret = 'gfd_' + 'x' * 30
    def rejected(_fs):
        raise ValueError('unavailable token=' + secret + ' https://invalid.example/?secret=' + secret)
    monkeypatch.setattr(ec, '_snapshot', rejected)
    assert ec.offer(c.turn) is None
    row = diagnostics(c)[-1]
    assert row['reason'] == 'snapshot_rejected'
    assert secret not in row['error'] and 'invalid.example' not in row['error']
    assert '[redacted' in row['error']
    assert 'arguments' not in row and 'prompt' not in row
