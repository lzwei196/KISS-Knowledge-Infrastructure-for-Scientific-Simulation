#!/usr/bin/env python3
"""EPIC quickstart — run a complete crop simulation at any location.

Chains all EPIC KI tools with ki_tools_common agronomic data modules
to produce a data-driven simulation from just lat/lon/crop/years.

Usage::

    python quickstart.py --lat 32.9 --lon 117.4 --crop corn --start 2000 --end 2010
    python quickstart.py --lat 41.17 --lon -96.44 --crop corn --start 2005 --end 2015

Steps:
  1. Look up crop calendar (planting/harvest dates) from GGCMI/China phenology
  2. Look up fertilizer N/P/K rates from NPKGRIDS
  3. Look up observed yield from SPAM2020 for validation target
  4. Build .SIT (site), .SOL (soil from HWSD)
  5. Convert forcing (CMFD) to .DLY/.WP1/.WND, THEN build .OPC (operations)
     with the site PHU derived from that .DLY (triplet EPIC_021)
  6. Build control files (EPICRUN.DAT, EPICCONT.DAT, etc.)
  7. Run EPIC 1102 via Wine
  8. Parse outputs, report yield and water balance
  9. Compare simulated vs observed yield, on a DECLARED moisture basis --
     EPIC yields are dry matter, the obs products are published at market
     moisture, and the conversion is applied only when the obs registry has a
     CITED crop-specific point w for this crop (triplet EPIC_025)

``--ppop`` (plant population) may be passed ONLY together with
``--ppop-source``, and any such run is reported as a labelled SENSITIVITY
rather than the verdict -- ``result["result_role"]`` / ``verdict_eligible``
carry that label (SKILL.md, triplet EPIC_022).
"""
import argparse
import os
import sys

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS_DIR)

# Add ki_tools_common to path
for _cand in [
    "KISSPATH_KI_TOOLS_COMMON",
    "KISSPATH_INTERNAL_NOT_SHIPPED/kdt-release",
]:
    if os.path.isdir(os.path.join(_cand, "ki_tools_common")):
        sys.path.insert(0, _cand)
        break

CHINA_DEM_PATH = "KISSPATH_STATIC/china_dem_90m/china_dem_90m.tif"


MERIT_DEM_DIR = "KISSPATH_DATA/MERIT_DEM"
# ~1 km plane-fit window on the 3-arcsec (~90 m) MERIT grid: 11 x 11 cells
# (triplet EPIC_031: the scale of the <=100 ha HLU EPIC simulates).
_MERIT_HALF = 5


def _merit_tile(lat, lon):
    """MERIT DEM v1.0.2 5x5 degree tile path, named by its lower-left corner
    (n45e005_dem.tif style, triplet EPIC_031)."""
    import math
    la = int(math.floor(lat / 5.0) * 5)
    lo = int(math.floor(lon / 5.0) * 5)
    name = (f"{'n' if la >= 0 else 's'}{abs(la):02d}"
            f"{'e' if lo >= 0 else 'w'}{abs(lo):03d}_dem.tif")
    return os.path.join(MERIT_DEM_DIR, name)


def _elev_slope_from_raster(path, lat, lon, half):
    """Centre-cell elevation (m) and slope (m/m) = gradient of a least-squares
    plane over a (2*half+1)^2 window. Raises if the centre cell has no data."""
    import numpy as np
    import rasterio
    from rasterio.windows import Window
    with rasterio.open(path) as src:
        row, col = src.index(lon, lat)
        n = 2 * half + 1
        data = src.read(1, window=Window(col - half, row - half, n, n),
                        boundless=True, fill_value=src.nodata if src.nodata is not None else np.nan
                        ).astype(float)
        if src.nodata is not None:
            data[data == src.nodata] = np.nan
        center = float(data[half, half])
        if not np.isfinite(center) or not (-500 < center < 9000):
            raise RuntimeError(f"no valid elevation at ({lat}, {lon}) in {path}")
        cellx = abs(src.res[0]) * 111320.0 * np.cos(np.radians(lat))
        celly = abs(src.res[1]) * 111320.0
    jj, ii = np.meshgrid(np.arange(n) - half, np.arange(n) - half)
    x = jj * cellx                       # east, m
    y = -ii * celly                      # north, m (row index grows south)
    ok = np.isfinite(data)
    if ok.sum() < 3 * n:
        raise RuntimeError(f"too few valid DEM cells ({int(ok.sum())}) around "
                           f"({lat}, {lon}) in {path} for a slope plane")
    A = np.column_stack([x[ok], y[ok], np.ones(int(ok.sum()))])
    coef, *_ = np.linalg.lstsq(A, data[ok], rcond=None)
    slope = float(np.hypot(coef[0], coef[1]))
    return center, max(0.001, slope)


