#!/usr/bin/env python3
"""
run_grid_ensemble.py — drive a GRIDDED ENSEMBLE of DSSAT point runs over one
gridded-yield observation cell (e.g. a GDHY 0.5-deg pixel).

WHY THIS EXISTS
---------------
dag.yaml outputs[HWAM].observability routes a gridded multi-season yield
observation to obs_shape='spatial_time_series' /
comparison_mode='spatial_field_comparison', whose caveat reads:

    "Requires a gridded ensemble of DSSAT point runs over multiple seasons"

DSSAT has no built-in spatial mode (SKILL.md "Known Limitations": "No built-in
spatial mode - grid simulations use wrapper scripts"). This IS that wrapper.
Scoring ONE point run against a ~2500 km2 area-average actual-yield pixel is a
run-SUPPORT mismatch, not a model verdict.

WHAT IT DOES
------------
1. Read SPAM2020 V2r0 PHYSICAL AREA for the crop over the obs cell
   (spam2020_V2r0_global_A_<CODE>_{A,I,R}.tif, 5-arcmin EPSG:4326, ha) and keep
   every 5-arcmin cell with area > 0.
2. Bin those cells onto the 0.1-deg CMFD / SoilGrids grid -> one ENSEMBLE NODE
   per 0.1-deg cell, carrying irrigated_ha and rainfed_ha.
   (Verified at 33.75N/114.25E, maize: 36 SPAM cells, 64281 ha,
    39296 ha irrigated = 61% / 24984 ha rainfed = 39%.)
3. Extract weather for every node in ONE pass (extract_cmfd_points.py) and one
   SoilGrids profile per node (convert_soilgrids_to_sol.py).
4. Run DSSAT for each (node, technology) pair: technology I -> irrigation='auto',
   technology R -> irrigation='none'. The SAME crop therefore appears as an
   irrigated AND a rainfed member, which is exactly what the obs pixel mixes.
5. Emit grid_yield_long.csv (member_id, tech, year, hwam_kgha, area_ha) for
   aggregate_grid_to_pixel.py to area-weight to the pixel support.

GUARANTEES
----------
* RESUMABLE  — a (member, tech) whose Summary.OUT already parses to the full
               season count is skipped; a completed member directory is NEVER
               deleted.
* NO SILENT TRUNCATION — every member that does not complete is written to
               members_failed.csv and the process exits non-zero.

Usage:
    python run_grid_ensemble.py \
        --lat 33.75 --lon 114.25 --cell_size 0.5 \
        --crop maize --cultivar CN0001 \
        --start_year 2000 --end_year 2016 \
        --forcing_dir /mnt/disk1/Hydrocraft_server/data/forcing/Data_forcing_03hr_010deg \
        --out_dir /tmp/dssat_gdhy_zhoukou_grid --resume

Exit codes: 0 = every member completed; 1 = input/setup error;
            2 = one or more members failed (see members_failed.csv).
"""

import argparse
import csv
import math
import os
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]          # .../knowledge_infrastructure/tools
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, '/mnt/disk1/Hydrocraft_server/models/ki_tools_common')

SPAM_PHYS_DIR = "/mnt/datasets/Crop_model_dataset/SPAM2020/physical_area"

# SPAM 4-letter crop code <-> DSSAT 2-letter crop code.
CROP_MAP = {
    'maize':   ('MAIZ', 'MZ'),
    'wheat':   ('WHEA', 'WH'),
    'rice':    ('RICE', 'RI'),
    'soybean': ('SOYB', 'SB'),
    'sorghum': ('SORG', 'SG'),
    'barley':  ('BARL', 'BA'),
    'potato':  ('POTA', 'PT'),
}

CMFD_GRID = 0.1          # deg — CMFD V2.0 cell size (centres at X.X5)

