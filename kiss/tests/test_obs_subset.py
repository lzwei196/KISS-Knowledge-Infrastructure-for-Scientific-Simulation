import hashlib
import io
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

from kiss_cli import obs_subset as s
from kiss_cli.obs_access import Client
from .test_obs_access import Opener, Response, json_response


BODY = {'dataset_id': 'cmfd_china_daily_010', 'bbox': [115,37,117,39],
        'variables': ['prec'], 'start': '1989-01-01', 'end': '1989-12-31'}
EST = {'subsettable': True, 'estimated_output_bytes': 100, 'over_output_cap': False,
       'coverage_complete': True, 'missing': [], 'transformations': [],
       'snapped_output_bounds': [115,37,117,39], 'variables': ['prec']}


def test_unconfirmed_raster_selector_cannot_create_job(tmp_path):
    raw = {k: v for k, v in EST.items() if k != 'variables'}
    raw.update(kind='raster', coverage_complete=None)
    c = client(json_response(raw))
    state = s.estimate(tmp_path, {**BODY, 'variables': ['made_up_field']}, client=c)
    assert 'variable_selection_unconfirmed' in state['offer']['blockers']
    for inspection in (False, True):
        with pytest.raises(ValueError):
            s.approve(tmp_path, state['id'], client=c, inspection=inspection)
    assert len(c._provided_opener.requests) == 1


def test_legacy_approval_does_not_bypass_new_selection_check_on_download(tmp_path, monkeypatch):
    raw = {k: v for k, v in EST.items() if k != 'variables'}
    legacy = {'status': 'ready', 'approved_at': 1, 'request': BODY, 'estimate': raw}
    monkeypatch.setattr(s, 'refresh', lambda *args, **kwargs: legacy)
    c = client()
    with pytest.raises(ValueError, match='selection is not confirmed'):
        s.download(tmp_path, 'a' * 32, client=c)
    assert not c._provided_opener.requests


@pytest.fixture(autouse=True)
def isolated_receipt_keys(tmp_path_factory, monkeypatch):
    monkeypatch.setenv('GEOFORGE_FLOW_KEYS', str(tmp_path_factory.mktemp('subset-keys')))


def client(*values):
    return Client(opener=Opener(*values), token_getter=lambda: 'fake-test-token')


def ready(tmp_path, c):
    e = s.estimate(tmp_path, BODY, client=c)
    a = s.approve(tmp_path, e['id'], client=c)
    return a['id']


def test_estimate_is_read_only_and_redacts_unknown_fields(tmp_path):
    c = client(json_response({**EST, 'token': 'PRIVATE', 'source_path': 'PRIVATE'}))
    e = s.estimate(tmp_path, BODY, client=c)
    assert e['status'] == 'awaiting_approval'
    assert 'PRIVATE' not in json.dumps(e)
    assert len(c._provided_opener.requests) == 1
    req = c._provided_opener.requests[0][0]
    assert req.method == 'POST' and req.full_url.endswith('/subsets/estimate')
    assert json.loads(req.data) == BODY


def test_gateway_failure_is_visible_and_retry_never_creates_job(tmp_path):
    failure = HTTPError('https://example.invalid/subsets/estimate', 530,
                        'error', {}, io.BytesIO(b'<html>PRIVATE server error</html>'))
    c = client(failure, json_response(EST), json_response({'job_id': 'approved-job'}))
    failed = s.estimate(tmp_path, BODY, client=c)
    assert failed['status'] == 'estimate_failed'
    assert failed['failure'] == {'stage': 'estimate', 'code': 'server_unavailable', 'http_status': 530}
    assert failed['request'] == BODY and failed['next_action'] == 'retry_estimate'
    assert not failed['offer']['inspection_allowed']
    assert 'HTTP 530' in failed['error']
    assert 'PRIVATE' not in json.dumps(s.list_states(tmp_path))
    assert s.list_states(tmp_path)[0]['id'] == failed['id']
    for inspection in (False, True):
        with pytest.raises(ValueError):
            s.approve(tmp_path, failed['id'], client=c, inspection=inspection)
    assert len(c._provided_opener.requests) == 1
    retried = s.retry_estimate(tmp_path, failed['id'], client=c)
    assert retried['id'] == failed['id'] and retried['attempts'] == 2
    assert retried['status'] == 'awaiting_approval'
    assert 'job_id' not in retried and 'authorization' not in retried
    assert 'failure' not in retried and 'error' not in retried
    assert all(req.full_url.endswith('/subsets/estimate') for req, _ in c._provided_opener.requests)
    approved = s.approve(tmp_path, retried['id'], client=c)
    with pytest.raises(ValueError):
        s.retry_estimate(tmp_path, approved['id'], client=c)
    assert len(c._provided_opener.requests) == 3


