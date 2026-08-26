#!/usr/bin/env python3
"""
prepare_runoff_input.py -- Convert VIC/wflow/HYPE/generic runoff to CaMa-Flood input format.

Produces yearly NetCDF files with:
  - Variable: Runoff (mm/day)
  - Dimensions: (time, lat, lon)
  - Latitude order: North-to-South (descending)
  - One file per year: {basin}_runoff_1d_{YYYY}.nc

This is Stage 1 of the CaMa-Flood pipeline.

Usage:
    python prepare_runoff_input.py \\
        --source vic \\
        --input_dir /path/to/vic_result \\
        --output_dir /path/to/cama_input \\
        --basin_name bengbu \\
        --start_year 2000 --end_year 2005 \\
        --file_prefix "huaihe_fluxes_"

    python prepare_runoff_input.py \\
        --source wflow \\
        --input_dir /path/to/wflow_output \\
        --output_dir /path/to/cama_input \\
        --basin_name bengbu \\
        --start_year 2000 --end_year 2005

    python prepare_runoff_input.py \\
        --source netcdf \\
        --input_dir /path/to/generic \\
        --output_dir /path/to/cama_input \\
        --basin_name bengbu \\
        --start_year 2000 --end_year 2005 \\
        --netcdf_var "runoff" \\
        --netcdf_pattern "runoff_{year}.nc"
"""

import argparse
import glob
import os
import sys
from datetime import datetime

import numpy as np

try:
    import netCDF4 as nc
except ImportError:
    print("ERROR: netCDF4 not installed. Run: pip install netCDF4")
    sys.exit(1)


def open_nc(path, **kwargs):
    """xr.open_dataset with an engine fallback -- see dt_cama_014.

    In the HydroCraft python_env (netCDF4 1.7.4 / HDF5 1.14.6 / xarray 2025.11.0) xarray's
    DEFAULT 'netcdf4' backend raises `OSError: [Errno -101] NetCDF: HDF error` on EVERY
    NETCDF4/HDF5 file, including the shipped e2o test forcing under
    model/cmf_v420_pkg/inp/test_15min_nc/. `netCDF4.Dataset(path)` opens the same file fine,
    so the file is NOT corrupt -- do not go looking for a bad download. 'h5netcdf' works.
    """
    import xarray as xr
    last = None
    for engine in (None, "h5netcdf", "netcdf4", "scipy"):
        try:
            return xr.open_dataset(path, engine=engine, **kwargs)
        except Exception as exc:                       # noqa: BLE001 - try every backend
            last = exc
    raise OSError(f"cannot open {path} with any xarray engine (dt_cama_014): {last}")


# ---------------------------------------------------------------------------
# VIC source: reads VIC flux text files
# ---------------------------------------------------------------------------

def _vic_find_runoff_columns(header_line):
    """Find RUNOFF and BASEFLOW column indices in a VIC flux file header."""
    cols = header_line.strip().split()
    runoff_idx = baseflow_idx = None
    for i, col in enumerate(cols):
        if "OUT_RUNOFF" in col:
            runoff_idx = i
        elif "OUT_BASEFLOW" in col:
            baseflow_idx = i
    return runoff_idx, baseflow_idx


def _vic_parse_coord_from_filename(filename, file_prefix):
    """Extract (lat, lon) from VIC flux filename like huaihe_fluxes_33.1250_117.1250.txt."""
    basename = os.path.basename(filename)
    stripped = basename.replace(file_prefix, "").replace(".txt", "")
    parts = stripped.split("_")
    if len(parts) >= 2:
        return float(parts[0]), float(parts[1])
    raise ValueError(f"Cannot parse lat/lon from filename: {filename}")


