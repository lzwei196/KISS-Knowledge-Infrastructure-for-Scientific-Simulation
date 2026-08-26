#!/usr/bin/env python3
"""
parse_cama_output.py -- Extract and analyze CaMa-Flood output.

Capabilities:
  1. Extract discharge (outflw) time series at a gauge point (lat/lon)
  2. Extract flood depth/extent statistics
  3. Compute summary metrics (peak Q, mean Q, flood duration)
  4. Output CSV for downstream analysis/plotting
  5. Downscale flddph to the native high-resolution grid (--downscale) and read the result
     back as a 2-D field (--downscaled_dir), which is what flood-extent validation needs.

This is Stage 4 of the CaMa-Flood pipeline.

DOWNSCALING LIVES HERE, NOT IN tools/downscale/ (read this before looking for a shell script).
  Every *.sh under tools/downscale/ is a symlink into Hydrocraft/skills/cama-downscale/, and
  those scripts hard-code BASE=/Volumes/Expansion2t/... (a macOS laptop path) plus an output
  directory pattern configure_simulation.py never produces -- they cannot run on this server
  (dt_cama_016; run_cama.py already treats a "/Volumes/" path in a run script as a fatal legacy
  bug). SKILL.md Stage 5 still shows `bash tools/downscale/run_downscale.sh ...`; that command
  does NOT work. Use `parse_cama_output.py --downscale` instead -- it drives the same official
  utility (etc/downscale_flddph/src/downscale_flddph_trib, Yamazaki) directly, with every path
  an explicit argument. Do not "fix" the symlinks by editing them; they are outside this tool's
  file contract.

Usage:
    # Extract discharge at Bengbu station
    python parse_cama_output.py \\
        --output_dir KISSPATH_BINARIES/cmf_v420_pkg/out/bengbu_2000_2005_cama \\
        --variable outflw \\
        --lat 32.95 --lon 117.35 \\
        --start_year 2000 --end_year 2005 \\
        --csv discharge_bengbu.csv

    # Extract flood depth spatial statistics
    python parse_cama_output.py \\
        --output_dir /path/to/output \\
        --variable flddph \\
        --start_year 2003 --end_year 2003 \\
        --spatial_stats

    # Extract all variables at a point
    python parse_cama_output.py \\
        --output_dir /path/to/output \\
        --variable outflw,rivdph,sfcelv,flddph \\
        --lat 32.95 --lon 117.35 \\
        --start_year 2000 --end_year 2005

    # Downscale flddph 15min -> 1min over an event window (needs binary output)
    python parse_cama_output.py --downscale \\
        --output_dir /path/to/out_bin --map_dir /path/to/map/mekong_15min \\
        --start_year 2001 --end_year 2001 --start_month 8 --end_month 11 \\
        --res 1min --west 98 --east 109.5 --south 8.5 --north 21.75 \\
        --downscale_dest /path/to/downscale_1min

    # Read the downscaled event back as one max-extent field (compare against GFD)
    python parse_cama_output.py --downscaled_dir /path/to/downscale_1min \\
        --res 1min --west 98 --east 109.5 --south 8.5 --north 21.75 \\
        --field_reduce max --field_out model_1min_max.nc
"""

import argparse
import calendar
import os
import subprocess
import sys
from datetime import datetime

import numpy as np

try:
    import xarray as xr
except ImportError:
    print("ERROR: xarray not installed. Run: pip install xarray")
    sys.exit(1)


RMIS = 1.0e20   # CaMa's undefined value (src/cmf_ctrl_nmlist_mod.F90: RMIS=1.E20_JPRM)

CAMA_ROOT = os.environ.get("CAMA_ROOT", "KISSPATH_BINARIES/cmf_v420_pkg")

# high-resolution pixels per degree, per downscale_flddph_trib.F90's own csize table
HIRES_PX_PER_DEG = {"1sec": 3600, "3sec": 1200, "5sec": 720,
                    "15sec": 240, "30sec": 120, "1min": 60}

# Permanent water floor applied by the downscaler: it forces every pixel flagged in
# <res>.rivwth.bin up to max(0.1, depth) (downscale_flddph_trib.F90). Threshold flood extent
# STRICTLY ABOVE this, or the world's rivers score as false alarms (dt_cama_015).
PERM_WATER_FLOOR_M = 0.1


def open_nc(path, **kwargs):
    """xr.open_dataset with an engine fallback -- see dt_cama_014.

    In the HydroCraft python_env (netCDF4 1.7.4 / HDF5 1.14.6 / xarray 2025.11.0) xarray's
    DEFAULT 'netcdf4' backend raises `OSError: [Errno -101] NetCDF: HDF error` on EVERY
    NETCDF4/HDF5 file -- including files it has just written, and including CaMa's own
    o_*.nc output. `netCDF4.Dataset(path)` opens the same file fine, so the data is not
    corrupt; it is the xarray backend that is broken. 'h5netcdf' works.

    Never "work around" this by declaring a file unreadable: fall back to h5netcdf, then to
    scipy for classic NetCDF-3. preflight_check.py now OPENS a file rather than merely
    importing xarray, so this fails loudly at stage 0 instead of mid-pipeline.
    """
    last = None
    for engine in (None, "h5netcdf", "netcdf4", "scipy"):
        try:
            return xr.open_dataset(path, engine=engine, **kwargs)
        except Exception as exc:                       # noqa: BLE001 - try every backend
            last = exc
    raise OSError(f"cannot open {path} with any xarray engine (dt_cama_014): {last}")


