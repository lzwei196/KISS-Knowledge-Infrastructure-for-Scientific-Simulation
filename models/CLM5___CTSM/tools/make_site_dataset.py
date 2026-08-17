#!/usr/bin/env python3
"""
make_site_dataset.py -- Build CLM5 single-point (1PT/CLM_USRDAT) surface and
domain datasets by subsetting a global CLM surface dataset.

WHY THIS TOOL EXISTS
--------------------
SKILL.md pipeline stage 1 ("Surface Data") points at ``mksurfdata_esmf`` and
stage 4 ("Domain & Mapping") at ``ESMF_RegridWeightGen``.  Neither is usable in
the HydroCraft container: mksurfdata_esmf needs an ESMF build with PIO enabled
(the same blocker that stops the CTSM-5.4 / NUOPC executable, see
builder_result.json) and it needs the multi-hundred-GB raw-data tree.  For the
single-point tower workflow that CLM5 is normally validated with, the community
tool is CTSM's ``tools/site_and_regional/subset_data.py``, which does NOT
regrid at all -- it *subsets* an existing global surface dataset to the grid
cell containing the site, and writes a matching 1x1 domain file (the job of
``mknoocnmap.pl`` in the older PTCLM workflow).  This tool reproduces that
documented behaviour with no ESMF dependency.

WHAT IT WRITES
--------------
  surfdata_<site>_c<stamp>.nc   -- 1x1 CLM surface dataset (all variables of the
                                  parent global file, subset to one grid cell)
  domain.lnd.<site>_navy.nc     -- 1x1 CESM domain file (xc/yc/xv/yv/mask/
                                  frac/area), used for BOTH ATM_DOMAIN_FILE and
                                  LND_DOMAIN_FILE and by the DATM CLM1PT stream

CRITICAL DETAILS (see docs/s0_configuration_skill.md)
-----------------------------------------------------
* LONGXY/LATIXY in the surface dataset and xc/yc in the domain file are set to
  the SITE coordinates, not the parent grid-cell centre.  CLM compares the
  surface dataset grid against fatmlndfrc and aborts on a mismatch, and the
  DATM CLM1PT stream is read on the same domain -- all three must agree.
* Longitude is written in 0-360 (CLM convention) in both files.
* ``--dominant-pft`` overrides the grid-cell PFT composition with 100% of one
  PFT.  This is CTSM ``subset_data.py --dompft`` behaviour and is the standard
  way to make a ~100 km parent cell represent a tower footprint (dag caveat:
  "gridcell (~100 km) vs tower footprint (~1 km) representativeness").
  Percentages are renormalised so PCT_NATVEG + PCT_CROP + urban + lake +
  wetland + glacier == 100 exactly (diagnostic triplet dt_006).
* ``area`` in the domain file is in RADIANS^2 (steradians); ``AREA`` in the
  surface dataset is in km^2.  Mixing them silently corrupts the land fraction.

Usage
-----
    python make_site_dataset.py --site-name US-MMS \
        --lat 39.3232 --lon -86.4131 \
        --global-surfdata KISSPATH_HOME/cesm/inputdata/lnd/clm2/surfdata_map/\
release-clm5.0.18/surfdata_0.9x1.25_hist_78pfts_CMIP6_simyr1850_c190214.nc \
        --outdir KISSPATH_HOME/cesm/inputdata/lnd/clm2/surfdata_map \
        --domain-outdir KISSPATH_HOME/cesm/inputdata/share/domains \
        --dominant-pft 7
"""

import argparse
import json
import os
import sys
import time

import numpy as np

try:
    import netCDF4 as nc
except ImportError:  # pragma: no cover
    nc = None

DEG2RAD = np.pi / 180.0

# CLM5 natural PFT indices (surfdata natpft dimension, 0..14).
PFT_NAMES = {
    0: "not_vegetated",
    1: "needleleaf_evergreen_temperate_tree",
    2: "needleleaf_evergreen_boreal_tree",
    3: "needleleaf_deciduous_boreal_tree",
    4: "broadleaf_evergreen_tropical_tree",
    5: "broadleaf_evergreen_temperate_tree",
    6: "broadleaf_deciduous_tropical_tree",
    7: "broadleaf_deciduous_temperate_tree",
    8: "broadleaf_deciduous_boreal_tree",
    9: "broadleaf_evergreen_shrub",
    10: "broadleaf_deciduous_temperate_shrub",
    11: "broadleaf_deciduous_boreal_shrub",
    12: "c3_arctic_grass",
    13: "c3_non-arctic_grass",
    14: "c4_grass",
}