def _lookup_terrain(lat, lon):
    """Elevation (m), slope (m/m) and source label for the .SIT.

    Order: China DEM 90m (central difference, kept so the Changchun reference
    run stays reproducible) -> global MERIT DEM tile (plane fit, triplet
    EPIC_031). If neither gives a value the run STOPS: there is no 100 m / 1%
    placeholder any more (that fabricated site geometry changes PET and
    curve-number runoff / erosion).
    """
    import numpy as np

    errors = []
    if os.path.isfile(CHINA_DEM_PATH):
        try:
            import rasterio
            with rasterio.open(CHINA_DEM_PATH) as src:
                row, col = src.index(lon, lat)
                if 2 <= row < src.height - 2 and 2 <= col < src.width - 2:
                    win = rasterio.windows.Window(col - 2, row - 2, 5, 5)
                    data = src.read(1, window=win).astype(float)
                    if src.nodata is not None:
                        data[data == src.nodata] = np.nan
                    center = float(data[2, 2])
                    if not np.isnan(center) and 0 <= center < 9000:
                        cellx = abs(src.res[0]) * 111320 * np.cos(np.radians(lat))
                        celly = abs(src.res[1]) * 111320
                        dzdx = (data[2, 3] - data[2, 1]) / (2 * cellx)
                        dzdy = (data[1, 2] - data[3, 2]) / (2 * celly)
                        slope = float(np.sqrt(dzdx**2 + dzdy**2))
                        if np.isfinite(slope):
                            return center, max(0.001, slope), "China DEM 90m"
                        errors.append("China DEM: neighbour cell has no data")
                    else:
                        errors.append("China DEM: no valid centre value")
                else:
                    errors.append("China DEM: point outside the raster")
        except Exception as e:  # fall through to MERIT, keep the reason
            errors.append(f"China DEM read failed: {e}")
    else:
        errors.append(f"China DEM missing: {CHINA_DEM_PATH}")

    tile = _merit_tile(lat, lon)
    if os.path.isfile(tile):
        try:
            elev, slope = _elev_slope_from_raster(tile, lat, lon, _MERIT_HALF)
            return elev, slope, f"MERIT DEM {os.path.basename(tile)}"
        except Exception as e:
            errors.append(f"MERIT: {e}")
    else:
        errors.append(f"MERIT tile missing: {tile}")

    raise RuntimeError(
        f"no elevation/slope for ({lat}, {lon}); .SIT not built. Tried: "
        + "; ".join(errors))


def _obs_moisture_basis(obs_source, crop):
    """ESTABLISHED moisture basis of the obs product FOR THIS CROP, or None.

    EPIC .ACY yields are DRY MATTER; the census-anchored obs products this
    quickstart validates against (SPAM2020 / FAOSTAT-derived) publish MARKET
    (commercial) moisture, so the bias printed below depends on which basis the
    pair is scored on -- at Changchun that undeclared choice moved PBIAS from
    +26.8% to +50.1% (triplet EPIC_025).

    The answer is looked up, never guessed: resolve_obs_shape's registry returns
    a cited ``w`` only when the (obs product, crop) pair is ESTABLISHED, and an
    explicit undetermined record otherwise -- including when the crop is one the
    registry's documentary chain does not reach. Returns None only if the
    registry is unavailable, which is reported as undetermined too.
    """
    try:
        from resolve_obs_shape import lookup_obs_moisture_basis
        return lookup_obs_moisture_basis(obs_source, crop=crop)
    except Exception:
        return None