def convert_vic(input_dir, output_dir, basin_name, start_year, end_year,
                file_prefix="huaihe_fluxes_"):
    """Convert VIC text flux files to CaMa-Flood NetCDF runoff input."""
    import pandas as pd

    pattern = os.path.join(input_dir, f"{file_prefix}*.txt")
    files = sorted(glob.glob(pattern))
    if not files:
        print(f"ERROR: No files matching {pattern}")
        return False

    print(f"Found {len(files)} VIC flux files")

    # Read header from first file to find column indices
    with open(files[0], "r") as f:
        lines = f.readlines()
    header_idx = 0
    for i, line in enumerate(lines):
        if line.startswith("YEAR"):
            header_idx = i
            break

    runoff_idx, baseflow_idx = _vic_find_runoff_columns(lines[header_idx])
    if runoff_idx is None or baseflow_idx is None:
        print(f"ERROR: Cannot find OUT_RUNOFF/OUT_BASEFLOW in header: {lines[header_idx].strip()}")
        return False
    print(f"Column indices -- RUNOFF: {runoff_idx}, BASEFLOW: {baseflow_idx}")

    # Extract coordinates from all filenames
    coords = []
    for fp in files:
        try:
            lat, lon = _vic_parse_coord_from_filename(fp, file_prefix)
            coords.append((lat, lon, fp))
        except ValueError as e:
            print(f"WARNING: {e}")
            continue

    lats = sorted(set(c[0] for c in coords), reverse=True)  # North-to-South
    lons = sorted(set(c[1] for c in coords))  # West-to-East
    print(f"Grid: {len(lats)} lats x {len(lons)} lons")
    print(f"  Lat range: {max(lats):.4f} (N) to {min(lats):.4f} (S)")
    print(f"  Lon range: {min(lons):.4f} (W) to {max(lons):.4f} (E)")

    os.makedirs(output_dir, exist_ok=True)

    for year in range(start_year, end_year + 1):
        print(f"\nProcessing year {year}...")
        ndays = 366 if ((year % 4 == 0 and year % 100 != 0) or year % 400 == 0) else 365
        runoff_data = np.full((ndays, len(lats), len(lons)), 0.0, dtype=np.float32)

        for lat, lon, filepath in coords:
            lat_idx = lats.index(lat)
            lon_idx = lons.index(lon)
            try:
                df = pd.read_csv(filepath, sep=r"\s+", skiprows=header_idx + 1, header=None)
                df_year = df[df.iloc[:, 0] == year]
                if len(df_year) == 0:
                    continue
                runoff = df_year.iloc[:, runoff_idx].values + df_year.iloc[:, baseflow_idx].values
                n = min(len(runoff), ndays)
                runoff_data[:n, lat_idx, lon_idx] = runoff[:n]
            except Exception as e:
                print(f"  WARNING: Error processing {filepath}: {e}")
                continue

        output_file = os.path.join(output_dir, f"{basin_name}_runoff_1d_{year}.nc")
        _write_runoff_nc(output_file, runoff_data, lats, lons, year, "VIC 5.1")
        print(f"  Wrote: {output_file}")
        print(f"  Max Runoff: {np.nanmax(runoff_data):.2f} mm/day, "
              f"Mean: {np.nanmean(runoff_data[runoff_data > 0]):.2f} mm/day")

    return True


# ---------------------------------------------------------------------------
# wflow source: reads wflow NetCDF output
# ---------------------------------------------------------------------------