def test_invalid_estimate_is_retained_but_invalid_user_scope_is_not(tmp_path):
    c = client(json_response({'unexpected': 'PRIVATE'}))
    failed = s.estimate(tmp_path, BODY, client=c)
    assert failed['status'] == 'estimate_failed'
    assert failed['failure']['code'] == 'invalid_response'
    assert 'PRIVATE' not in json.dumps(failed)
    with pytest.raises(ValueError):
        s.estimate(tmp_path, {**BODY, 'bbox': [0, 0, 0, 0]}, client=c)
    assert len(s.list_states(tmp_path)) == 1


def test_unknown_variable_is_a_correction_not_an_outage_or_download(tmp_path):
    failure = HTTPError('https://example.invalid/subsets/estimate', 400, 'bad variable', {},
        io.BytesIO(json.dumps({'detail': {'error': 'unknown_variable', 'message': 'PRIVATE'}}).encode()))
    c = client(failure)
    state = s.estimate(tmp_path, BODY, client=c)
    assert state['failure']['code'] == 'unknown_variable'
    assert state['next_action'] == 'describe_and_revise'
    assert '--describe' in state['error'] and 'PRIVATE' not in json.dumps(state)
    assert not state['offer']['inspection_allowed'] and 'job_id' not in state
    assert len(c._provided_opener.requests) == 1


def test_member_file_count_is_not_lost_from_estimate(tmp_path):
    state = s.estimate(tmp_path, BODY, client=client(json_response({**EST, 'n_files': 9})))
    assert state['estimate']['n_files'] == 9


@pytest.mark.parametrize('changes', [{'subsettable': False}, {'coverage_complete': False},
    {'over_output_cap': True}, {'estimated_output_bytes': s.MAX_OUTPUT+1},
    {'missing': ['1989']}, {'transformations': ['reproject']}, {'coverage_complete': None}])
def test_cannot_approve_unsafe_or_incomplete_estimate(tmp_path, changes):
    c = client(json_response({**EST, **changes}))
    e = s.estimate(tmp_path, BODY, client=c)
    assert e['status'] == 'needs_review'
    with pytest.raises(ValueError): s.approve(tmp_path, e['id'], client=c)
    assert len(c._provided_opener.requests) == 1


def test_old_estimates_do_not_expire_and_ids_are_validated(tmp_path, monkeypatch):
    # No TTL: freshness is guaranteed by re-estimation before the card and at approval.
    c = client(json_response(EST), json_response({'job_id': 'j1'}))
    e = s.estimate(tmp_path, BODY, client=c)
    monkeypatch.setattr(s.time, 'time', lambda: e['created_at'] + 3 * 3600)
    assert s.approve(tmp_path, e['id'], client=c)['status'] == 'queued'
    with pytest.raises(ValueError): s.read(tmp_path, '../escape')


def test_all_parts_verified_before_publication(tmp_path):
    data = b'actual test bytes'
    digest = hashlib.sha256(data).hexdigest()
    manifest = {'job_id':'job1','dataset_id':BODY['dataset_id'],'ready':True,'n_parts':1,'total_bytes':len(data),
                'parts':[{'n':4,'name':'rain.dat','bytes':len(data),'sha256':digest,'units':'kg m-2 s-1'}]}
    c = client(json_response(EST), json_response({'job_id':'job1'}),
               json_response({'status':'ready'}), json_response(manifest),
               Response(data, {'X-Content-SHA256':digest}))
    ident = ready(tmp_path,c)
    out = s.download(tmp_path,ident,client=c)
    assert out['status'] == 'downloaded' and out['scientific_validation'] == 'pending'
    assert (tmp_path/'inputs/geoforge_subsets'/ident/'rain.dat').read_bytes() == data
    assert c._provided_opener.requests[-1][0].full_url.endswith('/parts/4')
    assert out['files'][0]['units'] == 'kg m-2 s-1'


