"""The Setup-page action checks an existing exact project, never shared setup."""
import json
from pathlib import Path

import pytest

from kiss_cli import gui, install, ki_guard, paths, project_verification, sessions, setup_jobs
from .test_project_readiness_shared_provenance import build_case, assert_old_shared_preserved
from .test_runtime_data_project_retry import prepared_project


def case(tmp_path, monkeypatch, **kwargs):
    c = build_case(tmp_path, monkeypatch, **kwargs)
    c.working, c.cfg = c.handler._session_workspace(c.project, c.ki)
    c.sid = '5' * 12
    monkeypatch.setattr(sessions, 'load', lambda root, sid: {'id': sid, 'models': ['Demo']} if sid == c.sid else None)
    monkeypatch.setattr(sessions, 'project_path', lambda *args: c.project)
    c.responses = []
    c.handler._json = lambda body, status=200: c.responses.append((status, body))
    c.handler._open_stream = lambda: None
    c.handler._end_stream = lambda: None
    c.handler._chunk = lambda text: c.messages.append(text) or True
    with gui._LIVE_AGENT_RUNS_LOCK:
        gui._LIVE_AGENT_RUNS.pop(c.sid, None)
    return c


def run(c):
    c.handler._stream_setup_project_preflight({'model': 'Demo', 'session': c.sid})


def test_setup_page_checks_existing_project_without_shared_writes_or_flow_resume(tmp_path, monkeypatch):
    c = case(tmp_path, monkeypatch)
    before = {p.relative_to(c.project): p.read_bytes() for p in c.project.rglob('*') if p.is_file()}
    monkeypatch.setattr(c.handler, '_session_workspace', lambda *a, **k: pytest.fail('Must not rematerialize'))
    monkeypatch.setattr(c.handler, '_config', lambda *a, **k: pytest.fail('Must not resolve fallback runtime'))
    run(c)
    assert not c.responses
    report = project_verification.status(c.project, c.working)
    assert report['can_run']
    assert 'EXACT_PROJECT_PREFLIGHT_EXECUTED' in report['receipt']['checks'][0]['detail']
    assert report['receipt']['checks'][0]['evidence']['source_root'] == str(c.working.root)
    assert_old_shared_preserved(c)
    assert not c.transitions  # no approval, setup_verified, plan execution, or provider
    for relative, data in before.items():
        assert (c.project / relative).read_bytes() == data
    assert setup_jobs.status(c.handler.workroot, 'Demo') is None
    ui = c.handler._setup_project_preflight_state(c.ki, c.sid)
    assert ui['software']['can_run'] and ui['job']['state'] == 'completed'
    assert ui['project_preflight']['can_check'] and ui['request'] is None
    monkeypatch.setattr(install, 'run_preflight', lambda *a, **k: pytest.fail('GET must not execute'))
    assert c.handler._setup_project_preflight_state(c.ki, c.sid)['software']['can_run']


@pytest.mark.parametrize('failure', ['preflight', 'coupled', 'requirements'])
def test_real_project_failure_does_not_touch_shared_readiness(tmp_path, monkeypatch, failure):
    c = case(tmp_path, monkeypatch, passed=failure != 'preflight', coupled=failure == 'coupled', requirements=failure == 'requirements')
    run(c)
    assert not c.responses and not project_verification.status(c.project, c.working)['can_run']
    assert c.handler._setup_project_preflight_state(c.ki, c.sid)['job']['state'] == 'failed'
    assert_old_shared_preserved(c)