def convert_wflow(input_dir, output_dir, basin_name, start_year, end_year):
    """Convert wflow output to CaMa-Flood NetCDF runoff input.

    wflow_sbm produces lateral subsurface flow + overland flow which,
    when summed, give total runoff. CRITICAL: do NOT use the routed Q
    variable -- that would double-count routing.
    """
    import xarray as xr

    # Look for wflow output file
    candidates = [
        os.path.join(input_dir, "run_default", "output.nc"),
        os.path.join(input_dir, "output.nc"),
        os.path.join(input_dir, "run_default", "output_scalar.nc"),
    ]
    wflow_nc = None
    for c in candidates:
        if os.path.isfile(c):
            wflow_nc = c
            break

    if wflow_nc is None:
        print(f"ERROR: Cannot find wflow output in {input_dir}")
        print(f"  Searched: {candidates}")
        return False

    print(f"Reading wflow output: {wflow_nc}")
    ds = open_nc(wflow_nc)

    # Identify runoff variable (lateral_subsurface + overland, or total_runoff)
    runoff_var = None
    for vname in ["total_runoff", "runoff", "ssf", "overland_flow"]:
        if vname in ds.data_vars:
            runoff_var = vname
            break

    if runoff_var is None:
        # Try summing lateral subsurface + overland
        ssf_var = ovf_var = None
        for v in ds.data_vars:
            if "subsurface" in v.lower() or "ssf" in v.lower():
                ssf_var = v
            if "overland" in v.lower() or "surface_runoff" in v.lower():
                ovf_var = v
        if ssf_var and ovf_var:
            print(f"  Summing {ssf_var} + {ovf_var} for total runoff")
            ds["total_runoff"] = ds[ssf_var] + ds[ovf_var]
            runoff_var = "total_runoff"
        else:
            print(f"ERROR: Cannot identify runoff variable in wflow output.")
            print(f"  Available variables: {list(ds.data_vars)}")
            ds.close()
            return False

    print(f"  Using variable: {runoff_var}")

    lat_name = "lat" if "lat" in ds.coords else "y"
    lon_name = "lon" if "lon" in ds.coords else "x"
    lats = ds[lat_name].values
    lons = ds[lon_name].values

    # Ensure North-to-South ordering
    if len(lats) > 1 and lats[0] < lats[-1]:
        print("  Flipping latitude to North-to-South")
        ds = ds.isel({lat_name: slice(None, None, -1)})
        lats = lats[::-1]

    os.makedirs(output_dir, exist_ok=True)

    for year in range(start_year, end_year + 1):
        print(f"\nProcessing year {year}...")
        time_sel = ds.sel(time=ds.time.dt.year == year)
        if len(time_sel.time) == 0:
            print(f"  WARNING: No data for year {year}")
            continue

        runoff = time_sel[runoff_var].values.astype(np.float32)

        # Check units -- wflow typically outputs mm, need mm/day
        # If sub-daily, aggregate to daily
        if len(time_sel.time) > 400:
            print(f"  Sub-daily data detected ({len(time_sel.time)} steps), aggregating to daily")
            time_sel_daily = time_sel.resample(time="1D").sum()
            runoff = time_sel_daily[runoff_var].values.astype(np.float32)

        output_file = os.path.join(output_dir, f"{basin_name}_runoff_1d_{year}.nc")
        _write_runoff_nc(output_file, runoff, list(lats), list(lons), year, "wflow_sbm")
        print(f"  Wrote: {output_file}")

    ds.close()
    return True


# ---------------------------------------------------------------------------
# Generic NetCDF source
# ---------------------------------------------------------------------------