@pytest.mark.parametrize('fault', ['checksum','path','wrong_job','oversize'])
def test_bad_outputs_not_published(tmp_path, fault):
    digest = hashlib.sha256(b'good').hexdigest()
    part = {'n':0,'name':'rain.nc','bytes':4,'sha256':digest}
    if fault=='path': part['name']='../rain.nc'
    if fault=='oversize': part['bytes']=s.MAX_OUTPUT+1
    manifest={'job_id':'other' if fault=='wrong_job' else 'job1',
              'dataset_id':BODY['dataset_id'],'ready':True,'parts':[part],'n_parts':1,'total_bytes':part['bytes']}
    c=client(json_response(EST),json_response({'job_id':'job1'}),json_response({'status':'ready'}),
             json_response(manifest),Response(b'evil',{'X-Content-SHA256':digest}))
    ident=ready(tmp_path,c)
    with pytest.raises(ValueError): s.download(tmp_path,ident,client=c)
    assert not (tmp_path/'inputs/geoforge_subsets'/ident).exists()


def test_request_rejects_silent_transform_and_bad_bbox():
    with pytest.raises(ValueError): s.request_body({**BODY,'target_crs':'EPSG:3857'})
    with pytest.raises(ValueError): s.request_body({**BODY,'bbox':[117,39,115,37]})


def test_unknown_coverage_requires_explicit_inspection_approval(tmp_path):
    estimate = {**EST, 'coverage_complete': None, 'kind': 'raster',
                'selection_empty': False, 'n_selected_cells': 10, 'reason': 'coverage_unknown'}
    c = client(json_response(estimate), json_response({'job_id': 'job1'}))
    state = s.estimate(tmp_path, BODY, client=c)
    assert state['offer']['inspection_allowed'] and state['status'] == 'needs_review'
    assert state['estimate']['n_selected_cells'] == 10
    with pytest.raises(ValueError):
        s.approve(tmp_path, state['id'], client=c)
    approved = s.approve(tmp_path, state['id'], client=c, inspection=True)
    assert approved['authorization']['mode'] == 'inspection'
    assert s._authorized(tmp_path, approved)
    assert not approved['eligible']


def test_changed_request_or_job_cannot_reuse_user_authorization(tmp_path):
    c = client(json_response(EST), json_response({'job_id': 'job1'}))
    ident = ready(tmp_path, c)
    state = s.read(tmp_path, ident)
    state['request']['bbox'] = [0, 0, 1, 1]
    s._save(tmp_path, state)
    with pytest.raises(ValueError, match='approval'):
        s.refresh(tmp_path, ident, client=c)
    assert len(c._provided_opener.requests) == 2  # no unauthorized status or transfer


