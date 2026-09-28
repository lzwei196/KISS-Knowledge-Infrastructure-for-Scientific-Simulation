"""Offline audit of GUI-acquired subset files; never changes project state.

Reads saved acquisition requests/part manifests and actual NetCDF/GeoTIFF files.
Reports transport integrity separately from structural and scientific limitations.
No credentials, network client, model execution, or approval functions are used.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import platform
import re

import netCDF4
import numpy as np
import rasterio


MAX_ARRAY_BYTES = 128 * 1024**2
STATE_FIELDS = ('id', 'status', 'job_id', 'stage', 'verified_bytes',
                'scientific_validation', 'created_at', 'updated_at')
REQUEST_FIELDS = ('dataset_id', 'bbox', 'variables', 'start', 'end')
ESTIMATE_FIELDS = ('kind', 'processor_version', 'source_version_hash', 'n_files',
                   'n_parts', 'variables', 'years', 'estimated_output_bytes',
                   'snapped_output_bounds', 'native_crs', 'n_selected_cells',
                   'source_audit', 'skipped_files', 'excluded_files',
                   'unreadable_files', 'exclusions', 'source_file_count')
PART_FIELDS = ('name', 'n', 'bytes', 'sha256', 'variables', 'variable', 'year',
               'units', 'time_range', 'n_time_steps', 'calendar', 'bounds', 'crs',
               'shape', 'resolution', 'nodata', 'bands', 'layers',
               'processor_version', 'source_version_hash', 'crs_source')


def serial(value):
    if isinstance(value, np.generic):
        return serial(value.item())
    if isinstance(value, np.ndarray):
        return [serial(v) for v in value.tolist()]
    if isinstance(value, dict):
        return {str(k): serial(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serial(v) for v in value]
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def pick(value, fields):
    return {key: serial(value[key]) for key in fields if key in value}


def checksum(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024**2), b''):
            digest.update(block)
    return digest.hexdigest()


def states(project):
    result = []
    for path in sorted((project / '.geoforge/subsets').glob('*.json')):
        state = json.loads(path.read_text())
        if re.fullmatch(r'[a-f0-9]{32}', str(state.get('id', ''))):
            result.append(state)
    return result


def snapshot(project):
    entries = []
    for state in states(project):
        item = pick(state, STATE_FIELDS)
        item['request'] = pick(state.get('request', {}), REQUEST_FIELDS)
        item['estimate'] = pick(state.get('estimate', {}), ESTIMATE_FIELDS)
        item['accepted_parts'] = [pick(p, PART_FIELDS) for p in state.get('files', [])]
        entries.append(item)
    return {'captured_at_utc': datetime.now(timezone.utc).isoformat(),
            'project_name': project.name, 'acquisitions': entries,
            'status_counts': dict(Counter(s['status'] for s in entries))}


def stats(value):
    arr = np.ma.asarray(value)
    mask = np.ma.getmaskarray(arr)
    result = {'shape': list(arr.shape), 'total_count': int(arr.size),
              'masked_count': int(mask.sum()),
              'masked_fraction': float(mask.mean()) if arr.size else None}
    numeric = np.issubdtype(arr.dtype, np.number)
    if not numeric:
        result['numeric'] = False
        return result
    finite = np.isfinite(np.ma.getdata(arr)) & ~mask
    selected = np.asarray(np.ma.getdata(arr)[finite])
    result.update(valid_count=int(selected.size),
                  nonfinite_unmasked_count=int((~np.isfinite(np.ma.getdata(arr)) & ~mask).sum()),
                  valid_fraction=float(selected.size / arr.size) if arr.size else None,
                  all_masked_or_nonfinite=bool(arr.size and not selected.size))
    if selected.size:
        unique = np.unique(selected)
        result.update(minimum=float(selected.min()), maximum=float(selected.max()),
                      mean=float(selected.mean()), unique_count=int(unique.size))
        if unique.size <= 64:
            result['unique_values'] = serial(unique)
    return result


def small_read(variable):
    size = int(np.prod(variable.shape, dtype=np.int64)) * variable.dtype.itemsize
    if size > MAX_ARRAY_BYTES:
        raise ValueError('Decoded variable exceeds audit memory cap; not sampled or silently skipped')
    return variable[:]


def inspect_netcdf(path, request, part):
    errors, warnings = [], []
    result = {'format': 'NetCDF', 'errors': errors, 'warnings': warnings}
    declared = part.get('variables') or ([part['variable']] if part.get('variable') else [])
    with netCDF4.Dataset(path) as ds:
        result.update(dimensions={n: len(d) for n, d in ds.dimensions.items()},
                      actual_variable_names=list(ds.variables),
                      file_format=ds.file_format, variables={}, coordinates={})
        absent = sorted(set(declared) - set(ds.variables))
        if absent:
            errors.append('Declared variables absent: ' + ', '.join(absent))
        coordinate_names = set(ds.dimensions)
        support_names = set()
        for variable in ds.variables.values():
            for attr in ('bounds', 'grid_mapping', 'coordinates'):
                support_names.update(str(getattr(variable, attr, '')).split())
        for name, variable in ds.variables.items():
            axis = getattr(variable, 'axis', '').upper()
            standard = getattr(variable, 'standard_name', '')
            is_coord = (name in coordinate_names or axis in {'X', 'Y', 'Z', 'T'}
                        or standard in {'latitude', 'longitude', 'time'}
                        or name.lower() in {'lat', 'lon', 'latitude', 'longitude', 'time'})
            values = small_read(variable)
            info = {'dtype': str(variable.dtype), 'dimensions': list(variable.dimensions),
                    'units': str(getattr(variable, 'units', '')),
                    'long_name': str(getattr(variable, 'long_name', '')),
                    'standard_name': str(standard), **stats(values)}
            for attr in ('_FillValue', 'missing_value', 'scale_factor', 'add_offset'):
                if hasattr(variable, attr):
                    info[attr] = serial(getattr(variable, attr))
            result['coordinates' if is_coord else 'variables'][name] = info
            if not is_coord and name not in support_names and info.get('all_masked_or_nonfinite'):
                warnings.append(f'All values masked/nonfinite: {name}')
            if name in declared:
                expected_units = part.get('units')
                expected_units = expected_units.get(name) if isinstance(expected_units, dict) else expected_units
                if expected_units is not None and str(expected_units) != info['units']:
                    errors.append(f'Units contradict manifest for {name}')
            if axis == 'T' or standard == 'time' or name.lower() == 'time':
                if variable.ndim != 1 or not hasattr(variable, 'units'):
                    warnings.append('Unrecognized time axis')
                    continue
                if np.ma.count_masked(values):
                    errors.append('Masked time coordinate')
                    continue
                calendar = getattr(variable, 'calendar', 'standard')
                decoded = netCDF4.num2date(values, variable.units, calendar=calendar)
                timestamps = [str(d) for d in decoded]
                dates = [d.strftime('%Y-%m-%d') for d in decoded]
                step_seconds = [(b-a).total_seconds() for a, b in zip(decoded, decoded[1:])]
                time_info = {'name': name, 'calendar': calendar, 'count': len(decoded),
                             'first': timestamps[0] if timestamps else None,
                             'last': timestamps[-1] if timestamps else None,
                             'strictly_increasing': all(v > 0 for v in step_seconds),
                             'step_seconds_unique': sorted(set(step_seconds)),
                             'all_timestamps': timestamps if len(timestamps) <= 32 else None}
                result['time'] = time_info
                if not decoded.size:
                    errors.append('Empty time axis')
                if not time_info['strictly_increasing']:
                    errors.append('Time axis not strictly increasing')
                if part.get('n_time_steps') is not None and part['n_time_steps'] != len(decoded):
                    errors.append('Time count contradicts manifest')
                if dates and part.get('time_range') and [x[:10] for x in part['time_range']] != [dates[0], dates[-1]]:
                    errors.append('Time endpoints contradict manifest')
                if dates and ((request.get('start') and dates[0] < request['start'])
                              or (request.get('end') and dates[-1] > request['end'])):
                    errors.append('Time exceeds requested dates')
                if request.get('start') and request.get('end') and 'daily' in request['dataset_id']:
                    start, end = date.fromisoformat(request['start']), date.fromisoformat(request['end'])
                    expected = [(start + timedelta(days=i)).isoformat() for i in range((end-start).days+1)]
                    time_info['requested_inclusive_daily_count'] = len(expected)
                    time_info['exact_requested_daily_dates'] = dates == expected
                    if dates != expected:
                        errors.append('Daily dates are not exactly the inclusive requested date sequence')
        data_names = set(result['variables']) - support_names
        result['actual_data_variables'] = sorted(data_names)
        if declared and data_names != set(declared):
            warnings.append('Actual non-coordinate fields differ from manifest selection')
        if (request.get('start') or request.get('end')) and 'time' not in result:
            errors.append('Requested temporal data has no recognized time coordinate')
        result['crs_metadata'] = {name: {
            key: serial(getattr(var, key)) for key in ('grid_mapping_name', 'spatial_ref', 'crs_wkt')
            if hasattr(var, key)} for name, var in ds.variables.items()
            if any(hasattr(var, key) for key in ('grid_mapping_name', 'spatial_ref', 'crs_wkt'))}
    return result


def inspect_raster(path, request, part):
    errors, warnings = [], []
    with rasterio.open(path) as ds:
        result = {'format': 'GeoTIFF', 'errors': errors, 'warnings': warnings,
                  'shape': [ds.count, ds.height, ds.width], 'dtype': list(ds.dtypes),
                  'crs': str(ds.crs) if ds.crs else None, 'bounds': list(ds.bounds),
                  'resolution': list(ds.res), 'transform': list(ds.transform)[:6],
                  'nodata': serial(ds.nodata), 'compression': str(ds.compression),
                  'units': list(ds.units), 'band_descriptions': list(ds.descriptions),
                  'bands': {}}
        if not ds.crs:
            warnings.append('Missing CRS')
        if ds.nodata is None:
            warnings.append('No nodata value declared; valid-mask counts rely on source masks')
        if part.get('bounds') and not np.allclose(part['bounds'], ds.bounds, rtol=0, atol=1e-5):
            errors.append('Bounds contradict manifest')
        if part.get('crs') and ds.crs and rasterio.crs.CRS.from_user_input(part['crs']) != ds.crs:
            errors.append('CRS contradicts manifest')
        if part.get('shape') and list(part['shape']) not in ([ds.height, ds.width], [ds.count, ds.height, ds.width]):
            errors.append('Shape contradicts manifest')
        if not ds.width or not ds.height or not ds.count:
            errors.append('Empty raster dimensions')
        for band in ds.indexes:
            if ds.width * ds.height * np.dtype(ds.dtypes[band-1]).itemsize > MAX_ARRAY_BYTES:
                errors.append('Decoded raster exceeds audit memory cap')
                continue
            info = stats(ds.read(band, masked=True))
            result['bands'][str(band)] = info
            if info.get('all_masked_or_nonfinite'):
                warnings.append(f'All values masked/nonfinite in band {band}')
    return result


def inspect_state(project, state):
    request = pick(state.get('request', {}), REQUEST_FIELDS)
    report = {**pick(state, STATE_FIELDS), 'request': request,
              'estimate': pick(state.get('estimate', {}), ESTIMATE_FIELDS),
              'app_content_validation': pick(state.get('content_validation', {}), ('status', 'pending', 'note')),
              'app_scope_validation': pick(state.get('scope_validation', {}), ('status', 'pending', 'note')),
              'files': [], 'errors': [], 'warnings': []}
    folder = project / 'inputs/geoforge_subsets' / state['id']
    parts = state.get('files', [])
    if state['status'] != 'downloaded':
        report['errors'].append('Not an accepted downloaded acquisition; no private temporary files inspected')
        return report
    if not parts:
        report['errors'].append('No saved accepted parts')
    for part in parts:
        name = part.get('name', '')
        item = {'name': name, 'manifest': pick(part, PART_FIELDS), 'errors': []}
        report['files'].append(item)
        if Path(name).name != name or name in {'', '.', '..'}:
            item['errors'].append('Unsafe manifest name')
            continue
        path = folder / name
        if not path.is_file() or not path.resolve().is_relative_to(folder.resolve()):
            item['errors'].append('Missing file or path escaped acquisition')
            continue
        item.update(actual_bytes=path.stat().st_size, actual_sha256=checksum(path))
        item['size_matches'] = item['actual_bytes'] == part.get('bytes')
        item['sha256_matches'] = item['actual_sha256'] == str(part.get('sha256', '')).lower()
        if not item['size_matches'] or not item['sha256_matches']:
            item['errors'].append('File size/hash differs from accepted manifest')
        try:
            if path.suffix.lower() in {'.nc', '.nc4', '.cdf'}:
                item['native'] = inspect_netcdf(path, request, part)
            elif path.suffix.lower() in {'.tif', '.tiff'}:
                item['native'] = inspect_raster(path, request, part)
            else:
                item['errors'].append('Unsupported audit format')
        except Exception as exc:
            # Do not echo exception strings that may contain raw filesystem paths.
            item['errors'].append('Native audit raised ' + type(exc).__name__)
    actual_names = sorted(p.name for p in folder.iterdir() if p.is_file()) if folder.is_dir() else []
    expected_names = sorted(p.get('name', '') for p in parts)
    if actual_names != expected_names:
        report['errors'].append('On-disk file set differs from accepted part manifest')
    wanted = set(request.get('variables') or [])
    delivered = {v for p in parts for v in (p.get('variables') or [p.get('variable')]) if v}
    if wanted and wanted != delivered:
        report['errors'].append('Delivered field union differs from requested fields')
    report['total_bytes'] = sum(f.get('actual_bytes', 0) for f in report['files'])
    report['all_transport_checks_passed'] = bool(parts) and all(f.get('size_matches') and f.get('sha256_matches') for f in report['files'])
    report['structural_error_count'] = len(report['errors']) + sum(len(f['errors']) + len(f.get('native', {}).get('errors', [])) for f in report['files'])
    report['all_masked_fields'] = [{'file': f['name'], 'field': name} for f in report['files']
                                 for name, info in f.get('native', {}).get('variables', {}).items()
                                 if info.get('all_masked_or_nonfinite')]
    report['maize_members'] = [f['name'] for f in report['files']
                               if re.search(r'maize|corn|(?:^|[_\-.])mai[rs](?:[_\-.]|$)', f['name'], re.I)
                               or any('maize' in v.get('long_name', '').lower()
                                      for v in f.get('native', {}).get('variables', {}).values())]
    if request.get('dataset_id') == 'ggcmi_crop_calendar':
        report['source_membership_caveat'] = ('Delivered filenames/count are independently checked. Reasons for members absent from an earlier 40-file inventory require retained source audit/exclusion metadata; count alone does not prove completeness.')
    return report


def markdown(report):
    rows = ['# Native-file EDA audit: GUI-acquired GeoForge subsets', '',
            f"Generated: {report['captured_at_utc']}", '',
            '## Basic information and file types', '',
            'Offline, read-only inspection of accepted project files. NetCDF stores named multidimensional fields; GeoTIFF stores georeferenced raster bands. Readers: netCDF4, NumPy, rasterio. No network, approvals, model runs or project writes.', '',
            '## Data structure, statistics and quality', '',
            '| Dataset | Acquisition | Files | Bytes | Hashes/sizes | Structural errors | Fully masked fields |',
            '|---|---|---:|---:|---|---:|---:|']
    for item in report['acquisitions']:
        rows.append(f"| {item['request']['dataset_id']} | `{item['id']}` | {len(item['files'])} | {item.get('total_bytes', 0)} | {item.get('all_transport_checks_passed', False)} | {item.get('structural_error_count', len(item['errors']))} | {len(item.get('all_masked_fields', []))} |")
    for item in report['acquisitions']:
        rows.extend(['', f"### {item['request']['dataset_id']}", '',
                     f"Request: `{json.dumps(item['request'], sort_keys=True)}`", '',
                     f"Processor version: `{item['estimate'].get('processor_version', 'not retained')}`. App scientific validation: `{item.get('scientific_validation', 'not recorded')}`."])
        for file in item['files']:
            native = file.get('native', {})
            rows.extend(['', f"- `{file['name']}`: {file.get('actual_bytes', '?')} bytes; {native.get('format', 'unread')}."])
            if 'time' in native:
                rows.append('  - Time: `' + json.dumps(native['time'], sort_keys=True) + '`.')
            for name, info in native.get('variables', {}).items():
                rows.append(f"  - `{name}`: shape `{info['shape']}`, units `{info.get('units', '')}`, valid {info.get('valid_count', '?')}/{info['total_count']}, masked {info['masked_count']}; range {info.get('minimum')}–{info.get('maximum')}.")
            for name, info in native.get('bands', {}).items():
                rows.append(f"  - Band {name}: shape `{info['shape']}`, valid {info.get('valid_count', '?')}/{info['total_count']}, masked {info['masked_count']}; range {info.get('minimum')}–{info.get('maximum')}.")
            if native.get('crs'):
                rows.append(f"  - CRS: `{native['crs']}`; bounds `{native['bounds']}`; resolution `{native['resolution']}`.")
            for error in file['errors'] + native.get('errors', []):
                rows.append('  - ERROR: ' + error)
            for warning in native.get('warnings', []):
                rows.append('  - Caveat: ' + warning)
        if item.get('maize_members'):
            rows.extend(['', 'Maize-associated members: ' + ', '.join('`' + v + '`' for v in item['maize_members']) + '.'])
        if item.get('source_membership_caveat'):
            rows.extend(['', item['source_membership_caveat']])
        for error in item['errors']:
            rows.append('ERROR: ' + error)
    rows.extend(['', '## Key findings and recommendations', '',
                 '- Treat byte/hash matching as successful transport, not proof of correct scientific inputs.',
                 '- Fully masked crop/member selections may be authentic source gaps. Do not fill them with invented values; select a documented suitable member/product or report the gap.',
                 '- Unit strings are compared to the manifest, but no conversion is performed. Rate/amount conversions and model-specific units still require explicit preparation.',
                 '- Soil mapping-unit rasters are categorical identifiers, not complete soil profiles; retain nearest-neighbor semantics and obtain the matching property/horizon tables.',
                 '- Metadata, selected field names and local values do not independently establish equality with inaccessible server source pixels.',
                 '- Tiny native-grid clips can have tiny valid payloads. Suitability for a model domain is a separate decision.',
                 '- No plots are needed for one/few-cell smoke tests. For a scientific run, inspect maps, missing-data masks and timeseries over the actual study region.', '',
                 '## Audit software', '', '`' + json.dumps(report['software'], sort_keys=True) + '`', ''])
    return '\n'.join(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--snapshot-only', action='store_true')
    parser.add_argument('--ids', nargs='*')
    args = parser.parse_args()
    project, output = args.project.resolve(), args.output.resolve()
    if output.is_relative_to(project):
        parser.error('Audit output must be outside the project; project files are read-only')
    output.mkdir(parents=True, exist_ok=True)
    if args.snapshot_only:
        target = output / 'baseline-inventory.json'
        if target.exists():
            parser.error('Baseline already exists; refusing to replace it')
        report = snapshot(project)
        target.write_text(json.dumps(serial(report), indent=2, allow_nan=False) + '\n')
        print(json.dumps({'baseline': str(target), 'counts': report['status_counts']}))
        return
    baseline = json.loads(args.baseline.read_text()) if args.baseline else {'acquisitions': []}
    baseline_ids = {s['id'] for s in baseline['acquisitions']}
    selected = [s for s in states(project) if (s['id'] in args.ids if args.ids else s['id'] not in baseline_ids and s['status'] == 'downloaded')]
    report = {'captured_at_utc': datetime.now(timezone.utc).isoformat(),
              'project_name': project.name, 'baseline_ids': sorted(baseline_ids),
              'software': {'python': platform.python_version(), 'numpy': np.__version__,
                           'netCDF4': netCDF4.__version__, 'rasterio': rasterio.__version__},
              'acquisitions': [inspect_state(project, state) for state in selected]}
    (output / 'native-file-audit.json').write_text(json.dumps(serial(report), indent=2, allow_nan=False) + '\n')
    (output / 'native-file-audit.md').write_text(markdown(report))
    print(json.dumps({'audited': [{'id': r['id'], 'dataset': r['request']['dataset_id'],
                                  'files': len(r['files']), 'bytes': r.get('total_bytes'),
                                  'transport_pass': r.get('all_transport_checks_passed'),
                                  'structural_errors': r.get('structural_error_count'),
                                  'all_masked_fields': len(r.get('all_masked_fields', []))}
                                 for r in report['acquisitions']]}))


if __name__ == '__main__':
    main()
