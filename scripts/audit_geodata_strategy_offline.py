"""Read-only architecture probes against saved estimates and isolated fixtures.

No service credentials, network requests, real datasets, or production project
state are used. Run from the repository with PYTHONPATH=kiss:ki_tools_common.
These probes document current behavior, not a passing acceptance specification.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from kiss_cli import flowrun, obs_access, obs_subset
from ki_tools_common.flow import receipts


class ReplayClient:
    def __init__(self, estimate, manifest=None, payload=b''):
        self.estimate = estimate
        self.manifest = manifest
        self.payload = payload

    def _json(self, route, **kwargs):
        if route == '/subsets/estimate':
            return self.estimate
        if route == '/subsets/jobs':
            return {'job_id': 'offline-job'}
        if route == '/subsets/jobs/offline-job':
            return {'status': 'ready'}
        if route == '/subsets/jobs/offline-job/manifest':
            return self.manifest
        raise AssertionError(f'Unexpected replay route: {route}')

    def _request(self, route):
        assert route == '/subsets/jobs/offline-job/parts/0'
        response = io.BytesIO(self.payload)
        response.headers = {'X-Content-SHA256': hashlib.sha256(self.payload).hexdigest()}
        return response


def run(root, saved):
    report = {'mode': 'offline; saved responses plus synthetic fixtures; no network'}
    matrix = json.loads(saved.read_text())['items']
    outcomes = Counter()
    eligible = []
    inspection = []
    positive = []
    stripped_fields = Counter()
    for row in matrix:
        estimate = row.get('estimate')
        if not isinstance(estimate, dict):
            outcomes['no_saved_estimate'] += 1
            continue
        state = obs_subset.estimate(root / 'replay', row['request'],
                                    client=ReplayClient(estimate))
        outcomes[state['status']] += 1
        if state['eligible']:
            eligible.append(row['dataset_id'])
        if (state.get('offer') or {}).get('inspection_allowed'):
            inspection.append(row['dataset_id'])
        if estimate.get('subsettable') and (estimate.get('estimated_output_bytes') or 0) > 0:
            positive.append(row)
        stripped_fields.update(set(estimate) - set(state['estimate']))
    report['saved_estimate_replay'] = {
        'records': len(matrix), 'states': dict(outcomes),
        'nonzero_subset_estimates': len(positive),
        'eligible_ids': eligible,
        'explicit_inspection_offer_count': len(inspection),
        'nonzero_missing_coverage_complete': sum('coverage_complete' not in r['estimate'] for r in positive),
        'discarded_fields_occurrences': dict(stripped_fields),
    }

    record = {'id': 'fixture_product', 'variables': ['prec', 'temp'],
              'bbox': [110, 30, 120, 40], 'start_date': '1980', 'end_date': '2000'}
    report['query_consistency'] = {
        'single_variable_results': obs_access.local_search([record], variable='prec')['total'],
        'two_variable_results': obs_access.local_search([record], variable='prec,temp')['total'],
        'same_two_variable_assessment': obs_access.assess_dataset(record, variable='prec,temp'),
    }

    # Fixture bytes deliberately are NOT a scientific file. This exercises the
    # transport layer only; the production code correctly leaves science pending.
    data = b'offline transport fixture; NOT real scientific data'
    sha = hashlib.sha256(data).hexdigest()
    body = {'dataset_id': 'fixture_generic_nc', 'bbox': [115, 37, 117, 39],
            'variables': ['prec'], 'start': '1989-01-01', 'end': '1989-01-07'}
    estimate = {'subsettable': True, 'kind': 'netcdf_grid',
                'estimated_output_bytes': len(data), 'over_output_cap': False,
                'coverage_complete': True, 'missing': [], 'transformations': [],
                'snapped_output_bounds': body['bbox'], 'n_parts': 1}
    part = {'n': 0, 'name': 'fixture.nc', 'bytes': len(data), 'sha256': sha,
            'bounds': [0, 0, 1, 1], 'variables': ['wrong_variable'],
            'time_range': ['1989-01-01', '1989-12-31'], 'n_time_steps': 365,
            'time_subset_applied': False, 'crs_source': 'inferred_fixture'}
    manifest = {'job_id': 'offline-job', 'dataset_id': body['dataset_id'],
                'ready': True, 'n_parts': 1, 'total_bytes': len(data), 'parts': [part]}
    replay = ReplayClient(estimate, manifest, data)
    project = root / 'subset-project'
    state = obs_subset.estimate(project, body, client=replay)
    obs_subset.approve(project, state['id'], client=replay)
    try:
        result = obs_subset.download(project, state['id'], client=replay)
        report['generic_manifest_scope_fixture'] = {'status': result['status'],
            'scientific_validation': result['scientific_validation'],
            'lost_manifest_fields': sorted(set(part) - set(result['files'][0]))}
    except ValueError as error:
        report['generic_manifest_scope_fixture'] = {'status': 'rejected', 'reason': str(error),
            'published': (project / 'inputs/geoforge_subsets' / state['id']).exists()}

    empty = {**estimate, 'estimated_output_bytes': 0, 'selection_empty': True,
             'n_selected_cells': 0, 'reason': 'empty fixture selection'}
    state = obs_subset.estimate(root / 'empty', body, client=ReplayClient(empty))
    report['empty_selection_fixture'] = {
        'status': state['status'], 'eligible': state['eligible'],
        'selection_empty_preserved': 'selection_empty' in state['estimate'],
        'interpretation': 'Synthetic combination, not evidence that a live server returned this exact combination.',
    }

    project = root / 'reuse-project'
    (project / 'inputs').mkdir(parents=True)
    raw = project / 'inputs/old-source.bin'
    raw.write_bytes(b'offline old-source bytes')
    with patch.object(receipts, 'keys_dir', return_value=root / 'isolated-test-keys'):
        receipt_path = receipts.record_download(
            project, item_id='forcing', source='fixture_A',
            request_url='https://fixture.invalid/A', http_status=200, raw_files=[raw],
            approval_sha256='old-plan', plan_step_id='prepare',
            inventory_item={'id': 'forcing', 'dataset_id': 'fixture_A',
                            'requirements': {'start': '1989', 'end': '1990'}})
        receipt = json.loads(receipt_path.read_text())
        new_inventory = {'items': [{'id': 'forcing', 'dataset_id': 'fixture_B',
            'chosen_source': 'fixture_B', 'status': 'resolved', 'delivery': 'served',
            'required_by': ['fixture_KI'], 'requirements': {'start': '2001', 'end': '2002'},
            'catalogue': {'start_date': '2000', 'end_date': '2010'}}]}
        flow = SimpleNamespace(receipts=receipts, plan=SimpleNamespace(
            read_artifacts=lambda _project: ({'steps': []}, new_inventory)))
        with patch.object(flowrun, '_flow', return_value=flow), \
                patch.object(flowrun.setup_flow, 'request', return_value=None):
            ui_row = flowrun.plan_data_status(project)['items'][0]
        report['receipt_reuse_changed_selection'] = {
            'signature_valid': receipts.verify(project, receipt),
            'same_item_id_but_different_dataset_and_period_accepted':
                receipts._download_still_valid(project, receipt, new_inventory),
            'project_status': ui_row['status'], 'project_action': ui_row['action'],
            'new_selected_dataset': ui_row['dataset_id'],
        }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--estimates', type=Path,
        default=Path('output/geodata-subset-retest-2026-09-14/estimates.json'))
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='geodata-strategy-audit-') as temporary, \
            patch.object(obs_access.Client, '_request', side_effect=AssertionError('Network forbidden')), \
            patch.object(receipts, 'keys_dir', return_value=Path(temporary) / 'keys'):
        report = run(Path(temporary), args.estimates)
    if args.output:
        obs_access._atomic_json(args.output, report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