def read_map_params(map_dir):
    """Parse a CaMa map directory's params.txt -> grid definition + cell-centre lat/lon axes.

    params.txt (written by set_map) is the authority for a regional map's dimensions:
      nXX, nYY, nflp, gsize, west, east, south, north

    Two comment styles exist in the wild and both must parse: the shipped global maps write
    `1440      !! grid number (east-west)`, while the regional maps our own regionalization
    produces write `28            grid number (east-west)` with no `!!` at all. CaMa itself
    does `read(11,*) nXX`, i.e. it takes the FIRST list-directed item and ignores the rest of
    the line -- so take the first whitespace-separated token, never a `!!` split.
    """
    ppath = os.path.join(map_dir, "params.txt")
    if not os.path.isfile(ppath):
        raise FileNotFoundError(f"params.txt not found in map dir: {map_dir}")
    with open(ppath) as f:
        vals = [line.split()[0] for line in f if line.split()]
    if len(vals) < 8:
        raise ValueError(f"{ppath}: expected 8 values (nXX nYY nflp gsize W E S N), got {len(vals)}")
    nx, ny = int(vals[0]), int(vals[1])
    gsize = float(vals[3])
    west, east, south, north = (float(v) for v in vals[4:8])
    lons = west + (np.arange(nx) + 0.5) * gsize
    lats = north - (np.arange(ny) + 0.5) * gsize          # descending, N->S (dt_cama_007)
    return {"nx": nx, "ny": ny, "gsize": gsize, "west": west, "east": east,
            "south": south, "north": north, "lons": lons, "lats": lats}


def load_output(output_dir, var, year, map_dir=None):
    """Load one year of a CaMa output variable, from EITHER output form.

    LOUTCDF=.TRUE.  -> o_{var}{YYYY}.nc   (self-describing; map_dir not needed)
    LOUTCDF=.FALSE. -> {var}{YYYY}.bin    (direct-access float32, RECL=4*NX*NY, one record per
                                           output step; needs map_dir/params.txt for the grid)

    Binary is the form CaMa's own downscaling utility consumes, so a KI that can only read the
    NetCDF form cannot post-process a run that was set up for flood-extent downscaling.

    Returns (data(ntime, ny, nx) float32 with RMIS/NaN -> NaN, times(ntime) datetime64, lats, lons)
    or None when neither file exists.
    """
    nc_path = os.path.join(output_dir, f"o_{var}{year}.nc")
    bin_path = os.path.join(output_dir, f"{var}{year}.bin")

    if os.path.isfile(nc_path):
        ds = open_nc(nc_path)
        if var not in ds.data_vars:
            ds.close()
            print(f"  WARNING: Variable '{var}' not in {nc_path}")
            return None
        data = np.asarray(ds[var].values, dtype="float32")
        times = np.asarray(ds.time.values)
        lats = np.asarray(ds.lat.values, dtype=float)
        lons = np.asarray(ds.lon.values, dtype=float)
        ds.close()
    elif os.path.isfile(bin_path):
        if map_dir is None:
            raise ValueError(
                f"{bin_path} is binary CaMa output; --map_dir is required to know its grid "
                f"(nx, ny, west/east/south/north come from {os.path.join('<map_dir>', 'params.txt')})")
        p = read_map_params(map_dir)
        nx, ny = p["nx"], p["ny"]
        raw = np.fromfile(bin_path, dtype="float32")
        if raw.size % (nx * ny) != 0:
            raise ValueError(f"{bin_path}: {raw.size} floats is not a whole number of "
                             f"{nx}x{ny} records -- wrong map_dir? (dt_cama_003)")
        ntime = raw.size // (nx * ny)
        # one record = NX*NY floats with ix fastest (Fortran) == C-order (ny, nx)
        data = raw.reshape((ntime, ny, nx))
        times = np.asarray(_daily_times(year, ntime))
        lats, lons = p["lats"], p["lons"]
    else:
        print(f"  WARNING: neither {nc_path} nor {bin_path} found, skipping")
        return None

    data = np.where(np.abs(data) >= RMIS * 0.1, np.nan, data)
    return data, times, lats, lons


def _daily_times(year, ntime):
    """Daily time axis for binary output (IFRQ_OUT=24, first record = Jan 1 of `year`)."""
    import pandas as pd
    return pd.date_range(f"{year}-01-01", periods=ntime, freq="D").values


def find_nearest_cell_xy(lats, lons, target_lat, target_lon):
    """Nearest cell indices for plain lat/lon axes (works for both output forms)."""
    lat_idx = int(np.argmin(np.abs(lats - target_lat)))
    lon_idx = int(np.argmin(np.abs(lons - target_lon)))
    actual_lat, actual_lon = float(lats[lat_idx]), float(lons[lon_idx])
    dlat = (actual_lat - target_lat) * 111.0
    dlon = (actual_lon - target_lon) * 111.0 * np.cos(np.radians(target_lat))
    return lat_idx, lon_idx, actual_lat, actual_lon, float(np.sqrt(dlat**2 + dlon**2))


