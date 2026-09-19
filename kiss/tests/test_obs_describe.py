"""Source-schema discovery: no downloads, inferred aliases or credential leaks."""
import copy
import io
import json
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import pytest

from kiss_cli import obs_access as o
from .test_obs_access import Opener, json_response


SCHEMA = {
    'dataset_id': 'crop_calendar_global', 'describable': True, 'kind': 'netcdf_grid',
    'source_version': 'header-version-1', 'n_source_files': 2, 'n_variables': 2,
    'variables': [
        {'name': 'plant', 'long_name': 'Barley: Planting date', 'units': 'day of year',
         'dims': ['latitude', 'longitude'], 'in_n_files': 2, 'select_by': 'variable'},
        {'name': 'tot.days', 'units': 'days', 'dims': ['latitude', 'longitude'],
         'select_by': 'variable'}],
    'coverage': {'bbox': [-180, -90, 180, 90]}, 'multi_schema': False,
    'schemas': [{'variables': ['plant', 'tot.days'], 'files': ['barley.nc', 'maize.nc'], 'count': 2}],
    'files': [{'file': 'barley.nc', 'sample_long_name': 'Barley: Planting date'},
              {'file': 'maize.nc', 'sample_long_name': 'Maize: Planting date'}],
    'files_truncated': False, 'note': 'Variable selection includes all members.'}


def client(*responses):
    return o.Client(opener=Opener(*responses), token_getter=lambda: 'host-only-test-token')


def test_live_describe_preserves_source_schema_not_catalogue_aliases():
    raw = copy.deepcopy(SCHEMA)
    raw.update(token='PRIVATE', source_path='PRIVATE', download_url='PRIVATE')
    raw['variables'][0]['credentials'] = 'PRIVATE'
    raw['files'][0]['source_path'] = 'PRIVATE'
    c = client(json_response(raw))
    result = o.search_catalogue(describe_dataset_id=raw['dataset_id'], client=c)
    assert result['variables'] == SCHEMA['variables']
    assert result['schemas'] == SCHEMA['schemas'] and result['files'] == SCHEMA['files']
    assert result['source_version'] == SCHEMA['source_version']
    assert result['source'] == 'source_file_schema' and result['schema_only']
    assert result['model_ready'] is False and result['subset_estimate'] == 'not_checked'
    assert 'PRIVATE' not in json.dumps(result) and 'host-only-test-token' not in json.dumps(result)
    req = c._provided_opener.requests[0][0]
    assert req.method == 'GET' and req.data is None
    assert urlparse(req.full_url).path == '/api/obs/subsets/describe'
    assert parse_qs(urlparse(req.full_url).query) == {'dataset_id': [SCHEMA['dataset_id']]}
    assert req.get_header('Authorization') == 'Bearer host-only-test-token'
    assert len(c._provided_opener.requests) == 1


def test_describe_refreshes_source_version_and_never_falls_back_to_catalogue():
    c = client(json_response(SCHEMA), json_response({**SCHEMA, 'source_version': 'new'}),
               HTTPError('https://example.invalid', 503, 'down', {}, io.BytesIO(b'PRIVATE')))
    assert o.describe_dataset(SCHEMA['dataset_id'], client=c)['source_version'] == 'header-version-1'
    assert o.describe_dataset(SCHEMA['dataset_id'], client=c)['source_version'] == 'new'
    with pytest.raises(o.ObsAccessError, match='HTTP 503'):
        o.describe_dataset(SCHEMA['dataset_id'], client=c)


def test_raster_bands_are_preserved_without_inventing_variables():
    raw = {'describable': True, 'dataset_id': 'dem', 'kind': 'raster', 'source_version': 'v1',
           'files': [{'file': 'dem.tif', 'n_bands': 1, 'dtype': 'int16', 'crs': 'EPSG:4326',
                      'crs_source': 'declared', 'bounds': [70, 15, 140, 55], 'res': [0.1, 0.1],
                      'bands': [{'band': 1, 'nodata': 32767, 'description': None}]}],
           'note': 'Bands are informational; crops the whole raster.'}
    result = o.describe_dataset('dem', client=client(json_response(raw)))
    assert result['files'] == raw['files'] and 'variables' not in result
    assert result['model_ready'] is False


def test_unmounted_is_not_reported_as_missing_data_or_successful_schema():
    raw = {'describable': False, 'dataset_id': 'external', 'reason': 'not_locally_indexed',
           'delivery_fallback': 'manual', 'message': 'PRIVATE internal source path'}
    result = o.describe_dataset('external', client=client(json_response(raw)))
    assert result['describable'] is False and result['delivery_fallback'] == 'manual'
    assert 'variables' not in result and 'PRIVATE' not in json.dumps(result)


@pytest.mark.parametrize('change', [
    {'dataset_id': 'other'}, {'describable': 'true'}, {'variables': ['plant']},
    {'n_variables': 99}, {'variables': [{'name': 'plant'}, {'name': 'plant'}]},
])
def test_invalid_or_incomplete_description_is_not_accepted(change):
    with pytest.raises(o.ObsAccessError):
        o.describe_dataset(SCHEMA['dataset_id'], client=client(json_response({**SCHEMA, **change})))


def test_variable_lists_are_not_silently_truncated():
    variables = [{'name': f'field_{i}'} for i in range(501)]
    result = o.describe_dataset(SCHEMA['dataset_id'], client=client(json_response(
        {**SCHEMA, 'variables': variables, 'n_variables': len(variables)})))
    assert result['variables'] == variables