def convert_netcdf(input_dir, output_dir, basin_name, start_year, end_year,
                   netcdf_var="runoff", netcdf_pattern="runoff_{year}.nc",
                   scale_factor=1.0, west=None, east=None, south=None, north=None):
    """Convert generic NetCDF runoff files to CaMa-Flood format.

    west/east/south/north (optional, in degrees, CELL-EDGE coordinates) trim the source grid to
    the basin. This is the implementation of the dt_cama_006 remedy ("trim NetCDF to the actual
    source grid extent"): a GLOBAL forcing product (e2o/ERA/MSWX) fed to CaMa untrimmed forces the
    inpmat WESTIN/EASTIN/NORTHIN/SOUTHIN to be global too, and every CaMa cell then maps through a
    global input matrix -- slow, memory-hungry, and impossible to reconcile with the regional
    domain a user passes to configure_simulation.py (which uses the SAME extent for both the
    inpmat source grid and the CaMa domain). Trim here, then hand the printed cell-edge extent
    straight to configure_simulation.py --west/--east/--south/--north (dt_cama_002).
    """
    import xarray as xr

    os.makedirs(output_dir, exist_ok=True)

    for year in range(start_year, end_year + 1):
        fname = netcdf_pattern.replace("{year}", str(year))
        fpath = os.path.join(input_dir, fname)
        if not os.path.isfile(fpath):
            print(f"WARNING: {fpath} not found, skipping year {year}")
            continue

        print(f"Processing: {fpath}")
        ds = open_nc(fpath)

        if netcdf_var not in ds.data_vars:
            print(f"ERROR: Variable '{netcdf_var}' not found. Available: {list(ds.data_vars)}")
            ds.close()
            return False

        lat_name = "lat" if "lat" in ds.coords else "y"
        lon_name = "lon" if "lon" in ds.coords else "x"

        # Ensure North-to-South BEFORE any subsetting so the written file obeys dt_cama_007.
        lats = ds[lat_name].values
        if len(lats) > 1 and lats[0] < lats[-1]:
            ds = ds.isel({lat_name: slice(None, None, -1)})

        # Optional bbox trim (cell CENTRES kept when they fall inside the requested EDGES).
        if any(v is not None for v in (west, east, south, north)):
            lat_v = ds[lat_name].values
            lon_v = ds[lon_name].values
            lat_keep = np.ones(lat_v.shape, dtype=bool)
            lon_keep = np.ones(lon_v.shape, dtype=bool)
            if south is not None:
                lat_keep &= lat_v > south
            if north is not None:
                lat_keep &= lat_v < north
            if west is not None:
                lon_keep &= lon_v > west
            if east is not None:
                lon_keep &= lon_v < east
            if lat_keep.sum() == 0 or lon_keep.sum() == 0:
                print(f"ERROR: bbox W={west} E={east} S={south} N={north} selects no cells from "
                      f"lat[{lat_v.min()},{lat_v.max()}] lon[{lon_v.min()},{lon_v.max()}]")
                ds.close()
                return False
            ds = ds.isel({lat_name: np.where(lat_keep)[0], lon_name: np.where(lon_keep)[0]})

        lats = ds[lat_name].values
        lons = ds[lon_name].values

        # Report the CELL-EDGE extent -- this is what inpmat generation needs (dt_cama_002).
        dlat = abs(float(lats[1] - lats[0])) if len(lats) > 1 else 0.0
        dlon = abs(float(lons[1] - lons[0])) if len(lons) > 1 else 0.0
        print(f"  Grid: {len(lats)} lat x {len(lons)} lon, res {dlon:g} deg")
        print(f"  Cell-edge extent for configure_simulation.py / inpmat (dt_cama_002): "
              f"--west {float(lons.min()) - dlon / 2:g} --east {float(lons.max()) + dlon / 2:g} "
              f"--south {float(lats.min()) - dlat / 2:g} --north {float(lats.max()) + dlat / 2:g}")

        runoff = ds[netcdf_var].values.astype(np.float32) * scale_factor

        output_file = os.path.join(output_dir, f"{basin_name}_runoff_1d_{year}.nc")
        _write_runoff_nc(output_file, runoff, list(lats), list(lons), year, "Generic NetCDF")
        finite = runoff[np.isfinite(runoff)]
        if finite.size:
            print(f"  Runoff range: {finite.min():.3f} .. {finite.max():.3f} mm/day "
                  f"(mean {finite.mean():.3f})")
        print(f"  Wrote: {output_file}")
        ds.close()

    return True


# ---------------------------------------------------------------------------
# Common NetCDF writer
# ---------------------------------------------------------------------------

def _write_runoff_nc(output_file, runoff_data, lats, lons, year, source_model):
    """Write a CaMa-Flood compatible NetCDF runoff file.

    Args:
        runoff_data: numpy array of shape (ndays, nlat, nlon), units mm/day
        lats: list of latitudes (must be descending, North-to-South)
        lons: list of longitudes (ascending, West-to-East)
        year: integer year
        source_model: string describing the source
    """
    ndays = runoff_data.shape[0]

    # Validate latitude order
    if len(lats) > 1 and lats[0] < lats[-1]:
        raise ValueError(
            f"Latitude must be in descending order (North-to-South). "
            f"Got {lats[0]} < {lats[-1]}. See dt_cama_007."
        )

    with nc.Dataset(output_file, "w", format="NETCDF4") as ds:
        ds.createDimension("time", ndays)
        ds.createDimension("lat", len(lats))
        ds.createDimension("lon", len(lons))

        time_var = ds.createVariable("time", "i4", ("time",))
        time_var.units = f"days since {year}-01-01"
        time_var.calendar = "standard"
        time_var[:] = np.arange(ndays)

        lat_var = ds.createVariable("lat", "f4", ("lat",))
        lat_var.units = "degrees_north"
        lat_var.long_name = "latitude"
        lat_var[:] = lats

        lon_var = ds.createVariable("lon", "f4", ("lon",))
        lon_var.units = "degrees_east"
        lon_var.long_name = "longitude"
        lon_var[:] = lons

        runoff_var = ds.createVariable("Runoff", "f4", ("time", "lat", "lon"),
                                       fill_value=-9999.0)
        runoff_var.units = "mm/day"
        runoff_var.long_name = "Total Runoff (surface + baseflow)"

        # Replace NaN with 0 (CaMa expects numeric values, not fill)
        data = np.where(np.isnan(runoff_data), 0.0, runoff_data)
        runoff_var[:] = data

        ds.title = f"Runoff for CaMa-Flood ({year})"
        ds.source = source_model
        ds.history = f"Created {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} by prepare_runoff_input.py"
        ds.conventions = "CF-1.6"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Convert gridded runoff output to CaMa-Flood input NetCDF format.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Sources:
  vic      VIC 5.x text flux files (huaihe_fluxes_*.txt)
  wflow    wflow_sbm NetCDF output (lateral runoff, NOT routed Q)
  hype     HYPE model output (same as generic NetCDF with scale)
  netcdf   Generic NetCDF with a runoff variable