def extract_field(output_dir, variable, start_year, end_year, map_dir=None,
                  date_start=None, date_end=None, reduce="max", out_nc=None):
    """Reduce a variable over a DATE WINDOW to a single 2-D field.

    This is the shape a flood-extent validation needs: dag.yaml binds `fldfrc`/`fldare` to
    gfd_v1_4_global, whose event product is a single composite max-extent raster over the event
    window -- so the model side must be the same window reduced the same way (reduce='max').
    The pre-existing --spatial_stats mode collapses each timestep to domain SCALARS and therefore
    cannot be compared against a flood-extent field at all.

    Returns dict(field(ny,nx), lats, lons, n_steps, date_start, date_end).
    """
    import pandas as pd

    acc = None
    n_steps = 0
    lats = lons = None
    used = []
    for year in range(start_year, end_year + 1):
        loaded = load_output(output_dir, variable, year, map_dir=map_dir)
        if loaded is None:
            continue
        data, times, lats, lons = loaded
        t = pd.to_datetime(pd.Series(times))
        keep = np.ones(len(t), dtype=bool)
        if date_start is not None:
            keep &= (t >= pd.Timestamp(date_start)).values
        if date_end is not None:
            keep &= (t <= pd.Timestamp(date_end)).values
        if not keep.any():
            continue
        sub = data[keep]
        used.extend(list(t[keep]))
        n_steps += int(keep.sum())
        if reduce == "max":
            step = np.nanmax(sub, axis=0)
            acc = step if acc is None else np.fmax(acc, step)
        elif reduce in ("mean", "sum"):
            step = np.nansum(sub, axis=0)
            acc = step if acc is None else acc + step
        else:
            raise ValueError(f"unknown reduce: {reduce}")
    if acc is None:
        return None
    if reduce == "mean":
        acc = acc / max(n_steps, 1)

    result = {"field": acc, "lats": lats, "lons": lons, "n_steps": n_steps,
              "date_start": str(min(used))[:10] if used else None,
              "date_end": str(max(used))[:10] if used else None,
              "variable": variable, "reduce": reduce}

    if out_nc:
        with xr.Dataset(
            {variable: (("lat", "lon"), acc)},
            coords={"lat": lats, "lon": lons},
            attrs={"reduce": reduce, "n_steps": n_steps,
                   "date_start": result["date_start"] or "", "date_end": result["date_end"] or "",
                   "source": "parse_cama_output.py extract_field"},
        ) as ds_out:
            ds_out.to_netcdf(out_nc)
        print(f"  Field written: {out_nc} ({reduce} of {variable} over {n_steps} steps, "
              f"{result['date_start']} .. {result['date_end']})")
    return result


# ---------------------------------------------------------------------------
# Flood-depth downscaling (15min -> 1min/30sec/...)
#
# Drives CaMa's OWN utility, etc/downscale_flddph/src/downscale_flddph_trib (Yamazaki), which:
#   * reads its low-res map from the hard-coded relative path ./map/  (F90 parameter mapdir),
#     so it must be run from a directory holding a `map` symlink -- we build a PRIVATE one per
#     call instead of mutating the shared etc/downscale_flddph/, which the sample scripts do and
#     which makes two concurrent runs silently downscale each other's map;
#   * takes the input flddph file, the output file and the RECORD NUMBER of the target day as
#     arguments, so it needs LOUTCDF=.FALSE. output ({var}{YYYY}.bin). It cannot read o_*.nc.
# ---------------------------------------------------------------------------

def _downscale_tool(cama_root=None):
    """Absolute path to the built downscaler; raises with the build command if it is missing."""
    root = cama_root or CAMA_ROOT
    exe = os.path.join(root, "etc", "downscale_flddph", "src", "downscale_flddph_trib")
    if not os.access(exe, os.X_OK):
        raise FileNotFoundError(
            f"downscaler not built: {exe}\n"
            f"       build it with: make -C {os.path.dirname(exe)}")
    return exe


def _days_in_year(year):
    return 366 if calendar.isleap(year) else 365