@pytest.mark.parametrize('download_first', [False, True])
def test_subset_binds_to_approved_inventory_without_mutating_plan(tmp_path, monkeypatch, download_first):
    from kiss_cli import api, cli, flowrun, obs_access
    from .test_flowgate import _session, _ki, _plan, _cfg
    from types import SimpleNamespace

    ki = _ki(tmp_path)
    project, fs = _session(tmp_path, ki, [('task_received', None),
                                      ('kis_resolved', {'selected_kis': ['M']})])
    data = b'opaque native fixture, scientific inspection pending'
    digest = hashlib.sha256(data).hexdigest()
    manifest = {'job_id': 'job1', 'dataset_id': BODY['dataset_id'], 'ready': True,
        'n_parts': 1, 'total_bytes': len(data), 'parts': [{'n': 0, 'name': 'rain.dat',
        'bytes': len(data), 'sha256': digest, 'variables': ['prec'], 'crs': 'EPSG:4326',
        'bounds': BODY['bbox'], 'time_range': ['1989-01-01', '1989-12-31'],
        'n_time_steps': 365, 'time_subset_applied': True, 'crs_source': 'declared'}]}
    c = client(json_response(EST), json_response({'job_id': 'job1'}),
               json_response({'status': 'ready'}), json_response(manifest),
               Response(data, {'X-Content-SHA256': digest}))
    ident = ready(project, c)
    if download_first:
        s.download(project, ident, client=c)
    plan, inventory = _plan(ki)
    inventory['items'][0].update(dataset_id=BODY['dataset_id'], acquisition_id=ident)
    assert fs.write_plan(plan, inventory) == []
    fs.flow.approval.approve(project, by='user')
    fs.reload_artifacts()
    before = (project / 'runs/data-inventory.json').read_bytes()
    from kiss_cli.flowgate import FlowDenied
    with pytest.raises(FlowDenied, match='no intact, bound acquisition'):
        fs.check_step_tool('M:run', 'M', ki.root / 'tools/run.py')
    if not download_first:
        s.download(project, ident, client=c)
    paths = s.bind_approved(project, ident)
    assert len(paths) == 1
    assert (project / 'runs/data-inventory.json').read_bytes() == before
    receipt = json.loads(Path(paths[0]).read_text())
    assert receipt['selection_sha256'] == fs.flow.receipts.selection_sha256(fs.inventory['items'][0])
    assert receipt['acquisition']['files'][0]['time_range'] == ['1989-01-01', '1989-12-31']
    assert receipt['acquisition']['files'][0]['crs_source'] == 'declared'
    assert receipt['acquisition']['scientific_validation'] == 'pending'
    assert flowrun.plan_data_status(project)['items'][0]['status'] == 'acquired'
    assert flowrun.plan_data_status(project)['items'][0]['action'] == 'agent_validate'
    assert fs.check_step_tool('M:run', 'M', ki.root / 'tools/run.py')['id'] == 'M:run'
    assert s.bind_approved(project, ident) == paths          # idempotent: same receipt, no duplicate
    assert not (project / 'runs/inventory-updates.jsonl').exists()   # dead log is gone

    # The host acquisition pass finds the bound receipt and downloads nothing more.
    from kiss_cli import acquire
    fs.move('plan_written', {'plan_valid': True}); fs.move('approved', {'approval': 'OK'})
    monkeypatch.setattr(obs_access, 'Client', lambda: c)
    result = acquire.run(project)
    assert result['status'] == 'done' and result['items']['forcing']['receipt'] == paths[0]

    (Path(s.read(project, ident)['path']) / 'rain.dat').write_bytes(b'changed')
    assert flowrun.plan_data_status(project)['items'][0]['status'] == 'pending'
    with pytest.raises(FlowDenied, match='no intact, bound acquisition'):
        fs.check_step_tool('M:run', 'M', ki.root / 'tools/run.py')
    with pytest.raises(ValueError, match='missing or changed'):
        s.download(project, ident, client=c)


def test_subset_cannot_bind_to_different_dataset_or_period(tmp_path):
    c = client(json_response(EST))
    state = s.estimate(tmp_path, BODY, client=c)
    for fields in ({'dataset_id': 'wrong'}, {'requirements': {'start': '2000-01-01'}},
                   {'requirements': {'variable': 'temp'}}, {'requirements': {'bbox': [0, 0, 1, 1]}}):
        with pytest.raises(ValueError, match='differs'):
            s.stamp_item(tmp_path, {'id': 'forcing', 'acquisition_id': state['id'], **fields})


def _v3_download(tmp_path, manifest_extra, estimate_extra=None):
    data = b'member bytes'
    digest = hashlib.sha256(data).hexdigest()
    est = {**EST, 'processing_version': 'obs_subset/3', 'source_version': 'src-1',
           'cell_centre_bounds': [115.05, 37.05, 116.95, 38.95], 'bounds_convention': 'cell_edges',
           **(estimate_extra or {})}
    manifest = {'job_id': 'job1', 'dataset_id': BODY['dataset_id'], 'ready': True, 'n_parts': 1,
                'total_bytes': len(data), 'processing_version': 'obs_subset/3', 'source_version': 'src-1',
                'parts': [{'n': 0, 'name': 'maize.dat', 'bytes': len(data), 'sha256': digest,
                           'bounds_convention': 'cell_edges', 'processing_version': 'obs_subset/3'}],
                **manifest_extra}
    c = client(json_response(est), json_response({'job_id': 'job1'}),
               json_response({'status': 'ready'}), json_response(manifest),
               Response(data, {'X-Content-SHA256': digest}))
    return c, ready(tmp_path, c)


