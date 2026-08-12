#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
============================================
Tool ID:      build_summa_forcing_from_reanalysis
Stage:        s2_forcing_prep
Description:  Build per-year SUMMA forcing NetCDF (time, hru) from a gridded
              reanalysis archive (CMFD) for an arbitrary GRU/HRU domain.

              The sibling tool convert_vic_forcing_to_summa.py only accepts
              --vic_forcing_dir, so building SUMMA forcing without it required
              a full VIC run upstream purely to produce forcing. This tool
              reads the reanalysis archive directly.

Inputs:
  - ATTRIBUTES_NC: SUMMA local attributes NetCDF. Supplies hruId, latitude,
    longitude and elevation. The hruId ORDER here is canonical -- every
    downstream tool must match it.
  - SOURCE:        Reanalysis archive identifier (currently 'cmfd').
  - START_YEAR / END_YEAR: inclusive year range.

Outputs:
  - <output_dir>/forcing_YYYY.nc  one file per year, all 7 SUMMA forcing
    variables on a (time, hru) layout, carrying data_step.
  - <output_dir>/forcingFileList.txt  file names in chronological order.
    NOTE (dt_032): this list is written next to the .nc files because
    output_dir is the only directory this tool is given, but SUMMA reads the
    list from **settingsPath**, not forcingPath
    (`ffile_info.f90:86  infile = trim(SETTINGS_PATH)//trim(FORCING_FILELIST)`)
    -- only the .nc names *inside* it resolve against forcingPath. Do NOT
    hand-copy it: `s6_execution/create_file_manager.py` owns that contract and
    places the list in settingsPath for you (it is the one tool that knows both
    paths). Point --forcing_path at this directory and it does the rest.

Conventions this tool is responsible for
----------------------------------------
* TIME STAMPS ARE PERIOD-ENDING (shared_specs.summa.input.forcing_files.
  time_stamp). The first record of a year is stamped at data_step, NOT at 0.
  The reanalysis loader returns interval-START stamps, so every stamp is
  shifted forward by one step. Writing `np.arange(n_steps) * dt` instead --
  which discards the loader's real dates and puts record 0 at the period
  start -- shifts the entire forcing series half a step early against the
  observations.
* DATA_STEP must equal the true forcing timestep (dt_003): 10800 s for
  3-hourly CMFD, and is written into every file so it can be verified rather
  than assumed.
* airpres is Pa, not kPa (dt_004).

Resumability
------------
A year is SKIPPED only if forcing_YYYY.nc opens cleanly AND carries the
expected n_hru AND the expected data_step AND the canonical hruId order AND
period-ending time stamps. Checking existence alone silently accepts files
written under an older, wrong convention.

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta

import numpy as np

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

EXIT_OK, EXIT_INPUT, EXIT_PROCESS, EXIT_OUTPUT = 0, 1, 2, 3

# SUMMA forcing variable -> (loader key, units attribute)
FORCING_VARS = [
    ("pptrate",  "prec_kgm2s", "kg m-2 s-1"),
    ("airtemp",  "temp_k",     "K"),
    ("SWRadAtm", "srad_wm2",   "W m-2"),
    ("LWRadAtm", "lrad_wm2",   "W m-2"),
    ("windspd",  "wind_ms",    "m s-1"),
    ("airpres",  "pres_pa",    "Pa"),
    ("spechum",  "shum_kgkg",  "kg kg-1"),
]

# Native timestep of each archive (dt_003). Declared up front so the resume
# check can run on the FIRST year too -- deriving it from the loader would mean
# year one could never be skipped -- and so a loader returning a different step
# is caught rather than silently written into data_step.
SOURCE_DT = {"cmfd": 10800}