@pytest.mark.parametrize('damage', ['project-ki', 'config', 'python', 'helper', 'shared-python', 'shared-home', 'missing-project'])
def test_bad_project_or_runtime_never_falls_back_to_shared_setup(tmp_path, monkeypatch, damage):
    c = case(tmp_path, monkeypatch)
    if damage == 'project-ki':
        (c.working.root / 'preflight_check.py').write_text('Changed')
    elif damage == 'config':
        (c.working.root.parent / 'kiss.toml').write_text('broken [[')
    elif damage == 'python':
        c.cfg.python = str(tmp_path / 'missing.exe')
        (c.working.root.parent / 'kiss.toml').write_text(c.cfg.dumps(), encoding='utf-8')
    elif damage == 'helper':
        (c.cfg.roles['ki_tools_common'] / 'ki_tools_common/__init__.py').write_text('Changed')
    elif damage == 'shared-python':
        c.shared.python = str(tmp_path / 'missing.exe')
        (c.shared.root / 'kiss.toml').write_text(c.shared.dumps(), encoding='utf-8')
    elif damage == 'shared-home':
        c.shared.roles['home'] = tmp_path / 'other-home'
        (c.shared.root / 'kiss.toml').write_text(c.shared.dumps(), encoding='utf-8')
    else:
        (c.working.root.parent / 'kiss.toml').unlink()
    monkeypatch.setattr(install, 'run_preflight', lambda *a, **k: pytest.fail('Invalid binding must not launch'))
    run(c)
    assert c.responses[-1][0] == 400
    assert not c.transitions


@pytest.mark.parametrize('payload', [{}, {'model': 'Demo', 'session': 'bad'}, {'model': 'Demo', 'session': '6'*12}, {'model': 'Other', 'session': '5'*12}])
def test_invalid_session_or_model_cannot_fall_back(tmp_path, monkeypatch, payload):
    c = case(tmp_path, monkeypatch)
    monkeypatch.setattr(install, 'run_preflight', lambda *a, **k: pytest.fail('Must not launch'))
    c.handler._stream_setup_project_preflight(payload)
    assert c.responses[-1][0] == 400


def test_project_operation_and_shared_setup_leases_prevent_overlap(tmp_path, monkeypatch):
    c = case(tmp_path, monkeypatch)
    token = gui._claim_project_operation(c.sid, 'Other operation')
    try:
        run(c)
        assert c.responses[-1][0] == 409
    finally:
        gui._release_project_operation(c.sid, token)
    with setup_jobs.idle_guard(c.handler.workroot, 'Demo', c.shared.root):
        run(c)
        assert c.responses[-1][0] == 409


def test_owned_project_check_holds_shared_lease_without_revoking_status(tmp_path, monkeypatch):
    c = case(tmp_path, monkeypatch)
    real = install.run_preflight
    def check(*args, **kwargs):
        with pytest.raises(setup_jobs.BusyError):
            with setup_jobs.idle_guard(c.handler.workroot, 'Demo', c.shared.root):
                pass
        assert_old_shared_preserved(c)
        return real(*args, **kwargs)
    monkeypatch.setattr(install, 'run_preflight', check)
    run(c)
    assert project_verification.status(c.project, c.working)['can_run']


def test_open_stream_failure_releases_live_state_and_leases(tmp_path, monkeypatch):
    c = case(tmp_path, monkeypatch)
    c.handler._open_stream = lambda: (_ for _ in ()).throw(OSError('Client disconnected'))
    run(c)
    assert gui._agent_run_snapshot(c.sid)['state'] != 'running'
    with setup_jobs.idle_guard(c.handler.workroot, 'Demo', c.shared.root):
        pass
    assert_old_shared_preserved(c)


def test_late_stop_revokes_receipt_and_does_not_stop_other_attempt(tmp_path, monkeypatch):
    c = case(tmp_path, monkeypatch)
    real = c.handler._verify_project_preflight
    def check(*args, **kwargs):
        result = real(*args, **kwargs)
        assert result
        event = gui._LIVE_AGENT_RUNS[c.sid]
        c.handler._stop_setup_project_preflight({'session': c.sid, 'model': 'Demo', 'job_id': 'stale'})
        assert not event['_handle'].stopped.is_set()
        c.handler._stop_setup_project_preflight({'session': c.sid, 'model': 'Demo', 'job_id': event['_turn_id']})
        return result
    monkeypatch.setattr(c.handler, '_verify_project_preflight', check)
    run(c)
    report = project_verification.status(c.project, c.working)
    assert not report['can_run'] and report['receipt']['state'] == 'cancelled'
    assert c.handler._setup_project_preflight_state(c.ki, c.sid)['job']['state'] == 'cancelled'
    assert_old_shared_preserved(c)


