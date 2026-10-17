"""Real signed producer attempts gate the common API/CLI execution boundary."""
import copy
import os
from pathlib import Path

import pytest

from kiss_cli import api, cli, flowgate, project_data_tools
from kiss_cli.catalog import KI
from .test_execution import _project, _execute, _receipt_docs


NATIVE = """from pathlib import Path
import sys
assert Path(sys.argv[1]).read_text()
Path('native-started').write_text('yes')
out = Path('outputs/q.csv'); out.parent.mkdir(exist_ok=True)
out.write_text('t,q\\n1,0.5\\n2,1.2\\n3,0.8\\n')
"""
INDEPENDENT = """from pathlib import Path
p = Path('outputs/independent.csv'); p.parent.mkdir(exist_ok=True)
p.write_text('t,q\\n1,0.5\\n2,1.2\\n3,0.8\\n')
"""
PRODUCER = """from pathlib import Path
import sys
raw = Path(sys.argv[1]).read_text()
out = Path(sys.argv[2]); out.parent.mkdir(parents=True, exist_ok=True)
out.write_text('{"value":' + raw.strip() + '}')
"""


@pytest.fixture(autouse=True)
def isolated_host_state(tmp_path, monkeypatch):
    monkeypatch.setenv('GEOFORGE_FLOW_KEYS', str(tmp_path / 'keys'))
    monkeypatch.setenv('GEOFORGE_FLOW_REGISTRY', str(tmp_path / 'registry'))


def chain(tmp_path, *, suffix='json'):
    ctx = _project(tmp_path, source=NATIVE, extra_tools={'independent.py': INDEPENDENT})
    ctx.flow.request_replan('Review a generic data producer and its native consumer')
    (ctx.project / 'inputs').mkdir(exist_ok=True)
    (ctx.project / 'inputs/raw.txt').write_text('1')
    authored = project_data_tools.write(ctx.project, 'M', 'stage', PRODUCER, 'converter')
    output = 'outputs/staged.' + suffix
    authored['project_data_tool']['arguments'] = ['inputs/raw.txt', output]
    plan = copy.deepcopy(ctx.plan)
    stage = {**authored['step_template'], 'id': 'stage', 'inputs': ['raw'], 'outputs': ['staged']}
    native = {**plan['steps'][0], 'inputs': ['staged'], 'outputs': ['q'], 'command': [output]}
    independent = {**native, 'id': 'independent', 'kind': 'check', 'inputs': [],
                   'outputs': ['inspection'], 'tool': str(ctx.root / 'tools/independent.py'), 'command': []}
    plan['steps'] = [stage, native, independent]
    inv = {'schema_version': '1.0', 'items': [
        {'id': 'raw', 'status': 'ready', 'required_by': ['M'], 'local_paths': ['inputs/raw.txt'],
         'acceptable_sources': ['local_fixture'], 'chosen_source': 'local_fixture',
         'agent_resolvable': True, 'needs_user': False},
        {'id': 'staged', 'status': 'missing', 'local_paths': [output]},
        {'id': 'q', 'status': 'missing', 'local_paths': ['outputs/q.csv']},
        {'id': 'inspection', 'status': 'missing', 'local_paths': ['outputs/independent.csv']},
    ]}
    assert ctx.flow.write_plan(plan, inv) == []
    ctx.flow.flow.approval.approve(ctx.project, by='auto')
    ctx.flow.reload_artifacts()
    ctx.flow.move('plan_written', {'plan_valid': True})
    ctx.flow.move('approved', {'approval': 'OK'})
    ctx.flow.move('execution_started', {'setup_verified': True})
    ctx.authored, ctx.output = authored, output
    return ctx


def stage(ctx):
    return _execute(ctx, tool=Path(ctx.authored['tool']), plan_step_id='stage',
                    arguments=ctx.authored['project_data_tool']['arguments'],
                    timeout=120, project_data_tool=True)


def native(ctx):
    return _execute(ctx, arguments=[ctx.output])


def denied(ctx):
    count = len(_receipt_docs(ctx))
    with pytest.raises(flowgate.FlowDenied, match='without current passed receipts: stage'):
        native(ctx)
    assert not (ctx.project / 'native-started').exists()
    assert len(_receipt_docs(ctx)) == count  # no launch, no pretend native receipt