# FLUXNET / IGBP land-cover class -> CLM5 natural PFT index.  Used by
# --igbp so a tower's documented vegetation type maps to a defensible PFT
# instead of an agent-chosen number.
IGBP_TO_PFT = {
    "ENF": 1,   # evergreen needleleaf forest (temperate; use 2 above ~55N)
    "EBF": 5,   # evergreen broadleaf forest (temperate; use 4 in tropics)
    "DNF": 3,   # deciduous needleleaf forest
    "DBF": 7,   # deciduous broadleaf forest (temperate)
    "MF": 7,    # mixed forest -> broadleaf deciduous temperate
    "CSH": 10,  # closed shrubland
    "OSH": 10,  # open shrubland
    "WSA": 7,   # woody savanna
    "SAV": 14,  # savanna
    "GRA": 13,  # grassland (C3 non-arctic)
    "WET": 13,  # wetland
    "CRO": 13,  # cropland -- SP mode without crop model; C3 grass proxy
}


def _fail(errors):
    print(json.dumps({"status": "error", "errors": errors}, indent=2))
    sys.exit(1)


def validate_inputs(args):
    errors = []
    if nc is None:
        errors.append("netCDF4 is required for make_site_dataset.py")
    if not os.path.exists(args.global_surfdata):
        errors.append(f"Global surface dataset not found: {args.global_surfdata}")
    if not (-90.0 <= args.lat <= 90.0):
        errors.append(f"--lat {args.lat} outside [-90, 90]")
    if not (-360.0 <= args.lon <= 360.0):
        errors.append(f"--lon {args.lon} outside [-360, 360]")
    if args.dominant_pft is not None and args.dominant_pft not in PFT_NAMES:
        errors.append(
            f"--dominant-pft {args.dominant_pft} is not a natural PFT index "
            f"(valid 0-14: {PFT_NAMES})"
        )
    if args.igbp is not None and args.igbp.upper() not in IGBP_TO_PFT:
        errors.append(
            f"--igbp {args.igbp} unknown; valid: {sorted(IGBP_TO_PFT)}"
        )
    # Checked HERE, not in main(), so a bad --aerosol-source cannot abort the
    # run after a surface dataset and a domain file have already been emitted.
    if args.aerosol_source is not None and not os.path.exists(args.aerosol_source):
        errors.append(f"--aerosol-source not found: {args.aerosol_source}")
    if errors:
        _fail(errors)


def _lon360(lon):
    lon = float(lon)
    while lon < 0.0:
        lon += 360.0
    while lon >= 360.0:
        lon -= 360.0
    return lon


def surface_paths(args, stamp):
    """(final, staging) paths for the site surface dataset.

    Single source of truth for the surfdata path: main() resolves it ONCE and
    passes the staging path into subset_surfdata(), so the cleanup in main()'s
    finally can never drift from the path actually written, and a run that
    straddles midnight cannot stage under one date stamp and promote under
    another.
    """
    out_path = os.path.join(
        args.outdir, f"surfdata_{args.site_name}_c{stamp}.nc"
    )
    return out_path, out_path + ".staging"


def domain_file_path(args):
    """Final path of the 1x1 CESM domain file."""
    return os.path.join(
        args.domain_outdir, f"domain.lnd.{args.site_name}_navy.nc"
    )


def aerosol_file_path(args):
    """Final path of the site aerosol file, or None if none was requested."""
    if not args.aerosol_source:
        return None
    return os.path.join(args.aerosol_outdir or args.outdir,
                        f"aerosoldep_{args.site_name}.nc")


def _discard(paths):
    """Remove every existing path in ``paths``; None entries are ignored.

    A removal failure is reported on stderr and does NOT raise: the caller is
    always already on an error path, and masking the reason the site was
    rejected with an OSError from the cleanup would be strictly worse.
    """
    for path in paths:
        if not path or not os.path.exists(path):
            continue
        try:
            os.remove(path)
        except OSError as exc:  # pragma: no cover - permissions / FS errors
            print(f"WARNING: could not remove {path}: {exc}", file=sys.stderr)