# Physical plausibility gates. A year that violates these is a processing
# error, not something to write out and discover later as a null metric.
RANGES = {
    "pptrate":  (0.0, 0.05),
    "airtemp":  (180.0, 340.0),
    "SWRadAtm": (0.0, 1500.0),
    "LWRadAtm": (40.0, 700.0),
    "windspd":  (0.0, 80.0),
    "airpres":  (30000.0, 110000.0),
    "spechum":  (0.0, 0.06),
}

# CMFD V0200 SRad carries rare spurious spikes over the Tibetan Plateau
# (probed 1980-1990 over this domain: none in 1980-82, then up to 2701 W/m2
# and at most 0.041% of a year's values in 1983-1990). A 3-hour MEAN can
# never exceed top-of-atmosphere horizontal irradiance at perihelion
# (~1410 W/m2), so anything above SW_CEILING_WM2 is an archive artifact,
# not weather. Spot artifacts are clipped WITH an audit trail (log +
# provenance); a widespread exceedance means a units/loader error and
# aborts instead of clipping. The RANGES gate above stays untouched.
SW_CEILING_WM2 = 1410.0
SW_QC_MAX_FRAC = 0.005

# RANGES above is the RAW-archive plausibility bound. POST_QC_MAX is the
# stricter bound every file this tool WRITES or ACCEPTS must already meet,
# i.e. the post-QC contract. Without it a cached year whose SWRadAtm max
# lands in the 1410-1500 band passes the range check and is silently skipped
# on resume, carrying a known CMFD spike artifact into SUMMA's energy
# balance. RANGES itself is deliberately NOT loosened or altered.
POST_QC_MAX = {"SWRadAtm": SW_CEILING_WM2}

# Global attributes stamped by write_year() on every QC-aware file. A file
# lacking them predates the shortwave QC step and must be rebuilt, not trusted.
REQUIRED_PROVENANCE_ATTRS = ("sw_qc",)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

def read_attributes(attributes_nc):
    """Read the canonical HRU list from attributes.nc."""
    from netCDF4 import Dataset

    with Dataset(attributes_nc) as ds:
        for name in ("hruId", "latitude", "longitude", "elevation"):
            if name not in ds.variables:
                raise KeyError(f"attributes.nc is missing required variable '{name}'")
        hru_id = np.asarray(ds.variables["hruId"][:]).astype("int64").ravel()
        lat = np.asarray(ds.variables["latitude"][:], dtype=float).ravel()
        lon = np.asarray(ds.variables["longitude"][:], dtype=float).ravel()
        elev = np.asarray(ds.variables["elevation"][:], dtype=float).ravel()

    if not (hru_id.size == lat.size == lon.size == elev.size):
        raise ValueError("attributes.nc hruId/latitude/longitude/elevation "
                         "have inconsistent lengths")
    if hru_id.size == 0:
        raise ValueError("attributes.nc contains no HRUs")

    # dt_031: a domain built with the old silent DEM fallback has elevation 0.0
    # everywhere, which makes any lapse correction warm a high basin by tens of
    # degrees. Refuse rather than propagate it.
    if np.all(elev == 0.0):
        raise ValueError(
            "Every HRU elevation in attributes.nc is 0.0 -- the domain was "
            "built with the silent DEM fallback (dt_031). Rebuild s1 first.")
    if not np.all(np.isfinite(elev)):
        raise ValueError("attributes.nc contains non-finite elevations")

    return hru_id, lat, lon, elev


# ---------------------------------------------------------------------------
# Resumability
# ---------------------------------------------------------------------------

