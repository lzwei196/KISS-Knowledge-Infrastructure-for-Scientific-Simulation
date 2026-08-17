#!/usr/bin/env python3
"""APEX quickstart — run a complete crop simulation at any location.

Chains all APEX KI tools (s1–s9) with ki_tools_common agronomic data modules.
Follows the same pattern as the EPIC quickstart.

Usage::

    python quickstart.py --lat 32.9 --lon 117.4 --crop corn --start 2008 --end 2013
    python quickstart.py --lat 41.17 --lon -96.44 --crop soybean --start 2005 --end 2010
"""
import argparse
import os
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
KI_ROOT = TOOLS_DIR.parent

# Add ki_tools_common to path
for _cand in [
    "KISSPATH_KI_TOOLS_COMMON",
    "KISSPATH_INTERNAL_NOT_SHIPPED/kdt-release",
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect_multi_agent",
]:
    if os.path.isdir(os.path.join(_cand, "ki_tools_common")):
        sys.path.insert(0, _cand)
        break

sys.path.insert(0, str(TOOLS_DIR))


def quickstart(lat, lon, crop, year1, year2, source="cmfd",
               workspace=None, verbose=True):
    from ki_tools_common.crop_calendar import get_planting_harvest
    from ki_tools_common.fertilizer import get_fertilizer_rates
    from ki_tools_common.crop_obs import get_observed_yield
    from ki_tools_common.terrain import get_terrain

    from s1_setup_workspace import setup
    from s2_convert_forcing import build_forcing
    from s3_build_soil import build_soil
    from s4_update_site import update_site
    from s5_update_control import update_control
    from s6_run_apex import run
    from s7_parse_output import parse
    from s9_generate_crop_opc import get_schedule, write_opc

    crop_lower = crop.lower()
    if crop_lower == "maize":
        crop_lower = "corn"

    if workspace is None:
        workspace = KI_ROOT / "runs" / f"APEX_{crop_lower}_{lat:.2f}_{lon:.2f}"
    workspace = Path(workspace).resolve()

    nbyr = year2 - year1 + 1

    # ── Step 1: Data lookups ─────────────────────────────────────
    if verbose:
        print(f"\n{'='*60}")
        print(f"APEX Quickstart: {crop} at ({lat}, {lon}), {year1}-{year2}")
        print(f"{'='*60}")

    cal = get_planting_harvest(lat, lon, crop=crop)
    fert = get_fertilizer_rates(lat, lon, crop=crop)
    obs = get_observed_yield(lat, lon, crop=crop)
    terrain = get_terrain(lat, lon)

    if verbose:
        pm = f"{cal['plant_month']:02d}/{cal['plant_day']:02d}"
        hm = f"{cal['harvest_month']:02d}/{cal['harvest_day']:02d}"
        print(f"\n  Calendar: plant {pm}, harvest {hm} [{cal['source']}]")
        print(f"  Fertilizer: N={fert['n_kgha']:.0f} kg/ha [{fert['source']}]")
        print(f"  Observed: {obs['yield_kgha']:.0f} kg/ha [{obs['source']}]")
        print(f"  Terrain: elev={terrain['elevation']:.0f}m, slope={terrain['slope']:.4f}")

    # ── Step 2: Copy workspace ───────────────────────────────────
    if verbose:
        print(f"\n[1/7] Setting up workspace...")
    setup(str(workspace))

    # ── Step 3: Generate crop OPC with data-driven dates ─────────
    if verbose:
        print(f"\n[2/7] Generating {crop} operations schedule...")

    # Use ki_tools_common calendar + fertilizer instead of s9's hardcoded defaults
    schedule = get_schedule(crop_lower, lat)
    schedule["plant_month"] = cal["plant_month"]
    schedule["plant_day"] = cal["plant_day"]
    schedule["harvest_month"] = cal["harvest_month"]
    schedule["harvest_day"] = cal["harvest_day"]
    schedule["n_rate_kgha"] = fert["n_kgha"]

    opc_path = str(workspace / "OPSC01.mgt")
    title = f"{schedule['crop_name']} at ({lat:.1f},{lon:.1f}) data-driven"
    write_opc(schedule, nbyr, opc_path, title=title)
    # Also write uppercase copy (APEX reads whichever MNGTLIST references)
    opc_upper = str(workspace / "OPSC01.MGT")
    if opc_path != opc_upper:
        import shutil
        shutil.copy2(opc_path, opc_upper)
    # THE MISSING LINK (root-caused 2026-07-04): write_opc() only WRITES the
    # generated schedule — nothing repoints OPSCCOM.DAT at it, so APEX keeps
    # running the shipped Riesel-TX rotations (Y10/RNGE/Y6/Y8.OPC) and the new
    # crop never runs (Texas dryland rotation at a China site -> ~0.3 t/ha
    # crop-failure, low stress but ~1 t/ha biomass). Wire every subarea to the
    # generated OPC exactly as the validated China-corn workspaces in outputs/.
    from s9_generate_crop_opc import wire_management_list
    wire_management_list(str(workspace), opc_name="OPSC01.MGT")

    if verbose:
        print(f"  Crop: {schedule['crop_name']} (ID={schedule['plant_id']})")
        print(f"  Plant: {cal['plant_month']:02d}/{cal['plant_day']:02d}, "
              f"Harvest: {cal['harvest_month']:02d}/{cal['harvest_day']:02d}")
        print(f"  N: {fert['n_kgha']:.0f} kg/ha")

    # ── Step 4: Update site ──────────────────────────────────────
    if verbose:
        print(f"\n[3/7] Updating site to ({lat}, {lon})...")
    update_site(str(workspace), lat=lat, lon=lon, elev_m=terrain['elevation'])

    # ── Step 5: Build soil ───────────────────────────────────────
    if verbose:
        print(f"\n[4/7] Building soil from HWSD...")
    try:
        build_soil(str(workspace), lat=lat, lon=lon)
    except Exception as e:
        if verbose:
            print(f"  WARN: soil build failed ({e}), keeping template soil")

    # ── Step 6: Convert forcing ──────────────────────────────────
    if verbose:
        print(f"\n[5/7] Converting {source.upper()} forcing...")
    try:
        build_forcing(str(workspace), lat=lat, lon=lon,
                      year1=year1, year2=year2, source=source)
    except Exception as e:
        if verbose:
            print(f"  Forcing conversion failed: {e}")
        raise

    # ── Step 7: Update control ───────────────────────────────────
    if verbose:
        print(f"\n[6/7] Updating control file ({nbyr} years from {year1})...")
    update_control(str(workspace), year1=year1, year2=year2)

    # ── Step 8: Run APEX ─────────────────────────────────────────
    if verbose:
        print(f"\n[7/7] Running APEX 1501...")
    try:
        run(str(workspace))
    except Exception as e:
        if verbose:
            print(f"  APEX run issue: {e}")
        # Check if outputs exist anyway
        out_files = list(workspace.glob("*.OUT")) + list(workspace.glob("*.ACY"))
        if not out_files:
            raise

    # ── Parse and report ─────────────────────────────────────────
    if verbose:
        print(f"\n{'='*60}")
        print(f"RESULTS: {crop} at ({lat}, {lon})")
        print(f"{'='*60}")

    result = {
        "workspace": str(workspace),
        "crop_calendar": cal,
        "fertilizer": fert,
        "observed": obs,
        "terrain": terrain,
    }

    try:
        parsed = parse(str(workspace))
        if parsed is not None and "yield_tha" in parsed:
            sim_tha = parsed["yield_tha"]
            result["simulated_yield_tha"] = sim_tha
            obs_tha = obs['yield_kgha'] / 1000
            if verbose:
                print(f"  Simulated:  {sim_tha:.2f} t/ha")
                print(f"  Observed:   {obs_tha:.1f} t/ha [{obs['source']}]")
                if sim_tha > 0 and obs_tha > 0:
                    bias = (sim_tha - obs_tha) / obs_tha * 100
                    print(f"  Bias:       {bias:+.1f}%")
    except Exception as e:
        if verbose:
            print(f"  Output parsing: {e}")
            # Try manual ACY check
            for acy in workspace.glob("*RUN.ACY"):
                print(f"  Found: {acy.name}")
                with open(acy) as f:
                    for line in f.readlines()[-5:]:
                        print(f"    {line.rstrip()}")

    if verbose:
        print(f"  Calendar:   plant {cal['plant_month']:02d}/{cal['plant_day']:02d}, "
              f"harvest {cal['harvest_month']:02d}/{cal['harvest_day']:02d} [{cal['source']}]")
        print(f"  Fertilizer: N={fert['n_kgha']:.0f} kg/ha [{fert['source']}]")
        print(f"{'='*60}\n")

    return result


def main():
    ap = argparse.ArgumentParser(description="APEX quickstart")
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--crop", default="corn")
    ap.add_argument("--start", type=int, default=2008)
    ap.add_argument("--end", type=int, default=2013)
    ap.add_argument("--source", default="cmfd", choices=["cmfd", "nasa_power", "mswx"])
    ap.add_argument("--workspace", default=None)
    args = ap.parse_args()

    try:
        quickstart(args.lat, args.lon, args.crop, args.start, args.end,
                   source=args.source, workspace=args.workspace)
    except Exception as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(2)


if __name__ == "__main__":
    main()