def test_exit_zero_with_failed_output_validation_blocks_native(tmp_path):
    ctx = chain(tmp_path, suffix='yaml')
    produced = stage(ctx)
    assert produced.exit_code == 0 and produced.receipt['validation'] == 'failed'
    assert (ctx.project / ctx.output).is_file()
    denied(ctx)


def test_missing_producer_receipt_blocks_even_when_file_exists(tmp_path):
    ctx = chain(tmp_path)
    (ctx.project / 'outputs').mkdir()
    (ctx.project / ctx.output).write_text('{"value":1}')
    denied(ctx)


def test_current_passed_producer_allows_native_execution(tmp_path):
    ctx = chain(tmp_path)
    produced = stage(ctx)
    assert produced.exit_code == 0 and produced.receipt['validation'] == 'passed'
    assert 'stage' in ctx.flow.evidence()['steps_passed']
    result = native(ctx)
    assert result.exit_code == 0 and result.receipt['validation'] == 'passed'
    assert (ctx.project / 'native-started').read_text() == 'yes'


@pytest.mark.parametrize('changed', ['inputs/raw.txt', 'outputs/staged.json'])
def test_same_size_and_mtime_byte_change_invalidates_producer(tmp_path, changed):
    ctx = chain(tmp_path)
    assert stage(ctx).receipt['validation'] == 'passed'
    path = ctx.project / changed
    before = path.stat()
    path.write_bytes(path.read_bytes().replace(b'1', b'2'))
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    denied(ctx)


def test_unrelated_failed_producer_does_not_block_independent_check(tmp_path):
    ctx = chain(tmp_path, suffix='yaml')
    assert stage(ctx).receipt['validation'] == 'failed'
    result = _execute(ctx, tool=ctx.root / 'tools/independent.py', plan_step_id='independent')
    assert result.exit_code == 0 and result.receipt['validation'] == 'passed'
    denied(ctx)


def test_latest_failed_retry_supersedes_previous_pass(tmp_path):
    ctx = chain(tmp_path)
    assert stage(ctx).receipt['validation'] == 'passed'
    (ctx.project / 'inputs/raw.txt').write_text('not-json')
    assert stage(ctx).receipt['validation'] == 'failed'
    denied(ctx)


@pytest.mark.parametrize('adapter', ['direct', 'cli'])
def test_all_provider_adapters_refuse_failed_producer_before_native(tmp_path, capsys, adapter):
    ctx = chain(tmp_path, suffix='yaml')
    assert stage(ctx).receipt['validation'] == 'failed'
    before = len(_receipt_docs(ctx))
    if adapter == 'direct':
        with pytest.raises(api.ToolError, match='without current passed receipts: stage'):
            api.execute_tool('run_ki_tool', {'tool_path': 'tools/run.py',
                'plan_step_id': 'M:run', 'arguments': [ctx.output]},
                KI('M', ctx.root), ctx.cfg, project_mode=True, flow=ctx.flow)
    else:
        assert cli.main(['run-tool', '--project', str(ctx.project), '--step', 'M:run',
                         'M', 'tools/run.py', '--', ctx.output]) == 3
        assert 'without current passed receipts: stage' in capsys.readouterr().err
    assert not (ctx.project / 'native-started').exists()
    assert len(_receipt_docs(ctx)) == before


def test_planning_guidance_distinguishes_transform_from_exact_copy(tmp_path):
    ctx = chain(tmp_path)
    from ki_tools_common.flow import contracts
    ctx.flow.request_replan('Inspect planning guidance')
    block = contracts.planning_block({'M': ctx.root}, ctx.flow.plan, ctx.flow.inventory, ctx.project)
    schema = next(row for row in api.tool_schemas(KI('M', ctx.root), project_mode=True, flow=ctx.flow)
                  if row['name'] == 'write_project_data_tool')
    for text in (block, schema['description']):
        assert 'Transformed nonbasic formats require a supported output_formats contract' in text
        assert 'edited or subset YAML is not an unchanged copy' in text
