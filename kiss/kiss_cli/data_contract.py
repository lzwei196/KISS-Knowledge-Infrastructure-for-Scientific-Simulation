"""Provider-neutral delivery contract; no dataset IDs or model-specific rules.

Normalizes legacy subset responses without inventing missing coverage. An
inspection approval authorizes acquisition only, never scientific readiness.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def normalize_estimate(request, estimate, max_bytes):
    blockers, warnings = [], []
    for flag in ('subsettable', 'over_output_cap', 'coverage_complete', 'selection_empty'):
        if estimate.get(flag) is not None and type(estimate[flag]) is not bool:
            blockers.append('invalid_' + flag)
    if ('n_selected_cells' in estimate and estimate['n_selected_cells'] is not None
            and (type(estimate['n_selected_cells']) is not int or estimate['n_selected_cells'] < 0)):
        blockers.append('invalid_selected_cell_count')
    size = estimate.get('estimated_output_bytes')
    if estimate.get('subsettable') is not True:
        blockers.append('unsupported_subset')
    if type(size) is not int or size <= 0:
        blockers.append('empty_or_unknown_size')
    elif size > max_bytes:
        blockers.append('over_output_cap')
    if estimate.get('over_output_cap') is not False:
        blockers.append('output_budget_unconfirmed')
    if estimate.get('selection_empty') is True or estimate.get('n_selected_cells') == 0:
        blockers.append('empty_selection')
    if estimate.get('transformations'):
        blockers.append('transformations_require_new_contract')
    # An explicit variable request must never silently widen to "all" or be
    # accepted as a different selection. Missing confirmation is also a blocker:
    # an unsupported raster selector must not turn into a whole-raster approval.
    wanted = request.get('variables') or []
    reported = estimate.get('variables')
    if wanted and reported is not None:
        if (not isinstance(reported, list)
                or any(not isinstance(v, str) for v in reported)
                or set(reported) != set(wanted)):
            blockers.append('variable_selection_mismatch')
    elif wanted:
        blockers.append('variable_selection_unconfirmed')
    coverage = ('complete' if estimate.get('coverage_complete') is True else
                'partial' if estimate.get('coverage_complete') is False else 'unknown')
    if estimate.get('missing') or coverage == 'partial':
        blockers.append('incomplete_coverage')
    if coverage == 'unknown':
        warnings.append('coverage_unknown_inspection_only')
    return {
        'schema_version': 'geoforge.data-offer.v1',
        'request_sha256': fingerprint(request), 'estimate_sha256': fingerprint(estimate),
        'coverage': {'overall': coverage,
                     'temporal': 'not_applicable' if not (request.get('start') or request.get('end')) else coverage},
        'blockers': sorted(set(blockers)), 'warnings': warnings,
        'eligible': not blockers and coverage == 'complete',
        'inspection_allowed': not blockers and coverage == 'unknown',
    }


def _box(value):
    if (not isinstance(value, (list, tuple)) or len(value) != 4
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in value)):
        return None
    return list(value) if value[0] < value[2] and value[1] < value[3] else None


def _geographic(crs):
    return str(crs).upper() in {'EPSG:4326', 'OGC:CRS84', 'CRS84'}


def check_manifest_scope(request, estimate, parts):
    """Reject contradictory public metadata; absent facts remain explicitly unknown.

    This is not file-content validation or proof of model suitability. Asset
    partitioning (variables, years, tiles, bands) is not inferred from ID syntax.
    """
    pending = []
    wanted = set(request.get('variables') or [])
    actual = set()
    for part in parts:
        variables = part.get('variables') or ([part['variable']] if part.get('variable') else [])
        if not isinstance(variables, list) or any(not isinstance(v, str) for v in variables):
            raise ValueError('Invalid manifest variable list')
        actual.update(variables)
        period = part.get('time_range')
        if period is not None:
            if not isinstance(period, list) or len(period) != 2 or any(not isinstance(v, str) for v in period):
                raise ValueError('Invalid manifest time range')
            # ISO calendar dates can be compared without silently coercing a
            # source's non-Gregorian calendar to Python datetime.
            first, last = (v[:10] for v in period)
            if not all(re.fullmatch(r'\d{4}-\d{2}-\d{2}', v) for v in (first, last)):
                raise ValueError('Invalid manifest ISO time range')
            if first > last or (request.get('start') and first < request['start']) or (request.get('end') and last > request['end']):
                raise ValueError('Manifest time range differs from the approved request')
        elif request.get('start') or request.get('end'):
            pending.append('actual_time_range_unknown')
        if part.get('n_time_steps') == 0:
            raise ValueError('Manifest contains an empty time selection')
        bounds = _box(part.get('bounds'))
        if part.get('bounds') is not None and bounds is None:
            raise ValueError('Invalid manifest bounds')
        expected = _box(estimate.get('snapped_output_bounds'))
        # A supplied snapped grid is a promised result extent. Native projected
        # coordinates are never compared numerically to a WGS84 request.
        same_frame = (part.get('crs') and part.get('crs') == estimate.get('native_crs'))
        if expected and bounds and (same_frame or _geographic(part.get('crs'))):
            if any(abs(a-b) > 1e-6 for a, b in zip(expected, bounds)):
                raise ValueError('Manifest bounds differ from the estimated output grid')
        elif bounds and _geographic(part.get('crs')):
            box = request['bbox']
            if bounds[2] <= box[0] or bounds[0] >= box[2] or bounds[3] <= box[1] or bounds[1] >= box[3]:
                raise ValueError('Manifest bounds do not intersect the approved request')
            pending.append('exact_output_grid_unconfirmed')
        else:
            pending.append('output_bounds_or_crs_unknown')
        if str(part.get('crs_source', '')).startswith('derived'):
            pending.append('source_crs_inferred')
    if wanted and actual and wanted != actual:
        raise ValueError('Manifest variables differ from the approved request')
    if wanted and not actual:
        pending.append('actual_variables_unknown')
    # Some legacy readers explicitly advertise an annual variable partition.
    # Validate that advertised partition without making it an ID/kind rule.
    if estimate.get('variables') and estimate.get('years'):
        expected = {(v, y) for v in estimate['variables'] for y in estimate['years']}
        delivered = {(p.get('variable'), p.get('year')) for p in parts}
        if not expected.issubset(delivered):
            raise ValueError('Manifest omits advertised variable/year parts')
    return {'status': 'pending' if pending else 'passed', 'pending': sorted(set(pending)),
            'note': 'Manifest scope checks only; actual file and KI input validation remain required.'}


def inspect_native_files(directory, request, parts):
    """Read actual native files, catching wrong-format/time/variable deliveries.

    Optional readers fail to *pending*, never to scientific pass. This limited
    inspection is not source-cell parity, full missing-data QA, or a KI adapter.
    """
    facts, pending = [], []
    for part in parts:
        path = Path(directory) / part['name']
        fact = {'name': part['name']}
        declared = part.get('variables') or ([part['variable']] if part.get('variable') else [])
        if path.suffix.lower() in {'.nc', '.nc4', '.cdf'}:
            try:
                import netCDF4
            except (ImportError, OSError):
                pending.append('netcdf_reader_unavailable')
                continue
            try:
                with netCDF4.Dataset(path) as ds:
                    fact['variables'] = list(ds.variables)
                    if not set(declared).issubset(ds.variables):
                        raise ValueError('Actual NetCDF variables contradict the manifest')
                    fact['units'] = {v: str(getattr(ds.variables[v], 'units', '')) for v in declared}
                    tv = next((v for n, v in ds.variables.items()
                               if n.lower() == 'time' or getattr(v, 'axis', '') == 'T'), None)
                    if tv is not None and tv.ndim == 1 and hasattr(tv, 'units'):
                        if tv.size == 0:
                            raise ValueError('Actual NetCDF time selection is empty')
                        dates = netCDF4.num2date([tv[0], tv[-1]], tv.units,
                                                calendar=getattr(tv, 'calendar', 'standard'))
                        fact.update(time_range=[d.strftime('%Y-%m-%d') for d in dates],
                                    n_time_steps=int(tv.size), calendar=getattr(tv, 'calendar', 'standard'))
                        first, last = fact['time_range']
                        if (first > last or (request.get('start') and first < request['start'])
                                or (request.get('end') and last > request['end'])):
                            raise ValueError('Actual NetCDF time range exceeds the approved request')
                        if part.get('n_time_steps') is not None and part['n_time_steps'] != tv.size:
                            raise ValueError('Actual NetCDF time count contradicts the manifest')
                        if part.get('time_range') and [t[:10] for t in part['time_range']] != fact['time_range']:
                            raise ValueError('Actual NetCDF dates contradict the manifest')
                    elif request.get('start') or request.get('end'):
                        pending.append('file_time_axis_unconfirmed')
            except (OSError, RuntimeError) as error:
                raise ValueError('Downloaded NetCDF cannot be read; files were not accepted') from error
        elif path.suffix.lower() in {'.tif', '.tiff'}:
            with path.open('rb') as stream:
                magic = stream.read(4)
            if magic not in {b'II*\x00', b'MM\x00*', b'II+\x00', b'MM\x00+'}:
                raise ValueError('Downloaded TIFF has an invalid file header')
            try:
                import rasterio
            except (ImportError, OSError):
                pending.append('raster_reader_unavailable')
                continue
            try:
                with rasterio.open(path) as ds:
                    if not ds.width or not ds.height or not ds.count:
                        raise ValueError('Downloaded raster is empty')
                    fact.update(shape=[ds.count, ds.height, ds.width], bounds=list(ds.bounds),
                                crs=str(ds.crs) if ds.crs else None)
                    if ds.crs is None:
                        pending.append('file_crs_unknown')
                    if part.get('bounds') and any(abs(a-b) > 1e-5 for a, b in zip(part['bounds'], ds.bounds)):
                        raise ValueError('Actual raster bounds contradict the manifest')
            except rasterio.errors.RasterioError as error:
                raise ValueError('Downloaded raster cannot be read; files were not accepted') from error
        else:
            pending.append('native_format_requires_ki_inspection')
        facts.append(fact)
    return {'status': 'pending' if pending else 'passed', 'files': facts,
            'pending': sorted(set(pending)),
            'note': 'File structure and reported scope only; full scientific/KI input validation is still pending.'}
