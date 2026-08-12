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
    "/mnt/disk1/Hydrocraft_server/models/ki_tools_common",
    "/home/server/knowledge-dissection-toolkit/kdt-release",
]:
    if os.path.isdir(os.path.join(_cand, "ki_tools_common")):
        sys.path.insert(0, _cand)
        break

CHINA_DEM_PATH = "/mnt/disk1/Hydrocraft_server/data/dem/china_dem_90m/china_dem_90m.tif"
CMFD_ELEV_PATH = "/mnt/disk1/Hydrocraft_server/data/elev/elev_CMFD_V0200_B-00_fx_010deg.nc"


def _lookup_terrain(lat, lon):
    """Get elevation (m) and slope (m/m) from China DEM 90m or CMFD grid.

    Returns (elevation, slope). Slope has a minimum of 0.001 for EPIC stability.
    """
    import numpy as np

    elev, slope = 100.0, 0.01  # defaults

    # Try China DEM 90m first (best resolution for slope)
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
                        elev = center
                        cellx = abs(src.res[0]) * 111320 * np.cos(np.radians(lat))
                        celly = abs(src.res[1]) * 111320
                        dzdx = (data[2, 3] - data[2, 1]) / (2 * cellx)
                        dzdy = (data[1, 2] - data[3, 2]) / (2 * celly)
                        slope = max(0.001, float(np.sqrt(dzdx**2 + dzdy**2)))
                        return elev, slope
        except Exception:
            pass

    # Fallback: CMFD elevation grid (0.1° resolution, China only)
    if 15 < lat < 55 and 70 < lon < 140 and os.path.isfile(CMFD_ELEV_PATH):
        try:
            import xarray as xr
            ds = xr.open_dataset(CMFD_ELEV_PATH)
            data = ds['elev'].sel(lat=lat, lon=lon, method='nearest')
            if 'time' in data.dims:
                data = data.isel(time=0)
            val = float(data.values)
            ds.close()
            if 0 < val < 9000:
                elev = val
        except Exception:
            pass

    return elev, slope


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
    schedule = get_split_schedule(n_total, crop=crop, plant_doy=cal['plant_doy'])
    if verbose:
        print(f"  N={fert['n_kgha']:.1f}, P={fert['p_kgha']:.1f}, "
              f"K={fert['k_kgha']:.1f} kg/ha, Source: {fert['source']}")
        for s in schedule:
            print(f"    {s['type']}: DOY {s['doy']}, N={s['n_kgha']:.1f} kg/ha")

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
    elev, slope = _lookup_terrain(lat, lon)
    if verbose:
        print(f"  elevation: {elev:.0f} m, slope: {slope:.4f} m/m ({slope*100:.2f}%)")
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
    try:
        run_epic(workspace, run_name, output_dir, timeout=120)
    except Exception as e:
        # EPIC may finish but Wine hangs — check if output files exist
        has_outputs = any(f.endswith(".ANN") for f in os.listdir(workspace))
        if has_outputs:
            if verbose:
                print(f"  Wine process timed out but EPIC produced output files.")
        else:
            raise

    # ── Step 9: Parse outputs ────────────────────────────────────────
    if verbose:
        print("\n[9/9] Parsing outputs...")
    result = {
        "workspace": workspace,
        "output_dir": output_dir,
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

    ann_path = None
    acy_path = None
    for fn in os.listdir(output_dir):
        if fn.upper().endswith(".ANN"):
            ann_path = os.path.join(output_dir, fn)
        elif fn.upper().endswith(".ACY"):
            acy_path = os.path.join(output_dir, fn)
    if not ann_path:
        for fn in os.listdir(workspace):
            if fn.upper().endswith(".ANN"):
                ann_path = os.path.join(workspace, fn)
            elif fn.upper().endswith(".ACY"):
                acy_path = os.path.join(workspace, fn)

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

    if acy_path:
        header, rows = parse_acy(acy_path)
        if header and rows:
            # Find yield column (YLD or YLDG or similar)
            idx = {c: i for i, c in enumerate(header)}
            yld_col = None
            for c in ["YLD", "YLDG", "YLDF"]:
                if c in idx:
                    yld_col = c
                    break
            if yld_col:
                yields = []
                for r in rows:
                    try:
                        y = float(r[idx[yld_col]])
                        if y > 0:
                            yields.append(y)
                    except (ValueError, IndexError):
                        pass
                if yields:
                    mean_yield = sum(yields) / len(yields)
                    result["simulated_yield_tha"] = round(mean_yield, 2)
                    result["simulated_yield_kgha"] = round(mean_yield * 1000, 0)

    # ── Moisture basis of the sim/obs pair (triplet EPIC_025) ────────
    # The sim side is DRY MATTER, the obs side is published as-is. Declare both
    # sides before reporting a bias, and apply the market-moisture conversion
    # ONLY when the registry carries a CITED w for THIS crop -- a product whose
    # basis is market does not license a constant for an arbitrary crop.
    sim_tha = result.get("simulated_yield_tha", 0)
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