def test_invalid_dataset_and_mixed_modes_do_not_issue_network_request():
    c = client()
    with pytest.raises(ValueError):
        o.describe_dataset('../bad?dataset_id=other', client=c)
    with pytest.raises(ValueError):
        o.search_catalogue(describe_dataset_id='a', resolve_dataset_id='b', client=c)
    assert not c._provided_opener.requests


def test_api_agent_and_direct_cli_can_describe_before_plan_approval(monkeypatch, tmp_path, capsys):
    from kiss_cli import api, cli
    from .test_flowgate import _ki, _session, _cfg
    c = client(json_response(SCHEMA), json_response(SCHEMA))
    monkeypatch.setattr(o, 'Client', lambda: c)
    ki = _ki(tmp_path)
    project, flow = _session(tmp_path, ki, [('task_received', None),
        ('kis_resolved', {'selected_kis': ['M']})])
    result = json.loads(api.execute_tool('describe_dataset',
        {'dataset_id': SCHEMA['dataset_id']}, ki, _cfg(project), project_mode=True, flow=flow))
    assert result['variables'] == SCHEMA['variables']
    assert cli.main(['obs-search', '--describe', SCHEMA['dataset_id']]) == 0
    assert json.loads(capsys.readouterr().out)['variables'] == SCHEMA['variables']
    assert len(c._provided_opener.requests) == 2


@pytest.mark.parametrize('embedded', [True, False])
def test_kimi_helpers_forward_describe_via_host_capability(monkeypatch, capsys, embedded):
    from kiss_cli import flowrun, gui
    if embedded:
        source = flowrun._DATABASE_HELPER
    else:
        source = (Path(__file__).parents[1] / 'system_kis/GeoForge_Database/tools/search_catalogue.py').read_text()
    scope = {'__name__': 'test_describe_helper'}
    exec(compile(source, '<database-helper>', 'exec'), scope)
    monkeypatch.setenv('GEOFORGE_AGENT_DATABASE_URL', 'http://127.0.0.1:12345/api/agent/obs/catalogue')
    monkeypatch.setenv('GEOFORGE_AGENT_DATABASE_TOKEN', 'loopback-only')
    monkeypatch.setattr(sys, 'argv', ['geoforge-db', '--describe', SCHEMA['dataset_id']])
    seen = []
    def open_request(request, timeout):
        seen.append(request)
        params = gui._catalogue_query(parse_qs(urlparse(request.full_url).query))
        assert params['describe_dataset_id'] == SCHEMA['dataset_id']
        assert request.get_header('X-geoforge-agent-token') == 'loopback-only'
        assert request.get_header('Authorization') is None
        return json_response(SCHEMA)
    monkeypatch.setattr('urllib.request.urlopen', open_request)
    assert scope['main']() == 0
    assert json.loads(capsys.readouterr().out) == SCHEMA
    assert len(seen) == 1 and seen[0].get_method() == 'GET'


def test_shared_planning_rules_teach_describe_without_loosening_approval(tmp_path):
    from kiss_cli import api
    from .test_flowgate import _ki
    assert 'describe_dataset' in o.DATA_DISCOVERY_RULES and '--describe' in o.DATA_DISCOVERY_RULES
    assert 'never guess a translation' in o.DATA_DISCOVERY_RULES
    assert 'does not authorize a job' in o.DATA_DISCOVERY_RULES
    names = {t['name'] for t in api.tool_schemas(_ki(tmp_path), project_mode=True)}
    assert {'search_catalogue', 'describe_dataset', 'estimate_clip'} <= names
    assert 'search_observation_data' not in names      # folded into the three tools


def test_describe_loopback_bridge_is_read_only_and_capability_protected(monkeypatch, tmp_path):
    import subprocess
    import threading
    import urllib.request
    from kiss_cli import flowrun, gui

    # Isolated server and fake remote: no real DB credential/provider turn.
    c = client(json_response(SCHEMA), json_response(SCHEMA))
    monkeypatch.setattr(o, 'Client', lambda: c)
    monkeypatch.setattr(gui.Handler, 'agent_database_token', 'test-process-capability')
    server = gui.GeoForgeHTTPServer(('127.0.0.1', 0), gui.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f'http://127.0.0.1:{server.server_port}/api/agent/obs/catalogue'
    try:
        with pytest.raises(HTTPError) as failure:
            urllib.request.urlopen(endpoint + '?describe_dataset_id=' + SCHEMA['dataset_id'], timeout=5)
        assert failure.value.code == 401 and not c._provided_opener.requests
        env = {'GEOFORGE_AGENT_DATABASE_URL': endpoint,
               'GEOFORGE_AGENT_DATABASE_TOKEN': 'test-process-capability'}
        for command in (
            [sys.executable, '-c', flowrun._DATABASE_HELPER],
            [sys.executable, str(Path(__file__).parents[1] / 'system_kis/GeoForge_Database/tools/search_catalogue.py')],
        ):
            result = subprocess.run(command + ['--describe', SCHEMA['dataset_id']],
                cwd=tmp_path, env=env, capture_output=True, text=True, timeout=10)
            assert result.returncode == 0, result.stderr
            assert json.loads(result.stdout)['variables'] == SCHEMA['variables']
            assert 'host-only-test-token' not in result.stdout
        assert len(c._provided_opener.requests) == 2
        assert all(req.get_method() == 'GET' for req, _ in c._provided_opener.requests)
        assert not list(tmp_path.iterdir())  # no subset jobs or project writes
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
