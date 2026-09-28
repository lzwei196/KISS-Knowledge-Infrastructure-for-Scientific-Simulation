"""Explicit live integration test; uses configured Desktop token without printing it.

Run only with user authorization: creates small backend jobs and downloads subsets.
No model runs, no synthetic data, no changes to scientific approval state.
"""
import json
import time
import sys
from pathlib import Path

import netCDF4
import numpy as np

from kiss_cli import obs_access, obs_subset

ROOT = Path('output/cmfd-all-variables-2026-09-14').resolve()


def inspect_file(path, part):
    with netCDF4.Dataset(path) as ds:
        name, year = part['variable'], part['year']
        var = ds.variables[name]
        values = np.ma.asarray(var[:])
        dates = netCDF4.num2date(ds.variables['time'][:], ds.variables['time'].units,
                               calendar=getattr(ds.variables['time'], 'calendar', 'standard'))
        lat, lon = np.asarray(ds.variables['lat'][:]), np.asarray(ds.variables['lon'][:])
        errors = []
        if var.shape != (365, 20, 20): errors.append('unexpected shape')
        if (dates[0].year, dates[0].month, dates[0].day) != (year, 1, 1): errors.append('start mismatch')
        if (dates[-1].year, dates[-1].month, dates[-1].day) != (year, 12, 31): errors.append('end mismatch')
        if any((b-a).total_seconds() != 86400 for a,b in zip(dates, dates[1:])): errors.append('time gaps')
        if not (lat.min() >= 37 and lat.max() <= 39 and lon.min() >= 115 and lon.max() <= 117): errors.append('out-of-bbox coordinates')
        if np.ma.count_masked(values) or not np.isfinite(values.compressed()).all(): errors.append('missing/nonfinite values')
        if getattr(var, 'units', None) != part.get('units'): errors.append('manifest units mismatch')
        return dict(variable=name, year=year, shape=list(var.shape), units=getattr(var,'units',None),
                    minimum=float(values.min()), maximum=float(values.max()), masked=int(np.ma.count_masked(values)),
                    first=str(dates[0]), last=str(dates[-1]), errors=errors)


def main():
    if '--check-existing' in sys.argv:
        report = json.loads((ROOT/'report.json').read_text())
        return compare_results(report)
    catalogue = obs_access.load_catalogue() or {}
    parent = next(d for d in catalogue['datasets'] if d.get('id') == 'cmfd_china_daily_010')
    variables = [v['name'] for v in parent['variables']]
    report = {'dataset_id': parent['id'], 'variables': variables, 'bbox': [115,37,117,39], 'cases': []}
    client = obs_access.Client(timeout=50)
    for selected in [[v] for v in variables] + [variables]:
        case = {'variables': selected}
        report['cases'].append(case)
        try:
            body = dict(dataset_id=parent['id'], bbox=report['bbox'], variables=selected,
                        start='1989-01-01', end='1990-12-31')
            state = obs_subset.estimate(ROOT, body, client=client)
            case.update(local_id=state['id'], estimate=state['estimate'], eligible=state['eligible'])
            print(json.dumps({'variables': selected, 'estimate': state['estimate'], 'eligible': state['eligible']}), flush=True)
            if state['eligible']:
                state = obs_subset.approve(ROOT, state['id'], client=client)
                case['job_id'] = state['job_id']
                deadline = time.monotonic()+600
                while time.monotonic() < deadline:
                    state = obs_subset.refresh(ROOT, state['id'], client=client)
                    if state['status'] not in ('queued','running'): break
                    time.sleep(3)
                case['status'] = state['status']
                if state['status'] == 'ready':
                    state = obs_subset.download(ROOT, state['id'], client=client)
                    case.update(status=state['status'], bytes=state['verified_bytes'], path=state['path'],
                                checks=[inspect_file(Path(state['path'])/p['name'], p) for p in state['files']])
                    actual = {(p['variable'],p['year']) for p in case['checks']}
                    expected = {(v,y) for v in selected for y in [1989,1990]}
                    case['passed'] = actual == expected and len(case['checks'])==len(expected) and not any(p['errors'] for p in case['checks'])
            else:
                case['status'] = 'estimate_blocked'
        except Exception as error:
            case.update(status='failed', error=type(error).__name__ + ': ' + str(error))
        obs_access._atomic_json(ROOT/'report.json', report)
        print(json.dumps({k:v for k,v in case.items() if k not in ('estimate','checks','path') }),flush=True)
    compare_results(report)


def compare_results(report):
    combined = report['cases'][-1]
    comparisons = []
    if combined.get('passed'):
        for individual in report['cases'][:-1]:
            if not individual.get('passed'): continue
            variable = individual['variables'][0]
            for year in (1989,1990):
                name = f"{report['dataset_id']}__{variable}_{year}_subset.nc"
                with netCDF4.Dataset(Path(combined['path'])/name) as a, netCDF4.Dataset(Path(individual['path'])/name) as b:
                    comparisons.append({'variable': variable, 'year': year,
                                        'identical': bool(np.ma.allequal(a.variables[variable][:], b.variables[variable][:]))})
    report['individual_vs_combined'] = comparisons
    report.pop('unknown_variable_negative_test', None)
    obs_access._atomic_json(ROOT/'report.json', report)
    print('Report:', ROOT/'report.json', flush=True)


if __name__ == '__main__': main()