Unit note:
  CaMa-Flood expects runoff in mm/day. Do NOT convert to m3/s -- the model
  handles area-weighted conversion internally using ctmare.bin.
"""
    )
    parser.add_argument("--source", required=True, choices=["vic", "wflow", "hype", "netcdf"],
                        help="Source model type")
    parser.add_argument("--input_dir", required=True, help="Directory containing source model output")
    parser.add_argument("--output_dir", required=True, help="Output directory for CaMa input files")
    parser.add_argument("--basin_name", required=True, help="Basin name for output file naming")
    parser.add_argument("--start_year", type=int, required=True)
    parser.add_argument("--end_year", type=int, required=True)
    # VIC-specific
    parser.add_argument("--file_prefix", default="huaihe_fluxes_",
                        help="VIC flux file prefix (default: huaihe_fluxes_)")
    # NetCDF-specific
    parser.add_argument("--netcdf_var", default="runoff",
                        help="Variable name in generic NetCDF (default: runoff)")
    parser.add_argument("--netcdf_pattern", default="runoff_{year}.nc",
                        help="Filename pattern with {year} placeholder")
    parser.add_argument("--scale_factor", type=float, default=1.0,
                        help="Multiply runoff values by this factor (unit conversion)")
    # Bounding box (netcdf/hype sources): trim a global product to the basin -- dt_cama_006.
    parser.add_argument("--west", type=float, help="West cell EDGE of the kept sub-grid (deg)")
    parser.add_argument("--east", type=float, help="East cell EDGE of the kept sub-grid (deg)")
    parser.add_argument("--south", type=float, help="South cell EDGE of the kept sub-grid (deg)")
    parser.add_argument("--north", type=float, help="North cell EDGE of the kept sub-grid (deg)")

    args = parser.parse_args()

    print(f"{'='*60}")
    print(f"  CaMa-Flood Runoff Input Preparation")
    print(f"  Source: {args.source}")
    print(f"  Basin:  {args.basin_name}")
    print(f"  Period: {args.start_year}-{args.end_year}")
    print(f"{'='*60}")

    if args.source == "vic":
        success = convert_vic(args.input_dir, args.output_dir, args.basin_name,
                              args.start_year, args.end_year, args.file_prefix)
    elif args.source == "wflow":
        success = convert_wflow(args.input_dir, args.output_dir, args.basin_name,
                                args.start_year, args.end_year)
    elif args.source in ("hype", "netcdf"):
        # HYPE uses the same NetCDF converter with a potential scale adjustment
        success = convert_netcdf(args.input_dir, args.output_dir, args.basin_name,
                                 args.start_year, args.end_year,
                                 netcdf_var=args.netcdf_var,
                                 netcdf_pattern=args.netcdf_pattern,
                                 scale_factor=args.scale_factor,
                                 west=args.west, east=args.east,
                                 south=args.south, north=args.north)
    else:
        print(f"ERROR: Unknown source: {args.source}")
        success = False

    if success:
        print(f"\nSUCCESS: Runoff input files written to {args.output_dir}")
    else:
        print(f"\nFAILED: See errors above.")
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