_OUT_EXTS = (".ANN", ".ACY")


def _output_snapshot(workspace):
    """{file name: mtime_ns} of every .ANN/.ACY in the workspace before a run.

    EPIC writes its outputs in the workspace; output/ only holds copies that
    run_epic makes with copy2 (which keeps the source's time stamp), so
    freshness is judged on the workspace file alone.
    """
    snap = {}
    if os.path.isdir(workspace):
        for fn in os.listdir(workspace):
            if fn.upper().endswith(_OUT_EXTS):
                try:
                    snap[fn] = os.stat(os.path.join(workspace, fn)).st_mtime_ns
                except OSError:
                    pass
    return snap


def _fresh_output(ext, run_name, workspace, pre_run):
    """Workspace path of a <ext> file EPIC wrote in THIS run, or None.

    A file counts only if it did not exist before the run or its mtime_ns
    changed. A copy in output/ never counts on its own (a stale workspace
    file copied there by run_epic would look new). Files named after
    run_name win over others.
    """
    best = None
    for fn in sorted(os.listdir(workspace)):
        if not fn.upper().endswith(ext):
            continue
        p = os.path.join(workspace, fn)
        try:
            st = os.stat(p)
        except OSError:
            continue
        if pre_run.get(fn) == st.st_mtime_ns:
            continue
        if fn.upper().startswith(run_name.upper()):
            return p
        if best is None:
            best = p
    return best