def test_v3_versions_and_grid_contract_are_kept(tmp_path):
    c, ident = _v3_download(tmp_path, {})
    out = s.download(tmp_path, ident, client=c)
    assert out['estimate']['processing_version'] == 'obs_subset/3'
    assert out['estimate']['bounds_convention'] == 'cell_edges'
    assert out['files'][0]['bounds_convention'] == 'cell_edges'
    assert out['manifest'] == {'processing_version': 'obs_subset/3', 'source_version': 'src-1',
                               'unreadable_files': [], 'missing_members': 0}
    assert out['content_validation']['status'] == 'pending'  # non-native format; unchanged
    assert 'members_missing' not in out['content_validation']['pending']
    assert out['manifest']['missing_members'] == 0


def test_v3_short_manifest_without_unreadable_list_is_still_partial(tmp_path):
    # Live GGCMI on 2026-09-16: estimate n_files=40, manifest n_parts=38, no unreadable_files.
    c, ident = _v3_download(tmp_path, {}, estimate_extra={'n_files': 40})
    out = s.download(tmp_path, ident, client=c)
    assert out['manifest']['missing_members'] == 39 and out['manifest']['n_files'] == 40
    assert 'members_missing' in out['content_validation']['pending']
    assert out['content_validation']['status'] == 'pending'


def test_v3_partial_member_delivery_is_flagged_not_silently_complete(tmp_path):
    c, ident = _v3_download(tmp_path, {'n_files': 40, 'unreadable_files': ['/srv/private/rice.nc4', 'wheat.nc4']})
    out = s.download(tmp_path, ident, client=c)
    assert out['status'] == 'downloaded'
    assert out['manifest']['unreadable_files'] == ['rice.nc4', 'wheat.nc4']
    assert out['manifest']['n_files'] == 40
    assert 'members_missing' in out['content_validation']['pending']
    assert '/srv/private' not in json.dumps(out) and '/srv/private' not in json.dumps(s.read(tmp_path, ident))


@pytest.mark.parametrize('key', ['processing_version', 'source_version'])
def test_v3_version_change_after_approval_blocks_download(tmp_path, key):
    c, ident = _v3_download(tmp_path, {key: 'changed-after-approval'})
    with pytest.raises(ValueError, match='changed after approval'):
        s.download(tmp_path, ident, client=c)
    assert not (tmp_path / 'inputs/geoforge_subsets' / ident).exists()


def test_variable_selection_unsupported_asks_for_describe_not_retry(tmp_path):
    failure = HTTPError('https://example.invalid/subsets/estimate', 400, 'error',
                        {}, io.BytesIO(b'{"detail":{"error":"variable_selection_unsupported","message":"PRIVATE"}}'))
    c = client(failure)
    failed = s.estimate(tmp_path, {**BODY, 'dataset_id': 'china_dem_90m', 'variables': ['elevation_m']}, client=c)
    assert failed['status'] == 'estimate_failed'
    assert failed['failure']['code'] == 'variable_selection_unsupported'
    assert failed['next_action'] == 'describe_and_revise'
    assert 'empty variable list' in failed['error']


# ---------------------------------------------------------------------------
# Step 2 (FLOW-TARGET-2026-09-17): the inventory is the proposal; the host joins,
# re-estimates and, on plan approval, starts the jobs.


def test_host_joins_item_to_estimate_by_requirements_or_single_candidate(tmp_path):
    c = client(json_response(EST), json_response({**EST, 'estimated_output_bytes': 50}))
    a = s.estimate(tmp_path, BODY, client=c)
    other = s.estimate(tmp_path, {**BODY, 'bbox': [100, 30, 101, 31]}, client=c)
    # requirements pick the right one of two
    item = {'id': 'forcing', 'dataset_id': BODY['dataset_id'],
            'requirements': {'bbox': '115,37,117,39', 'start': '1989-01-01', 'end': '1989-12-31', 'variable': 'prec'}}
    st = s.stamp_item(tmp_path, item)
    assert st['id'] == a['id'] and item['acquisition_id'] == a['id'] and item['delivery'] == 'subset'
    assert item['estimate_summary']['bytes'] == 100 and 'estimate_sha256' not in json.dumps(item)
    # no requirements and two distinct scopes: an error naming the candidates
    with pytest.raises(ValueError, match='2 different clip estimates'):
        s.stamp_item(tmp_path, {'id': 'x', 'dataset_id': BODY['dataset_id']})
    # a single candidate needs nothing
    s.cancel(tmp_path, other['id'])
    item2 = {'id': 'y', 'dataset_id': BODY['dataset_id']}
    assert s.stamp_item(tmp_path, item2)['id'] == a['id']
    # explicit id whose hash no longer matches the item's recorded hash is refused
    with pytest.raises(ValueError, match='request changed'):
        s.stamp_item(tmp_path, {'id': 'z', 'acquisition_id': a['id'], 'acquisition_request_sha256': 'f' * 64})