def downscale_flddph(output_dir, map_dir, start_year, end_year, start_month=1, end_month=12,
                     res="1min", west=None, east=None, south=None, north=None,
                     dest=None, jobs=8, cama_root=None):
    """Downscale daily flddph to the map's native high-resolution grid.

    Writes DEST/flood_{YYYYMMDD}.bin -- float32, (lx, ly) pixels with ix fastest (Fortran
    order), ROW 0 = NORTH edge (downscale_flddph_trib.F90: lat(iy)=north3-(iy-0.5)*csize),
    units metres of floodplain water depth.

    west/east/south/north default to the map's own domain (params.txt). Keep the window at
    least 1.25 deg (5 low-res grids) inside the map domain -- the downscaler pads the working
    array by gsize*5 and reads high-res tiles for the padded box.

    Returns a report dict (dest, files, n_files, lx, ly, res, window, records).
    """
    exe = _downscale_tool(cama_root)
    map_dir = os.path.abspath(map_dir)
    output_dir = os.path.abspath(output_dir)

    if res not in HIRES_PX_PER_DEG:
        raise ValueError(f"unknown resolution {res!r}; choose from {sorted(HIRES_PX_PER_DEG)}")
    if not os.path.isdir(os.path.join(map_dir, res)):
        raise FileNotFoundError(
            f"no {res} directory in {map_dir} -- re-run regionalization so combine_hires builds "
            f"the high-resolution tiles (dt_cama_011)")
    if not os.path.isfile(os.path.join(map_dir, res, "location.txt")):
        raise FileNotFoundError(f"{map_dir}/{res}/location.txt missing (tile index for {res})")

    p = read_map_params(map_dir)
    west = p["west"] if west is None else float(west)
    east = p["east"] if east is None else float(east)
    south = p["south"] if south is None else float(south)
    north = p["north"] if north is None else float(north)

    npd = HIRES_PX_PER_DEG[res]
    lx = int(round((east - west) * npd))
    ly = int(round((north - south) * npd))
    if lx <= 0 or ly <= 0:
        raise ValueError(f"empty downscale window: lx={lx}, ly={ly}")

    # Record index of each day inside flddph{YYYY}.bin. The file starts at Jan 1 with one
    # record per output step, so IREC is the day-of-year -- but only if the run kept the
    # calendar this loop assumes. Gate on the file's OWN record count rather than trusting it:
    # a run with LLEAPYR=.FALSE. drops Feb 29 and every record after it would be off by one.
    nx, ny = p["nx"], p["ny"]
    rec_bytes = 4 * nx * ny
    year_files = {}
    for year in range(start_year, end_year + 1):
        bin_path = os.path.join(output_dir, f"flddph{year}.bin")
        if not os.path.isfile(bin_path):
            raise FileNotFoundError(
                f"{bin_path} not found. The run must be configured with "
                f"--output_format binary (LOUTCDF=.FALSE.) and CVARSOUT must include flddph.")
        nrec = os.path.getsize(bin_path) // rec_bytes
        expected = _days_in_year(year)
        if nrec != expected:
            raise ValueError(
                f"{bin_path} holds {nrec} records but {year} has {expected} days on the "
                f"standard calendar. Day-of-year record indexing would be wrong -- check "
                f"IFRQ_OUT (daily output assumed) and LLEAPYR before downscaling.")
        year_files[year] = bin_path

    dest = os.path.abspath(dest) if dest else os.path.join(output_dir, f"downscale_{res}")
    os.makedirs(dest, exist_ok=True)

    # Private scratch dir supplying the ./map that the F90 hard-codes.
    work = os.path.join(dest, ".work")
    os.makedirs(work, exist_ok=True)
    map_link = os.path.join(work, "map")
    if os.path.islink(map_link) or os.path.exists(map_link):
        os.remove(map_link)
    os.symlink(map_dir, map_link)

    sdate = start_year * 10000 + start_month * 100 + 1
    edate = end_year * 10000 + end_month * 100 + 31

    jobs_list = []
    for year in range(start_year, end_year + 1):
        irec = 0
        for month in range(1, 13):
            for day in range(1, calendar.monthrange(year, month)[1] + 1):
                irec += 1
                cdate = year * 10000 + month * 100 + day
                if sdate <= cdate <= edate:
                    jobs_list.append((cdate, year_files[year], irec))
    if not jobs_list:
        raise ValueError(f"no days in the requested window "
                         f"{start_year}-{start_month:02d} .. {end_year}-{end_month:02d}")

    print(f"  downscaling {len(jobs_list)} days -> {res} ({lx} x {ly} px), dest {dest}")
    failures = []
    running = []      # (proc, cdate, out_path, log_path, log_handle)

    def _finish(entry):
        """Wait for one job, then PROVE it produced a correctly sized file.

        The downscaler exits 0 and writes nothing when a high-res tile is missing (it only
        prints 'no data: <file>'), so a rc check alone would report a silent success.
        """
        proc, cdate, out_path, log_path, log_handle = entry
        rc = proc.wait()
        log_handle.close()
        problem = None
        if rc != 0:
            problem = f"exit {rc}"
        elif not os.path.isfile(out_path):
            problem = "no output file written"
        elif os.path.getsize(out_path) != 4 * lx * ly:
            problem = f"{os.path.getsize(out_path)} bytes, expected {4 * lx * ly}"
        if problem is None:
            os.remove(log_path)
            return
        try:
            with open(log_path, "rb") as lf:
                tail = lf.read()[-400:].decode("utf-8", "replace").replace("\n", " | ")
        except OSError:
            tail = ""
        failures.append(f"{cdate}: {problem} :: {tail}")

    for cdate, bin_path, irec in jobs_list:
        out_path = os.path.join(dest, f"flood_{cdate}.bin")
        log_path = os.path.join(work, f"downscale_{cdate}.log")
        # stdout to a FILE, not a pipe: the utility prints one line per high-res tile and a
        # pipe nobody drains would deadlock the whole pool.
        log_handle = open(log_path, "wb")
        proc = subprocess.Popen(
            [exe, f"{west}", f"{east}", f"{south}", f"{north}", res,
             bin_path, out_path, str(irec)],
            cwd=work, stdout=log_handle, stderr=subprocess.STDOUT)
        running.append((proc, cdate, out_path, log_path, log_handle))
        if len(running) >= max(1, int(jobs)):
            _finish(running.pop(0))
    while running:
        _finish(running.pop(0))

    if failures:
        raise RuntimeError("downscaling failed for %d of %d day(s):\n  %s"
                           % (len(failures), len(jobs_list), "\n  ".join(failures[:10])))

    # only the files THIS call produced -- dest may still hold an earlier window's output
    files = sorted(f"flood_{cdate}.bin" for cdate, _bin, _irec in jobs_list)
    report = {"dest": dest, "files": files, "n_files": len(files), "lx": lx, "ly": ly,
              "res": res, "west": west, "east": east, "south": south, "north": north,
              "perm_water_floor_m": PERM_WATER_FLOOR_M}
    print(f"  DONE: {len(files)} daily files in {dest}")
    print(f"        float32 {lx} x {ly} (ix fastest), row 0 = north, metres")
    print(f"        threshold ABOVE {PERM_WATER_FLOOR_M} m for flood extent (dt_cama_015)")
    return report