def find_nearest_cell(ds, lat, lon360):
    """Return (j, i) of the global grid cell containing/nearest the site."""
    latixy = ds.variables["LATIXY"][:]
    longxy = ds.variables["LONGXY"][:]
    dlon = np.abs((longxy - lon360 + 180.0) % 360.0 - 180.0)
    dlat = np.abs(latixy - lat)
    dist = dlat ** 2 + (dlon * np.cos(lat * DEG2RAD)) ** 2
    j, i = np.unravel_index(np.argmin(dist), dist.shape)
    return int(j), int(i)


def subset_surfdata(args, j, i, staging_path):
    """Copy the parent surface dataset into ``staging_path``, keeping one cell.

    The CLM percentage invariants (check_sums_equal_1) can only be evaluated
    AFTER apply_site_overrides() has run, so the dataset is built at a staging
    path and promoted onto its final path by main() only once every gate has
    passed.  main() owns the path computation AND every removal (one
    try/finally covering all exit paths), so a dataset CLM would reject never
    appears at the final path, where run_and_score.py's stage_site_datasets()
    glob would find it and reuse it on the next resume.
    """
    os.makedirs(os.path.dirname(staging_path) or ".", exist_ok=True)
    src = nc.Dataset(args.global_surfdata)
    dst = nc.Dataset(staging_path, "w", format="NETCDF3_64BIT_OFFSET")

    for name, dim in src.dimensions.items():
        if name in ("lsmlat", "lsmlon"):
            dst.createDimension(name, 1)
        elif dim.isunlimited():
            dst.createDimension(name, None)
        else:
            dst.createDimension(name, len(dim))

    info = {}
    for name, var in src.variables.items():
        newvar = dst.createVariable(name, var.dtype, var.dimensions)
        newvar.setncatts({k: var.getncattr(k) for k in var.ncattrs()})
        data = var[:]
        dims = var.dimensions
        if "lsmlat" in dims and "lsmlon" in dims:
            jax = dims.index("lsmlat")
            iax = dims.index("lsmlon")
            data = np.take(np.take(data, [j], axis=jax), [i], axis=iax)
        newvar[:] = data
        info[name] = data

    dst.setncatts({k: src.getncattr(k) for k in src.ncattrs()})
    dst.setncattr("Site_ID", args.site_name)
    dst.setncattr(
        "History_Log",
        "Subset to a single point by CLM5___CTSM KI make_site_dataset.py "
        f"from {os.path.basename(args.global_surfdata)} "
        f"(parent cell j={j}, i={i})",
    )
    src.close()
    return dst, info


