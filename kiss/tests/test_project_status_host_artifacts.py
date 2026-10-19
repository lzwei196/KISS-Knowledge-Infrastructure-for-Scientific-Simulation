"""Physical host figures are available without becoming model/science proof."""
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from kiss_cli import flowgate, project_status


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setenv('GEOFORGE_FLOW_KEYS', str(tmp_path / 'keys'))
    project = tmp_path / 'project'
    (project / 'artifacts').mkdir(parents=True)
    plan = {'selected_kis': [], 'steps': []}
    inventory = {'items': [{'id': 'figure', 'required_by': ['M'], 'status': 'missing',
                            'local_paths': ['artifacts/figure.svg'],
                            'agent_resolvable': True, 'needs_user': False}]}
    return project, plan, inventory


def project_data(case, proof=None):
    project, plan, inventory = case
    before = deepcopy((plan, inventory))
    result = project_status._plan_data(project, flowgate.load(), plan, inventory,
                                      proof or {}, None, {}, [])
    assert (plan, inventory) == before
    return result


def test_host_figure_is_present_without_rewriting_approved_inventory(case):
    project, plan, inventory = case
    path = project / 'artifacts/figure.svg'
    path.write_text('<svg>fixture figure</svg>', encoding='utf-8')
    (project / 'runs').mkdir()
    inv_path = project / 'runs/data-inventory.json'
    inv_path.write_text(json.dumps(inventory), encoding='utf-8')
    before = inv_path.read_bytes()
    result = project_data(case)
    row = result['items'][0]
    assert row['status'] == 'present_unverified' and row['how'] == 'on_disk'
    assert row['note'] == '' and row['evidence_source'] == 'local_files'
    assert row['scientific_validation'] == 'pending' and row['action'] == 'agent_validate'
    assert project_status._data_summary(result) == {
        'severity': 'warn', 'label': 'Files available', 'available': 1, 'total': 1}
    assert inv_path.read_bytes() == before and inventory['items'][0]['status'] == 'missing'
    assert not (project / '.geoforge/receipts').exists()


@pytest.mark.parametrize('kind', ['missing', 'empty', 'partial', 'directory',
    'outside', 'escape', 'leaf-symlink', 'parent-symlink', 'hardlink', 'outputs'])
def test_missing_partial_or_nonordinary_paths_never_gain_availability(case, tmp_path, kind):
    project, plan, inventory = case
    path = project / 'artifacts/figure.svg'
    outside = tmp_path / 'outside.svg'
    outside.write_text('<svg>preserve external bytes</svg>', encoding='utf-8')
    original = outside.read_bytes()
    if kind == 'empty':
        path.touch()
    elif kind == 'partial':
        path.write_text('<svg/>', encoding='utf-8')
        inventory['items'][0]['local_paths'].append('artifacts/absent.svg')
    elif kind == 'directory':
        path.mkdir()
        (path / 'nested.svg').write_text('<svg/>', encoding='utf-8')
    elif kind == 'outside':
        inventory['items'][0]['local_paths'] = [str(outside)]
    elif kind == 'escape':
        inventory['items'][0]['local_paths'] = ['artifacts/../../outside.svg']
    elif kind == 'leaf-symlink':
        path.symlink_to(outside)
    elif kind == 'parent-symlink':
        linked = project / 'artifacts/linked'
        linked.symlink_to(tmp_path, target_is_directory=True)
        inventory['items'][0]['local_paths'] = ['artifacts/linked/outside.svg']
    elif kind == 'hardlink':
        os.link(outside, path)
    elif kind == 'outputs':
        (project / 'outputs').mkdir()
        (project / 'outputs/result.svg').write_text('<svg/>', encoding='utf-8')
        inventory['items'][0]['local_paths'] = ['outputs/result.svg']
    result = project_data(case)
    assert result['items'][0]['status'] == 'unused'
    assert project_status._data_summary(result)['available'] == 0
    assert outside.read_bytes() == original


@pytest.mark.parametrize('role', ['native-output', 'prepared-input'])
def test_existing_artifact_cannot_bypass_ki_step_or_input_readiness(case, role):
    project, plan, inventory = case
    (project / 'artifacts/figure.svg').write_text('<svg/>', encoding='utf-8')
    plan['steps'] = [{'id': 'M:run', 'tool': 'tools/run.py', 'kind': 'run',
                      'inputs': ['figure'] if role == 'prepared-input' else [],
                      'outputs': ['figure'] if role == 'native-output' else []}]
    result = project_data(case)
    assert result['items'][0]['status'] == 'present_unverified'
    assert result['items'][0]['evidence_source'] == 'local_files'
    assert project_status._data_summary(result)['available'] == 1
    assert result['items'][0]['scientific_validation'] == 'pending'
    if role == 'native-output':
        passed = project_data(case, {'steps_passed': ['M:run']})
        assert passed['items'][0]['status'] == 'produced'
        assert passed['items'][0]['evidence_source'] == 'signed_receipt'


@pytest.mark.parametrize('delivery', ['served', 'subset', 'manual'])
def test_artifact_bytes_do_not_change_acquisition_classification(case, delivery):
    project, plan, inventory = case
    (project / 'artifacts/figure.svg').write_text('<svg/>', encoding='utf-8')
    inventory['items'][0].update(delivery=delivery, dataset_id='remote-data')
    result = project_data(case)
    assert result['items'][0]['status'] == 'unused'
    assert result['items'][0]['how'] in {'served', 'clip', 'manual'}
    assert project_status._data_summary(result)['available'] == 0


@pytest.mark.parametrize('zh', [False, True])
def test_actual_renderer_shows_file_presence_without_stale_preparation_note(case, monkeypatch, zh):
    from . import test_project_status_render as rendering
    if rendering.NODE is None:
        pytest.skip('Node is required for actual renderer checks')
    project, plan, inventory = case
    (project / 'artifacts/figure.svg').write_text('<svg/>', encoding='utf-8')
    pd = project_data(case)
    data = rendering.fixture_data()
    data['plan_data'] = pd
    data['project_status']['data_summary'] = project_status._data_summary(pd)
    # Execute the real itemNote too; the common status harness normally stubs it.
    runner = rendering.RUNNER.replace(
        "vm.createContext(context);",
        "vm.createContext(context);\nvm.runInContext(extract('function itemNote(item,zh){','function renderPlanReview'),context);")
    monkeypatch.setattr(rendering, 'RUNNER', runner)
    html = rendering.evaluate(data, zh=zh)['html']
    assert ('文件存在，尚未核实' if zh else 'Present; not verified') in html
    # The unchanged shared group title includes on-disk and generated items;
    # only this row's stale preparation instruction must disappear.
    assert '运行时自动准备。' not in html and 'Prepared during the run.' not in html
    assert '计划中未用到' not in html and 'No step uses it' not in html
    assert '1/1' in html and 'Produced (tool receipt)' not in html