def read_downscaled_field(dest, west, east, south, north, res="1min", reduce="max",
                          date_start=None, date_end=None, out_nc=None):
    """Reduce the daily flood_{YYYYMMDD}.bin files in `dest` to one 2-D field.

    Same contract as extract_field(), but on the high-resolution downscaled grid, so the result
    is directly comparable to gfd_flood_obs.py's aggregated observation (both are row 0 = north,
    col 0 = west, cell centres). reduce='max' is the one that matches a GFD composite event
    raster; see gfd_flood_obs.py for why max, not a single day.
    """
    npd = HIRES_PX_PER_DEG[res]
    lx = int(round((east - west) * npd))
    ly = int(round((north - south) * npd))
    expect = 4 * lx * ly

    names = sorted(f for f in os.listdir(dest) if f.startswith("flood_") and f.endswith(".bin"))
    if not names:
        raise FileNotFoundError(f"no flood_*.bin in {dest} (run --downscale first)")

    def _keep(name):
        d = name[len("flood_"):-len(".bin")]
        iso = f"{d[0:4]}-{d[4:6]}-{d[6:8]}"
        if date_start and iso < str(date_start)[:10]:
            return None
        if date_end and iso > str(date_end)[:10]:
            return None
        return iso

    acc = None
    used = []
    for name in names:
        iso = _keep(name)
        if iso is None:
            continue
        path = os.path.join(dest, name)
        if os.path.getsize(path) != expect:
            raise ValueError(f"{path}: {os.path.getsize(path)} bytes, expected {expect} for a "
                             f"{lx}x{ly} {res} grid -- window/resolution do not match the files")
        day = np.fromfile(path, dtype="float32").reshape(ly, lx)   # row 0 = north
        day = np.where(np.abs(day) >= RMIS * 0.1, np.nan, day)
        used.append(iso)
        if reduce == "max":
            acc = day if acc is None else np.fmax(acc, day)
        elif reduce in ("mean", "sum"):
            acc = day if acc is None else acc + day
        else:
            raise ValueError(f"unknown reduce: {reduce}")
    if acc is None:
        raise ValueError(f"no flood_*.bin in {dest} inside {date_start} .. {date_end}")
    if reduce == "mean":
        acc = acc / len(used)

    lats = north - (np.arange(ly) + 0.5) / npd
    lons = west + (np.arange(lx) + 0.5) / npd
    result = {"field": acc, "lats": lats, "lons": lons, "n_steps": len(used),
              "date_start": min(used), "date_end": max(used),
              "variable": "flddph", "reduce": reduce, "res": res}

    if out_nc:
        with xr.Dataset(
            {"flddph": (("lat", "lon"), acc.astype("float32"))},
            coords={"lat": lats, "lon": lons},
            attrs={"reduce": reduce, "n_steps": len(used), "resolution_tag": res,
                   "date_start": result["date_start"], "date_end": result["date_end"],
                   "perm_water_floor_m": PERM_WATER_FLOOR_M,
                   "source": "parse_cama_output.py read_downscaled_field"},
        ) as ds_out:
            ds_out.to_netcdf(out_nc)
        print(f"  Field written: {out_nc} ({reduce} of downscaled flddph over {len(used)} days, "
              f"{result['date_start']} .. {result['date_end']})")
    return result


def find_nearest_cell(ds, target_lat, target_lon):
    """Find the nearest CaMa-Flood grid cell to the target coordinates.

    Returns (lat_idx, lon_idx, actual_lat, actual_lon, distance_km).
    """
    lats = ds.lat.values
    lons = ds.lon.values

    # Simple nearest-neighbor (fine for 0.25-degree resolution)
    lat_idx = int(np.argmin(np.abs(lats - target_lat)))
    lon_idx = int(np.argmin(np.abs(lons - target_lon)))

    actual_lat = float(lats[lat_idx])
    actual_lon = float(lons[lon_idx])

    # Approximate distance in km
    dlat = (actual_lat - target_lat) * 111.0
    dlon = (actual_lon - target_lon) * 111.0 * np.cos(np.radians(target_lat))
    dist_km = np.sqrt(dlat**2 + dlon**2)

    return lat_idx, lon_idx, actual_lat, actual_lon, dist_km


def extract_point_timeseries(output_dir, variables, target_lat, target_lon,
                              start_year, end_year, map_dir=None):
    """Extract time series at a point for one or more variables (NetCDF or binary output)."""
    results = {}

    for var in variables:
        all_times = []
        all_values = []
        act_lat = act_lon = None
        reported = False

        for year in range(start_year, end_year + 1):
            loaded = load_output(output_dir, var, year, map_dir=map_dir)
            if loaded is None:
                continue
            data, times, lats, lons = loaded

            lat_idx, lon_idx, act_lat, act_lon, dist = find_nearest_cell_xy(
                lats, lons, target_lat, target_lon
            )

            if not reported:
                print(f"  Variable: {var}")
                print(f"    Target:  ({target_lat:.4f}, {target_lon:.4f})")
                print(f"    Nearest: ({act_lat:.4f}, {act_lon:.4f}), distance: {dist:.1f} km")
                if dist > 30:
                    print(f"    WARNING: Nearest cell is {dist:.1f} km away. "
                          f"Check coordinates.")
                reported = True

            all_times.extend(times)
            all_values.extend(data[:, lat_idx, lon_idx])

        if all_values:
            results[var] = {
                "times": all_times,
                "values": np.array(all_values, dtype=float),
                "lat": act_lat,
                "lon": act_lon,
            }

    return results


