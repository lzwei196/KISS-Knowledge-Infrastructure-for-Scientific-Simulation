"""Changed real artifacts invalidate the cached GUI status without rewriting history."""
import json

import pytest

from kiss_cli import flowrun, project_status
from test_execution_continuation import c, run_step
from test_execution_evidence_currentness import case, approve, run


@pytest.mark.parametrize('change', ['delete', 'rewrite'])
def test_completed_artifact_drift_updates_status_without_rewriting_history(c, change):
    run_step(c, 1)
    run_step(c, 2)
    flowrun.after(c.project, c.turn, 'Finished.')
    assert c.fs.state.value == 'COMPLETED'
    first = project_status.snapshot(c.project)
    assert first['progress']['status'] == 'complete'
    receipts = {p: p.read_bytes() for p in
                (c.project / '.geoforge/receipts/model-runs').glob('*.json')}
    history = (c.project / 'runs/flow-state.json').read_bytes()
    result = c.project / 'outputs/two.csv'
    if change == 'delete':
        result.unlink()
    else:
        result.write_text('day,value\n1,999\n', encoding='utf-8')
    # Same process/cache, same plan/approval, changed real output bytes.
    current = project_status.snapshot(c.project)
    assert current['progress']['status'] == 'failed'
    assert 'no longer current' in current['progress']['summary']
    assert 's2' in current['progress']['summary']
    assert not current['progress']['science_complete']
    assert receipts == {p: p.read_bytes() for p in receipts}
    assert history == (c.project / 'runs/flow-state.json').read_bytes()
    assert all(json.loads(value)['validation']['status'] == 'passed'
               for value in receipts.values())


def test_execution_chat_explains_output_drift_without_claiming_engine_failure(c):
    run_step(c, 1)
    run_step(c, 2)
    (c.project / 'outputs/two.csv').unlink()
    result = flowrun.after(c.project, c.turn, 'Everything completed.')
    assert c.fs.state.value == 'EXECUTING'
    assert 'input or output evidence is incomplete or has changed' in result.message
    assert 'earlier receipts are preserved' in result.message
    assert 's2' in result.message


def test_new_nested_external_input_file_invalidates_status_cache(case):
    c = case
    external = c.project.parent / 'approved-forcing'
    nested = external / 'nested'
    nested.mkdir(parents=True)
    source = external / 'forcing.csv'
    source.write_bytes((c.project / 'inputs/source.csv').read_bytes())
    # The argument-path policy remains unchanged. This checks host coverage of
    # an additional approved input folder, not native tool access permissions.
    c.fs.inventory['items'][0]['local_paths'] = ['inputs/source.csv', str(external)]
    approve(c)
    run(c, 'produce')
    run(c, 'consume')
    flowrun.after(c.project, c.turn, 'Finished.')
    first = project_status.snapshot(c.project)
    assert first['progress']['status'] == 'complete'
    old_receipts = {p: p.read_bytes() for p in
                    (c.project / '.geoforge/receipts/model-runs').glob('*.json')}
    # The directory is outside the project's artifact scan, and this file did
    # not exist in the cached input list. Parent-directory metadata must evict it.
    (nested / 'new-station.csv').write_text('day,value\n1,7\n', encoding='utf-8')
    current = project_status.snapshot(c.project)
    assert current['progress']['status'] == 'failed'
    assert 'no longer current' in current['progress']['summary']
    assert old_receipts == {p: p.read_bytes() for p in old_receipts}