def apply_site_overrides(dst, args, parent_lat, parent_lon):
    """Force site coordinates and (optionally) a single dominant PFT."""
    lon360 = _lon360(args.lon)
    dst.variables["LONGXY"][:] = lon360
    dst.variables["LATIXY"][:] = args.lat
    dst.variables["PFTDATA_MASK"][:] = 1
    dst.variables["LANDFRAC_PFT"][:] = 1.0

    hw = args.half_width_deg
    # AREA in the surface dataset is km^2.
    area_km2 = (
        (2 * hw * DEG2RAD)
        * (2 * hw * DEG2RAD)
        * np.cos(args.lat * DEG2RAD)
        * (6.37122e3 ** 2)
    )
    dst.variables["AREA"][:] = area_km2

    pft_before = np.array(dst.variables["PCT_NAT_PFT"][:]).reshape(-1).tolist()
    applied = None
    if args.dominant_pft is not None or args.igbp is not None:
        pft = (
            args.dominant_pft
            if args.dominant_pft is not None
            else IGBP_TO_PFT[args.igbp.upper()]
        )
        npft = dst.variables["PCT_NAT_PFT"].shape[0]
        new = np.zeros((npft, 1, 1))
        new[pft, 0, 0] = 100.0
        dst.variables["PCT_NAT_PFT"][:] = new
        # A tower footprint is entirely the vegetated landunit.
        dst.variables["PCT_NATVEG"][:] = 100.0
        dst.variables["PCT_CROP"][:] = 0.0
        dst.variables["PCT_URBAN"][:] = 0.0
        dst.variables["PCT_LAKE"][:] = 0.0
        dst.variables["PCT_WETLAND"][:] = 0.0
        dst.variables["PCT_GLACIER"][:] = 0.0
        # dt_023: PCT_GLC_MEC is NOT a landunit weight -- it is the
        # distribution of the glacier landunit over the nglcec elevation
        # classes.  CLM reads it UNCONDITIONALLY in surfrd_special
        # (components/clm/src/main/surfrdMod.F90:602-607:
        #  ncd_io 'PCT_GLC_MEC' -> /100 -> check_sums_equal_1(wt_glc_mec,...))
        # with NO guard on PCT_GLACIER, and endruns at
        # surfrdUtilsMod.F90:80 when the sum is not 1.0.  Zeroing it aborts
        # the model before the first timestep even though the glacier
        # landunit has zero weight.  Put all the weight in elevation class 0,
        # which is what every cell of the parent global surface dataset
        # carries.
        glc = np.zeros(dst.variables["PCT_GLC_MEC"].shape, dtype="f8")
        glc[0] = 100.0
        dst.variables["PCT_GLC_MEC"][:] = glc
        cft = np.array(dst.variables["PCT_CFT"][:])
        cft[:] = 0.0
        cft[0] = 100.0  # CFT percentages must still sum to 100 within the
        dst.variables["PCT_CFT"][:] = cft  # (now zero-weight) crop landunit
        applied = {"index": pft, "name": PFT_NAMES[pft]}

    # dt_023 check: the glacier elevation-class weights must ALSO sum to
    # 100, independently of PCT_GLACIER (CLM check_sums_equal_1 on
    # wt_glc_mec).  Checked on BOTH paths, override or not.
    glc_sum = float(np.sum(dst.variables["PCT_GLC_MEC"][:]))

    # dt_006 check: landunit percentages must sum to exactly 100.
    total = (
        float(np.sum(dst.variables["PCT_NATVEG"][:]))
        + float(np.sum(dst.variables["PCT_CROP"][:]))
        + float(np.sum(dst.variables["PCT_URBAN"][:]))
        + float(np.sum(dst.variables["PCT_LAKE"][:]))
        + float(np.sum(dst.variables["PCT_WETLAND"][:]))
        + float(np.sum(dst.variables["PCT_GLACIER"][:]))
    )
    # Same FATAL class as dt_023: CLM calls check_sums_equal_1 on FOUR
    # arrays in components/clm/src/main/surfrdMod.F90 -- wt_lunit (line 412),
    # wt_glc_mec (607), wt_nat_patch (894 and 945) and wt_cft (898) -- and
    # every one of them endruns at surfrdUtilsMod.F90:80.  Report all four
    # so main() can gate on them instead of only warning.
    nat_pft_sum = float(np.sum(dst.variables["PCT_NAT_PFT"][:]))
    cft_sum = float(np.sum(dst.variables["PCT_CFT"][:]))

    return {
        "landunit_pct_sum": total,
        "glc_mec_pct_sum": glc_sum,
        "nat_pft_pct_sum": nat_pft_sum,
        "cft_pct_sum": cft_sum,
        "pft_pct_before": pft_before,
        "dominant_pft_applied": applied,
        "parent_cell_lat": parent_lat,
        "parent_cell_lon": parent_lon,
        "area_km2": area_km2,
    }