def compute_statistics(values, var_name):
    """Compute summary statistics for a time series."""
    valid = values[~np.isnan(values)]
    if len(valid) == 0:
        return {}

    stats = {
        "n_timesteps": len(valid),
        "mean": float(np.mean(valid)),
        "std": float(np.std(valid)),
        "min": float(np.min(valid)),
        "max": float(np.max(valid)),
        "median": float(np.median(valid)),
        "p95": float(np.percentile(valid, 95)),
        "p99": float(np.percentile(valid, 99)),
    }

    # Variable-specific metrics
    if var_name == "outflw":
        stats["peak_discharge_m3s"] = stats["max"]
        stats["mean_discharge_m3s"] = stats["mean"]
        # Days above threshold (flood days)
        if stats["mean"] > 0:
            flood_threshold = stats["mean"] * 2.0
            stats["flood_days_2x_mean"] = int(np.sum(valid > flood_threshold))
    elif var_name == "flddph":
        stats["max_flood_depth_m"] = stats["max"]
        stats["flooded_days"] = int(np.sum(valid > 0.01))  # >1cm threshold
    elif var_name == "fldfrc":
        stats["max_flood_fraction"] = stats["max"]
        stats["mean_flood_fraction"] = stats["mean"]

    return stats


def extract_spatial_stats(output_dir, variable, start_year, end_year, map_dir=None):
    """Compute spatial statistics over the entire domain for each time step."""
    print(f"\n  Spatial statistics for: {variable}")

    all_stats = []

    for year in range(start_year, end_year + 1):
        loaded = load_output(output_dir, variable, year, map_dir=map_dir)
        if loaded is None:
            continue
        data, times, _lats, _lons = loaded

        for t in range(len(times)):
            snapshot = data[t, :, :]
            valid = snapshot[~np.isnan(snapshot)]
            if len(valid) == 0:
                continue

            stat = {
                "time": str(times[t])[:10],
                "spatial_mean": float(np.mean(valid)),
                "spatial_max": float(np.max(valid)),
                "spatial_min": float(np.min(valid)),
            }

            if variable == "flddph":
                stat["flooded_cells"] = int(np.sum(valid > 0.01))
                stat["total_cells"] = len(valid)
                stat["flooded_fraction"] = stat["flooded_cells"] / stat["total_cells"]
            elif variable == "outflw":
                stat["max_discharge_m3s"] = stat["spatial_max"]

            all_stats.append(stat)

    return all_stats


def write_csv(results, csv_path):
    """Write extracted time series to CSV."""
    import csv

    # Determine all variable names
    var_names = list(results.keys())
    if not var_names:
        print("  No data to write")
        return

    # Use times from first variable
    first_var = var_names[0]
    times = results[first_var]["times"]

    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)

        # Header
        header = ["datetime"] + [f"{v}_value" for v in var_names]
        writer.writerow(header)

        # Data rows
        for i, t in enumerate(times):
            row = [str(t)[:10]]
            for var in var_names:
                if i < len(results[var]["values"]):
                    row.append(f"{results[var]['values'][i]:.6f}")
                else:
                    row.append("")
            writer.writerow(row)

    print(f"  CSV written: {csv_path} ({len(times)} rows)")


def write_spatial_csv(stats, csv_path):
    """Write spatial statistics to CSV."""
    import csv

    if not stats:
        print("  No spatial stats to write")
        return

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=stats[0].keys())
        writer.writeheader()
        writer.writerows(stats)

    print(f"  Spatial stats CSV: {csv_path} ({len(stats)} rows)")