# Width of the DSSBatch.v48 @FILEX path field, in columns.
#
# PRIMARY SOURCE — dssat-csm-os v4.8 (/home/server/DSSAT), not KI folklore:
#   CSM_Main/CSM.for:268  END_POS = LEN(TRIM(CHARTEST(1:92)))+1   -> field = cols 1-92
#   CSM_Main/CSM.for:269  FILEX  = CHARTEST((END_POS-12):(END_POS-1))
#   CSM_Main/CSM.for:270  PATHEX = CHARTEST(1:END_POS-13)
#   CSM_Main/CSM.for:271  READ(CHARTEST(93:113),110) TRTNUM,TRTREP,ROTNUM
#   InputModule/ipexp.for:97  CHARACTER*92 FILEX_P
# Matches shared_specs/dssat/base/format_spec.yaml
# `field_widths.FILEX.record_length: 92`, and is the tighter of that spec's two
# FILEX width rules (`path_constraints.FILEX.max_chars: 95` disagrees; a tier-2
# correction to 92 is proposed separately). A field written to 92 satisfies both.
FILEX_MAX = 92


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# Step 1-2: SPAM cropland mask -> ensemble nodes on the 0.1-deg grid
# ---------------------------------------------------------------------------

def build_members(crop, lat, lon, cell_size, bbox=None, grid=CMFD_GRID):
    """Bin SPAM 5-arcmin physical area onto the 0.1-deg grid.

    Returns (nodes, totals) where nodes is a list of dicts
        {lat, lon, irrigated_ha, rainfed_ha, total_ha, n_spam_cells}
    sorted by total_ha descending, and totals summarises the whole obs cell.
    """
    import numpy as np
    import rasterio
    from rasterio.windows import from_bounds

    spam_code = CROP_MAP[crop][0]
    if bbox:
        lon_min, lat_min, lon_max, lat_max = bbox
    else:
        h = cell_size / 2.0
        lat_min, lat_max = lat - h, lat + h
        lon_min, lon_max = lon - h, lon + h

    layers = {}
    for tech in ('I', 'R'):
        path = os.path.join(SPAM_PHYS_DIR,
                            f"spam2020_V2r0_global_A_{spam_code}_{tech}.tif")
        if not os.path.isfile(path):
            raise FileNotFoundError(f"SPAM physical-area layer missing: {path}")
        with rasterio.open(path) as ds:
            win = from_bounds(lon_min, lat_min, lon_max, lat_max, ds.transform)
            # shared_specs/spam2020/format_spec.yaml `recommended_read_pattern`,
            # followed verbatim and in the order the spec gives:
            #   data = src.read(1).astype(float)
            #   data = np.nan_to_num(data, nan=0.0)   # explicit NaN clearing
            #   # ONLY THEN apply negative-value filter if needed:
            #   # data[data < 0] = 0
            # `nodata_conventions.sentinel: NaN` with
            # `must_explicit_nan_check: true` — NaN, not a negative value, is
            # the nodata sentinel, and `data[data<0]=0` does NOT clear it (it
            # propagates through .sum(); the Xinjiang failure the rule records).
            # `also_negative_values: false` means negatives are NOT nodata, so
            # they are cleared as a SEPARATE, explicit domain guard below —
            # physical area in ha cannot be < 0 — never as NaN handling.
            arr = ds.read(1, window=win).astype(float)
            arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
            arr[arr < 0] = 0.0
            layers[tech] = (arr, ds.window_transform(win))

    (arr_i, tr), (arr_r, _) = layers['I'], layers['R']
    if arr_i.shape != arr_r.shape:
        raise RuntimeError("SPAM _I and _R windows differ in shape — "
                           "layers are not on the same grid")

    nodes = {}
    nrow, ncol = arr_i.shape
    for r in range(nrow):
        for c in range(ncol):
            ai, ar = float(arr_i[r, c]), float(arr_r[r, c])
            if ai <= 0 and ar <= 0:
                continue
            # 5-arcmin cell centre
            clon, clat = tr * (c + 0.5, r + 0.5)
            # Bin onto the CMFD/SoilGrids 0.1-deg grid (centres at X.X5)
            nlat = round(math.floor(clat / grid) * grid + grid / 2.0, 4)
            nlon = round(math.floor(clon / grid) * grid + grid / 2.0, 4)
            n = nodes.setdefault((nlat, nlon),
                                 {'lat': nlat, 'lon': nlon, 'irrigated_ha': 0.0,
                                  'rainfed_ha': 0.0, 'n_spam_cells': 0})
            n['irrigated_ha'] += ai
            n['rainfed_ha'] += ar
            n['n_spam_cells'] += 1

    out = sorted(nodes.values(),
                 key=lambda n: -(n['irrigated_ha'] + n['rainfed_ha']))
    for n in out:
        n['total_ha'] = n['irrigated_ha'] + n['rainfed_ha']

    totals = {
        'bbox': (lon_min, lat_min, lon_max, lat_max),
        'n_spam_cells': int(sum(n['n_spam_cells'] for n in out)),
        'total_ha': float(sum(n['total_ha'] for n in out)),
        'irrigated_ha': float(sum(n['irrigated_ha'] for n in out)),
        'rainfed_ha': float(sum(n['rainfed_ha'] for n in out)),
        'n_nodes': len(out),
    }
    totals['irrigated_fraction'] = (totals['irrigated_ha'] / totals['total_ha']
                                    if totals['total_ha'] > 0 else None)
    return out, totals