def quickstart(lat, lon, crop, year1, year2, source="cmfd", workspace=None,
               run_name=None, irrigation="dryland", verbose=True, ppop=None,
               ppop_source=None):
    """Run a complete EPIC simulation from location + crop + years.

    Returns dict with simulated yield, observed yield, water balance, paths.

    ppop: plant population (plants m-2) written to the PLANT row's OPV5 and
        echoed as the .ACY PPOP column. ``None`` keeps build_opc_file's
        documented default (10.0, the umstead North-Carolina legacy).
        SKILL.md and triplet EPIC_022 require a SOURCED value here whenever
        one exists for the site -- but until now quickstart(), the recommended
        one-command entry point, had no way to pass one, so every quickstart
        run silently inherited the legacy 10.0 plants m-2 (= 100,000 plants/ha,
        above the top of the realistic rainfed range). Passing a value here is
        parameter SOURCING; EPIC_022 still forbids moving it to chase PBIAS.
    ppop_source: REQUIRED whenever ``ppop`` is given -- SKILL.md says to pass a
        non-default plant population "ONLY with a recorded source", so the
        source is recorded here (and in the returned record) rather than living
        only in whatever the operator happened to type in the run notes. A
        ``ppop`` with no source raises instead of running.

    RESULT ROLE (why a --ppop run is never the verdict)
    ---------------------------------------------------
    No gridded planting-density product exists on this server, and SKILL.md is
    explicit that the AVERAGE FARMER DENSITY for a given cell-year is not
    established here: published NE-China spring-maize treatments span
    30,000-97,500 plants ha-1, any pick inside that range moves PBIAS a lot, and
    the observation being scored is a cell mean over exactly those unknown
    densities. So a recorded source makes the value SOURCED, not PINNED, and
    every ``ppop`` run is labelled a SENSITIVITY: the returned dict carries
    ``result_role="sensitivity"`` and ``verdict_eligible=False``. Lifting that
    label is not a per-run flag (that would just re-open the tuning hole
    EPIC_022 closed) -- it needs a cited site-density registry in this KI, the
    way the obs moisture basis lives in resolve_obs_shape's registry. The
    verdict run is the default-density one.
    """
    # Fail fast, before any file is built: a non-default PPOP without a
    # recorded source is exactly what SKILL.md / triplet EPIC_022 forbid, and
    # a run that cannot name its source cannot be audited afterwards.
    ppop_source = (ppop_source or "").strip()
    if ppop is not None and not ppop_source:
        raise ValueError(
            "ppop=%r was given with no ppop_source. SKILL.md: pass a "
            "non-default plant population 'ONLY with a recorded source' "
            "(triplet EPIC_022). Re-run with --ppop-source '<the source that "
            "gives this density for THIS site>', e.g. a field-survey or "
            "published density treatment with its citation. Omit --ppop "
            "entirely to keep the documented 10.0 plants m-2 default."
            % (ppop,))
    if ppop is None and ppop_source:
        raise ValueError(
            "ppop_source=%r was given without ppop, so nothing would record "
            "it. Pass both, or neither." % (ppop_source,))

    from ki_tools_common.crop_calendar import get_planting_harvest
    from ki_tools_common.fertilizer import get_fertilizer_rates, get_split_schedule
    from ki_tools_common.crop_obs import get_observed_yield

    from build_site_file import build as build_site
    from build_soil_file import build as build_soil
    from build_opc_file import build as build_opc, compute_phu, crop_base_temp
    from convert_forcing_to_epic import build as build_forcing
    from build_control_files import build as build_control
    from configure_irrigation import configure as configure_irr
    from run_epic import run as run_epic
    from parse_outputs import parse_ann, parse_acy, water_balance_check

    crop_lower = crop.lower()
    if crop_lower == "maize":
        crop_lower = "corn"
    epic_crop = crop_lower.upper()  # EPIC CROPCOM uses uppercase: CORN, WWHT, RICE, etc.

    # Map common names to EPIC CROPCOM names
    epic_crop_map = {
        "corn": "CORN", "maize": "CORN",
        "wheat": "WWHT", "winter_wheat": "WWHT", "spring_wheat": "SWHT",
        "rice": "RICE",
        "soybean": "SOYB", "soy": "SOYB",
        "sorghum": "GRSG",
        "cotton": "COTN",
        "barley": "BARL",
        "potato": "POTA",
    }
    epic_crop_name = epic_crop_map.get(crop.lower(), crop.upper()[:4])

    if run_name is None:
        run_name = f"EPIC_{epic_crop_name}"
    if workspace is None:
        workspace = os.path.join(TOOLS_DIR, "..", "runs",
                                 f"{run_name}_{lat:.2f}_{lon:.2f}")
    workspace = os.path.abspath(workspace)
    output_dir = os.path.join(workspace, "output")
    os.makedirs(workspace, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    stn = "STN01"

    # ── Step 1: Crop calendar ────────────────────────────────────────
    if verbose:
        print(f"\n{'='*60}")
        print(f"EPIC Quickstart: {crop} at ({lat}, {lon}), {year1}-{year2}")
        print(f"{'='*60}")
        print("\n[1/9] Looking up crop calendar...")
    cal = get_planting_harvest(lat, lon, crop=crop)
    plant_mmdd = f"{cal['plant_month']:02d}-{cal['plant_day']:02d}"
    harvest_mmdd = f"{cal['harvest_month']:02d}-{cal['harvest_day']:02d}"
    # Kill date = harvest date for annual crops
    kill_mmdd = harvest_mmdd
    if verbose:
        print(f"  Plant: {plant_mmdd} (DOY {cal['plant_doy']}), "
              f"Harvest: {harvest_mmdd} (DOY {cal['harvest_doy']}), "
              f"Source: {cal['source']}")

    # ── Step 2: Fertilizer rates ─────────────────────────────────────
    if verbose:
        print("\n[2/9] Looking up fertilizer rates...")
    fert = get_fertilizer_rates(lat, lon, crop=crop)
    n_total = fert['n_kgha']
    schedule = get_split_schedule(n_total, crop=crop, plant_doy=cal['plant_doy'],
                                  maturity_doy=cal.get('harvest_doy'))   # winter vs spring wheat by season length (2026-09-24)
    if verbose:
        print(f"  N={fert['n_kgha']:.1f}, P={fert['p_kgha']:.1f}, "
              f"K={fert['k_kgha']:.1f} kg/ha, Source: {fert['source']}")
        for s in schedule:
            print(f"    {s['type']}: DOY {s['doy']}, N={s['n_kgha']:.1f} kg/ha")
        print("    (display only: build_opc writes the FULL N rate at planting; the split above is not executed)")

    # ── Step 3: Observed yield ───────────────────────────────────────
    if verbose:
        print("\n[3/9] Looking up observed yield for validation...")
    obs = get_observed_yield(lat, lon, crop=crop)
    if verbose:
        print(f"  Observed: {obs['yield_kgha']:.0f} kg/ha "
              f"({obs['yield_kgha']/1000:.1f} t/ha), Source: {obs['source']}")

    # ── Step 4: Build site + soil ────────────────────────────────────
    if verbose:
        print("\n[4/9] Building site and soil files...")
    elev, slope, terrain_source = _lookup_terrain(lat, lon)
    if verbose:
        print(f"  elevation: {elev:.0f} m, slope: {slope:.4f} m/m ({slope*100:.2f}%) "
              f"[{terrain_source}]")
    build_site(run_name, lat, lon, elev=elev, slope=slope, co2=410.0,
               workspace=workspace)
    build_soil(run_name, lat, lon, workspace=workspace)

    # ── Step 5: Convert forcing ──────────────────────────────────────
    # ORDER MATTERS: the forcing is built BEFORE the .OPC because the plant
    # operation's OPV1 (PHU, potential heat units) must be derived from THIS
    # site's own .DLY. Building the .OPC first forces the umstead North
    # Carolina legacy PHU=1550 at every site and pushes HUSC at harvest out
    # of the dag's 0.9-1.2 band -> "yields are suspect" (triplet EPIC_021).
    if verbose:
        print(f"\n[5/9] Converting {source.upper()} forcing to EPIC format...")
    dly_path, _wp1, _wnd = build_forcing(source, lat, lon, year1, year2,
                                         workspace, stn)

    # ── Step 6: Build OPC (operations) ───────────────────────────────
    if verbose:
        print("\n[6/9] Building operations schedule...")
    # Apply full N/P/K at planting (using elemental codes: N=21, P=22, K=23)
    p_total = fert.get('p_kgha', 0)
    k_total = fert.get('k_kgha', 0)
    nbyr = year2 - year1 + 1
    # triplet EPIC_018: OPV6 is a CUMULATIVE LIFETIME N cap, not an annual one.
    # It must exceed nbyr * annual rate or fertiliser silently stops after the
    # first year or two and yields decay as soil N is mined.
    n_cap = max(9999.0, 3.0 * nbyr * float(n_total))
    # triplet EPIC_021: site PHU from the run's own weather, not umstead's 1550.
    tbs = crop_base_temp(epic_crop_name)
    phu = compute_phu(dly_path, plant_mmdd, harvest_mmdd, tbs)
    if verbose:
        if phu is None:
            print(f"  WARNING: PHU could not be derived from {dly_path}; "
                  f"falling back to the umstead legacy 1550 (HUSC at harvest "
                  f"will likely fall outside the dag's 0.9-1.2 band)")
        else:
            print(f"  PHU={phu} degC-days (TBS={tbs}), OPV6 N-cap={n_cap:.0f}")
    opc_kw = {}
    ppop_record = None
    if ppop is not None:
        opc_kw["ppop"] = float(ppop)
        # SOURCED, not PINNED -- see the result-role note in the docstring.
        # The record travels with the result so the sensitivity label and its
        # source cannot be separated from the numbers downstream.
        ppop_record = {
            "ppop_plants_m2": float(ppop),
            "ppop_plants_ha": round(float(ppop) * 10000.0),
            "source": ppop_source,
            "replaced_default": 10.0,
            "result_role": "sensitivity",
            "verdict_eligible": False,
            "reason": (
                "PPOP was moved off the documented 10.0 default. No gridded "
                "planting-density product exists on this server and the "
                "average farmer density for this cell-year is not established, "
                "so this run is a labelled SENSITIVITY on plant population, "
                "never the verdict (SKILL.md / triplet EPIC_022). The verdict "
                "run is the one at the documented default; EPIC_022 also "
                "forbids choosing this value to move PBIAS."
            ),
        }
        if verbose:
            print(f"  PPOP={float(ppop):.2f} plants/m2 "
                  f"({ppop_record['ppop_plants_ha']:.0f} plants/ha) -- SOURCED "
                  f"override of the umstead legacy 10.0")
            print(f"    source: {ppop_source}")
            print(f"    => this run is a SENSITIVITY, NOT the verdict "
                  f"(triplet EPIC_022)")
    build_opc(run_name, epic_crop_name, plant_mmdd, harvest_mmdd, kill_mmdd,
              plant_mmdd, n_total, workspace, fert_code=21,
              fert_p=p_total, fert_k=k_total, n_cap=n_cap, phu=phu, **opc_kw)

    # ── Step 7: Control files ────────────────────────────────────────
    if verbose:
        print("\n[7/9] Building control files...")
    build_control(workspace, run_name,
                  f"{run_name}.SIT", f"{run_name}.SOL", f"{run_name}.OPC",
                  stn, nbyr=nbyr, iyr0=year1)

    # ── Step 7b: Irrigation ─────────────────────────────────────────
    if irrigation != "dryland":
        if verbose:
            print(f"  irrigation: {irrigation} mode")
        configure_irr(workspace, irrigation, water_stress=0.8, efficiency=0.85)

    # ── Step 8: Run EPIC ─────────────────────────────────────────────
    if verbose:
        print("\n[8/9] Running EPIC 1102 via Wine...")
    # Any run_epic failure (missing binary, non-zero exit, Wine timeout)
    # stops quickstart. It used to be swallowed whenever ANY .ANN sat in the
    # workspace, so a re-used workspace could report an old run's numbers.
    pre_run = _output_snapshot(workspace)
    run_epic(workspace, run_name, output_dir, timeout=120)

    # ── Step 9: Parse outputs ────────────────────────────────────────
    if verbose:
        print("\n[9/9] Parsing outputs...")
    result = {
        "workspace": workspace,
        "output_dir": output_dir,
        "terrain": {"elevation_m": elev, "slope_m_m": slope,
                    "source": terrain_source},
        "crop_calendar": cal,
        "fertilizer": fert,
        "observed": obs,
        # Role of THIS run's numbers. A --ppop run is a labelled sensitivity on
        # plant population and must never be reported as the verdict; the
        # default-density run is the verdict-eligible one (triplet EPIC_022).
        "ppop": ppop_record,
        "result_role": "sensitivity" if ppop_record else "verdict_eligible",
        "verdict_eligible": ppop_record is None,
        "non_verdict_reason": ppop_record["reason"] if ppop_record else None,
    }

    # Only output written by THIS run is read; stale .ANN/.ACY from an
    # earlier run in the same workspace are ignored, never reported.
    ann_path = _fresh_output(".ANN", run_name, workspace, pre_run)
    acy_path = _fresh_output(".ACY", run_name, workspace, pre_run)
    if not acy_path:
        raise RuntimeError(
            f"EPIC run finished but wrote no new .ACY (annual crop yield) file "
            f"in {workspace}; no result is reported "
            f"(old files from an earlier run are not used)")
    if not ann_path and verbose:
        print("  WARNING: no new .ANN file from this run; water balance skipped")

    if ann_path:
        header, rows, data = parse_ann(ann_path)
        if data:
            wb = water_balance_check(data)
            result["water_balance"] = wb
            if verbose:
                print(f"\n  Water Balance:")
                print(f"    P={wb['P_mean']:.0f} ET={wb['ET_mean']:.0f} "
                      f"Q={wb['Q_surface_mean']:.0f} mm/yr")
                print(f"    Status: {'OK' if wb['ok'] else 'WARNING'}")

    # acy_path is always set here (no fresh .ACY raised above). The yield
    # table must be usable or the run stops: no header-only table, no missing
    # yield column, no NaN / negative / unreadable value is turned into a
    # result (it used to fall back to a printed 0.00 t/ha with exit 0).
    import math
    header, rows = parse_acy(acy_path)
    if not header or not rows:
        raise RuntimeError(f"{acy_path}: no harvest rows in the .ACY yield table; "
                           f"no result is reported")
    idx = {c: i for i, c in enumerate(header)}
    yld_col = next((c for c in ("YLD", "YLDG", "YLDF") if c in idx), None)
    if yld_col is None:
        raise RuntimeError(f"{acy_path}: no YLD/YLDG/YLDF column in header {header}")
    # Every harvest row counts, zero-yield years too: a 0 is a crop failure
    # EPIC simulated, and dropping it would raise the mean (e.g. [0, 10] -> 10
    # instead of 5).
    yields = []
    for n, r in enumerate(rows):
        try:
            y = float(r[idx[yld_col]])
        except (ValueError, IndexError) as e:
            raise RuntimeError(
                f"{acy_path}: harvest row {n + 1} has no readable "
                f"{yld_col} value ({e})") from e
        if not math.isfinite(y) or y < 0:
            raise RuntimeError(
                f"{acy_path}: harvest row {n + 1} has invalid {yld_col}={y!r} "
                f"(must be finite and >= 0)")
        yields.append(y)
    mean_yield = sum(yields) / len(yields)
    result["simulated_yield_tha"] = round(mean_yield, 2)
    result["simulated_yield_kgha"] = round(mean_yield * 1000, 0)
    result["simulated_yield_years"] = len(yields)
    result["simulated_zero_yield_years"] = sum(1 for y in yields if y == 0)

    # ── Moisture basis of the sim/obs pair (triplet EPIC_025) ────────
    # The sim side is DRY MATTER, the obs side is published as-is. Declare both
    # sides before reporting a bias, and apply the market-moisture conversion
    # ONLY when the registry carries a CITED w for THIS crop -- a product whose
    # basis is market does not license a constant for an arbitrary crop.
    sim_tha = result["simulated_yield_tha"]
    obs_kgha = obs['yield_kgha']
    obs_tha = obs_kgha / 1000
    basis = _obs_moisture_basis(obs.get('source'), crop)
    result["obs_moisture_basis"] = basis
    result["sim_moisture_basis"] = "dry_matter (EPIC .ACY YLDG/YLDF)"
    w = basis.get("w") if (basis and basis.get("established")
                           and basis.get("basis") == "market") else None
    if sim_tha > 0 and obs_tha > 0:
        result["bias_pct_dry_vs_as_published"] = round(
            (sim_tha - obs_tha) / obs_tha * 100, 1)
        if w is not None:
            result["bias_pct_market"] = round(
                (sim_tha / (1.0 - w) - obs_tha) / obs_tha * 100, 1)
            result["moisture_w"] = w

    # ── Summary ──────────────────────────────────────────────────────
    if verbose:
        print(f"\n{'='*60}")
        print(f"RESULTS: {crop} at ({lat}, {lon})")
        if ppop_record:
            print(f"  *** SENSITIVITY RUN -- NOT THE VERDICT ***")
        print(f"{'='*60}")
        print(f"  Simulated:  {sim_tha:.2f} t/ha ({sim_tha*1000:.0f} kg/ha) [DRY MATTER]")
        print(f"  Observed:   {obs_tha:.1f} t/ha ({obs_kgha:.0f} kg/ha) [{obs['source']}]")
        if sim_tha > 0 and obs_tha > 0:
            print(f"  Bias:       {result['bias_pct_dry_vs_as_published']:+.1f}% "
                  f"(sim DRY MATTER vs obs AS PUBLISHED)")
            if w is not None:
                print(f"  Bias:       {result['bias_pct_market']:+.1f}% "
                      f"(sim converted to MARKET basis, w={w:.3f}) -- "
                      f"report BOTH, the verdict basis is the dag's")
                print(f"    w source: {basis.get('w_source')}")
            else:
                why = (basis or {}).get("undetermined_reason") \
                    or "obs moisture-basis registry unavailable"
                print(f"  Moisture:   obs basis UNDETERMINED for "
                      f"({obs['source']}, {crop}) -- NO moisture factor applied, "
                      f"the bias above is the raw dry-vs-as-published pairing")
                print(f"    why: {why}")
        print(f"  Calendar:   plant {plant_mmdd}, harvest {harvest_mmdd} [{cal['source']}]")
        print(f"  Fertilizer: N={fert['n_kgha']:.0f} kg/ha [{fert['source']}]")
        if ppop_record:
            print(f"  PPOP:       {ppop_record['ppop_plants_m2']:.2f} plants/m2 "
                  f"(default {ppop_record['replaced_default']:.1f} overridden)")
            print(f"    source:   {ppop_record['source']}")
            print(f"  ROLE:       SENSITIVITY on plant population -- report it "
                  f"as such, never as the verdict")
            print(f"    why:      {ppop_record['reason']}")
        else:
            print(f"  PPOP:       10.0 plants/m2 (documented default, "
                  f"umstead legacy) -- pass --ppop with --ppop-source to run a "
                  f"labelled density sensitivity")
            print(f"  ROLE:       verdict-eligible (no unsourced parameter "
                  f"override)")
        print(f"{'='*60}\n")

    return result


def main():
    ap = argparse.ArgumentParser(
        description="EPIC quickstart — complete crop simulation from lat/lon/crop/years")
    ap.add_argument("--lat", type=float, required=True, help="Latitude")
    ap.add_argument("--lon", type=float, required=True, help="Longitude")
    ap.add_argument("--crop", default="corn", help="Crop name (corn, wheat, rice, soybean...)")
    ap.add_argument("--start", type=int, default=2000, help="Start year")
    ap.add_argument("--end", type=int, default=2010, help="End year")
    ap.add_argument("--source", default="cmfd", choices=["cmfd", "nasa_power", "mswx"])
    ap.add_argument("--irrigation", default="dryland",
                    choices=["dryland", "auto"], help="Irrigation mode")
    ap.add_argument("--workspace", default=None)
    ap.add_argument("--run-name", default=None)
    ap.add_argument("--ppop", type=float, default=None,
                    help="plant population (plants m-2) for the PLANT row's "
                         "OPV5. Omit to keep the documented 10.0 default. "
                         "REQUIRES --ppop-source, and the run is reported as a "
                         "labelled SENSITIVITY, never as the verdict (triplet "
                         "EPIC_022 forbids tuning it against PBIAS).")
    ap.add_argument("--ppop-source", dest="ppop_source", default=None,
                    help="the source that gives the --ppop density for THIS "
                         "site (field survey, published treatment + citation, "
                         "etc.). Mandatory with --ppop: SKILL.md allows a "
                         "non-default plant population 'ONLY with a recorded "
                         "source'. It is recorded in the returned result as "
                         "ppop.source. Recording a source makes the value "
                         "sourced, not pinned -- the run stays a sensitivity.")
    args = ap.parse_args()

    try:
        quickstart(args.lat, args.lon, args.crop, args.start, args.end,
                   source=args.source, workspace=args.workspace,
                   run_name=args.run_name, irrigation=args.irrigation,
                   ppop=args.ppop, ppop_source=args.ppop_source)
    except Exception as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(2)


if __name__ == "__main__":
    main()