def test_binding_change_after_pass_revokes_new_receipt(tmp_path, monkeypatch):
    c = case(tmp_path, monkeypatch)
    real = c.handler._verify_project_preflight
    def check(*args, **kwargs):
        result = real(*args, **kwargs)
        c.shared.roles['binaries'] = tmp_path / 'new-software'
        (c.shared.root / 'kiss.toml').write_text(c.shared.dumps(), encoding='utf-8')
        return result
    monkeypatch.setattr(c.handler, '_verify_project_preflight', check)
    run(c)
    report = project_verification.status(c.project, c.working)
    assert not report['can_run'] and report['receipt']['state'] == 'failed'
    assert gui._LIVE_AGENT_RUNS[c.sid]['check_state'] == 'failed'


def test_active_other_project_agent_and_acquisition_block(tmp_path, monkeypatch):
    c = case(tmp_path, monkeypatch)
    monkeypatch.setattr(gui, '_agent_run_snapshot', lambda sid: {'state': 'running'})
    run(c)
    assert c.responses[-1][0] == 409
    monkeypatch.setattr(gui, '_agent_run_snapshot', lambda sid: {'state': 'idle'})
    monkeypatch.setattr(gui.project_status, 'snapshot', lambda p: {'progress': {'acquisition': {'active': True}}})
    run(c)
    assert c.responses[-1][0] == 400


def test_pending_repaired_other_model_blocks_single_model_check(tmp_path, monkeypatch):
    c = case(tmp_path, monkeypatch)
    monkeypatch.setattr(gui.ki_investigation, 'pending_preflight', lambda p: {'pending': True, 'kis': {'Other': {'passed': False, 'digest': 'a'*64}}})
    monkeypatch.setattr(install, 'run_preflight', lambda *a, **k: pytest.fail('Other pending repair must block'))
    run(c)
    assert not project_verification.status(c.project, c.working)['can_run']
    assert 'Select every repaired KI' in ''.join(c.messages)


def test_real_data_only_action_then_setup_page_recheck_uses_adopted_project(prepared_project):
    c = prepared_project
    shared_status = (c.shared.root / 'status.json').read_bytes()
    c.handler._stream_setup_project_preflight({'model': 'Demo', 'session': c.sid})
    assert not c.responses
    report = project_verification.status(c.project, c.working)
    assert report['can_run']
    assert 'UPDATED_PROJECT_DATA_KI_CHECK_EXECUTED' in report['receipt']['checks'][0]['detail']
    assert (c.shared.root / 'status.json').read_bytes() == shared_status
    assert not c.handler._status_for(c.ki)['can_run'] and len(c.fetches) == 1
    assert not c.transitions


def test_missing_data_after_preparation_is_checked_not_downloaded_by_project_recheck(prepared_project):
    c = prepared_project
    c.target.unlink()
    c.handler._stream_setup_project_preflight({'model': 'Demo', 'session': c.sid})
    assert not c.responses
    report = project_verification.status(c.project, c.working)
    assert not report['can_run'] and report['receipt']['state'] == 'failed'
    assert len(c.fetches) == 1 and not c.target.exists()


def test_even_green_shared_badge_cannot_substitute_a_missing_saved_python(tmp_path, monkeypatch):
    c = case(tmp_path, monkeypatch)
    c.shared.python = str(tmp_path / 'absent.exe')
    (c.shared.root / 'kiss.toml').write_text(c.shared.dumps(), encoding='utf-8')
    monkeypatch.setattr(c.handler, '_status_for', lambda ki: {'can_run': True})
    monkeypatch.setattr(install, 'run_preflight', lambda *a, **k: pytest.fail('No fallback'))
    run(c)
    assert c.responses[-1][0] == 400 and 'interpreter is missing' in c.responses[-1][1]['error']


def test_intact_helpers_for_another_saved_binding_are_not_accepted(tmp_path, monkeypatch):
    c = case(tmp_path, monkeypatch)
    c.cfg.roles['outputs'] = c.project / 'outputs/other-scenario'
    (c.working.root.parent / 'kiss.toml').write_text(c.cfg.dumps(), encoding='utf-8')
    monkeypatch.setattr(install, 'run_preflight', lambda *a, **k: pytest.fail('Wrong helper binding'))
    run(c)
    assert c.responses[-1][0] == 400 and 'helpers belong' in c.responses[-1][1]['error']