# ---------------------------------------------------------------------------
# Management (mirrors run_and_score.py stage 7 so members are comparable)
# ---------------------------------------------------------------------------

def node_management(lat, lon, crop, plant_doy_override=None, fert_n_override=None):
    """Per-node planting DOY and N rate from the real data sources."""
    note = []
    if plant_doy_override is not None:
        plant_doy = int(plant_doy_override)
        note.append(f"plant_doy={plant_doy} (CLI override)")
    else:
        from ki_tools_common.crop_calendar import get_planting_harvest
        cal = get_planting_harvest(lat, lon, crop)
        plant_doy = int(cal['plant_doy'])
        note.append(f"plant_doy={plant_doy} ({cal['source']})")
        # SKILL.md "Crop Calendar Reference (China)": in the Huang-Huai belt
        # (32-36N) maize is the SUMMER crop sown after the winter-wheat
        # harvest. The GGCMI global 'maize' calendar returns a late-May date
        # because it does not separate the double-cropping system.
        if crop == 'maize' and 32.0 <= lat <= 36.0 and plant_doy < 160:
            plant_doy = 165
            note.append("clamped to 165 (SKILL.md Huang-Huai summer maize)")

    if fert_n_override is not None:
        fert_n = float(fert_n_override)
        note.append(f"n_kgha={fert_n} (CLI override)")
    else:
        from ki_tools_common.fertilizer import get_fertilizer_rates
        fert = get_fertilizer_rates(lat, lon, crop)
        fert_n = round(float(fert['n_kgha']), 1)
        note.append(f"n_kgha={fert_n} ({fert['source']})")

    return plant_doy, fert_n, "; ".join(note)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description='Run a gridded ensemble of DSSAT point simulations over a '
                    'gridded-yield observation cell.')
    ap.add_argument('--lat', type=float, help='Obs cell centre latitude')
    ap.add_argument('--lon', type=float, help='Obs cell centre longitude')
    ap.add_argument('--cell_size', type=float, default=0.5,
                    help='Obs cell size in degrees (GDHY = 0.5)')
    ap.add_argument('--bbox', type=str, default=None,
                    help='Alternative to --lat/--lon/--cell_size: '
                         'lon_min,lat_min,lon_max,lat_max')
    ap.add_argument('--crop', default='maize', choices=sorted(CROP_MAP))
    ap.add_argument('--cultivar', default=None)
    ap.add_argument('--start_year', type=int, required=True)
    ap.add_argument('--end_year', type=int, required=True)
    ap.add_argument('--forcing_dir', required=True)
    ap.add_argument('--out_dir', required=True)
    ap.add_argument('--members_step', type=float, default=CMFD_GRID,
                    help='Ensemble node spacing in degrees (default 0.1 = the '
                         'CMFD/SoilGrids grid)')
    ap.add_argument('--max_members', type=int, default=None,
                    help='Cap the number of NODES (largest cropland area '
                         'first). Dropped area is logged, never silent.')
    ap.add_argument('--plant_doy', type=int, default=None)
    ap.add_argument('--fert_n', type=float, default=None)
    ap.add_argument('--irr_ithrl', type=float, default=40,
                    help='Automatic-irrigation threshold (%% of AWC) for '
                         'IRRIGATED members')
    ap.add_argument('--irr_amt', type=float, default=40,
                    help='Automatic-irrigation application (mm) for '
                         'IRRIGATED members')
    ap.add_argument('--ppop', type=float, default=6.0)
    ap.add_argument('--plrs', type=int, default=60)
    ap.add_argument('--timeout', type=int, default=3600)
    ap.add_argument('--resume', action='store_true')
    ap.add_argument('--python', default=sys.executable)
    a = ap.parse_args()

    if a.bbox:
        bbox = tuple(float(v) for v in a.bbox.split(','))
        if len(bbox) != 4:
            sys.stderr.write("ERROR: --bbox needs lon_min,lat_min,lon_max,lat_max\n")
            sys.exit(1)
    elif a.lat is not None and a.lon is not None:
        bbox = None
    else:
        sys.stderr.write("ERROR: give either --lat/--lon (+--cell_size) or --bbox\n")
        sys.exit(1)

    if a.end_year < a.start_year:
        sys.stderr.write("ERROR: --end_year must be >= --start_year\n")
        sys.exit(1)

    out_dir = os.path.abspath(a.out_dir)
    members_dir = os.path.join(out_dir, 'members')
    weather_dir = os.path.join(out_dir, 'weather')
    soil_dir = os.path.join(out_dir, 'soil')
    for d in (out_dir, members_dir, weather_dir, soil_dir):
        os.makedirs(d, exist_ok=True)

    # Fail fast on the Fortran FileX field rather than deep in DSSAT.
    #
    # The check is on the string DSSAT RECEIVES, not on the host path. Each
    # member's DSSBatch.v48 records the FileX RELATIVE to that member's workdir
    # (dssat_workdir_setup._generate_batch, per format_spec
    # path_constraints.FILEX.must_be_relative_to_workdir), because run_dssat
    # launches ./dscsm048 with cwd=<member workdir>. So --out_dir length does
    # NOT enter the 92-column field and must not be gated on it — the previous
    # check here measured an absolute host path DSSAT never sees, which both
    # capped --out_dir for no reason and proved nothing about the real field.
    probe = 'G0000001.MZX'                      # the FILEX field a member writes
    if os.path.isabs(probe) or len(probe) > FILEX_MAX:
        sys.stderr.write(
            f"ERROR: member FILEX field {probe!r} violates the {FILEX_MAX}-column "
            f"DSSBatch field (CSM.for:268)\n")
        sys.exit(1)

    # --out_dir DOES reach DSSAT through DSSATPRO.v48, which records absolute
    # paths read into CHARACTER*102 DSSATP / CHARACTER*120 PATHX
    # (CSM_Main/CSM.for:97,99). Warn against that budget, not the FileX one.
    member_probe = os.path.join(members_dir, 'G000_I')
    if len(member_probe) > 102:
        sys.stderr.write(
            f"WARNING: --out_dir is long: a member workdir is {len(member_probe)} "
            f"chars and DSSATPRO.v48 entries are read into CHARACTER*102 "
            f"(CSM.for:97). Consider a shorter --out_dir (e.g. under /tmp).\n")

    # ---------------- Step 1-2: ensemble design from the cropland mask -----
    try:
        nodes, totals = build_members(a.crop, a.lat, a.lon, a.cell_size,
                                      bbox=bbox, grid=a.members_step)
    except Exception as e:                                    # noqa: BLE001
        sys.stderr.write(f"ERROR building ensemble from SPAM: {e}\n")
        sys.exit(1)

    if not nodes:
        sys.stderr.write(
            f"ERROR: SPAM2020 reports NO {a.crop} physical area in "
            f"{totals['bbox']} — this obs cell has no cropland to simulate.\n")
        sys.exit(1)

    log(f"SPAM2020 {a.crop} over {totals['bbox']}: "
        f"{totals['n_spam_cells']} 5-arcmin cells, {totals['total_ha']:.0f} ha "
        f"({totals['irrigated_ha']:.0f} ha irrigated = "
        f"{100 * totals['irrigated_fraction']:.1f}% / "
        f"{totals['rainfed_ha']:.0f} ha rainfed) -> {len(nodes)} node(s) "
        f"on the {a.members_step}-deg grid")

    if a.max_members is not None and a.max_members < len(nodes):
        dropped = nodes[a.max_members:]
        nodes = nodes[:a.max_members]
        d_ha = sum(n['total_ha'] for n in dropped)
        # No silent caps: say exactly what coverage was given up.
        log(f"WARNING --max_members={a.max_members}: DROPPED {len(dropped)} "
            f"node(s) totalling {d_ha:.0f} ha "
            f"({100 * d_ha / totals['total_ha']:.1f}% of the cell's cropland). "
            f"The aggregate is a SUBSET, not the full pixel.")

    # ---------------- Step 2: members.csv ----------------------------------
    members = []          # one row per (node, tech)
    for i, n in enumerate(nodes):
        station = f"G{i:03d}"
        for tech, area in (('I', n['irrigated_ha']), ('R', n['rainfed_ha'])):
            if area <= 0:
                continue
            members.append({
                'member_id': station,
                'lat': n['lat'], 'lon': n['lon'],
                'tech': tech, 'area_ha': round(area, 3),
            })

    members_csv = os.path.join(out_dir, 'members.csv')
    with open(members_csv, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=['member_id', 'lat', 'lon', 'tech', 'area_ha'])
        w.writeheader()
        w.writerows(members)
    log(f"members.csv: {len(members)} (node,technology) member(s) over "
        f"{len(nodes)} node(s) -> {members_csv}")

    failures = []   # (member_id, tech, stage, error)

    # ---------------- Step 3a: weather, ONE pass over the CMFD store -------
    points_csv = os.path.join(out_dir, 'points.csv')
    with open(points_csv, 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['station', 'lat', 'lon'])
        for i, n in enumerate(nodes):
            w.writerow([f"G{i:03d}", n['lat'], n['lon']])

    cmd = [a.python, str(TOOLS / 's2_weather_prep' / 'extract_cmfd_points.py'),
           '--forcing_dir', a.forcing_dir, '--points_csv', points_csv,
           '--start_year', str(a.start_year), '--end_year', str(a.end_year),
           '--out_dir', weather_dir]
    if a.resume:
        cmd.append('--resume')
    log("Extracting weather for all nodes in one pass ...")
    rc = subprocess.run(cmd).returncode
    if rc not in (0, 2):
        sys.stderr.write(f"ERROR: extract_cmfd_points.py failed (rc={rc})\n")
        sys.exit(1)

    # ---------------- Step 3b: soil, one profile per node ------------------
    log("Building one SoilGrids profile per node ...")
    node_ok = {}
    for i, n in enumerate(nodes):
        station = f"G{i:03d}"
        wth = os.path.join(weather_dir, f"{station}0001.WTH")
        sol = os.path.join(soil_dir, f"{station}.SOL")
        soil_id = f"{station}000001"          # 10 chars — matches .SOL profile
        if not (os.path.isfile(wth) and os.path.getsize(wth) > 0):
            node_ok[station] = (None, None, None, 'weather', f"missing {wth}")
            continue
        if not (a.resume and os.path.isfile(sol) and soil_id in open(sol).read()):
            p = subprocess.run(
                [a.python, str(TOOLS / 's3_soil_setup' / 'convert_soilgrids_to_sol.py'),
                 '--lat', str(n['lat']), '--lon', str(n['lon']),
                 '--output', sol, '--soil_id', soil_id],
                capture_output=True, text=True)
            if p.returncode != 0 or not os.path.isfile(sol):
                node_ok[station] = (None, None, None, 'soil',
                                    (p.stderr or p.stdout or '')[-300:])
                continue
        node_ok[station] = (wth, sol, soil_id, None, None)

    # ---------------- Step 4: run every (node, technology) member ----------
    sys.path.insert(0, str(TOOLS))
    from dssat_workdir_setup import create_workdir, run_dssat, parse_summary

    dssat_crop = CROP_MAP[a.crop][1]
    n_seasons = a.end_year - a.start_year + 1
    mgmt_notes = {}

    for m in members:
        station, tech = m['member_id'], m['tech']
        wth, sol, soil_id, bad_stage, bad_err = node_ok[station]
        if bad_stage:
            failures.append((station, tech, bad_stage, bad_err))
            continue

        wd = os.path.join(members_dir, f"{station}_{tech}")

        if a.resume and os.path.isfile(os.path.join(wd, 'Summary.OUT')):
            try:
                done = [r for r in parse_summary(wd)
                        if r.get('HWAM') not in (None, '', -99)]
            except Exception:                                 # noqa: BLE001
                done = []
            if len(done) >= n_seasons:
                log(f"  [{station}_{tech}] CACHED ({len(done)} seasons)")
                continue

        try:
            plant_doy, fert_n, note = node_management(
                m['lat'], m['lon'], a.crop, a.plant_doy, a.fert_n)
            mgmt_notes[station] = note
        except Exception as e:                                # noqa: BLE001
            failures.append((station, tech, 'management', str(e)[:300]))
            continue

        # THE ensemble distinction: the SAME crop as an irrigated and as a
        # rainfed member. tech=I -> DSSAT automatic irrigation (IRRIG=A),
        # tech=R -> genuinely dryland (IRRIG=N).
        irr_kwargs = ({'irrigation': 'auto', 'irr_ithrl': int(a.irr_ithrl),
                       'irr_amt': int(a.irr_amt), 'irr_imdep': 30}
                      if tech == 'I' else {'irrigation': 'none'})

        try:
            create_workdir(
                crop=dssat_crop, cultivar=a.cultivar, weather_file=wth,
                soil_id=soil_id, soil_file=sol,
                lat=m['lat'], lon=m['lon'],
                planting_date=(a.start_year % 100) * 1000 + plant_doy,
                start_year=a.start_year, end_year=a.end_year,
                output_dir=wd,
                ppop=a.ppop, plrs=a.plrs, pldp=5,
                fert_n=fert_n, fert_date_offset=30,
                **irr_kwargs)
        except Exception as e:                                # noqa: BLE001
            failures.append((station, tech, 'create_workdir', str(e)[:300]))
            continue

        res = run_dssat(wd, timeout=a.timeout)
        if not res.get('success'):
            failures.append((station, tech, 'run_dssat',
                             f"rc={res.get('return_code')} "
                             f"{(res.get('stderr') or '')[-200:]}"))
            continue
        try:
            got = [r for r in parse_summary(wd)
                   if r.get('HWAM') not in (None, '', -99)]
        except Exception as e:                                # noqa: BLE001
            failures.append((station, tech, 'parse_summary', str(e)[:300]))
            continue
        log(f"  [{station}_{tech}] {len(got)}/{n_seasons} seasons, "
            f"mean HWAM {sum(float(r['HWAM']) for r in got) / max(1, len(got)):.0f} kg/ha")

    # ---------------- Step 5: grid_yield_long.csv --------------------------
    # Rebuilt from the member directories (not blind-appended), so a --resume
    # relaunch cannot duplicate rows.
    long_csv = os.path.join(out_dir, 'grid_yield_long.csv')
    n_rows = 0
    with open(long_csv, 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['member_id', 'tech', 'year', 'hwam_kgha', 'area_ha'])
        for m in members:
            wd = os.path.join(members_dir, f"{m['member_id']}_{m['tech']}")
            if not os.path.isfile(os.path.join(wd, 'Summary.OUT')):
                continue
            try:
                rows = parse_summary(wd)
            except Exception:                                 # noqa: BLE001
                continue
            for r in rows:
                try:
                    yr = int(r.get('WYEAR'))
                    hw = float(r.get('HWAM', r.get('HWAH')))
                except (TypeError, ValueError):
                    continue
                if hw < 0:
                    continue
                w.writerow([m['member_id'], m['tech'], yr, round(hw, 1), m['area_ha']])
                n_rows += 1
    log(f"grid_yield_long.csv: {n_rows} (member,tech,season) row(s) -> {long_csv}")

    # ---------------- failures ---------------------------------------------
    failed_csv = os.path.join(out_dir, 'members_failed.csv')
    with open(failed_csv, 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['member_id', 'tech', 'stage', 'error'])
        w.writerows(failures)

    if mgmt_notes:
        log("management: " + next(iter(mgmt_notes.values())))

    if failures:
        sys.stderr.write(
            f"{len(failures)} member(s) FAILED — see {failed_csv}. The "
            f"aggregate below is INCOMPLETE; do not score it as the pixel.\n")
        for f in failures[:10]:
            sys.stderr.write(f"  {f[0]}_{f[1]} @{f[2]}: {f[3]}\n")
        sys.exit(2)

    log(f"All {len(members)} member(s) completed.")


if __name__ == '__main__':
    main()
