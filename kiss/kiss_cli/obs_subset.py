"""Project-scoped subset delivery. Estimates never authorize jobs or downloads.

Only the browser approval route calls approve(); agent tools may estimate/status.
Downloaded files are transport-verified, never labelled scientifically validated.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path

from . import obs_access as obs
from . import data_contract

MAX_OUTPUT = 2 * 1024**3
PART_OVERHEAD = 64 * 1024     # per-file container overhead allowed above the payload estimate
LOCK = threading.RLock()
_LOCKS = {}
PUBLIC = frozenset(('subsettable snapped_output_bounds estimated_output_bytes '
                   'source_io_bytes transformations over_output_cap delivery_fallback '
                   'coverage_complete missing kind n_parts n_files variables years units_preserved '
                   'calendar_preserved output_grid cell_selection requested_bbox '
                   'native_crs target_crs output_size_px resampling categorical halo_deg '
                   'selection_empty n_selected_cells reason coverage '
                   'schema_version processor_version source_version_hash estimate_id '
                   'processing_version source_version cell_centre_bounds shape spacing_deg '
                   'regular_grid bounds_convention').split())
PART_PUBLIC = frozenset(('n name bytes sha256 bounds crs variables variable year units '
                        'source_version_hash time_range n_time_steps time_subset_applied '
                        'crs_source calendar shape resolution nodata bands layers processor_version '
                        'processing_version source_version cell_centre_bounds bounds_convention '
                        'spacing_deg regular_grid').split())
# obs_subset/3 manifest-level facts kept with the acquisition (no paths, no URLs).
MANIFEST_PUBLIC = frozenset('processing_version source_version time_range n_files'.split())


def _lock(project, ident):
    # Do not serialize unrelated projects/transfers behind one global mutex.
    with LOCK:
        return _LOCKS.setdefault((str(Path(project).resolve()), ident), threading.RLock())


def _receipts():
    from . import flowgate
    return flowgate.load().receipts


def _authorized(project, state):
    auth = state.get('authorization') or {}
    return (auth.get('kind') == 'subset_acquisition_approval'
            and _receipts().verify(Path(project), auth)
            and auth.get('request_sha256') == data_contract.fingerprint(state['request'])
            and auth.get('estimate_sha256') == data_contract.fingerprint(state['estimate'])
            and auth.get('job_id') == state.get('job_id'))


def request_body(value):
    if not isinstance(value, dict):
        raise ValueError('subset request must be an object')
    allowed = {'dataset_id', 'bbox', 'variables', 'start', 'end'}
    if set(value) - allowed:
        raise ValueError('Unsupported subset options; no implicit transformations')
    dataset = str(value.get('dataset_id') or '')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,180}', dataset):
        raise ValueError('Invalid catalogue dataset id')
    raw_box = value.get('bbox')
    if not isinstance(raw_box, list) or len(raw_box) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) for v in raw_box):
        raise ValueError('A valid WGS84 bbox is required')
    box = list(map(float, raw_box))
    if not (-180 <= box[0] < box[2] <= 180 and -90 <= box[1] < box[3] <= 90):
        raise ValueError('Invalid bbox order/range; antimeridian requests need separate boxes')
    obs.local_search([], bbox=box, start=value.get('start'), end=value.get('end'))
    variables = value.get('variables', [])
    if not isinstance(variables, list) or any(not isinstance(v, str) or not re.fullmatch(r'[\w.-]{1,80}', v) for v in variables):
        raise ValueError('variables must be an array of variable names')
    result = {'dataset_id': dataset, 'bbox': box, 'variables': sorted(set(variables))}
    for key in ('start', 'end'):
        if value.get(key):
            result[key] = obs._iso(value[key], end=key == 'end')
    return result


def _root(project):
    root = Path(project).resolve() / '.geoforge' / 'subsets'
    if not root.resolve().is_relative_to(Path(project).resolve()):
        raise ValueError('Subset state escapes project')
    root.mkdir(parents=True, exist_ok=True)
    return root


def _path(project, ident):
    if not re.fullmatch(r'[a-f0-9]{32}', str(ident)):
        raise ValueError('Invalid local subset id')
    return _root(project) / (ident + '.json')


def read(project, ident):
    return json.loads(_path(project, ident).read_text(encoding='utf-8'))


def _save(project, state):
    state['updated_at'] = time.time()
    obs._atomic_json(_path(project, state['id']), state)
    return state


def _pending(state):
    return not state.get('job_id') and state.get('status') in {'awaiting_approval', 'needs_review'}


def candidates(project, dataset_id):
    """Pending clip estimates for one dataset, newest first (the agent's exploration log)."""
    return sorted((s for s in list_states(project)
                   if s['request']['dataset_id'] == dataset_id and _pending(s)),
                  key=lambda s: s.get('created_at', 0), reverse=True)


def _requirement_key(request):
    return {'bbox': request['bbox'], 'start': request.get('start'), 'end': request.get('end'),
            'variable': ','.join(request['variables'])}


def _item_requirements(item):
    req = item.get('requirements') or {}
    if not isinstance(req, dict):
        raise ValueError('Data requirements must be an object')
    out = {}
    if req.get('bbox') is not None:
        box = obs._bbox(req['bbox'])
        if box is None:
            raise ValueError('requirements.bbox is not a valid west,south,east,north box')
        out['bbox'] = list(box)
    for key in ('start', 'end'):
        if req.get(key):
            out[key] = obs._iso(req[key], end=key == 'end')
    if req.get('variable') is not None:
        out['variable'] = obs.variable_terms(req['variable'])
    return out


def _matches(item_req, request):
    want = _requirement_key(request)
    for key, value in item_req.items():
        actual = want[key]
        if key == 'variable':
            actual = obs.variable_terms(actual)
            if not actual:
                continue            # whole-file delivery covers any named variable
        if actual != value:
            return False
    return True


def match_item(project, item):
    """Find the estimate an inventory item refers to. The host does this join.

    Order: an explicit acquisition_id (verified by request hash), then the item's
    requirements against pending estimates of its dataset, then a single pending
    estimate. Anything else is an error that names the candidates.
    """
    dataset = str(item.get('dataset_id') or '')
    if item.get('acquisition_id'):
        state = read(project, item['acquisition_id'])
        request = request_body(state['request'])
        if dataset and dataset != request['dataset_id']:
            raise ValueError('Acquisition dataset differs from the selected inventory dataset')
        want = item.get('acquisition_request_sha256')
        if want and want != data_contract.fingerprint(request):
            fresh = [c for c in candidates(project, request['dataset_id'])
                     if data_contract.fingerprint(c['request']) == want]
            if fresh:
                return fresh[0]
            raise ValueError('Acquisition request changed; estimate the study scope again')
        return state
    if not dataset:
        raise ValueError('An acquisition needs a dataset_id')
    pool = candidates(project, dataset)
    if not pool:
        raise ValueError(f'no clip estimate on file for {dataset}; call estimate_clip for the study bbox first')
    req = _item_requirements(item)
    hits = [c for c in pool if _matches(req, c['request'])] if req else []
    if len(hits) >= 1:
        return hits[0]
    distinct = {data_contract.fingerprint(c['request']): c for c in pool}
    if len(distinct) == 1:
        return pool[0]
    listing = '; '.join(f"{c['id'][:8]} bbox={c['request']['bbox']} {c['request'].get('start') or ''}"
                        f"..{c['request'].get('end') or ''} vars={','.join(c['request']['variables']) or 'all'}"
                        for c in list(distinct.values())[:6])
    raise ValueError(f'{len(distinct)} different clip estimates exist for {dataset}; put the chosen '
                     f'acquisition_id on the item or give requirements that match one: {listing}')


def stamp_item(project, item):
    """Bind an inventory item to one clip estimate before plan review.

    Writes only stable facts on the item (request hash, size, versions), never the
    whole estimate, so a benign re-estimate does not change the approval hash.
    """
    state = match_item(project, item)
    request = request_body(state['request'])
    req = _item_requirements(item)
    if req and not _matches(req, request):
        bad = next(k for k in req if not _matches({k: req[k]}, request))
        raise ValueError(f'Acquisition {bad} differs from the scientific data requirement')
    offer = data_contract.normalize_estimate(request, state['estimate'], MAX_OUTPUT)
    if offer['blockers']:
        raise ValueError('Acquisition is blocked: ' + ', '.join(offer['blockers']))
    est = state['estimate']
    item.update(dataset_id=request['dataset_id'], delivery='subset',
                acquisition_id=state['id'], acquisition_request_sha256=offer['request_sha256'],
                status='resolved', agent_resolvable=True, needs_user=False,
                requirements={**(item.get('requirements') or {}),
                              **{k: v for k, v in _requirement_key(request).items() if v is not None}},
                catalogue={'name': request['dataset_id'], 'size': est.get('estimated_output_bytes')},
                acquisition_offer={k: offer[k] for k in ('eligible', 'inspection_allowed', 'coverage', 'blockers', 'warnings')},
                estimate_summary={'bytes': est.get('estimated_output_bytes'),
                                  'n_parts': est.get('n_parts') or est.get('n_files'),
                                  'processing_version': est.get('processing_version'),
                                  'source_version': est.get('source_version')})
    return state


def prefer_clip(project, item, record, *, client=None) -> bool:
    """Turn a large or manual catalogue pin into a server clip when the server can.

    Runs at plan submission for items that carry a study bbox. One read-only
    estimate; on 'subsettable' with an eligible or inspection-only offer the item
    becomes a subset acquisition. Any failure leaves the pin as it was."""
    req = item.get('requirements') or {}
    if not isinstance(req, dict) or not req.get('bbox'):
        return False
    size = record.get('size')
    if record.get('delivery') != 'manual' and not (isinstance(size, int) and size > obs.MAX_SERVED_BYTES):
        return False
    try:
        body = {'dataset_id': str(item.get('dataset_id')), 'bbox': list(obs._bbox(req['bbox']) or []),
                'variables': obs.variable_terms(req.get('variable')) if req.get('variable') else []}
        for key in ('start', 'end'):
            if req.get(key):
                body[key] = obs._iso(req[key], end=key == 'end')
        if not body['bbox']:
            return False
        for c in candidates(project, body['dataset_id']):
            if _matches(_item_requirements(item), c['request']):
                state = c
                break
        else:
            state = estimate(project, body, client=client)
            if body['variables'] and (state.get('failure') or {}).get('code') == 'variable_selection_unsupported':
                # whole-file raster (hwsd, DEMs): the server clips the bbox but not bands
                body['variables'] = []
                state = estimate(project, body, client=client)
    except (ValueError, TypeError, OSError, obs.ObsAccessError):
        return False
    if state.get('status') not in {'awaiting_approval', 'needs_review'}:
        return False
    offer = state.get('offer') or {}
    if not (offer.get('eligible') or offer.get('inspection_allowed')):
        return False
    try:
        item['acquisition_id'] = state['id']
        stamp_item(project, item)
    except (ValueError, OSError, KeyError):
        item.pop('acquisition_id', None)
        return False
    return True


def refresh_estimate(project, ident, *, client=None):
    """Re-run a pending (or previously failed) estimate in place, same id."""
    with _lock(project, ident):
        state = read(project, ident)
        if state.get('job_id') or not (_pending(state) or state.get('status') == 'estimate_failed'):
            return state
        state['request'] = request_body(state['request'])
        return _estimate_attempt(project, state, client=client)


SIZE_TOLERANCE = (0.10, 16 * 1024**2)     # +10 % or 16 MB, whichever is larger


def changed_since_review(summary, state):
    """Why a fresh estimate no longer matches what the user reviewed (empty = unchanged)."""
    est = state.get('estimate') or {}
    reasons = []
    if state.get('status') == 'estimate_failed':
        return [state.get('error') or 'estimate failed']
    for key in ('processing_version', 'source_version'):
        if summary.get(key) and est.get(key) and summary[key] != est[key]:
            reasons.append(f'{key} {summary[key]} -> {est[key]}')
    before, after = summary.get('bytes'), est.get('estimated_output_bytes')
    if type(before) is int and type(after) is int:
        if after > before + max(before * SIZE_TOLERANCE[0], SIZE_TOLERANCE[1]):
            reasons.append(f'size {obs.size_label(before)} -> {obs.size_label(after)}')
    offer = data_contract.normalize_estimate(state['request'], est, MAX_OUTPUT)
    if offer['blockers']:
        reasons.append('blocked: ' + ', '.join(offer['blockers']))
    return reasons


def refresh_inventory(project, inventory, *, client=None):
    """Fresh estimates for every clip item; returns {item_id: [reasons]} for changed ones."""
    changed = {}
    for item in (inventory or {}).get('items') or []:
        if not isinstance(item, dict) or not item.get('acquisition_id'):
            continue
        try:
            state = refresh_estimate(project, item['acquisition_id'], client=client)
        except (OSError, ValueError, KeyError) as error:
            changed[item.get('id')] = [str(error)]
            continue
        reasons = changed_since_review(item.get('estimate_summary') or {}, state)
        if reasons:
            changed[item.get('id')] = reasons
    return changed


def approve_inventory(project, inventory, *, client=None):
    """Create the server job for every clip item of a just-approved plan.

    The plan approval is the user's consent; this is its consequence. A failed
    job creation is reported per item and never blocks the others.
    """
    results = []
    for item in (inventory or {}).get('items') or []:
        if not isinstance(item, dict) or not item.get('acquisition_id'):
            continue
        ident = item['acquisition_id']
        try:
            state = read(project, ident)
            offer = data_contract.normalize_estimate(state['request'], state['estimate'], MAX_OUTPUT)
            accepted = approve(project, ident, client=client, inspection=not offer['eligible'])
            results.append({'item': item.get('id'), 'ok': True, 'status': accepted['status']})
        except (OSError, ValueError, KeyError, obs.ObsAccessError) as error:
            results.append({'item': item.get('id'), 'ok': False, 'error': str(error)})
    return results


def presentation(project):
    """What Project status shows: jobs of this project and the estimate log. No approvals here."""
    states = list_states(project)
    public = lambda s: {k: v for k, v in s.items() if k not in {'authorization', 'acquisition_receipt', 'bound_receipts'}}
    active = sorted((public(s) for s in states if s.get('job_id')), key=lambda s: s.get('approved_at', 0), reverse=True)
    estimates = sorted((public(s) for s in states if not s.get('job_id')), key=lambda s: s.get('created_at', 0), reverse=True)
    return {'active': active, 'estimates': estimates}


def verified_acquisition(project, state):
    """Return signed, intact asset evidence; never trust agent-editable paths."""
    project = Path(project).resolve()
    doc = state.get('acquisition_receipt') or {}
    r = _receipts()
    if (doc.get('kind') != 'subset_acquisition' or not r.verify(project, doc) or not _authorized(project, state)
            or doc.get('acquisition_id') != state.get('id')
            or doc.get('job_id') != state.get('job_id')
            or doc.get('request_sha256') != data_contract.fingerprint(state['request'])):
        raise ValueError('Acquisition evidence is missing or changed; re-acquire or inspect legacy files')
    directory = (project / str(doc.get('path') or '')).resolve()
    if not directory.is_relative_to(project / 'inputs'):
        raise ValueError('Acquisition path escapes project inputs')
    files = doc.get('files') or []
    if not files:
        raise ValueError('Acquisition evidence has no files')
    for part in files:
        path = (directory / part['name']).resolve()
        if (not path.is_relative_to(directory) or not path.is_file()
                or path.stat().st_size != part['bytes'] or r.sha256_file(path) != part['sha256']):
            raise ValueError('Acquired file is missing or changed; input is not ready')
    return doc


def bind_approved(project, ident=None):
    """Attach acquired files to the approved inventory without editing that inventory.

    Safe to retry after acquisition or plan approval. Both provider paths use the
    same signed receipts and append-only progress updates.
    """
    from . import flowgate
    project = Path(project).resolve()
    flow = flowgate.load()
    if flow.approval.check(project) != 'OK':
        return []
    plan, inventory = flow.plan.read_artifacts(project)
    approved = flow.approval.approval_id(flow.approval.read(project))
    bound = []
    for item in inventory.get('items') or []:
        aid = item.get('acquisition_id')
        if not aid or (ident and aid != ident):
            continue
        with _lock(project, aid):
            state = read(project, aid)
            if state.get('status') != 'downloaded':
                continue
            checked = json.loads(json.dumps(item))
            stamp_item(project, checked)
            if flow.receipts.selection_sha256(checked) != flow.receipts.selection_sha256(item):
                raise ValueError('Acquisition selection was not included in the approved plan')
            doc = verified_acquisition(project, state)
            steps = [s for s in plan.get('steps') or [] if item['id'] in (s.get('inputs') or [])]
            if not steps:
                raise ValueError('No approved step consumes this acquisition')
            step = next((s for s in steps if s.get('kind') == 'download'), steps[0])
            existing = [p for p, d, ok in flow.receipts._read_all(project, flow.receipts.DATA_SUB)
                        if ok and d.get('approval_sha256') == approved
                        and d.get('plan_step_id') == step['id']
                        and d.get('item_id') == item['id']
                        and flow.receipts._download_still_valid(project, d, inventory)]
            if existing:
                bound.append(str(existing[-1]))
                continue
            directory = project / doc['path']
            receipt = flow.receipts.record_download(
                project, item_id=item['id'], source='GeoForge Database subset',
                request_url=f"{obs.BASE_URL}/subsets/jobs/{doc['job_id']}/manifest",
                http_status=200, raw_files=[directory / p['name'] for p in doc['files']],
                approval_sha256=approved, plan_step_id=step['id'], inventory_item=item,
                acquisition=doc)
            bound.append(str(receipt))
    if ident is None:
        obs._atomic_json(project / '.geoforge/data-binding-status.json', {'status': 'ok'})
    return bound


def _approved_item_for(project, ident):
    """The approved inventory item that names this acquisition, or None."""
    from . import flowgate
    flow = flowgate.load()
    if flow.approval.check(Path(project)) != 'OK':
        return None
    _plan, inventory = flow.plan.read_artifacts(Path(project))
    for item in (inventory or {}).get('items') or []:
        if isinstance(item, dict) and item.get('acquisition_id') == ident:
            return item
    return None


def advance_approved(project, ident, *, client=None):
    """Provider-neutral progress for a plan-approved subset (plan approval is the consent)."""
    state = read(project, ident)
    if not state.get('job_id') and _pending(state) and _approved_item_for(project, ident):
        # The Approve click normally creates the job; do it here if that failed.
        offer = data_contract.normalize_estimate(state['request'], state['estimate'], MAX_OUTPUT)
        approve(project, ident, client=client, inspection=not offer['eligible'])
        state = read(project, ident)
    if not _authorized(project, state):
        raise ValueError('This clip is not part of the approved plan; add it to the inventory and get the plan approved')
    state = refresh(project, ident, client=client)
    if state['status'] in {'ready', 'downloaded'}:
        state = download(project, ident, client=client)
    bound = bind_approved(project, ident)
    # Reconcile prior plan-approval diagnostics after the requested acquisition
    # succeeds. Do not hide problems in another selected input.
    if bound:
        bind_approved(project)
    return {'delivery': 'subset', 'served': True, 'acquisition_id': ident,
            'dataset_id': state['request']['dataset_id'], 'status': state['status'],
            'scientific_validation': 'pending', 'receipt': bound[0] if bound else None,
            'path': state.get('path'),
            'next_action': 'validate_and_prepare' if bound else 'poll_or_review_project_status'}


def list_states(project):
    states = []
    for p in sorted(_root(project).glob('*.json')):
        try:
            state = json.loads(p.read_text(encoding='utf-8'))
            if isinstance(state, dict) and state.get('id') == p.stem and re.fullmatch(r'[a-f0-9]{32}', p.stem):
                request_body(state['request'])
                if not isinstance(state.get('estimate'), dict):
                    continue
                states.append(state)
        except (OSError, ValueError, KeyError, TypeError):
            continue  # One damaged state must not hide every other acquisition.
    return states


def _estimate_attempt(project, state, *, client=None):
    """Keep failed read-only requests visible; never turn failure into approval."""
    body = state['request']
    state['attempted_at'] = time.time()
    state['attempts'] = state.get('attempts', 0) + 1
    try:
        raw = (client or obs.Client())._json('/subsets/estimate', method='POST', body=body)
        if not isinstance(raw, dict) or type(raw.get('subsettable')) is not bool:
            raise ValueError('Invalid subset estimate')
    except (obs.ObsAccessError, ValueError, TypeError, OSError) as error:
        code = error.code if isinstance(error, obs.ObsAccessError) else 'invalid_response'
        # Do not persist server bodies, URLs, credentials or private source paths.
        if code not in obs.ERROR_MESSAGES:
            code = 'request_failed' if isinstance(error, obs.ObsAccessError) else 'invalid_response'
        status = getattr(error, 'status', None)
        message = obs.ERROR_MESSAGES.get(code, 'GeoForge Database could not provide a valid subset estimate.')
        if type(status) is int and 100 <= status < 600:
            message += f' HTTP {status}.'
        else:
            status = None
        state.update(status='estimate_failed', eligible=False, estimate={},
                     offer={'eligible': False, 'inspection_allowed': False,
                            'coverage': {'overall': 'unknown'},
                            'blockers': ['estimate_unavailable']},
                     failure={'stage': 'estimate', 'code': code, 'http_status': status},
                     error=message, next_action=('describe_and_revise' if code in ('unknown_variable', 'variable_selection_unsupported') else 'retry_estimate'),
                     acquisition_verified=False)
        return _save(project, state)
    summary = {k: v for k, v in raw.items() if k in PUBLIC}
    if 'reason' in summary and not re.fullmatch(r'[a-zA-Z0-9_ .-]{1,120}', str(summary['reason'])):
        summary['reason'] = 'server_reported_issue'
    offer = data_contract.normalize_estimate(body, summary, MAX_OUTPUT)
    for key in ('failure', 'error', 'next_action', 'acquisition_verified'):
        state.pop(key, None)
    state.update(offer=offer, estimate=summary,
                 status='awaiting_approval' if offer['eligible'] else 'needs_review',
                 created_at=time.time(), eligible=offer['eligible'])
    return _save(project, state)


def estimate(project, body, *, client=None):
    state = {'id': uuid.uuid4().hex, 'request': request_body(body), 'created_at': time.time()}
    return _estimate_attempt(project, state, client=client)


def retry_estimate(project, ident, *, client=None):
    """Explicit retry of the same failed scope; success still needs user approval."""
    with _lock(project, ident):
        state = read(project, ident)
        if state.get('status') != 'estimate_failed':
            raise ValueError('Only a failed estimate can be retried here')
        if any(state.get(k) for k in ('authorization', 'job_id', 'acquisition_receipt')):
            raise ValueError('An existing job cannot be replaced by an estimate retry')
        state['request'] = request_body(state['request'])
        return _estimate_attempt(project, state, client=client)


def approve(project, ident, *, client=None, inspection=False, expected=None):
    with _lock(project, ident):
        state = read(project, ident)
        if expected is not None and (
                expected.get('request_sha256') != data_contract.fingerprint(state['request'])
                or expected.get('estimate_sha256') != data_contract.fingerprint(state['estimate'])):
            raise ValueError('Acquisition changed since the proposal was reviewed')
        if state.get('job_id'):
            if not _authorized(project, state):
                raise ValueError('Unverified legacy/changed acquisition; estimate and approve again')
            return state
        if state.get('status') not in {'awaiting_approval', 'needs_review'}:
            raise ValueError('Request a new estimate before approving this acquisition')
        offer = data_contract.normalize_estimate(state['request'], state['estimate'], MAX_OUTPUT)
        if not (offer['eligible'] or (inspection is True and offer['inspection_allowed'])):
            raise ValueError('Only an eligible estimate can be approved')
        raw = (client or obs.Client())._json('/subsets/jobs', method='POST', body=state['request'])
        job = str(raw.get('job_id') or '')
        if not re.fullmatch(r'[\w-]{1,150}', job):
            raise ValueError('Invalid server job id')
        state.update(job_id=job, status='queued', approved_at=time.time(), offer=offer)
        state['authorization'] = _receipts().sign(Path(project), {
            'kind': 'subset_acquisition_approval', 'request_sha256': offer['request_sha256'],
            'estimate_sha256': offer['estimate_sha256'], 'job_id': job,
            'mode': 'inspection' if inspection else 'acquire', 'approved_at': state['approved_at']})
        return _save(project, state)


def refresh(project, ident, *, client=None):
    with _lock(project, ident):
        state = read(project, ident)
        if not state.get('job_id') or state['status'] == 'downloaded':
            return state
        if not _authorized(project, state):
            raise ValueError('Acquisition approval is missing or changed')
        raw = (client or obs.Client())._json('/subsets/jobs/' + state['job_id'])
        status = raw.get('status')
        if status not in {'queued', 'running', 'ready', 'failed', 'cancelled', 'expired'}:
            raise ValueError('Unrecognized server status')
        state.update(status=status, stage=str(raw.get('stage') or ''),
                     total_bytes=raw.get('total_bytes'), n_parts=raw.get('n_parts'))
        # Do not persist raw backend errors, which may contain source paths.
        if status == 'failed':
            state['error'] = 'Server subset job failed; inspect backend logs with the job id.'
        return _save(project, state)


def cancel(project, ident, *, client=None):
    with _lock(project, ident):
        state = read(project, ident)
        if state.get('job_id'):
            if not _authorized(project, state):
                raise ValueError('Acquisition approval is missing or changed')
            (client or obs.Client())._json('/subsets/jobs/' + state['job_id'] + '/cancel', method='POST', body={})
        state['status'] = 'cancelled'
        return _save(project, state)


def download(project, ident, *, client=None):
    """Download all parts, bounded and checksum-verified; publish only after all pass."""
    client = client or obs.Client()
    with _lock(project, ident):
        state = refresh(project, ident, client=client)
        if state['status'] == 'downloaded':
            verified_acquisition(project, state)
            state['bound_receipts'] = bind_approved(project, ident)
            state.pop('binding_error', None)
            return _save(project, state)
        if state['status'] != 'ready' or not state.get('approved_at'):
            raise ValueError('An approved, ready job is required')
        if data_contract.normalize_estimate(state['request'], state['estimate'], MAX_OUTPUT)['blockers']:
            raise ValueError('The previously approved selection is not confirmed; obtain a corrected estimate and review before downloading')
        route = '/subsets/jobs/' + state['job_id']
        manifest = client._json(route + '/manifest')
        if manifest.get('job_id') != state['job_id'] or manifest.get('dataset_id') != state['request']['dataset_id'] or manifest.get('ready') is not True:
            raise ValueError('Manifest does not belong to the approved job/dataset')
        parts = manifest.get('parts')
        if not isinstance(parts, list) or not parts:
            raise ValueError('Manifest has no parts')
        if manifest.get('n_parts') != len(parts) or state['estimate'].get('n_parts', len(parts)) != len(parts):
            raise ValueError('Manifest part count differs from estimate')
        total = 0
        names = set()
        indices = set()
        for part in parts:
            name = part.get('name', '')
            if not re.fullmatch(r'[\w.-]{1,200}', name) or name in {'.', '..'} or name in names:
                raise ValueError('Unsafe or duplicate part filename')
            names.add(name)
            index = part.get('n')
            if type(index) is not int or index < 0 or index in indices:
                raise ValueError('Invalid or duplicate part index')
            indices.add(index)
            size = part.get('bytes')
            if type(size) is not int or size < 0 or not re.fullmatch(r'[a-fA-F0-9]{64}', str(part.get('sha256', ''))):
                raise ValueError('Invalid manifest size/checksum')
            total += size
        if manifest.get('total_bytes') != total:
            raise ValueError('Manifest total does not match its parts')
        for key in ('processing_version', 'source_version'):
            if state['estimate'].get(key) and manifest.get(key) and manifest[key] != state['estimate'][key]:
                raise ValueError(f'Server {key} changed after approval; re-estimate and review before downloading')
        unreadable = manifest.get('unreadable_files') or []
        if not isinstance(unreadable, list) or any(not isinstance(v, str) for v in unreadable):
            raise ValueError('Invalid manifest unreadable_files')
        unreadable = sorted({Path(v).name[:120] for v in unreadable if Path(v).name})
        summary = {k: manifest[k] for k in MANIFEST_PUBLIC if k in manifest
                   and isinstance(manifest[k], (str, int)) or (
                       k == 'time_range' and isinstance(manifest.get(k), list)
                       and all(isinstance(v, str) for v in manifest[k]))}
        summary['unreadable_files'] = unreadable
        # obs_subset/3 skips unreadable members instead of failing the job. The
        # estimate's member count is the promise; a shorter manifest is partial
        # even when the server forgets to list the skipped members.
        expected_files = state['estimate'].get('n_files')
        summary['missing_members'] = (expected_files - len(parts)
                                      if type(expected_files) is int and expected_files > len(parts) else 0)
        if summary['missing_members'] and expected_files:
            summary['n_files'] = expected_files
        scope = data_contract.check_manifest_scope(state['request'], state['estimate'], parts)
        # The server estimates array payload; every NetCDF/GeoTIFF part carries its own
        # header (about 25 KB for a single-cell CMFD file, 176 of them for 22 years).
        budget = state['estimate']['estimated_output_bytes'] * 2 + 1024**2 + PART_OVERHEAD * len(parts)
        if total > MAX_OUTPUT or total > budget:
            raise ValueError(f'Actual output {total} bytes exceeds the approval budget {budget} bytes; '
                             're-estimate before downloading')
        parent = Path(project).resolve() / 'inputs' / 'geoforge_subsets'
        if not parent.resolve().is_relative_to(Path(project).resolve()):
            raise ValueError('Download destination escapes project')
        parent.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(parent).free < total + 32 * 1024**2:
            raise ValueError('Insufficient local disk space for the complete verified acquisition')
        target = parent / ident
        if target.exists():
            # A previous attempt published the files but failed to record them:
            # re-verify against the signed acquisition receipt instead of refusing forever.
            doc = state.get('acquisition_receipt') or {}
            if doc and _receipts().verify(Path(project), doc):
                state.update(status='downloaded', path=str(target))
                verified_acquisition(project, state)
                state['bound_receipts'] = bind_approved(project, ident)
                return _save(project, state)
            raise ValueError(f'Destination {target} already exists without acquisition evidence; '
                             'move it away and retry')
        state.update(status='downloading', received_bytes=0)
        state.pop('error', None)
        _save(project, state)
        try:
            with tempfile.TemporaryDirectory(prefix='.subset-', dir=parent) as temp:
                receipts = []
                for index, part in enumerate(parts):
                    digest, received = hashlib.sha256(), 0
                    with client._request(route + '/parts/' + str(part['n'])) as response, open(Path(temp) / part['name'], 'wb') as out:
                        header = response.headers.get('X-Content-SHA256', '').lower()
                        if header != part['sha256'].lower():
                            raise ValueError('Part header does not match manifest checksum')
                        for chunk in iter(lambda: response.read(1024**2), b''):
                            received += len(chunk)
                            if received > part['bytes']:
                                raise ValueError('Part exceeded manifest size')
                            digest.update(chunk)
                            out.write(chunk)
                            state['received_bytes'] += len(chunk)
                            _save(project, state)
                    if received != part['bytes'] or digest.hexdigest() != part['sha256'].lower():
                        raise ValueError('Part size or SHA-256 mismatch')
                    receipts.append({**{k: part[k] for k in PART_PUBLIC if k in part},
                                     'sha256': part['sha256'].lower()})
                content = data_contract.inspect_native_files(temp, state['request'], receipts)
                if unreadable or summary['missing_members']:
                    # A partial member delivery is never "complete": the KI must
                    # decide whether the skipped members matter for this study.
                    content['pending'] = sorted(set(content['pending']) | {'members_missing'})
                    content['status'] = 'pending'
                acquisition_receipt = _receipts().sign(Path(project), {
                    'kind': 'subset_acquisition', 'acquisition_id': ident, 'job_id': state['job_id'],
                    'request': state['request'], 'request_sha256': data_contract.fingerprint(state['request']),
                    'files': receipts, 'path': str(target.relative_to(Path(project).resolve())),
                    'scope_validation': scope, 'content_validation': content, 'scientific_validation': 'pending',
                    'manifest': summary, 'downloaded_at': time.time()})
                os.rename(temp, target)
            state.update(status='downloaded', files=receipts, path=str(target),
                         scientific_validation='pending', scope_validation=scope,
                         content_validation=content, manifest=summary, verified_bytes=total)
            state['acquisition_receipt'] = acquisition_receipt
            _save(project, state)
            try:
                state['bound_receipts'] = bind_approved(project, ident)
                state.pop('binding_error', None)
            except (ValueError, OSError, KeyError):
                state['binding_error'] = 'Files acquired, but plan binding failed. Review the selected request and file evidence.'
            _save(project, state)
            return state
        except Exception:
            message = ('Verified files were published but recording failed; preserve the folder and repair acquisition evidence.'
                       if target.exists() else 'Download not accepted; no partial inputs published. Retry status before downloading again.')
            state.update(status='download_failed', error=message)
            _save(project, state)
            raise
