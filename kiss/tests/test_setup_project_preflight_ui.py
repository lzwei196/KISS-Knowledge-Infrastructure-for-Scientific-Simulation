"""Exercise the actual setup JS route and polling in a Node VM."""
import json
import subprocess

import pytest
from . import test_setup_verification_ui as ui

pytestmark = ui.pytestmark


def render(*states, **kwargs):
    runner = ui.RUNNER.replace("MODEL:'CRHM',STATE:", "MODEL:'CRHM',DATA_SESSION:'555555555555',STATE:")
    runner = runner.replace("saveInstallLocation:async()=>true", "saveInstallLocation:async()=>{throw new Error('Project action must not save installation location')}")
    runner = runner.replace("if(url==='/api/setup-stop')", "if(url==='/api/setup-stop'||url==='/api/setup-project-preflight-stop')")
    runner = runner.replace("if(url!=='/api/setup-agent')", "if(url!=='/api/setup-project-preflight')")
    result = subprocess.run([ui.NODE, '-e', runner, str(ui.PAGE)],
        input=json.dumps({'states': states, **kwargs}), text=True, encoding='utf-8', capture_output=True, check=True, timeout=12)
    return json.loads(result.stdout)


BASE = {**ui.STALE, 'job': None, 'attention': None, 'request': None,
        'project_preflight': {'session': '555555555555', 'can_check': True, 'detail': 'Exact project check required'},
        'software': {'can_run': False, 'label': 'Project preflight required'}, 'log_tail': 'Exact project check required'}


@pytest.mark.parametrize('zh', [False, True])
def test_project_recheck_preserves_session_skips_install_form_and_needs_no_provider(zh):
    active = {**BASE, 'job': ui.job(provider='project-preflight')}
    done = {**BASE, 'job': ui.job('completed', provider='project-preflight'), 'software': {'can_run': True, 'label': 'Project preflight passed'}}
    old, started, polled, finished = render(BASE, active, done, noProvider=True, zh=zh,
        actions=[{'kind': 'start'}, {'kind': 'poll', 'state': 1}, {'kind': 'finish', 'state': 2}])
    assert not old['#retry']['disabled'] and not old['#start']['disabled']
    assert old['.install-location']['display'] == 'none'
    assert ('也不会运行模型' if zh else 'or start the model') in old['#need']['html']
    # An unchecked project is checked when its approved plan runs; it is not shown as blocked.
    assert ('批准的计划开始运行时 GeoForge 也会自动检查' if zh else 'automatically when an approved plan starts') in old['#need']['html']
    assert old['#needbadge']['text'] == ('运行模型时检查' if zh else 'Checked when the model runs')
    assert old['#needbadge']['className'] == 'badge'
    post = next(row for row in started['__calls'] if row['url'] == '/api/setup-project-preflight')
    assert post['body'] == {'model': 'CRHM', 'session': '555555555555'}
    assert not any(row['url'] in ('/api/setup-agent', '/api/setup-location') for row in finished['__calls'])
    assert started['#retry']['disabled'] and polled['#start']['disabled']
    assert finished['#statusbadge']['text'] == 'Project preflight passed'


def test_project_stop_targets_only_exact_project_attempt():
    active = {**BASE, 'job': ui.job(provider='project-preflight')}
    cancelled = {**BASE, 'job': ui.job('cancelled', provider='project-preflight')}
    old, stopped, done = render(active, cancelled, actions=[{'kind': 'stop'}, {'kind': 'poll', 'state': 1}])
    call = next(row for row in stopped['__calls'] if row['url'] == '/api/setup-project-preflight-stop')
    assert call['body'] == {'model': 'CRHM', 'job_id': 'attempt-1', 'session': '555555555555'}
    assert done['#statusbadge']['className'] != 'badge ok'


def test_missing_or_invalid_project_binding_has_no_generic_setup_fallback():
    state = {**BASE, 'project_preflight': {'can_check': False, 'detail': 'Project session does not exist.'}}
    first, clicked = render(state, actions=[{'kind': 'start'}])
    assert first['#retry']['disabled'] and first['#start']['disabled']
    assert not clicked['__calls']
    assert 'Project session does not exist.' in first['#need']['html']


def test_setup_page_has_explicit_host_route_and_existing_project_return_link():
    source = ui.PAGE.read_text(encoding='utf-8')
    assert 'projectCheck?"/api/setup-project-preflight"' in source
    assert 'if(projectSetup()){location.href="/?session="+encodeURIComponent(DATA_SESSION);return}' in source