def write_domain(args, path):
    """Write a 1x1 CESM domain file (the mknoocnmap.pl / subset_data job).

    ``path`` comes from domain_file_path(); main() resolves it before anything
    is written so its finally can remove it if the invocation does not produce
    a complete, gate-passing output set.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    lon360 = _lon360(args.lon)
    hw = args.half_width_deg

    ds = nc.Dataset(path, "w", format="NETCDF3_64BIT_OFFSET")
    ds.createDimension("n", 1)
    ds.createDimension("ni", 1)
    ds.createDimension("nj", 1)
    ds.createDimension("nv", 4)

    def _v(name, dims, value, units, long_name, dtype="f8"):
        var = ds.createVariable(name, dtype, dims)
        var.units = units
        var.long_name = long_name
        var[:] = value
        return var

    _v("xc", ("nj", "ni"), lon360, "degrees_east", "longitude of grid cell center")
    _v("yc", ("nj", "ni"), args.lat, "degrees_north", "latitude of grid cell center")

    xv = np.array([lon360 - hw, lon360 + hw, lon360 + hw, lon360 - hw])
    yv = np.array([args.lat - hw, args.lat - hw, args.lat + hw, args.lat + hw])
    _v("xv", ("nj", "ni", "nv"), xv.reshape(1, 1, 4), "degrees_east",
       "longitude of grid cell vertices")
    _v("yv", ("nj", "ni", "nv"), yv.reshape(1, 1, 4), "degrees_north",
       "latitude of grid cell vertices")

    # area MUST be in radians^2 (steradians) in a CESM domain file.
    area_sr = (2 * hw * DEG2RAD) * (2 * hw * DEG2RAD) * np.cos(args.lat * DEG2RAD)
    _v("area", ("nj", "ni"), area_sr, "radian2", "area of grid cell in radians squared")
    _v("frac", ("nj", "ni"), 1.0, "unitless",
       "fraction of grid cell that is active")
    mask = ds.createVariable("mask", "i4", ("nj", "ni"))
    mask.units = "unitless"
    mask.long_name = "domain mask"
    mask[:] = 1

    ds.title = f"CESM domain data for single point {args.site_name}"
    ds.source = ("CLM5___CTSM KI make_site_dataset.py (equivalent of "
                 "CTSM subset_data.py / mknoocnmap.pl for a 1x1 point)")
    ds.Site_ID = args.site_name
    ds.close()
    return float(area_sr)


def write_site_aerosol(args, path):
    """Extract the site column from a global aerosol-deposition stream file.

    WHY: an I-compset with CLM refuses DATM_PRESAERO=none --
    ``ERROR: A DATM_MODE for CLM is incompatible with DATM_PRESAERO=none``
    (datm/cime_config/buildnml).  The default clim_2000 stream file for CESM is
    aerosoldep_WACCM.ensmean_monthly_hist_1849-2015_0.9x1.25_CMIP6 -- 6.2 GB,
    which is absurd to fetch for one grid point.  The 1.9x2.5 year-2000
    climatology (9 MB) carries the same 14 deposition fields; this routine cuts
    the site column out of it and adds the ``area``/``mask`` domain variables
    that the presaero stream's strm_domvar requires and that the raw CAM file
    does not carry.
    """
    src = nc.Dataset(args.aerosol_source)
    lat = src.variables["lat"][:]
    lon = src.variables["lon"][:]
    lon360 = _lon360(args.lon)
    j = int(np.argmin(np.abs(lat - args.lat)))
    i = int(np.argmin(np.abs((lon - lon360 + 180.0) % 360.0 - 180.0)))

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    dst = nc.Dataset(path, "w", format="NETCDF3_64BIT_OFFSET")
    ntime = len(src.dimensions["time"])
    dst.createDimension("time", None)
    dst.createDimension("lat", 1)
    dst.createDimension("lon", 1)

    tv = dst.createVariable("time", "f8", ("time",))
    for a in src.variables["time"].ncattrs():
        tv.setncattr(a, src.variables["time"].getncattr(a))
    # TRAP: CIME writes the presaero stream as "<file> <align> <first> <last>",
    # e.g. "datm.streams.txt.presaero.clim_2000 1 2000 2000" — it asks for
    # stream year 2000.  The 1.9x2.5 climatology carries its 12 mid-month
    # offsets on "days since 0001-01-01", i.e. stream year 1, and shr_stream
    # then finds no data for the requested year.  Rebase the reference date to
    # the stream year (the offsets themselves are mid-month on a 365-day year
    # and are unchanged).
    tv.units = f"days since {args.aerosol_year:04d}-01-01 00:00:00"
    tv.calendar = "noleap"
    tv[:] = src.variables["time"][:]

    lv = dst.createVariable("lat", "f8", ("lat",))
    lv.units = "degrees_north"
    lv[:] = args.lat
    ov = dst.createVariable("lon", "f8", ("lon",))
    ov.units = "degrees_east"
    ov[:] = lon360

    hw = args.half_width_deg
    av = dst.createVariable("area", "f8", ("lat", "lon"))
    av.units = "radian2"
    av[:] = (2 * hw * DEG2RAD) ** 2 * np.cos(args.lat * DEG2RAD)
    mv = dst.createVariable("mask", "i4", ("lat", "lon"))
    mv.units = "unitless"
    mv[:] = 1

    fields = []
    for name, var in src.variables.items():
        if name in ("lat", "lon", "time", "date"):
            continue
        if var.dimensions != ("time", "lat", "lon"):
            continue
        nv = dst.createVariable(name, "f8", ("time", "lat", "lon"))
        nv.setncatts({k: var.getncattr(k) for k in var.ncattrs()})
        nv[:] = np.asarray(var[:, j, i]).reshape(ntime, 1, 1)
        fields.append(name)

    dst.title = f"Aerosol deposition at {args.site_name}"
    dst.source = (f"single column ({j},{i}) of "
                  f"{os.path.basename(args.aerosol_source)}, extracted by "
                  "CLM5___CTSM KI make_site_dataset.py")
    dst.close()
    src.close()
    return fields


# dt_023 generalised: CLM divides EVERY one of these four percentage sums by
# 100 and hands it to check_sums_equal_1, which endruns unconditionally at
# components/clm/src/main/surfrdUtilsMod.F90:80.  A violation is FATAL, never a
# warning -- that mis-severity is exactly what let a zeroed PCT_GLC_MEC ship and
# abort the 2026-08-09 US-MMS run before its first timestep.
SURFACE_SUM_GATES = (
    ("landunit_pct_sum",
     "dt_006: landunit percentages (PCT_NATVEG + PCT_CROP + PCT_URBAN + "
     "PCT_LAKE + PCT_WETLAND + PCT_GLACIER)", "wt_lunit", "412"),
    ("glc_mec_pct_sum",
     "dt_023: PCT_GLC_MEC across the nglcec dimension (read regardless "
     "of PCT_GLACIER)", "wt_glc_mec", "607"),
    ("nat_pft_pct_sum",
     "PCT_NAT_PFT across the natpft dimension", "wt_nat_patch", "894"),
    ("cft_pct_sum",
     "PCT_CFT across the cft dimension", "wt_cft", "898"),
)


def validate_surface_sums(diag, discarded_on_failure):
    """Gate the STAGED surface dataset before it is emitted.

    Called while the dataset is still at its staging path, so a violation exits
    non-zero BEFORE os.replace() promotes it and before write_domain() /
    write_site_aerosol() run.  This function only REPORTS -- the single
    try/finally in main() performs every removal, so there is exactly ONE
    cleanup site and it covers the validation failure (SystemExit from
    _fail()), an unhandled exception, and a partially written output set alike.
    ``discarded_on_failure`` is that path list, quoted in the error so the
    caller sees precisely what will not exist when the process exits.

    Tolerance 1e-6 is safe: every cell of the parent global surfdata is within
    ~4e-14 of 100.0 on all four arrays (probed on
    surfdata_0.9x1.25_hist_78pfts_CMIP6_simyr1850_c190214.nc: PCT_GLC_MEC
    per-cell sum min 99.99999999999997, max 100.00000000000004).
    """
    errors = []
    for _key, _what, _arr, _line in SURFACE_SUM_GATES:
        if abs(diag[_key] - 100.0) > 1e-6:
            errors.append(
                f"{_what} sums to {diag[_key]} instead of 100.0; CLM "
                f"surfrdMod.F90:{_line} calls check_sums_equal_1 on "
                f"{_arr} and endruns at surfrdUtilsMod.F90:80")
    if errors:
        errors.append(
            "nothing emitted for this site; discarded before exit: "
            + ", ".join(p for p in discarded_on_failure if p))
        _fail(errors)


def main():
    p = argparse.ArgumentParser(
        description="Build CLM5 single-point surface + domain datasets"
    )
    p.add_argument("--site-name", required=True,
                   help="CLM_USRDAT_NAME to use, e.g. US-MMS")
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True,
                   help="Site longitude, -180..180 or 0..360")
    p.add_argument("--global-surfdata", required=True)
    p.add_argument("--outdir", required=True,
                   help="Directory for the site surface dataset")
    p.add_argument("--domain-outdir", default=None,
                   help="Directory for the domain file (default: --outdir)")
    p.add_argument("--dominant-pft", type=int, default=None,
                   help="Force 100%% of this natural PFT index (0-14)")
    p.add_argument("--igbp", type=str, default=None,
                   help="IGBP class (DBF, ENF, GRA, ...) -> dominant PFT")
    p.add_argument("--half-width-deg", type=float, default=0.05,
                   help="Half-width of the single-point cell in degrees")
    p.add_argument("--aerosol-source", default=None,
                   help="Global aerosol-deposition stream file to cut the site "
                        "column out of (DATM presaero stream)")
    p.add_argument("--aerosol-outdir", default=None,
                   help="Directory for the site aerosol file (default: --outdir)")
    p.add_argument("--aerosol-year", type=int, default=2000,
                   help="Stream year to stamp the aerosol climatology with "
                        "(must match DATM_PRESAERO, e.g. 2000 for clim_2000)")
    args = p.parse_args()
    if args.domain_outdir is None:
        args.domain_outdir = args.outdir

    # Every output path of THIS invocation, resolved from argparse alone --
    # os.path.join on already-parsed arguments; no I/O, no validation, nothing
    # here can fail -- so the try/finally below is entered BEFORE the first
    # statement that can.  time.strftime() is called once here and nowhere
    # else, so a run that straddles midnight cannot stage under one date stamp
    # and clean up another.
    stamp = time.strftime("%y%m%d")
    surf_path, staging_path = surface_paths(args, stamp)
    domain_path = domain_file_path(args)
    aerosol_path = aerosol_file_path(args)
    final_paths = (surf_path, domain_path, aerosol_path)

    emitted = False
    try:
        # INSIDE the try, so the finally covers them: validate_inputs() ends in
        # _fail() -> SystemExit, and opening the parent surfdata /
        # find_nearest_cell() can raise.  An early input rejection or a bad
        # parent source is therefore exactly as fail-closed as a percentage
        # gate violation -- neither can leave a stale same-day surfdata, domain
        # or aerosol file at the paths this invocation targets, and neither can
        # leave a .staging file behind.
        validate_inputs(args)

        src = nc.Dataset(args.global_surfdata)
        try:
            j, i = find_nearest_cell(src, args.lat, _lon360(args.lon))
            parent_lat = float(src.variables["LATIXY"][j, i])
            parent_lon = float(src.variables["LONGXY"][j, i])
        finally:
            src.close()

        # Only a hard-killed EARLIER process can leave a staging file behind;
        # this one's finally removes it on every exit path of this process.
        _discard([staging_path])

        dst, _info = subset_surfdata(args, j, i, staging_path)
        try:
            diag = apply_site_overrides(dst, args, parent_lat, parent_lon)
        finally:
            dst.close()

        # GATE BEFORE EMIT.  validate_surface_sums() exits non-zero on any
        # violation while the dataset is still at staging_path, so os.replace()
        # is reached only for a dataset CLM will accept -- and the domain and
        # aerosol writers below never run for a rejected site.
        validate_surface_sums(diag, (staging_path,) + final_paths)
        os.replace(staging_path, surf_path)

        area_sr = write_domain(args, domain_path)
        aerosol_fields = []
        if args.aerosol_source:
            aerosol_fields = write_site_aerosol(args, aerosol_path)
        emitted = True
    finally:
        # THE single cleanup site, and the ONLY statement in main() that is
        # outside the try.  Reached on an input rejection from
        # validate_inputs(), on a parent-surfdata open / nearest-cell failure,
        # on the percentage gate's _fail() (SystemExit), on any unhandled
        # exception from the NetCDF writers, and on a normal return alike.
        # On anything short of a complete
        # gate-passing output set, the staging file AND every final path this
        # invocation targets are removed -- including a same-day rerun's stale
        # predecessors, which sit at those identical paths.  A caller such as
        # run_and_score.py's stage_site_datasets() therefore cannot pick up a
        # rejected or half-written surface / domain / aerosol file.
        _discard([staging_path])
        if not emitted:
            _discard(final_paths)

    warnings_list = []
    if abs(parent_lat - args.lat) > 1.5 or abs(parent_lon - _lon360(args.lon)) > 1.5:
        warnings_list.append(
            "Parent grid cell centre is far from the site; surface properties "
            "(soil texture, LAI climatology) are those of the parent cell"
        )

    print(json.dumps({
        "status": "success",
        "site": args.site_name,
        "lat": args.lat,
        "lon": _lon360(args.lon),
        "surfdata": surf_path,
        "domain": domain_path,
        "aerosol": aerosol_path,
        "aerosol_fields": aerosol_fields,
        "parent_cell": {"j": j, "i": i,
                        "lat": parent_lat, "lon": parent_lon},
        "domain_area_sr": area_sr,
        "diagnostics": diag,
        "warnings": warnings_list,
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