def year_is_complete(path, year, n_hru, expected_dt, expected_hru_id):
    """True if *path* is a usable forcing file for *year*.

    Verifies the full contract, not just existence: shape, data_step, hruId
    order, period-ending time stamps and variable presence. Any mismatch means
    the file was written by a different (or older, wrong) code path and must be
    rebuilt.
    """
    if not os.path.isfile(path):
        return False, "absent"

    try:
        from netCDF4 import Dataset
        with Dataset(path) as ds:
            if "hru" not in ds.dimensions or "time" not in ds.dimensions:
                return False, "missing time/hru dimension"
            if len(ds.dimensions["hru"]) != n_hru:
                return False, (f"n_hru {len(ds.dimensions['hru'])} != expected {n_hru}")

            if "data_step" not in ds.variables:
                return False, "no data_step variable"
            dt_s = float(np.asarray(ds.variables["data_step"][:]).ravel()[0])
            if abs(dt_s - expected_dt) > 1e-6:
                return False, f"data_step {dt_s} != expected {expected_dt}"

            if "hruId" not in ds.variables:
                return False, "no hruId variable"
            got_id = np.asarray(ds.variables["hruId"][:]).astype("int64").ravel()
            if got_id.size != expected_hru_id.size or not np.array_equal(got_id, expected_hru_id):
                return False, "hruId order does not match attributes.nc"

            for vname, _, _ in FORCING_VARS:
                if vname not in ds.variables:
                    return False, f"missing variable {vname}"

            tvar = ds.variables["time"]
            tvals = np.asarray(tvar[:], dtype=float).ravel()
            if tvals.size == 0:
                return False, "empty time axis"

            # Period-ending check: offsets must start at one full step past the
            # epoch-anchored year start and end exactly on the year boundary.
            base = _epoch_from_units(getattr(tvar, "units", ""))
            if base is None:
                return False, "unparseable time units"
            year_start = datetime(year, 1, 1)
            offset0 = (year_start - base).total_seconds() + expected_dt
            if abs(tvals[0] - offset0) > 1e-3:
                return False, (
                    f"time[0]={tvals[0]:.0f}s is not period-ending "
                    f"(expected {offset0:.0f}s = year start + one data_step)")

            n_expected = int(round(
                ((datetime(year + 1, 1, 1) - year_start).total_seconds()) / expected_dt))
            if tvals.size != n_expected:
                return False, f"n_steps {tvals.size} != expected {n_expected}"

            # A correct first stamp and a correct count do not imply a correct
            # axis: a duplicated stamp paired with a gap satisfies both. Require
            # every interior step to be exactly one data_step.
            if tvals.size > 1:
                d = np.diff(tvals)
                bad = np.nonzero(np.abs(d - expected_dt) > 1e-3)[0]
                if bad.size:
                    i = int(bad[0])
                    return False, (
                        f"time axis not contiguous at index {i}: step "
                        f"{d[i]:.0f}s != data_step {expected_dt:.0f}s "
                        f"({bad.size} irregular step(s) total)")
    except Exception as exc:
        return False, f"unreadable ({exc})"

    return True, "complete"


def _epoch_from_units(units):
    """Parse 'seconds since YYYY-MM-DD[ HH:MM[:SS]]' into a datetime."""
    if "since" not in units:
        return None
    stamp = units.split("since", 1)[1].strip().replace("T", " ")
    stamp = stamp.split("+")[0].strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(stamp, fmt)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Lapse correction (opt-in)
# ---------------------------------------------------------------------------

def apply_lapse(data, hru_elev, ref_elev, lapse_rate):
    """Adjust temperature and pressure from the reanalysis reference elevation
    to the HRU elevation.

    Humidity is then clamped below saturation at the corrected state so the
    correction can never produce supersaturated air.
    """
    dz = (hru_elev - ref_elev)[None, :]          # (1, hru), metres
    t_old = data["temp_k"]
    t_new = t_old + lapse_rate * dz

    # Hypsometric adjustment on the layer mean temperature.
    g, r_d = 9.80665, 287.058
    t_mean = np.maximum(0.5 * (t_old + t_new), 150.0)
    data["pres_pa"] = data["pres_pa"] * np.exp(-g * dz / (r_d * t_mean))
    data["temp_k"] = t_new

    # Clamp q below saturation (Tetens over water, w.r.t. the new T and p).
    t_c = t_new - 273.15
    e_sat = 610.94 * np.exp(17.625 * t_c / (t_c + 243.04))
    q_sat = 0.622 * e_sat / np.maximum(data["pres_pa"] - 0.378 * e_sat, 1.0)
    data["shum_kgkg"] = np.minimum(data["shum_kgkg"], 0.99 * q_sat)
    return data