def main():
    parser = argparse.ArgumentParser(
        description="Parse CaMa-Flood output: extract time series and compute statistics.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Variables:
  outflw   River discharge (m3/s) -- primary validation variable
  rivdph   River channel water depth (m)
  sfcelv   Water surface elevation (m ASL)
  flddph   Floodplain inundation depth (m)
  fldfrc   Floodplain inundation fraction (0-1)
  rivsto   River channel storage (m3)

Flood extent (fldfrc / fldare) needs the downscaling modes, not --spatial_stats:
  --downscale       flddph{YYYY}.bin -> flood_{YYYYMMDD}.bin on the map's <res> grid
  --downscaled_dir  those files -> one 2-D field, comparable to gfd_flood_obs.py output
The tools/downscale/*.sh symlinks are dead macOS scripts (dt_cama_016); use these instead.
"""
    )
    parser.add_argument("--output_dir",
                        help="CaMa-Flood output directory containing o_*.nc / *.bin files "
                             "(required except in --downscaled_dir mode)")
    parser.add_argument("--variable",
                        help="Variable(s) to extract (comma-separated, e.g. outflw,flddph)")
    parser.add_argument("--lat", type=float, help="Target latitude for point extraction")
    parser.add_argument("--lon", type=float, help="Target longitude for point extraction")
    parser.add_argument("--start_year", type=int)
    parser.add_argument("--end_year", type=int)
    parser.add_argument("--csv", help="Output CSV file path")
    parser.add_argument("--spatial_stats", action="store_true",
                        help="Compute spatial statistics instead of point extraction")
    parser.add_argument("--obs_csv", help="Observed discharge CSV for comparison (date,Q columns)")
    parser.add_argument("--map_dir",
                        help="CaMa map directory (map/{basin}_15min). REQUIRED when the run used "
                             "LOUTCDF=.FALSE. (binary {var}{YYYY}.bin output) -- the grid comes "
                             "from <map_dir>/params.txt")
    parser.add_argument("--field", action="store_true",
                        help="Reduce the variable over a date window to a single 2-D field "
                             "(for flood-extent / spatial-snapshot validation)")
    parser.add_argument("--field_reduce", choices=["max", "mean", "sum"], default="max",
                        help="Reduction applied over the window in --field mode (default: max, "
                             "which matches a GFD composite max-extent event raster)")
    parser.add_argument("--date_start", help="Window start YYYY-MM-DD (--field mode)")
    parser.add_argument("--date_end", help="Window end YYYY-MM-DD (--field mode)")
    parser.add_argument("--field_out", help="Output NetCDF path for the reduced field")

    # --- flood-extent downscaling (replaces the dead tools/downscale/*.sh symlinks) ---
    parser.add_argument("--downscale", action="store_true",
                        help="Downscale flddph to the map's high-resolution grid using CaMa's "
                             "own downscale_flddph_trib. Needs binary output and --map_dir.")
    parser.add_argument("--downscaled_dir",
                        help="Read flood_{YYYYMMDD}.bin produced by --downscale and reduce them "
                             "to one 2-D field (uses --field_reduce/--date_start/--date_end)")
    parser.add_argument("--res", default="1min", choices=sorted(HIRES_PX_PER_DEG),
                        help="Downscaling target resolution (must exist under <map_dir>/)")
    parser.add_argument("--start_month", type=int, default=1, help="--downscale window start month")
    parser.add_argument("--end_month", type=int, default=12, help="--downscale window end month")
    parser.add_argument("--west", type=float, help="Downscale window west (default: map domain)")
    parser.add_argument("--east", type=float, help="Downscale window east (default: map domain)")
    parser.add_argument("--south", type=float, help="Downscale window south (default: map domain)")
    parser.add_argument("--north", type=float, help="Downscale window north (default: map domain)")
    parser.add_argument("--downscale_dest",
                        help="Where to write flood_{YYYYMMDD}.bin (default <output_dir>/downscale_<res>)")
    parser.add_argument("--jobs", type=int, default=8,
                        help="Parallel downscaling processes (default 8)")

    args = parser.parse_args()

    # --- downscaled-field mode: no CaMa output dir involved, just the flood_*.bin files ---
    if args.downscaled_dir:
        missing = [n for n in ("west", "east", "south", "north")
                   if getattr(args, n) is None]
        if missing:
            print(f"ERROR: --downscaled_dir needs the window it was produced with: "
                  f"missing --{', --'.join(missing)}")
            sys.exit(1)
        try:
            got = read_downscaled_field(args.downscaled_dir, args.west, args.east, args.south,
                                        args.north, res=args.res, reduce=args.field_reduce,
                                        date_start=args.date_start, date_end=args.date_end,
                                        out_nc=args.field_out)
        except (OSError, ValueError) as exc:
            print(f"ERROR: {exc}")
            sys.exit(1)
        fld = got["field"]
        fin = fld[np.isfinite(fld)]
        wet = int((fin > PERM_WATER_FLOOR_M).sum())
        print(f"  downscaled flddph ({args.field_reduce} over {got['n_steps']} days, "
              f"{got['date_start']} .. {got['date_end']}): "
              f"min {fin.min():.4g}, max {fin.max():.4g}, "
              f"pixels > {PERM_WATER_FLOOR_M} m: {wet}/{fin.size}")
        return

    if not args.output_dir:
        print("ERROR: --output_dir is required")
        sys.exit(1)
    if args.start_year is None or args.end_year is None:
        print("ERROR: --start_year and --end_year are required")
        sys.exit(1)

    if args.downscale:
        if not args.map_dir:
            print("ERROR: --downscale requires --map_dir (the downscaler reads its low-res map "
                  "and the high-resolution tiles from there)")
            sys.exit(1)
        if not os.path.isdir(args.output_dir):
            print(f"ERROR: Output directory not found: {args.output_dir}")
            sys.exit(1)
        try:
            downscale_flddph(args.output_dir, args.map_dir, args.start_year, args.end_year,
                             start_month=args.start_month, end_month=args.end_month,
                             res=args.res, west=args.west, east=args.east, south=args.south,
                             north=args.north, dest=args.downscale_dest, jobs=args.jobs)
        except (OSError, ValueError, RuntimeError) as exc:
            print(f"ERROR: {exc}")
            sys.exit(1)
        return

    if not args.variable:
        print("ERROR: --variable is required")
        sys.exit(1)

    variables = [v.strip() for v in args.variable.split(",")]

    print(f"{'='*60}")
    print(f"  CaMa-Flood Output Parser")
    print(f"  Directory:  {args.output_dir}")
    print(f"  Variables:  {variables}")
    print(f"  Period:     {args.start_year}-{args.end_year}")
    print(f"{'='*60}")

    if not os.path.isdir(args.output_dir):
        print(f"ERROR: Output directory not found: {args.output_dir}")
        sys.exit(1)

    # List available output files
    out_files = sorted([f for f in os.listdir(args.output_dir)
                        if (f.endswith(".nc") and f.startswith("o_")) or f.endswith(".bin")])
    print(f"\n  Available output files: {len(out_files)}")
    available_vars = set()
    for f in out_files:
        # o_{var}{year}.nc  (LOUTCDF=.TRUE.)  or  {var}{year}.bin  (LOUTCDF=.FALSE.)
        base = f[2:] if f.startswith("o_") else f
        base = base.rsplit(".", 1)[0]
        var = base.rstrip("0123456789")
        if var and not var.startswith("restart"):
            available_vars.add(var)
    print(f"  Available variables: {sorted(available_vars)}")

    if args.field:
        for var in variables:
            out_nc = args.field_out
            if out_nc and len(variables) > 1:
                out_nc = out_nc.replace(".nc", f"_{var}.nc")
            res = extract_field(args.output_dir, var, args.start_year, args.end_year,
                                map_dir=args.map_dir, date_start=args.date_start,
                                date_end=args.date_end, reduce=args.field_reduce,
                                out_nc=out_nc)
            if res is None:
                print(f"  ERROR: no data for {var} in the requested window")
                sys.exit(1)
            fld = res["field"]
            fin = fld[np.isfinite(fld)]
            print(f"  {var} ({args.field_reduce} over {res['n_steps']} steps, "
                  f"{res['date_start']} .. {res['date_end']}): "
                  f"min {fin.min():.4g}, max {fin.max():.4g}, "
                  f"cells>0 {int((fin > 0).sum())}/{fin.size}")
    elif args.spatial_stats:
        # Spatial statistics mode
        for var in variables:
            stats = extract_spatial_stats(args.output_dir, var,
                                          args.start_year, args.end_year,
                                          map_dir=args.map_dir)
            if stats:
                # Print summary
                max_vals = [s.get("spatial_max", 0) for s in stats]
                print(f"\n  {var} spatial summary:")
                print(f"    Time steps: {len(stats)}")
                print(f"    Overall max: {max(max_vals):.2f}")

                if args.csv:
                    csv_path = args.csv.replace(".csv", f"_{var}_spatial.csv")
                    write_spatial_csv(stats, csv_path)
    else:
        # Point extraction mode
        if args.lat is None or args.lon is None:
            print("ERROR: --lat and --lon required for point extraction")
            print("       Use --spatial_stats for domain-wide statistics")
            sys.exit(1)

        results = extract_point_timeseries(args.output_dir, variables,
                                            args.lat, args.lon,
                                            args.start_year, args.end_year,
                                            map_dir=args.map_dir)

        # Print statistics
        for var, data in results.items():
            stats = compute_statistics(data["values"], var)
            print(f"\n  {var} statistics at ({data['lat']:.4f}, {data['lon']:.4f}):")
            for key, val in stats.items():
                if isinstance(val, float):
                    print(f"    {key}: {val:.4f}")
                else:
                    print(f"    {key}: {val}")

        # Write CSV
        if args.csv and results:
            write_csv(results, args.csv)

        # Compare with observations if provided
        if args.obs_csv and "outflw" in results:
            compare_with_obs(results["outflw"], args.obs_csv)


def compare_with_obs(sim_data, obs_csv_path):
    """Compare simulated discharge with observed data."""
    import csv

    print(f"\n  --- Comparison with Observations ---")
    print(f"  Observed data: {obs_csv_path}")

    if not os.path.isfile(obs_csv_path):
        print(f"  ERROR: Observed CSV not found: {obs_csv_path}")
        return

    # Read observed data
    obs_dates = []
    obs_values = []
    with open(obs_csv_path, "r") as f:
        reader = csv.reader(f)
        header = next(reader)
        for row in reader:
            try:
                date = row[0].strip()
                val = float(row[1])
                obs_dates.append(date)
                obs_values.append(val)
            except (IndexError, ValueError):
                continue

    obs_values = np.array(obs_values)
    print(f"  Observed: {len(obs_values)} values, "
          f"range [{obs_values.min():.1f}, {obs_values.max():.1f}] m3/s")

    # Match dates between sim and obs
    sim_times = sim_data["times"]
    sim_values = sim_data["values"]

    # Convert sim times to date strings
    sim_date_strs = [str(t)[:10] for t in sim_times]

    matched_sim = []
    matched_obs = []
    matched_dates = []

    for i, date in enumerate(obs_dates):
        if date in sim_date_strs:
            sim_idx = sim_date_strs.index(date)
            matched_sim.append(sim_values[sim_idx])
            matched_obs.append(obs_values[i])
            matched_dates.append(date)

    if len(matched_sim) < 10:
        print(f"  WARNING: Only {len(matched_sim)} matching dates. Cannot compute metrics.")
        return

    matched_sim = np.array(matched_sim)
    matched_obs = np.array(matched_obs)

    # Metrics come from the SHARED, deterministic implementation -- never hand-rolled here.
    # The local re-implementations this replaced silently differed from the platform standard
    # (population vs sample std in KGE) and, more importantly, produced NO evidence capture, so
    # the number could not be re-derived from the scored series.
    from ki_tools_common.metrics import all_metrics
    m = all_metrics(matched_obs, matched_sim, dates=matched_dates, label="headline",
                    meta={"unit": "m3/s", "obs_source": obs_csv_path})

    print(f"\n  Performance Metrics ({len(matched_sim)} matched days):")
    print(f"    NSE:   {m['NSE']:.4f}")
    print(f"    PBIAS: {m['PBIAS']:.2f}%")
    print(f"    KGE:   {m['KGE']:.4f}")
    print(f"    r:     {m['r']:.4f}")
    print(f"    RMSE:  {m['RMSE']:.4f}")

    if m["NSE"] < 0:
        print("    NOTE: NSE < 0 means model performs worse than mean observed.")
    elif m["NSE"] > 0.5:
        print("    NOTE: NSE > 0.5 is generally considered acceptable.")
    return m


if __name__ == "__main__":
    main()
