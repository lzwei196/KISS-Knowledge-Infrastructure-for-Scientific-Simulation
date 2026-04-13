#!/usr/bin/env python3
"""
run_wrfhydro_full_pipeline.py  --  End-to-End WRF-Hydro Pipeline
================================================================
Chains all WRF-Hydro setup tools into a single command:

  1. define_lambert_domain  (s1)  -> domain_def.json
  2. build_geo_em           (s2)  -> DOMAIN/geo_em.d01.nc
  3. build_wrfinput         (s3)  -> DOMAIN/wrfinput_d01.nc
  4. build_fulldom_hires    (s4)  -> DOMAIN/Fulldom_hires.nc
  5. build_soil_properties  (s5)  -> DOMAIN/soil_properties.nc
  6. build_groundwater      (s6)  -> DOMAIN/GWBASINS.nc, GWBUCKPARM.nc, etc.
  7. cmfd_to_ldasin         (s8)  -> FORCING/*.LDASIN_DOMAIN1
  8. generate_namelists     (s9)  -> namelist.hrldas, hydro.namelist
  9. run_wrfhydro           (s10) -> simulation outputs

Accepts a basin shapefile, date range, and grid resolution (in degrees),
automatically computing DX in metres.

Usage
-----
    python run_wrfhydro_full_pipeline.py \\
        --basin_shp data/shp/bengbu_shp/bengbu_boundary.shp \\
        --start_date 2001-01-01 --end_date 2001-12-31 \\
        --dx_deg 0.1 \\
        --output_dir outputs/bengbu_wrfhydro_test \\
        --nproc 4

    # Use 0.25 deg to match VIC comparison runs:
    python run_wrfhydro_full_pipeline.py \\
        --basin_shp data/shp/bengbu_shp/bengbu_boundary.shp \\
        --start_date 2001-07-01 --end_date 2001-07-31 \\
        --dx_deg 0.25 \\
        --output_dir outputs/bengbu_wrfhydro_025deg

Notes
-----
- Resolution conversion: 1 deg latitude ~ 111 km, so 0.1 deg ~ 11.1 km
  The script computes DX = dx_deg * 111000 (metres) and rounds to nearest 1000.
- For CMFD native resolution (0.1 deg), DX ~ 11000 m -> near 1:1 mapping.
- For VIC-comparable (0.25 deg), DX ~ 28000 m -> coarser, faster.
- Default data paths assume the HydroCraft server layout.
"""

import argparse
import json
import subprocess
import sys
import time as _time
from datetime import datetime
from pathlib import Path


# ===================================================================
# Default paths on HydroCraft server
# ===================================================================
TOOLS_DIR = Path(__file__).parent / "knowledge_infrastructure" / "tools"
# If this script is already inside the tools dir, adjust
if not TOOLS_DIR.exists():
    TOOLS_DIR = Path(__file__).parent

PROJECT_ROOT = Path("/mnt/disk1/Hydrocraft_server")
PYTHON = str(PROJECT_ROOT / "python_env" / "bin" / "python")

# Default data paths
DEFAULT_CMFD_DIR = str(PROJECT_ROOT / "data/forcing/Data_forcing_03hr_010deg")
DEFAULT_DEM = str(PROJECT_ROOT / "data/dem/china_dem_90m/china_dem_90m.tif")
DEFAULT_LANDCOVER = str(PROJECT_ROOT / "data/landcover/AVHRR_1km_LANDCOVER_1981_1994.GLOBAL.tif")
DEFAULT_HWSD_RASTER = str(PROJECT_ROOT / "data/soil/HWSD_RASTER/hwsd.bil")
DEFAULT_HWSD_MDB = str(PROJECT_ROOT / "data/forcing/huaihe_raw/soil/HWSD.mdb")
DEFAULT_SOILPARM = str(PROJECT_ROOT / "model/wrf_hydro/source/trunk/NDHMS/Run/SOILPARM.TBL")
DEFAULT_MPTABLE = str(PROJECT_ROOT / "model/wrf_hydro/source/trunk/NDHMS/Run/MPTABLE.TBL")