def test_refresh_keeps_id_and_reports_material_changes(tmp_path):
    c = client(json_response(EST),
               json_response({**EST, 'estimated_output_bytes': 105, 'processing_version': 'obs_subset/3'}),
               json_response({**EST, 'estimated_output_bytes': 100 * 1024**2, 'processing_version': 'obs_subset/4'}))
    a = s.estimate(tmp_path, BODY, client=c)
    item = {'id': 'forcing', 'acquisition_id': a['id']}
    s.stamp_item(tmp_path, item)
    inv = {'items': [item]}
    assert s.refresh_inventory(tmp_path, inv, client=c) == {}          # +5 bytes: within tolerance
    assert s.read(tmp_path, a['id'])['estimate']['estimated_output_bytes'] == 105
    s.stamp_item(tmp_path, item)                                        # after() re-stamps before the card
    assert item['estimate_summary']['processing_version'] == 'obs_subset/3'
    changed = s.refresh_inventory(tmp_path, inv, client=c)
    assert list(changed) == ['forcing'] and any('size' in r for r in changed['forcing'])
    assert any('processing_version' in r for r in changed['forcing'])


def test_plan_approval_starts_clip_jobs_and_execution_self_heals(tmp_path, monkeypatch):
    from .test_flowgate import _session, _ki, _plan
    ki = _ki(tmp_path)
    project, fs = _session(tmp_path, ki, [('task_received', None), ('kis_resolved', {'selected_kis': ['M']})])
    c = client(json_response(EST), json_response({'job_id': 'job-A'}))
    a = s.estimate(project, BODY, client=c)
    plan, inventory = _plan(ki)
    inventory['items'][0].update(dataset_id=BODY['dataset_id'], acquisition_id=a['id'])
    assert fs.write_plan(plan, inventory) == []
    fs.flow.approval.approve(project, by='user')
    fs.reload_artifacts()
    results = s.approve_inventory(project, fs.inventory, client=c)
    assert results == [{'item': inventory['items'][0]['id'], 'ok': True, 'status': 'queued'}]
    assert s.read(project, a['id'])['job_id'] == 'job-A'
    # a second clip whose job creation was missed at approval time is created by execution
    c2 = client(json_response({**EST, 'variables': ['temp']}), json_response({'job_id': 'job-B'}), json_response({'status': 'running'}))
    b = s.estimate(project, {**BODY, 'variables': ['temp']}, client=c2)
    inventory['items'].append({**inventory['items'][0], 'id': 'temp_item', 'acquisition_id': b['id'],
                               'acquisition_request_sha256': None})
    fs.flow.plan.write_artifacts(project, plan, inventory)
    fs.flow.approval.approve(project, by='user')
    out = s.advance_approved(project, b['id'], client=c2)
    assert out['status'] == 'running' and s.read(project, b['id'])['job_id'] == 'job-B'
    # a clip that is not in the approved plan is refused
    c3 = client(json_response({**EST, 'variables': ['wind']}))
    z = s.estimate(project, {**BODY, 'variables': ['wind']}, client=c3)
    with pytest.raises(ValueError, match='not part of the approved plan'):
        s.advance_approved(project, z['id'], client=c3)


def test_presentation_has_no_approval_surface(tmp_path):
    c = client(json_response(EST), json_response({'job_id': 'j'}))
    a = s.estimate(tmp_path, BODY, client=c)
    s.estimate(tmp_path, {**BODY, 'variables': ['temp']}, client=client(json_response(EST)))
    s.approve(tmp_path, a['id'], client=c)
    view = s.presentation(tmp_path)
    assert {k for k in view} == {'active', 'estimates'}
    assert [x['id'] for x in view['active']] == [a['id']] and len(view['estimates']) == 1
    assert 'authorization' not in json.dumps(view)


