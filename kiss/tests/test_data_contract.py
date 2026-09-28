import pytest

from kiss_cli import data_contract as c


REQUEST = {'dataset_id': 'unseen_product', 'bbox': [115, 37, 117, 39],
           'variables': ['rain'], 'start': '2000-01-01', 'end': '2000-01-07'}
ESTIMATE = {'subsettable': True, 'kind': 'netcdf_grid', 'estimated_output_bytes': 1000,
            'over_output_cap': False, 'transformations': [], 'variables': ['rain']}


def test_unknown_coverage_is_an_inspection_offer_not_an_automatic_pass():
    offer = c.normalize_estimate(REQUEST, ESTIMATE, 10000)
    assert offer['inspection_allowed'] and not offer['eligible']
    assert offer['coverage']['overall'] == 'unknown'
    static = c.normalize_estimate({'dataset_id': 'another_unseen', 'bbox': REQUEST['bbox']}, ESTIMATE, 10000)
    assert static['coverage']['temporal'] == 'not_applicable'


@pytest.mark.parametrize('variables', ['all', [], ['wrong'], ['rain', 'extra'], [None]])
def test_estimate_cannot_silently_change_explicit_variable_selection(variables):
    offer = c.normalize_estimate(REQUEST, {**ESTIMATE, 'coverage_complete': True,
        'variables': variables}, 10000)
    assert 'variable_selection_mismatch' in offer['blockers']
    assert not offer['eligible'] and not offer['inspection_allowed']


def test_explicit_all_is_supported_but_never_inferred_from_a_failed_selection():
    assert c.normalize_estimate({**REQUEST, 'variables': []},
        {**ESTIMATE, 'variables': 'all'}, 10000)['inspection_allowed']
    assert c.normalize_estimate(REQUEST, {**ESTIMATE, 'variables': ['rain']}, 10000)['inspection_allowed']


@pytest.mark.parametrize('kind', ['raster', 'netcdf_grid', 'unknown_format'])
@pytest.mark.parametrize('coverage', [None, True])
def test_unconfirmed_explicit_selection_blocks_all_approval(kind, coverage):
    estimate = {k: v for k, v in ESTIMATE.items() if k != 'variables'}
    estimate.update(kind=kind, coverage_complete=coverage)
    offer = c.normalize_estimate(REQUEST, estimate, 10000)
    assert 'variable_selection_unconfirmed' in offer['blockers']
    assert not offer['eligible'] and not offer['inspection_allowed']
    whole = c.normalize_estimate({**REQUEST, 'variables': []}, estimate, 10000)
    assert whole['eligible'] or whole['inspection_allowed']


@pytest.mark.parametrize('change', [
    {'coverage_complete': False}, {'missing': ['layer_2']},
    {'selection_empty': True}, {'n_selected_cells': 0}, {'estimated_output_bytes': 0},
    {'estimated_output_bytes': -1}, {'estimated_output_bytes': 20000},
    {'estimated_output_bytes': True}, {'over_output_cap': True},
    {'subsettable': False}, {'transformations': ['reproject']},
    {'coverage_complete': 'true'}, {'selection_empty': 'false'}, {'n_selected_cells': -1},
])
def test_bad_estimates_cannot_be_inspection_approved(change):
    offer = c.normalize_estimate(REQUEST, {**ESTIMATE, 'coverage_complete': True, **change}, 10000)
    assert not offer['eligible'] and not offer['inspection_allowed']
    assert offer['blockers']


@pytest.mark.parametrize('change', [
    {'variables': ['wrong']}, {'time_range': ['2000-01-01', '2000-12-31']},
    {'bounds': [0, 0, 1, 1]}, {'n_time_steps': 0},
])
def test_non_cmfd_manifest_scope_conflicts_are_rejected(change):
    part = {'variables': ['rain'], 'bounds': REQUEST['bbox'], 'crs': 'EPSG:4326',
            'time_range': ['2000-01-01', '2000-01-07'], 'n_time_steps': 7}
    with pytest.raises(ValueError):
        c.check_manifest_scope(REQUEST, ESTIMATE, [{**part, **change}])


def test_variable_year_partition_advertisement_is_checked_without_dataset_kind():
    estimate = {**ESTIMATE, 'variables': ['rain'], 'years': [2000, 2001]}
    with pytest.raises(ValueError, match='omits'):
        c.check_manifest_scope(REQUEST, estimate, [{'variable': 'rain', 'year': 2000}])


def test_actual_netcdf_time_axis_is_checked_even_when_manifest_claims_success(tmp_path):
    nc = pytest.importorskip('netCDF4')
    path = tmp_path / 'rain.nc'
    with nc.Dataset(path, 'w') as ds:
        ds.createDimension('time', 8)
        time = ds.createVariable('time', 'i4', ('time',))
        time.units = 'days since 2000-01-01'
        time[:] = list(range(8))
        ds.createVariable('rain', 'f4', ('time',))[:] = 1
    part = {'name': 'rain.nc', 'variables': ['rain'], 'n_time_steps': 7,
            'time_range': ['2000-01-01', '2000-01-07']}
    with pytest.raises(ValueError, match='exceeds'):
        c.inspect_native_files(tmp_path, REQUEST, [part])
    with nc.Dataset(path, 'a') as ds:
        ds.variables['time'][:] = [0, 1, 2, 3, 4, 5, 6, 6]
    with pytest.raises(ValueError, match='count'):
        c.inspect_native_files(tmp_path, REQUEST, [part])


def test_invalid_tiff_and_netcdf_are_not_published_as_success(tmp_path):
    pytest.importorskip('netCDF4')
    for name in ('fake.tif', 'fake.nc'):
        (tmp_path / name).write_bytes(b'not a scientific file')
        with pytest.raises(ValueError):
            c.inspect_native_files(tmp_path, REQUEST, [{'name': name}])