def resolve_tool(subdir, script_name):
    """Find a tool script, searching multiple possible locations."""
    candidates = [
        TOOLS_DIR / subdir / script_name,
        Path(__file__).parent / subdir / script_name,
        PROJECT_ROOT / "models" / "WRF_Hydro" / "knowledge_infrastructure" / "tools" / subdir / script_name,
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    raise FileNotFoundError(
        f"Tool not found: {subdir}/{script_name}\n"
        f"Searched: {[str(c) for c in candidates]}"
    )


def run_step(step_num, step_name, cmd, timeout=600):
    """Run a pipeline step, print output, check for errors."""
    print(f"\n{'='*70}")
    print(f"  Step {step_num}: {step_name}")
    print(f"{'='*70}")
    print(f"  Command: {' '.join(cmd[:5])}{'...' if len(cmd) > 5 else ''}")

    t0 = _time.time()
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    elapsed = _time.time() - t0

    # Print stdout
    if result.stdout:
        for line in result.stdout.strip().split('\n'):
            print(f"  | {line}")

    if result.returncode != 0:
        print(f"\n  FAILED (exit code {result.returncode}, {elapsed:.1f}s)")
        if result.stderr:
            print(f"  STDERR:")
            for line in result.stderr.strip().split('\n')[-20:]:
                print(f"  | {line}")
        raise RuntimeError(f"Step {step_num} ({step_name}) failed with exit code {result.returncode}")

    print(f"\n  Completed in {elapsed:.1f}s")
    return result


def auto_merge_srtm_dem(domain_json_path, output_dir, srtm_dir="/mnt/disk4/SRTMGL1"):
    """Auto-merge SRTM tiles based on domain_def.json tile list.

    Parameters
    ----------
    domain_json_path : str
        Path to domain_def.json (produced by define_lambert_domain.py).
    output_dir : str
        Directory to write the merged DEM GeoTIFF.
    srtm_dir : str
        Directory containing SRTM GL1 .hgt.zip tiles.

    Returns
    -------
    str
        Path to the merged DEM file.
    """
    import math
    import rasterio
    from rasterio.merge import merge as rasterio_merge

    with open(domain_json_path) as f:
        dom = json.load(f)

    tiles = dom.get("srtm_tiles", [])

    if not tiles:
        # Fallback: compute tiles from lat/lon range
        lat_range = dom.get("domain_lat_range", [])
        lon_range = dom.get("domain_lon_range", [])
        if lat_range and lon_range:
            lat_start = math.floor(lat_range[0])
            lat_end = math.floor(lat_range[1])
            lon_start = math.floor(lon_range[0])
            lon_end = math.floor(lon_range[1])
            tiles = []
            for lat in range(lat_start, lat_end + 1):
                for lon in range(lon_start, lon_end + 1):
                    ns = "N" if lat >= 0 else "S"
                    ew = "E" if lon >= 0 else "W"
                    tiles.append(f"{ns}{abs(lat):02d}{ew}{abs(lon):03d}")
        if not tiles:
            raise FileNotFoundError(
                "No SRTM tiles specified in domain_def.json and cannot compute from lat/lon range")

    print(f"  SRTM tiles to merge: {len(tiles)}")

    # Find and open tile files
    srcs = []
    missing = []
    for tile_name in tiles:
        zippath = Path(srtm_dir) / f"{tile_name}.SRTMGL1.hgt.zip"
        if zippath.exists():
            vsi = f"/vsizip/{zippath}/{tile_name}.hgt"
            try:
                srcs.append(rasterio.open(vsi))
            except Exception as e:
                print(f"  [WARN] Could not open tile {tile_name}: {e}")
                missing.append(tile_name)
        else:
            missing.append(tile_name)

    if missing:
        print(f"  [WARN] Missing SRTM tiles ({len(missing)}): {', '.join(missing[:20])}"
              f"{'...' if len(missing) > 20 else ''}")
    if not srcs:
        raise FileNotFoundError(
            f"No SRTM tiles found for domain in {srtm_dir}. "
            f"Needed: {', '.join(tiles[:10])}{'...' if len(tiles) > 10 else ''}")

    # Merge all tiles
    mosaic, transform = rasterio_merge(srcs)
    # Grab metadata from the first source for CRS and dtype
    meta = srcs[0].meta.copy()
    for s in srcs:
        s.close()

    meta.update(
        driver='GTiff',
        height=mosaic.shape[1],
        width=mosaic.shape[2],
        transform=transform,
        compress='lzw',
    )

    # Write merged DEM
    out_path = str(Path(output_dir) / "dem_srtm_merged.tif")
    with rasterio.open(out_path, 'w', **meta) as dst:
        dst.write(mosaic)

    print(f"  Auto-merged SRTM DEM: {out_path} ({mosaic.shape[2]}x{mosaic.shape[1]} pixels)")
    return out_path


def main():
    parser = argparse.ArgumentParser(
        description="End-to-end WRF-Hydro pipeline: domain setup through simulation")

    # Required
    parser.add_argument("--basin_shp", required=True,
                        help="Path to basin boundary shapefile (.shp)")
    parser.add_argument("--start_date", required=True,
                        help="Simulation start date YYYY-MM-DD")
    parser.add_argument("--end_date", required=True,
                        help="Simulation end date YYYY-MM-DD (inclusive)")
    parser.add_argument("--output_dir", required=True,
                        help="Output directory for all products")

    # Resolution
    parser.add_argument("--dx_deg", type=float, default=0.1,
                        help="LSM grid resolution in degrees (default 0.1). "
                             "Converted to metres: DX = dx_deg * 111000")
    parser.add_argument("--dx_m", type=float, default=None,
                        help="LSM grid resolution in metres (overrides --dx_deg)")

    # Optional data paths
    parser.add_argument("--cmfd_dir", default=DEFAULT_CMFD_DIR,
                        help="CMFD forcing directory")
    parser.add_argument("--dem_path", default=DEFAULT_DEM,
                        help="DEM GeoTIFF")
    parser.add_argument("--landcover_path", default=DEFAULT_LANDCOVER,
                        help="Land cover GeoTIFF")
    parser.add_argument("--hwsd_raster", default=DEFAULT_HWSD_RASTER,
                        help="HWSD raster (.bil)")
    parser.add_argument("--hwsd_mdb", default=DEFAULT_HWSD_MDB,
                        help="HWSD MDB database")
    parser.add_argument("--srtm_dir", default="/mnt/disk4/SRTMGL1",
                        help="SRTM tile directory for auto-merge (default /mnt/disk4/SRTMGL1)")

    # Domain/projection
    parser.add_argument("--truelat1", type=float, default=30.0)
    parser.add_argument("--truelat2", type=float, default=60.0)
    parser.add_argument("--stand_lon", type=float, default=None,
                        help="Standard longitude (default: auto from basin)")
    parser.add_argument("--buffer_cells", type=int, default=3,
                        help="Buffer cells around basin (default 3)")

    # Routing
    parser.add_argument("--aggfactrt", type=int, default=4,
                        help="Routing grid aggregation factor (default 4)")
    parser.add_argument("--stream_threshold", type=int, default=100,
                        help="Stream threshold for channel definition (default 100)")

    # Execution
    parser.add_argument("--nproc", type=int, default=4,
                        help="MPI processes for WRF-Hydro (default 4)")
    parser.add_argument("--timeout", type=int, default=7200,
                        help="WRF-Hydro run timeout in seconds (default 7200)")

    # Control
    parser.add_argument("--skip_run", action="store_true",
                        help="Stop after forcing, do not run WRF-Hydro")
    parser.add_argument("--start_from", type=int, default=1,
                        help="Start from step N (skip previous steps, assume outputs exist)")
    parser.add_argument("--stop_after", type=int, default=9,
                        help="Stop after step N")

    args = parser.parse_args()

    # Compute DX in metres
    if args.dx_m is not None:
        dx_m = args.dx_m
    else:
        dx_m = round(args.dx_deg * 111000.0 / 1000.0) * 1000.0  # round to nearest km
    dx_m = max(1000.0, dx_m)  # minimum 1km

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    domain_dir = output_dir / "DOMAIN"
    domain_dir.mkdir(parents=True, exist_ok=True)
    forcing_dir = output_dir / "FORCING"
    forcing_dir.mkdir(parents=True, exist_ok=True)

    # Key file paths
    domain_json = output_dir / "domain_def.json"
    geo_em_path = domain_dir / "geo_em.d01.nc"
    wrfinput_path = domain_dir / "wrfinput_d01.nc"
    fulldom_path = domain_dir / "Fulldom_hires.nc"
    soil_props_path = domain_dir / "soil_properties.nc"

    start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
    end_date = datetime.strptime(args.end_date, "%Y-%m-%d")
    duration_days = (end_date - start_date).days + 1

    print("=" * 70)
    print("WRF-Hydro Full Pipeline")
    print("=" * 70)
    print(f"  Basin:      {args.basin_shp}")
    print(f"  Period:     {args.start_date} to {args.end_date} ({duration_days} days)")
    print(f"  DX:         {dx_m:.0f} m ({dx_m/1000:.1f} km, ~{dx_m/111000:.3f} deg)")
    print(f"  Output:     {output_dir}")
    print(f"  CMFD:       {args.cmfd_dir}")
    print(f"  Routing:    AGGFACTRT={args.aggfactrt}, DXRT={dx_m/args.aggfactrt:.0f} m")
    print(f"  Steps:      {args.start_from} to {args.stop_after}")
    if args.skip_run:
        print(f"  Skip run:   Yes (setup only)")

    wall_t0 = _time.time()

    # ======================================================================
    # Step 1: Define Lambert domain
    # ======================================================================
    if args.start_from <= 1 <= args.stop_after:
        cmd = [
            PYTHON,
            resolve_tool("s1_domain", "define_lambert_domain.py"),
            "--basin_shp", args.basin_shp,
            "--dx", str(dx_m),
            "--truelat1", str(args.truelat1),
            "--truelat2", str(args.truelat2),
            "--buffer_cells", str(args.buffer_cells),
            "--output", str(domain_json),
        ]
        if args.stand_lon is not None:
            cmd.extend(["--stand_lon", str(args.stand_lon)])
        run_step(1, "Define Lambert Domain", cmd)

    # ======================================================================
    # Step 1.5: Auto-merge SRTM DEM if needed
    # ======================================================================
    if args.start_from <= 2:
        dem_path_resolved = args.dem_path
        needs_srtm = False

        if not Path(dem_path_resolved).exists():
            needs_srtm = True
            print(f"\n  DEM not found at {dem_path_resolved}, will auto-merge from SRTM.")
        elif domain_json.exists():
            # Check if domain is outside China (where default DEM covers)
            with open(domain_json) as f:
                dom_check = json.load(f)
            lat_range = dom_check.get("domain_lat_range", [0, 0])
            lon_range = dom_check.get("domain_lon_range", [0, 0])
            if lat_range and lon_range:
                # China DEM roughly covers lat 15-55, lon 73-135
                outside_china = (lat_range[0] < 15 or lat_range[1] > 55 or
                                 lon_range[0] < 73 or lon_range[1] > 135)
                if outside_china:
                    needs_srtm = True
                    print(f"\n  Domain extends outside China DEM coverage "
                          f"(lat {lat_range[0]:.1f}-{lat_range[1]:.1f}, "
                          f"lon {lon_range[0]:.1f}-{lon_range[1]:.1f}). "
                          f"Will auto-merge from SRTM.")

        if needs_srtm:
            print(f"\n  [Step 1.5] Auto-merging SRTM DEM for domain...")
            dem_path_resolved = auto_merge_srtm_dem(
                str(domain_json), str(output_dir), args.srtm_dir)
            # Update args for downstream steps
            args.dem_path = dem_path_resolved

    # ======================================================================
    # Step 2: Build geo_em.d01.nc
    # ======================================================================
    if args.start_from <= 2 <= args.stop_after:
        cmd = [
            PYTHON,
            resolve_tool("s2_geo_em", "build_geo_em.py"),
            "--domain_json", str(domain_json),
            "--dem_path", args.dem_path,
            "--landcover_path", args.landcover_path,
            "--hwsd_raster", args.hwsd_raster,
            "--hwsd_mdb", args.hwsd_mdb,
            "--output", str(geo_em_path),
            "--basin_shp", args.basin_shp,
        ]
        run_step(2, "Build geo_em.d01.nc", cmd, timeout=300)

    # ======================================================================
    # Step 3: Build wrfinput_d01.nc
    # ======================================================================
    if args.start_from <= 3 <= args.stop_after:
        start_month = start_date.month
        cmd = [
            PYTHON,
            resolve_tool("s3_wrfinput", "build_wrfinput.py"),
            "--geo_em", str(geo_em_path),
            "--output_path", str(wrfinput_path),
            "--start_month", str(start_month),
        ]
        run_step(3, "Build wrfinput_d01.nc", cmd)

        # Post-step 3: Patch minimum soil moisture (prevents dt_v036 crash in arid basins)
        print("  [3b] Patching wrfinput: minimum SMOIS=0.25, TSLB>=270K...")
        import netCDF4 as nc4
        dsi = nc4.Dataset(str(wrfinput_path), "r+")
        if "SMOIS" in dsi.variables:
            sm = dsi["SMOIS"][:]
            sm[sm < 0.25] = 0.25
            dsi["SMOIS"][:] = sm
        if "TSLB" in dsi.variables:
            ts = dsi["TSLB"][:]
            ts[ts < 270] = 285.0
            dsi["TSLB"][:] = ts
        dsi.close()

    # ======================================================================
    # Step 4: Build Fulldom_hires.nc
    # ======================================================================
    if args.start_from <= 4 <= args.stop_after:
        cmd = [
            PYTHON,
            resolve_tool("s4_fulldom", "build_fulldom_hires.py"),
            "--geo_em", str(geo_em_path),
            "--domain_json", str(domain_json),
            "--dem_path", args.dem_path,
            "--basin_shp", args.basin_shp,
            "--output_path", str(fulldom_path),
            "--aggfactrt", str(args.aggfactrt),
            "--stream_threshold", str(args.stream_threshold),
        ]
        run_step(4, "Build Fulldom_hires.nc", cmd, timeout=600)

    # ======================================================================
    # Step 5: Build soil_properties.nc
    # ======================================================================
    if args.start_from <= 5 <= args.stop_after:
        cmd = [
            PYTHON,
            resolve_tool("s5_soil_properties", "build_soil_properties.py"),
            "--geo_em", str(geo_em_path),
            "--output_path", str(soil_props_path),
            "--soilparm_tbl", DEFAULT_SOILPARM,
            "--mptable_tbl", DEFAULT_MPTABLE,
        ]
        run_step(5, "Build soil_properties.nc", cmd)

    # ======================================================================
    # Step 6: Build groundwater + ancillary files
    # ======================================================================
    if args.start_from <= 6 <= args.stop_after:
        cmd = [
            PYTHON,
            resolve_tool("s6_groundwater", "build_groundwater.py"),
            "--geo_em", str(geo_em_path),
            "--domain_json", str(domain_json),
            "--basin_shp", args.basin_shp,
            "--output_dir", str(domain_dir),
        ]
        run_step(6, "Build groundwater + ancillary files", cmd)

    # ======================================================================
    # Step 7: CMFD -> LDASIN forcing (Option A: direct, no VIC intermediary)
    # ======================================================================
    if args.start_from <= 7 <= args.stop_after:
        cmd = [
            PYTHON,
            resolve_tool("s8_forcing", "cmfd_to_ldasin.py"),
            "--cmfd_dir", args.cmfd_dir,
            "--geo_em", str(geo_em_path),
            "--domain_json", str(domain_json),
            "--output_dir", str(forcing_dir),
            "--start_date", args.start_date,
            "--end_date", args.end_date,
            "--resolution", str(args.dx_deg if args.dx_m is None else args.dx_m / 111000.0),
        ]
        # Timeout: ~1 min per month at 0.1deg, more for finer grids
        n_months = len(set((start_date.year * 12 + start_date.month + i)
                           for i in range(
            (end_date.year - start_date.year) * 12 + end_date.month - start_date.month + 1
        )))
        forcing_timeout = max(600, n_months * 120)
        run_step(7, "CMFD -> LDASIN forcing (Option A)", cmd, timeout=forcing_timeout)

    # ======================================================================
    # Step 8: Generate namelists
    # ======================================================================
    if args.start_from <= 8 <= args.stop_after:
        cmd = [
            PYTHON,
            resolve_tool("s9_namelists", "generate_namelists.py"),
            "--domain_dir", str(domain_dir),
            "--forcing_dir", str(forcing_dir),
            "--output_dir", str(output_dir),
            "--start_date", args.start_date,
            "--end_date", args.end_date,
            "--nproc", str(args.nproc),
            "--output_timestep", "3600",
        ]
        run_step(8, "Generate namelists", cmd)

    # ======================================================================
    # Step 9: Run WRF-Hydro
    # ======================================================================
    if args.start_from <= 9 <= args.stop_after and not args.skip_run:
        cmd = [
            PYTHON,
            resolve_tool("s10_execution", "run_wrfhydro.py"),
            "--run_dir", str(output_dir),
            "--nproc", str(args.nproc),
            "--timeout", str(args.timeout),
        ]
        run_step(9, "Run WRF-Hydro", cmd, timeout=args.timeout + 60)

    # ======================================================================
    # Summary
    # ======================================================================
    wall_elapsed = _time.time() - wall_t0

    print(f"\n{'='*70}")
    print(f"  Pipeline Complete!")
    print(f"{'='*70}")
    print(f"  Total time:  {wall_elapsed:.0f}s ({wall_elapsed/60:.1f} min)")
    print(f"  Output dir:  {output_dir}")
    print(f"  DX:          {dx_m:.0f} m (~{dx_m/111000:.3f} deg)")

    # List key output files
    print(f"\n  Key files:")
    key_files = [
        domain_json,
        geo_em_path,
        wrfinput_path,
        fulldom_path,
        soil_props_path,
        domain_dir / "GWBASINS.nc",
        domain_dir / "GWBUCKPARM.nc",
        domain_dir / "hydro2dtbl.nc",
        domain_dir / "GEOGRID_LDASOUT_Spatial_Metadata.nc",
    ]
    for f in key_files:
        status = "OK" if f.exists() else "MISSING"
        size_mb = f.stat().st_size / 1e6 if f.exists() else 0
        print(f"    [{status}] {f.name} ({size_mb:.1f} MB)")

    # Count LDASIN files
    ldasin_files = list(forcing_dir.glob("*.LDASIN_DOMAIN1"))
    print(f"    [{'OK' if ldasin_files else 'MISSING'}] "
          f"FORCING/{len(ldasin_files)} LDASIN files")

    # Check for namelists
    for nl in ["namelist.hrldas", "hydro.namelist"]:
        nlp = output_dir / nl
        print(f"    [{'OK' if nlp.exists() else 'MISSING'}] {nl}")

    # Save pipeline metadata
    meta = {
        "basin_shp": str(args.basin_shp),
        "start_date": args.start_date,
        "end_date": args.end_date,
        "dx_m": dx_m,
        "dx_deg": dx_m / 111000.0,
        "aggfactrt": args.aggfactrt,
        "nproc": args.nproc,
        "cmfd_dir": args.cmfd_dir,
        "output_dir": str(output_dir),
        "forcing_method": "cmfd_to_ldasin_direct (Option A)",
        "total_time_s": round(wall_elapsed, 1),
        "n_ldasin_files": len(ldasin_files),
    }
    meta_path = output_dir / "pipeline_meta.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"\n  Pipeline metadata: {meta_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