def test_budget_allows_per_part_container_overhead(tmp_path):
    # Live 2026-09-18: 176 single-cell NetCDF parts, 502 KB estimated payload, 5.0 MB actual.
    data = b'x' * 28000
    digest = hashlib.sha256(data).hexdigest()
    parts = [{'n': i, 'name': f'p{i}.dat', 'bytes': len(data), 'sha256': digest} for i in range(176)]
    manifest = {'job_id': 'job1', 'dataset_id': BODY['dataset_id'], 'ready': True, 'n_parts': 176,
                'total_bytes': len(data) * 176, 'parts': parts}
    est = {**EST, 'estimated_output_bytes': 513920, 'n_parts': 176}
    c = client(json_response(est), json_response({'job_id': 'job1'}), json_response({'status': 'ready'}),
               json_response(manifest), *[Response(data, {'X-Content-SHA256': digest}) for _ in range(176)])
    ident = ready(tmp_path, c)
    out = s.download(tmp_path, ident, client=c)
    assert out['status'] == 'downloaded' and len(out['files']) == 176


def test_host_prefers_a_server_clip_over_a_large_manual_download(tmp_path):
    """Montreal 2026-09-18: the agent pinned hwsd_global as a 1.74 GB Baidu download although the
    server clips it to 14 KB. The host now tries the clip itself when the item has a study bbox."""
    from kiss_cli import obs_access as o
    record = {'id': 'hwsd_global', 'delivery': 'manual', 'size': 1_870_000_000}
    item = {'id': 'soil_texture_hwsd', 'dataset_id': 'hwsd_global', 'delivery': 'manual',
            'requirements': {'bbox': '-74,45,-73.4,45.8'}}
    est = {**EST, 'estimated_output_bytes': 13824, 'coverage_complete': None, 'variables': []}
    c = client(json_response(est))
    assert s.prefer_clip(tmp_path, item, record, client=c) is True
    assert item['delivery'] == 'subset' and item['acquisition_id'] and item['estimate_summary']['bytes'] == 13824
    # a station bundle that the server cannot clip stays manual
    item2 = {'id': 'met', 'dataset_id': 'agrometeo_quebec', 'delivery': 'manual', 'requirements': {'bbox': '-74,45,-73.4,45.8'}}
    c2 = client(json_response({**EST, 'subsettable': False, 'reason': 'table_not_raster'}))
    assert s.prefer_clip(tmp_path, item2, {'id': 'agrometeo_quebec', 'delivery': 'manual', 'size': 344_000_000}, client=c2) is False
    assert item2['delivery'] == 'manual' and 'acquisition_id' not in item2
    # a small served dataset is left alone (no server call)
    item3 = {'id': 'g', 'dataset_id': 'gauge', 'delivery': 'served', 'requirements': {'bbox': '-74,45,-73.4,45.8'}}
    c3 = client()
    assert s.prefer_clip(tmp_path, item3, {'id': 'gauge', 'delivery': 'served', 'size': 5000}, client=c3) is False
    assert not c3._provided_opener.requests


def test_host_clip_retries_without_variables_on_a_whole_file_raster(tmp_path):
    """Montreal 2026-09-19: hwsd_global refuses band selection (HTTP 400) and the host fell back
    to the 1.7 GB manual download. The server says 'empty variable list': the host does that."""
    record = {'id': 'hwsd_global', 'delivery': 'manual', 'size': 1_870_000_000}
    item = {'id': 'soil_texture_hwsd', 'dataset_id': 'hwsd_global', 'delivery': 'manual',
            'requirements': {'bbox': '-74,45,-73.4,45.8', 'variable': 'sand,silt,clay'}}
    refused = HTTPError('u', 400, 'bad', {}, io.BytesIO(
        b'{"detail":{"error":"variable_selection_unsupported","message":"PRIVATE"}}'))
    est = {**EST, 'estimated_output_bytes': 13824, 'coverage_complete': None, 'variables': []}
    c = client(refused, json_response(est))
    assert s.prefer_clip(tmp_path, item, record, client=c) is True
    assert item['delivery'] == 'subset' and item['estimate_summary']['bytes'] == 13824
    first, second = (json.loads(r.data) for r, _ in c._provided_opener.requests)
    assert first['variables'] == ['clay', 'sand', 'silt'] and second['variables'] == []
