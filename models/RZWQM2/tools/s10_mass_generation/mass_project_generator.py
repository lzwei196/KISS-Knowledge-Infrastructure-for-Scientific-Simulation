#!/usr/bin/env python3
"""
mass_project_generator.py
=========================
Generate multiple RZWQM2 scenarios from a CSV of sites.

THE SINGLE ENTRY POINT for batch RZWQM2 setup. Agents should call this tool,
not write custom setup scripts. Incorporates all validated bug fixes (20+).

For each site, runs the full pipeline:
  S0: Retrieve soil (HWSD/SoilGrids) + forcing (CMFD/MSWX) + crop selection
  S1: Write site properties (lat/lon/elev in radians)
  S2: Generate .met file (E-pan=0, PAR=0 enforced)
  S3: Generate .brk file (mm→inches conversion)
  S4: Write soil properties (all 8 sections atomically)
  S5: Node discretization
  S6: Initial conditions
  S6.5: Management events (planting per year, correct crop_ref)
  S7: Scenario assembly (ipnames dates, RZX relative paths, nitrogen ON, sno copy)

Input CSV format:
    site_id,lat,lon,start_date,end_date,crop_name
    site_001,32.33,114.57,2000-01-01,2018-12-31,maize

Optional CSV columns:
    elevation, slope, soil_source, forcing_source, forcing_source_path,
    planting_doy, harvest_doy, density_seeds_per_ha

Usage:
    python mass_project_generator.py <sites.csv> <project_path> <template_path> \
        [soil_source] [forcing_source] [forcing_path]

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""
import sys
import os
import csv
import json
import math
import shutil
import glob
import traceback
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# INPUTS (override via sys.argv or set directly for IDE use)
# ---------------------------------------------------------------------------
SITES_CSV = ""
PROJECT_PATH = ""
TEMPLATE_PATH = "/home/server/RZWQM2/RZWQM2/template_bengbu/bengbu_wheat"  # Canonical template (clean Bengbu wheat project)
SOIL_SOURCE = "hwsd"                       # hwsd, soilgrids, vic_global
FORCING_SOURCE = "cmfd"                    # cmfd, mswx, csv
FORCING_SOURCE_PATH = "/media/server/hc_ssd/forcing/Data_forcing_03hr_010deg"
NUM_HORIZONS = 6

# ---------------------------------------------------------------------------
# Add tool directories to path
# ---------------------------------------------------------------------------
TOOLS_DIR = os.path.join(os.path.dirname(__file__), '..')
LIB_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'lib')
GLOBAL_DATA_DIR = os.path.join(TOOLS_DIR, 's0_global_data')
sys.path.insert(0, os.path.abspath(TOOLS_DIR))
sys.path.insert(0, os.path.abspath(LIB_DIR))
sys.path.insert(0, os.path.abspath(GLOBAL_DATA_DIR))

# Crop defaults: code, density, planting_doy, harvest_doy, row_spacing
CROP_DEFAULTS = {
    'maize': {'code': '7000', 'ref': 1, 'density': 84014, 'plant_doy': 120, 'harvest_doy': 280, 'row_cm': 76.0},
    'corn':  {'code': '7000', 'ref': 1, 'density': 84014, 'plant_doy': 120, 'harvest_doy': 280, 'row_cm': 76.0},
    'soybean': {'code': '7001', 'ref': 2, 'density': 518910, 'plant_doy': 135, 'harvest_doy': 280, 'row_cm': 76.0},
    'wheat': {'code': '7002', 'ref': 3, 'density': 3884000, 'plant_doy': 288, 'harvest_doy': 166, 'row_cm': 19.0},
    'winter_wheat': {'code': '7002', 'ref': 3, 'density': 3884000, 'plant_doy': 288, 'harvest_doy': 166, 'row_cm': 19.0},
    'spring_wheat': {'code': '7002', 'ref': 3, 'density': 3884000, 'plant_doy': 75, 'harvest_doy': 180, 'row_cm': 19.0},
}


def _load_sites(csv_path):
    """Load sites CSV."""
    sites = []
    with open(csv_path, 'r', newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            sites.append({
                'site_id': row['site_id'].strip(),
                'lat': float(row['lat']),
                'lon': float(row['lon']),
                'start_date': row['start_date'].strip(),
                'end_date': row['end_date'].strip(),
                'crop_name': row.get('crop_name', 'maize').strip().lower(),
                'elevation': float(row.get('elevation', 0) or 0),
                'slope': float(row.get('slope', 0.02) or 0.02),
                'soil_source': row.get('soil_source', '').strip() or None,
                'forcing_source': row.get('forcing_source', '').strip() or None,
                'forcing_source_path': row.get('forcing_source_path', '').strip() or None,
                'planting_doy': int(row['planting_doy']) if row.get('planting_doy') else None,
                'harvest_doy': int(row['harvest_doy']) if row.get('harvest_doy') else None,
                'density': int(row['density_seeds_per_ha']) if row.get('density_seeds_per_ha') else None,
            })
    return sites


def _setup_project(project_path, template_path):
    """Create project dirs and verify template."""
    for d in ['Meteorology', 'Analysis']:
        os.makedirs(os.path.join(project_path, d), exist_ok=True)
    if not os.path.isdir(template_path):
        raise RuntimeError(f"Template not found: {template_path}")


def _clone_template(project_path, template_path, site_id):
    """Copy template to new scenario dir, clean outputs, ensure binary + sno."""
    scenario_dir = os.path.join(project_path, site_id)
    if os.path.exists(scenario_dir):
        shutil.rmtree(scenario_dir)
    shutil.copytree(template_path, scenario_dir)

    # Remove old outputs
    for f in os.listdir(scenario_dir):
        p = os.path.join(scenario_dir, f)
        if os.path.isfile(p) and (
            f.endswith(('.OUT', '.out', '.ana', '.log', '.PLT', '.plt',
                        '.WTH', '.BIN', '.bin'))
            or 'Zone.Identifier' in f or f.startswith('C:')
        ) and f != 'test.out':
            os.remove(p)

    # Ensure binary is executable
    for name in ('main_ryzen_patched', 'main_ryzen', 'RZWQMRelease.exe'):
        bp = os.path.join(scenario_dir, name)
        if os.path.isfile(bp):
            os.chmod(bp, 0o755)
            break

    # Copy .sno to Meteorology/ (Bug 19 fix)
    met_dir = os.path.join(project_path, 'Meteorology')
    sno_dest = os.path.join(met_dir, site_id + '.sno')
    if not os.path.isfile(sno_dest) or os.path.getsize(sno_dest) == 0:
        sno_sources = glob.glob(os.path.join(scenario_dir, '*.sno'))
        if sno_sources:
            shutil.copy2(sno_sources[0], sno_dest)

    return scenario_dir


def _generate_one_site(site, config):
    """Generate a complete RZWQM2 scenario for one site."""
    site_id = site['site_id']
    lat = site['lat']
    lon = site['lon']
    project_path = config['project_path']
    start_dt = datetime.strptime(site['start_date'], '%Y-%m-%d')
    end_dt = datetime.strptime(site['end_date'], '%Y-%m-%d')
    crop_name = site['crop_name']
    crop = CROP_DEFAULTS.get(crop_name, CROP_DEFAULTS['maize'])

    steps = []

    # === Step 0: Clone template ===
    scenario_dir = _clone_template(project_path, config['template_path'], site_id)
    steps.append('template_cloned')

    # === Step 1: Retrieve soil (S0) ===
    soil_source = site.get('soil_source') or config['soil_source']
    from soil_source_adapter import validate_inputs as sv, process as sp
    ok, err, args = sv(str(lat), str(lon), soil_source,
                       config.get('soil_source_path', ''),
                       str(config.get('num_horizons', 6)), '')
    if not ok:
        raise RuntimeError(f"Soil validation: {err}")
    ok, err, soil_result = sp(args)
    if not ok:
        raise RuntimeError(f"Soil retrieval: {err}")
    horizons = soil_result['horizons']
    steps.append(f'soil_{soil_source}_{len(horizons)}h')

    # === Step 2: Retrieve forcing (S0) — ALWAYS use CMFD/MSWX, never VIC (dt_015) ===
    forcing_source = site.get('forcing_source') or config['forcing_source']
    forcing_path = site.get('forcing_source_path') or config['forcing_source_path']
    weather_csv = os.path.join(project_path, 'weather_csv', site_id + '_weather.csv')
    os.makedirs(os.path.dirname(weather_csv), exist_ok=True)

    # Cache: skip if CSV already exists with correct line count
    expected_days = (end_dt - start_dt).days + 1
    if os.path.isfile(weather_csv):
        with open(weather_csv) as f:
            existing_lines = sum(1 for _ in f) - 1  # minus header
        if existing_lines >= expected_days * 0.95:
            steps.append('forcing_cached')
        else:
            os.remove(weather_csv)

    if not os.path.isfile(weather_csv):
        from forcing_source_adapter import validate_inputs as fv, process as fp
        ok, err, fargs = fv(str(lat), str(lon), site['start_date'], site['end_date'],
                            forcing_source, forcing_path, weather_csv)
        if not ok:
            raise RuntimeError(f"Forcing validation: {err}")
        ok, err, fsummary = fp(fargs)
        if not ok:
            raise RuntimeError(f"Forcing retrieval: {err}")
        steps.append(f'forcing_{forcing_source}_{fsummary["record_count"]}d')

    # === Step 3: Site properties (S1) — lat/lon in RADIANS (dt_009) ===
    from s1_site_config.write_site_properties import validate_inputs as s1v, process as s1p
    lat_rad = round(lat * math.pi / 180.0, 4)
    lon_rad = round(lon * math.pi / 180.0, 4)
    ok, err, s1args = s1v(project_path, site_id, str(lat_rad), str(lon_rad),
                          str(site['elevation']), str(site['slope']),
                          '10000', '0', '420', '1')
    if not ok:
        raise RuntimeError(f"Site config: {err}")
    s1p(s1args)
    steps.append('site_config')

    # === Step 4: Generate .met + QC (S2) — E-pan=0, PAR=0 enforced (dt_014) ===
    met_path = os.path.join(project_path, 'Meteorology', site_id + '.met')
    from s2_met_prep.generate_met_file import validate_inputs as m2v, process as m2p
    ok, err, m2args = m2v(weather_csv, met_path, site['start_date'], site['end_date'])
    if not ok:
        raise RuntimeError(f"Met file: {err}")
    m2p(m2args)
    steps.append('met_file')

    # QC
    from s2_met_prep.met_quality_check import process as qcp
    from rzwqm_file import RZWQM
    rz = RZWQM(project_path, site_id)
    rz.rzwqm_met_quality_check()
    steps.append('met_qc')

    # === Step 5: BRK (S3) — mm→inches (dt_004) ===
    rz.create_breakpoint_file()
    steps.append('brk_file')

    # === Step 6: Write soil properties (S4) — all 8 sections atomic ===
    from s4_soil_setup.write_soil_properties import process as s4p
    dat_path = rz.dat_path
    ok, err, _ = s4p({
        'project_path': project_path, 'station_id': site_id,
        'soil_config': {'horizons': horizons}, 'dat_path': dat_path,
    })
    if not ok:
        raise RuntimeError(f"Soil write: {err}")
    steps.append('soil_properties')

    # === Step 7: Node discretization (S5) ===
    from s5_node_discretization.generate_nodes import process as s5p
    depths = [h['depth_cm'] for h in horizons]
    ok, err, _ = s5p({
        'project_path': project_path, 'station_id': site_id,
        'horizon_depths': depths, 'dat_path': dat_path,
    })
    if not ok:
        raise RuntimeError(f"Nodes: {err}")
    steps.append('nodes')

    # === Step 8: Initial conditions (S6) ===
    horizon_list = list(range(1, len(horizons) + 1))
    rz_fresh = RZWQM(project_path, site_id)
    rz_fresh.write_new_soil_init_water_and_temp(horizon_list)
    rz_fresh.write_new_soil_init_chemistry(horizon_list)
    rz_fresh.write_new_soil_init_nutrient(horizon_list)
    steps.append('init_conditions')

    # === Step 9: Management events (S6.5) — correct crop_ref, density (Bug 8,9,10,11) ===
    sim_years = list(range(start_dt.year, end_dt.year + 1))
    plant_doy = site.get('planting_doy') or crop['plant_doy']
    harvest_doy = site.get('harvest_doy') or crop['harvest_doy']
    density = site.get('density') or crop['density']

    from s6_management_write.write_management_events import validate_inputs as m6v, process as m6p
    mgmt_config = {
        "planting": {
            "crop_ref": crop['ref'],
            "planting_doy": plant_doy,
            "harvest_doy": harvest_doy,
            "row_spacing_cm": crop['row_cm'],
            "depth_layer_index": 4,
            "density_seeds_per_ha": density,
            "method": 0,
            "harvest_trigger": 3,
            "growth_stage_threshold": 0.0,
            "stubble_height_cm": 10.0,
            "harvest_efficiency": 1.0,
            "harvest_type": 3,
        },
        "fertilizer": {
            "applications": [{
                "timing": 1, "offset_days": 0, "method": 2,
                "no3_kg_ha": 0, "nh4_kg_ha": 85, "urea_kg_ha": 85,
                "bmp_chem": 1, "bmp_method": 1,
                "split_min_days": 0, "split_starter_frac": 0,
                "split_max_n": 0, "p_mass_kg_ha": 0,
            }]
        },
        "irrigation": {"is_irrigated": False},
    }
    ok, err, m6args = m6v(project_path, site_id,
                          mgmt_config, sim_years)
    if not ok:
        raise RuntimeError(f"Management validation: {err}")
    ok, err, m6result = m6p(m6args)
    if not ok:
        raise RuntimeError(f"Management write: {err}")
    steps.append(f'management_{m6result.get("num_plantings", "?")}p')

    # === Step 10: Update ipnames paths + dates (S7) — case-aware (Bug 2,5,6) ===
    from s7_scenario_assembly.update_ipnames_paths import validate_inputs as ipv, process as ipp
    ok, err, ipargs = ipv(project_path, site_id, project_path,
                          site['start_date'], site['end_date'])
    if not ok:
        raise RuntimeError(f"Ipnames: {err}")
    ipp(ipargs)
    steps.append('ipnames')

    # === Step 11: Update RZX paths — relative, trailing slash, nitrogen ON (Bug 9,14) ===
    from s7_scenario_assembly.update_rzx_paths import _update_single_rzx
    for rzx_file in glob.glob(os.path.join(scenario_dir, '*.RZX')):
        _update_single_rzx(rzx_file, 'DSSAT/', './')
    steps.append('rzx_paths')

    # === Step 12: Update crop selection in rzwqm.dat (Bug 13) ===
    from s7_scenario_assembly.update_crop_selection import _update_file
    crop_line = f"{crop['code']}  {crop_name}"
    _update_file(dat_path, crop['code'], crop_line)
    steps.append('crop_selection')

    # === Step 13: Update cultivar from DSSAT China library (latitude-based) ===
    try:
        from s7_scenario_assembly.update_cultivar import _select_by_lat, _read_china_cul, _convert_to_040, _find_active_var_id
        china_culs, _ = _read_china_cul(crop_name)
        if china_culs:
            cul_id, cul_name = _select_by_lat(crop_name, lat)
            if cul_id and cul_id in china_culs:
                target_var = _find_active_var_id(scenario_dir, crop_name)
                new_line = _convert_to_040(china_culs[cul_id], crop_name, target_var)
                _, cul_filename = __import__('s7_scenario_assembly.update_cultivar', fromlist=['CROP_CUL_MAP']).CROP_CUL_MAP.get(crop_name, ('', 'MZCER040.CUL'))
                cul_path = os.path.join(scenario_dir, 'DSSAT', cul_filename)
                if os.path.isfile(cul_path):
                    with open(cul_path) as f:
                        cul_lines = f.readlines()
                    for ci, cl in enumerate(cul_lines):
                        if cl.startswith(target_var):
                            cul_lines[ci] = new_line + '\n'
                            break
                    with open(cul_path, 'w') as f:
                        f.writelines(cul_lines)
                    steps.append(f'cultivar_{cul_id}')
    except Exception:
        pass  # China cultivar library not available — use template default

    return steps


def validate_inputs(sites_csv, project_path, template_path,
                    soil_source, forcing_source, forcing_path):
    """Validate inputs."""
    errors = []
    if not sites_csv:
        errors.append("SITES_CSV is required.")
    elif not os.path.isfile(sites_csv):
        errors.append(f"SITES_CSV not found: {sites_csv}")
    if not project_path:
        errors.append("PROJECT_PATH is required.")
    if not template_path:
        errors.append("TEMPLATE_PATH is required.")
    elif not os.path.isdir(template_path):
        errors.append(f"TEMPLATE_PATH not found: {template_path}")
    if errors:
        return False, "; ".join(errors), None
    return True, "", {
        'sites_csv': sites_csv,
        'project_path': project_path if project_path.endswith('/') else project_path + '/',
        'template_path': template_path,
        'soil_source': soil_source or 'hwsd',
        'forcing_source': forcing_source or 'cmfd',
        'forcing_source_path': forcing_path or '',
        'num_horizons': NUM_HORIZONS,
    }


def process(args):
    """Generate scenarios for all sites."""
    try:
        sites = _load_sites(args['sites_csv'])
        if not sites:
            return False, "No sites in CSV.", None

        _setup_project(args['project_path'], args['template_path'])

        results = []
        for site in sites:
            try:
                steps = _generate_one_site(site, args)
                results.append({'site_id': site['site_id'], 'status': 'ok', 'steps': steps})
                print(f"  {site['site_id']}: OK ({len(steps)} steps)")
            except Exception as e:
                results.append({'site_id': site['site_id'], 'status': 'failed', 'error': str(e)})
                print(f"  {site['site_id']}: FAILED — {e}")

        ok_count = sum(1 for r in results if r['status'] == 'ok')
        fail_count = sum(1 for r in results if r['status'] == 'failed')
        summary = {'total': len(sites), 'succeeded': ok_count, 'failed': fail_count, 'results': results}
        return (fail_count == 0), (f"{fail_count} sites failed" if fail_count else ""), summary

    except Exception as e:
        return False, f"Processing error: {e}", None


def main():
    sites_csv = sys.argv[1] if len(sys.argv) > 1 else SITES_CSV
    project_path = sys.argv[2] if len(sys.argv) > 2 else PROJECT_PATH
    template_path = sys.argv[3] if len(sys.argv) > 3 else TEMPLATE_PATH
    soil_source = sys.argv[4] if len(sys.argv) > 4 else SOIL_SOURCE
    forcing_source = sys.argv[5] if len(sys.argv) > 5 else FORCING_SOURCE
    forcing_path = sys.argv[6] if len(sys.argv) > 6 else FORCING_SOURCE_PATH

    ok, err, args = validate_inputs(sites_csv, project_path, template_path,
                                     soil_source, forcing_source, forcing_path)
    if not ok:
        print(json.dumps({"status": "INPUT_ERROR", "message": err}))
        sys.exit(1)

    ok, err, summary = process(args)
    if not ok:
        print(json.dumps({"status": "PROCESSING_ERROR", "message": err, "summary": summary}))
        sys.exit(2)

    print(json.dumps({
        "status": "SUCCESS",
        "summary": {'total': summary['total'], 'succeeded': summary['succeeded'], 'failed': summary['failed']},
        "message": f"Generated {summary['succeeded']}/{summary['total']} scenarios."
    }))
    sys.exit(0)


if __name__ == '__main__':
    main()