def read_reference_elevation(path, lat, lon):
    """Sample a reanalysis orography NetCDF at each HRU location."""
    import xarray as xr

    ds = None
    for eng in ("h5netcdf", None):
        try:
            ds = xr.open_dataset(path, engine=eng) if eng else xr.open_dataset(path)
            break
        except Exception:
            ds = None
    if ds is None:
        raise RuntimeError(f"could not open reference elevation file {path}")

    try:
        cands = [v for v in ds.data_vars
                 if str(v).lower() in ("elevation", "orog", "hgt", "z", "height", "dem")]
        if not cands:
            cands = list(ds.data_vars)
        da = ds[cands[0]]
        lat_name = next((d for d in da.dims if "lat" in str(d).lower()), None)
        lon_name = next((d for d in da.dims if "lon" in str(d).lower()), None)
        if lat_name is None or lon_name is None:
            raise RuntimeError("reference elevation file has no lat/lon dimensions")
        sel = da.sel({lat_name: xr.DataArray(lat, dims="hru"),
                      lon_name: xr.DataArray(lon, dims="hru")}, method="nearest")
        return np.asarray(sel.values, dtype=float).ravel()
    finally:
        ds.close()


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def write_year(path, year, hru_id, times_end, dt_s, data, provenance):
    """Write one SUMMA forcing file with period-ending time stamps."""
    from netCDF4 import Dataset, date2num

    n_time, n_hru = data["temp_k"].shape
    epoch = datetime(year, 1, 1)
    units = f"seconds since {epoch:%Y-%m-%d %H:%M:%S}"

    tmp = path + ".tmp"
    with Dataset(tmp, "w", format="NETCDF4") as ds:
        ds.createDimension("time", None)
        ds.createDimension("hru", n_hru)

        tv = ds.createVariable("time", "f8", ("time",))
        tv.units = units
        tv.calendar = "standard"
        tv.long_name = "time since time reference (period-ending)"
        tv[:] = date2num(list(times_end), units=units, calendar="standard")

        hv = ds.createVariable("hruId", "i8", ("hru",))
        hv.long_name = "hru id"
        hv[:] = hru_id

        dv = ds.createVariable("data_step", "f8")
        dv.units = "seconds"
        dv.long_name = "data step length in seconds"
        dv[:] = float(dt_s)

        for vname, key, vunits in FORCING_VARS:
            var = ds.createVariable(vname, "f8", ("time", "hru"),
                                    zlib=True, complevel=4)
            var.units = vunits
            var[:, :] = data[key]

        ds.data_step = float(dt_s)
        ds.time_stamp_convention = "period-ending"
        ds.history = (f"created {datetime.now():%Y-%m-%dT%H:%M:%S} by "
                      f"build_summa_forcing_from_reanalysis.py")
        for k, v in provenance.items():
            setattr(ds, k, str(v))

    os.replace(tmp, path)


def qc_shortwave(srad, year):
    """Clip physically impossible shortwave spikes, loudly.

    Returns (cleaned_array, n_clipped). Raises ValueError when more than
    SW_QC_MAX_FRAC of the year exceeds the ceiling -- that is a systematic
    error (units, loader), not a spot artifact, and must never be clipped
    into silence.
    """
    bad = srad > SW_CEILING_WM2
    n_bad = int(bad.sum())
    if n_bad == 0:
        return srad, 0
    frac = n_bad / srad.size
    vmax = float(srad.max())
    if frac > SW_QC_MAX_FRAC:
        raise ValueError(
            f"{year}: SWRadAtm > {SW_CEILING_WM2} W/m2 in {frac:.3%} of values "
            f"(max {vmax:.0f}) -- too widespread for a spot artifact; "
            f"suspect a units or loader error, refusing to clip")
    logger.warning(
        f"{year}: SW QC clipped {n_bad}/{srad.size} values ({frac:.5%}) above "
        f"{SW_CEILING_WM2} W/m2 (max {vmax:.0f}) -- known CMFD V0200 "
        f"spurious-spike artifact")
    return np.minimum(srad, SW_CEILING_WM2), n_bad


def validate_year_output(path, year, n_hru, dt_s, hru_id):
    """Post-write verification. Returns (ok, reason)."""
    ok, reason = year_is_complete(path, year, n_hru, dt_s, hru_id)
    if not ok:
        return False, reason
    try:
        from netCDF4 import Dataset
        with Dataset(path) as ds:
            # Acceptance must enforce the same contract write_year() promises.
            # A file without the QC provenance stamp was written by an older
            # code path and its shortwave was never screened.
            present = set(ds.ncattrs())
            for attr in REQUIRED_PROVENANCE_ATTRS:
                if attr not in present:
                    return False, (f"missing '{attr}' provenance attribute -- "
                                   f"file predates the shortwave QC step, "
                                   f"rebuild it")
            for vname, _, _ in FORCING_VARS:
                arr = np.asarray(ds.variables[vname][:], dtype=float)
                if not np.all(np.isfinite(arr)):
                    return False, f"{vname} contains non-finite values"
                lo, hi = RANGES[vname]
                # Accept only against the tighter of the raw bound and the
                # post-QC ceiling, so a 1410-1500 SWRadAtm artifact cannot be
                # skipped as "complete" on resume.
                hi = min(hi, POST_QC_MAX.get(vname, hi))
                if float(arr.min()) < lo or float(arr.max()) > hi:
                    return False, (f"{vname} range [{arr.min():.4g}, {arr.max():.4g}] "
                                   f"outside accepted [{lo}, {hi}]")
    except Exception as exc:
        return False, f"post-write read failed ({exc})"
    return True, "ok"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Build per-year SUMMA forcing (time, hru) from a gridded "
                    "reanalysis archive.")
    ap.add_argument("--attributes_nc", required=True,
                    help="SUMMA attributes.nc; defines the canonical hruId order.")
    ap.add_argument("--source", default="cmfd", choices=["cmfd"],
                    help="Reanalysis archive identifier.")
    ap.add_argument("--start_year", type=int, required=True)
    ap.add_argument("--end_year", type=int, required=True)
    ap.add_argument("--output_dir", required=True)
    ap.add_argument("--forcing_dir", default=None,
                    help="Override the archive root (default: loader's built-in).")
    ap.add_argument("--lapse_rate", type=float, default=-0.0065,
                    help="Temperature lapse rate in K/m (default -0.0065, the "
                         "standard environmental lapse). Applied only when "
                         "--reference_elev_nc is supplied.")
    ap.add_argument("--no_lapse", action="store_true",
                    help="Explicitly build WITHOUT lapse correction. Required "
                         "when --reference_elev_nc is omitted, so that a high "
                         "basin can never be built uncorrected by accident.")
    ap.add_argument("--reference_elev_nc", default=None,
                    help="Reanalysis orography NetCDF, used as the elevation the "
                         "archive values are valid at.")
    ap.add_argument("--force", action="store_true",
                    help="Rebuild every year even if a complete file exists.")
    args = ap.parse_args()

    if args.end_year < args.start_year:
        logger.error("--end_year is before --start_year")
        return EXIT_INPUT
    if not os.path.isfile(args.attributes_nc):
        logger.error(f"attributes.nc not found: {args.attributes_nc}")
        return EXIT_INPUT
    # No silent no-op: asking for a lapse correction without a reference
    # elevation is an input error, not something to quietly skip.
    if args.reference_elev_nc and args.no_lapse:
        logger.error("--no_lapse and --reference_elev_nc are mutually exclusive")
        return EXIT_INPUT
    if not args.reference_elev_nc and not args.no_lapse:
        logger.error(
            "No --reference_elev_nc supplied. Lapse correction would be silently "
            "skipped, and on a high-elevation domain that leaves airtemp/airpres "
            "valid at the archive's native elevation rather than the HRU's "
            "(dt_031). Pass --reference_elev_nc (with --lapse_rate) to correct, "
            "or --no_lapse to record that uncorrected forcing is intended.")
        return EXIT_INPUT
    if args.reference_elev_nc and not os.path.isfile(args.reference_elev_nc):
        logger.error(f"reference elevation file not found: {args.reference_elev_nc}")
        return EXIT_INPUT

    try:
        hru_id, lat, lon, elev = read_attributes(args.attributes_nc)
    except Exception as exc:
        logger.error(f"could not read attributes.nc: {exc}")
        return EXIT_INPUT
    n_hru = hru_id.size
    logger.info(f"Domain: {n_hru} HRUs, elevation {elev.min():.0f}-{elev.max():.0f} m")

    try:
        os.makedirs(args.output_dir, exist_ok=True)
    except OSError as exc:
        logger.error(f"cannot create output dir: {exc}")
        return EXIT_OUTPUT

    ref_elev = None
    if args.reference_elev_nc:
        try:
            ref_elev = read_reference_elevation(args.reference_elev_nc, lat, lon)
            logger.info(f"Lapse correction ON: {args.lapse_rate} K/m against "
                        f"reference elevation {ref_elev.min():.0f}-{ref_elev.max():.0f} m")
        except Exception as exc:
            logger.error(f"reference elevation read failed: {exc}")
            return EXIT_INPUT
    else:
        logger.warning("Lapse correction DISABLED by explicit --no_lapse: archive "
                       "values are used at their native elevation. airtemp and "
                       "airpres are NOT adjusted to the HRU elevation.")

    from ki_tools_common.load_forcing import load_subdaily_forcing_points

    latlons = list(zip(lat.tolist(), lon.tolist()))
    written, skipped = [], []
    expected_dt = SOURCE_DT[args.source]

    for year in range(args.start_year, args.end_year + 1):
        path = os.path.join(args.output_dir, f"forcing_{year}.nc")

        if not args.force:
            # Resume must apply the SAME bar as the post-write validator: a
            # cached year written before a QC/range fix (e.g. a forcing file
            # carrying the 1590 W/m2 CMFD spike) would pass a structure-only
            # check and carry the artifact into SUMMA.
            ok, why = validate_year_output(path, year, n_hru, expected_dt, hru_id)
            if ok:
                logger.info(f"{year}: complete, skipping")
                skipped.append(os.path.basename(path))
                continue
            if os.path.isfile(path):
                logger.warning(f"{year}: rebuilding -- cached file rejected ({why})")

        logger.info(f"{year}: loading {args.source} at {n_hru} points")
        try:
            pts = load_subdaily_forcing_points(
                args.source, latlons, year, year, forcing_dir=args.forcing_dir)
        except Exception as exc:
            logger.error(f"{year}: forcing load failed: {exc}")
            return EXIT_PROCESS

        if not pts or len(pts) != n_hru:
            logger.error(f"{year}: loader returned {len(pts) if pts else 0} points "
                         f"for {n_hru} HRUs")
            return EXIT_PROCESS

        dates = list(pts[0]["dates"])
        dt_s = int(pts[0]["timestep_seconds"])
        n_steps = len(dates)
        if n_steps == 0:
            logger.error(f"{year}: loader returned an empty time axis")
            return EXIT_PROCESS

        # dt_003: the declared step must be the real one.
        expected_steps = int(round(
            (datetime(year + 1, 1, 1) - datetime(year, 1, 1)).total_seconds() / dt_s))
        if n_steps != expected_steps:
            logger.error(f"{year}: got {n_steps} steps, expected {expected_steps} "
                         f"at dt={dt_s}s -- incomplete archive coverage")
            return EXIT_PROCESS
        if dt_s != expected_dt:
            logger.error(f"{year}: loader reports dt={dt_s}s but source "
                         f"'{args.source}' is declared at {expected_dt}s (dt_003)")
            return EXIT_PROCESS

        # Assemble (time, hru), preserving the attributes.nc HRU order.
        data = {}
        try:
            data["temp_k"] = np.stack(
                [np.asarray(p["temp_c"], dtype=float) + 273.15 for p in pts], axis=1)
            for key in ("prec_kgm2s", "srad_wm2", "lrad_wm2",
                        "wind_ms", "pres_pa", "shum_kgkg"):
                data[key] = np.stack(
                    [np.asarray(p[key], dtype=float) for p in pts], axis=1)
        except Exception as exc:
            logger.error(f"{year}: could not assemble forcing arrays: {exc}")
            return EXIT_PROCESS

        # CMFD SRad spike QC -- must run before the RANGES gate so a known
        # archive artifact is corrected on the record instead of killing the
        # build (or, worse, the gate being loosened to swallow it).
        try:
            data["srad_wm2"], n_sw_clipped = qc_shortwave(data["srad_wm2"], year)
        except ValueError as exc:
            logger.error(str(exc))
            return EXIT_PROCESS

        if ref_elev is not None:
            data = apply_lapse(data, elev, ref_elev, args.lapse_rate)

        # PERIOD-ENDING: the loader hands back interval-START stamps, so shift
        # each one forward by a full step. Using the loader's real dates (rather
        # than a synthetic arange) also keeps any archive gap visible above.
        times_end = [d + timedelta(seconds=dt_s) for d in dates]

        provenance = {
            "source": args.source,
            "source_dir": str(args.forcing_dir or "loader default"),
            "attributes_nc": os.path.abspath(args.attributes_nc),
            "lapse_correction": ("disabled" if ref_elev is None
                                 else f"{args.lapse_rate} K/m"),
            "sw_qc": (f"clipped {n_sw_clipped} values above "
                      f"{SW_CEILING_WM2} W/m2 (CMFD spike artifact)"
                      if n_sw_clipped else "no values above ceiling"),
        }

        try:
            write_year(path, year, hru_id, times_end, dt_s, data, provenance)
        except Exception as exc:
            logger.error(f"{year}: write failed: {exc}")
            return EXIT_OUTPUT

        ok, why = validate_year_output(path, year, n_hru, dt_s, hru_id)
        if not ok:
            logger.error(f"{year}: output validation FAILED: {why}")
            return EXIT_OUTPUT

        logger.info(f"{year}: wrote {n_steps} steps x {n_hru} HRUs (dt={dt_s}s)")
        written.append(os.path.basename(path))

    # File list for fileManager.txt, chronological.
    listing = sorted(set(written) | set(skipped))
    list_path = os.path.join(args.output_dir, "forcingFileList.txt")
    try:
        with open(list_path, "w") as fh:
            for name in listing:
                fh.write(name + "\n")
    except OSError as exc:
        logger.error(f"could not write forcingFileList.txt: {exc}")
        return EXIT_OUTPUT

    if not listing:
        logger.error("no forcing files produced")
        return EXIT_OUTPUT

    logger.info("Output validation passed")
    print(json.dumps({
        "status": "success",
        "n_years": len(listing),
        "n_written": len(written),
        "n_skipped": len(skipped),
        "n_hru": int(n_hru),
        "data_step": int(expected_dt) if expected_dt else None,
        "time_stamp": "period-ending",
        "lapse_correction": "disabled" if ref_elev is None else f"{args.lapse_rate} K/m",
        "forcing_file_list": list_path,
        "output_dir": args.output_dir,
    }))
    return EXIT_OK


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(EXIT_PROCESS)
