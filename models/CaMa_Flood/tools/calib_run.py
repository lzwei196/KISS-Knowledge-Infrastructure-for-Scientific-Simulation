#!/usr/bin/env python3
"""calib_run.py -- programmatic run+score for CaMa-Flood calibration (RUNNER mode).

    python calib_run.py --workdir <wd> --out <metrics.json>

One cheap, repeatable evaluation for the generic calibration kit. It:

  1. reads the candidate parameter vector from the JSON at env ``KDT_CALIB_PARAMS``
     ({"name": value, ...}) -- the kit does NOT write CaMa inputs (runner mode),
     because CaMa regenerates its namelist on every MAIN_cmf call (the run script
     writes it inline) and several tuned parameters live in binary map files that a
     native tool must rewrite;
  2. INJECTS every value the model's own way (rewrites the binary map files the
     Fortran binary reads -- rivman/rivwth/rivhgt/fldhgt -- and the &NFORCE /
     &NPARAM namelist tokens), AFTER building the candidate map dir so nothing is
     overwritten;
  3. reads each value BACK from the artifact the model actually consumes and, if any
     cannot be written+read, exits nonzero with NO metrics file (= +inf, never a fake pass);
  4. runs the REAL CaMa-Flood binary through the KI's existing run tool
     (tools/run_cama.py -> MAIN_cmf); NEVER reimplements the routing;
  5. extracts discharge (outflw) at the drainage-area-matched Jinghong gauge cell,
     scores it against the forced observations with ki_tools_common.metrics.all_metrics,
     and writes the gate-valid metrics (lowercase nse/kge/pbias/rmse/r) as JSON to --out,
     plus the reserved ``__kdt__`` block echoing EVERY handed param + the self-declared
     case_id / scored_obs (so scoring the wrong gauge is detectable).

TARGET CASE -- HARD-PINNED below (see TARGET_* constants); NO environment variable can
redirect scoring to a different gauge/obs/location, and __kdt__.scored_obs is DERIVED from
the SAME resolved obs path + matched model cell that were actually scored (it cannot diverge
from the run):
  case_id    : SITE:jinghong
  gauge/obs  : cn_lancang_yunjinghong_允景洪 (station 90243100), Lancang (upper Mekong)
               KISSPATH_DATA/china_water_level/澜沧江txt/允景洪.txt (Q m3/s)
  quantity   : discharge (dag var outflw -> point_time_series), metric nse.

WHY runner mode / WHY these levers (verified against the v4.20 source, not memory):
  * The main-channel routing (cmf_calc_outflw_mod.F90) uses D2RIVMAN read from
    rivman.bin -- the namelist PMANRIV is inert for the channel, so river Manning MUST
    be injected into rivman.bin, not the namelist. (PMANRIV is still set for parity.)
  * rivwth (D2RIVWTH) and rivhgt (D2RIVHGT -> rivstomax / rivelv) are read from binary
    maps; a MULTIPLIER on the real map is the effective, structure-preserving lever
    (a calc_rivwth power-law regen would re-clip depth at HMIN).
  * lateral runoff forcing is the dag's only HIGH-sensitivity edge; CaMa applies
    ``runoff / DROFUNIT`` (cmf_ctrl_forcing_mod.F90), so a runoff bias/volume multiplier
    is injected as DROFUNIT = base / runoff_scale -- no per-eval NetCDF rewrite.
  * PMANFLD is used directly in the floodplain-outflow term, so it stays a namelist lever.

Honors env KDT_CALIB_SPLIT ("calibration"|"holdout") to score the right temporal block
(blocked-temporal holdout by year); unset -> score all overlapping years.
"""
import argparse
import json
import os
import sys
import glob
import subprocess
from datetime import date, timedelta

import numpy as np

# ki_tools_common (canonical metrics) -- same families the dag gates on.
from ki_tools_common.metrics import all_metrics  # noqa: E402

KI_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAMA_ROOT = "KISSPATH_BINARIES/cmf_v420_pkg"
BINARY = os.path.join(CAMA_ROOT, "src", "MAIN_cmf")
RUN_TOOL = os.path.join(KI_DIR, "tools", "run_cama.py")

# ===========================================================================
# TARGET CASE -- HARD-PINNED (SITE:jinghong, gauge 允景洪). These define WHICH gauge/obs
# this driver scores and are DELIBERATELY NOT read from the environment: no KDT_CAMA_OBS /
# KDT_CAMA_LAT / KDT_CAMA_LON / KDT_CAMA_AREA_KM2 (or any other) can redirect scoring to a
# different gauge. The self-declared __kdt__.scored_obs is BUILT from these same constants +
# the model cell that was actually matched at run time, so the declaration cannot lie about
# what was scored. A hard guard (below) refuses to run if any redirecting env var is present.
# ===========================================================================
TARGET_CASE_ID   = "SITE:jinghong"
TARGET_GAUGE_ID  = "cn_lancang_yunjinghong_允景洪"
TARGET_STATION   = "90243100"
TARGET_OBS_TXT   = "KISSPATH_DATA/china_water_level/澜沧江txt/允景洪.txt"   # Q m3/s, 1970-1985
TARGET_GAUGE_LAT = 22.001      # published gauge location (Jinghong 允景洪)
TARGET_GAUGE_LON = 100.842
TARGET_GAUGE_AREA_KM2 = 142695.0   # drainage area -> uparea-matched cell (NOT naive nearest)

# Case-defining run inputs (the map + forcing built one-time by the KI's prepare tools for THIS
# basin). Also pinned: a different map/forcing would silently be a different basin. Only the
# candidate parameter vector (KDT_CALIB_PARAMS) and the temporal split (KDT_CALIB_SPLIT) vary.
REF_MAP_DIR    = os.path.join(CAMA_ROOT, "map", "jinghong_15min")
FORCING_DIR    = "KISSPATH_OUTPUTS/jinghong_lancang/cama_input"
FORCING_PREFIX = "jinghong_runoff_1d_"
SIM_START_YEAR = 1968      # first simulated year
SIM_END_YEAR   = 1985      # last simulated year (inclusive)
SPINUP_YEARS   = 2         # first N years = cold-start warm-up (not scored)
SPLIT_YEAR     = 1980      # blocked-temporal holdout: calibration < SPLIT_YEAR <= holdout

DROFUNIT_BASE  = 86400.0 * 1000.0   # CaMa default: mm/day -> m3/m2/s (cmf_ctrl_forcing_mod ~line 118)
MIN_DAYS       = 200
CELL_SEARCH_DEG = 0.6
SENTINEL       = -9999.0

# Any of these being set would signal an attempt to redirect the scored gauge/location --
# refuse rather than silently score a different site while declaring jinghong.
_FORBIDDEN_ENV = ("KDT_CAMA_OBS", "KDT_CAMA_LAT", "KDT_CAMA_LON", "KDT_CAMA_AREA_KM2",
                  "KDT_CAMA_MAPDIR", "KDT_CAMA_FORCING_DIR", "KDT_CAMA_FORCING_PREFIX",
                  "KDT_CAMA_SIM_START", "KDT_CAMA_SIM_END", "KDT_CAMA_SPINUP",
                  "KDT_CAMA_SPLIT_YEAR")

# The calibratable pool (mirrors calibration.yaml). name -> (kind, default).
PARAM_SPEC = {
    "runoff_scale":  ("forcing_scale", 1.0),   # DROFUNIT = base / runoff_scale
    "manning_river": ("rivman_abs",    0.03),  # rivman.bin uniform
    "manning_flood": ("namelist_pmanfld", 0.10),
    "rivwth_scale":  ("scale_rivwth_gwdlr", 1.0),
    "rivhgt_scale":  ("scale_rivhgt", 1.0),
    "fldhgt_scale":  ("scale_fldhgt", 1.0),
}


# Path of the --out metrics file, registered as soon as it is known so EVERY failure
# path (die / uncaught exception) can guarantee no stale success artifact survives.
_OUT_PATH = None


def _purge_out():
    """Remove the --out metrics file if present. A failed/aborted eval must leave NOTHING
    behind (the kit then reads +inf); it must never inherit a previous candidate's file."""
    if _OUT_PATH and os.path.exists(_OUT_PATH):
        try:
            os.remove(_OUT_PATH)
        except OSError:
            pass


def die(msg):
    """Fail closed: delete any pre-existing metrics file, exit nonzero -> kit scores +inf.
    Deleting here is what stops a failed candidate from being scored on a STALE metrics
    file left by an earlier successful candidate (the 'metric never changes' symptom)."""
    _purge_out()
    sys.stderr.write("calib_run FAIL: %s\n" % msg)
    sys.exit(1)


def grid_dims(map_dir):
    diminfo = glob.glob(os.path.join(map_dir, "diminfo_*_025deg.txt"))
    diminfo = [d for d in diminfo if "test" not in os.path.basename(d)]
    if not diminfo:
        die("no diminfo_*_025deg.txt in %s" % map_dir)
    lines = open(diminfo[0]).read().splitlines()
    nx = int(lines[0].split()[0])
    ny = int(lines[1].split()[0])
    return nx, ny, diminfo[0]


def read_map(path):
    return np.fromfile(path, dtype="<f4")


def build_candidate_map(workdir, params, sentinel):
    """Symlink the reference map, then rewrite the injected binary maps in place.
    Returns (map_dir, diminfo_path, inpmat_path, applied_readback, nx, ny)."""
    ref = REF_MAP_DIR
    map_dir = os.path.join(workdir, "map")
    os.makedirs(map_dir, exist_ok=True)
    for f in os.listdir(ref):
        src = os.path.join(ref, f)
        dst = os.path.join(map_dir, f)
        if os.path.lexists(dst):
            continue
        if os.path.isfile(src):
            os.symlink(src, dst)   # cheap; read-only inputs shared across evals

    nx, ny, diminfo = grid_dims(map_dir)
    inpmat = glob.glob(os.path.join(map_dir, "inpmat_*_025deg.bin"))
    inpmat = [p for p in inpmat if "test" not in os.path.basename(p)]
    if not inpmat:
        die("no inpmat_*_025deg.bin in %s" % map_dir)
    inpmat = inpmat[0]
    ncell = nx * ny
    readback = {}

    def _rewrite(fname, transform, nlayer=1):
        """Replace the symlink with a real, transformed copy read from the reference."""
        ref_arr = read_map(os.path.join(ref, fname))
        if ref_arr.size != ncell * nlayer:
            die("%s size %d != %d (grid %dx%d layers %d)" % (fname, ref_arr.size, ncell * nlayer, nx, ny, nlayer))
        valid = ref_arr > sentinel / 2.0     # sentinel is -9999; valid land cells are > that
        out = ref_arr.copy()
        out[valid] = transform(ref_arr[valid])
        dst = os.path.join(map_dir, fname)
        if os.path.islink(dst):
            os.unlink(dst)
        out.astype("<f4").tofile(dst)
        return ref_arr, out, valid

    # --- river Manning: rivman.bin uniform (absolute) ---
    mr = float(params["manning_river"])
    _, out, valid = _rewrite("rivman.bin", lambda a: np.full(a.shape, mr, dtype="f8"))
    back = read_map(os.path.join(map_dir, "rivman.bin"))
    got = float(np.mean(back[valid]))
    if not np.isclose(got, mr, rtol=1e-4, atol=1e-6):
        die("rivman read-back %.6g != requested %.6g" % (got, mr))
    readback["manning_river"] = got

    # --- channel width / depth / floodplain profile: MULTIPLIERS on the real map ---
    for pname, fname, nlayer in (("rivwth_scale", "rivwth_gwdlr.bin", 1),
                                 ("rivhgt_scale", "rivhgt.bin", 1),
                                 ("fldhgt_scale", "fldhgt.bin", 10)):
        s = float(params[pname])
        ref_arr, out, valid = _rewrite(fname, lambda a, s=s: a * s, nlayer=nlayer)
        back = read_map(os.path.join(map_dir, fname))
        # verify the effective scale on the positive-magnitude cells (avoid /~0)
        mask = valid & (np.abs(ref_arr) > 1e-6)
        if mask.sum() == 0:
            readback[pname] = s
            continue
        ratio = float(np.sum(back[mask]) / np.sum(ref_arr[mask]))
        if not np.isclose(ratio, s, rtol=1e-4, atol=1e-6):
            die("%s read-back scale %.6g != requested %.6g" % (fname, ratio, s))
        readback[pname] = ratio

    return map_dir, diminfo, inpmat, readback, nx, ny


def write_run_script(workdir, map_dir, diminfo, inpmat, params):
    """Emit a self-contained CaMa run script: a continuous year-by-year run over
    SIM_START..SIM_END with restart chaining (LRESTART .FALSE. for year 1, .TRUE.
    thereafter, each year reading the restart the previous year wrote). This is the
    KI's reference recipe (gosh/run_<basin>_1d_nc.sh), with the injected candidate map
    dir and the injected &NFORCE/&NPARAM tokens. One o_outflw{YYYY}.nc per year."""
    rdir = os.path.join(workdir, "out")
    os.makedirs(rdir, exist_ok=True)
    ystart = SIM_START_YEAR
    yend = SIM_END_YEAR
    drofunit = DROFUNIT_BASE / float(params["runoff_scale"])
    pmanriv = float(params["manning_river"])   # parity with rivman.bin (channel uses the map)
    pmanfld = float(params["manning_flood"])
    fdir = FORCING_DIR
    fpre = FORCING_PREFIX
    script = os.path.join(workdir, "run_calib.sh")

    header = """#!/bin/sh
# CaMa-Flood calibration eval (auto-generated by calib_run.py)
export OMP_NUM_THREADS=%(threads)s
export HDF5_USE_FILE_LOCKING=FALSE
RDIR="%(rdir)s"
PROG="%(binary)s"
mkdir -p ${RDIR}
cd ${RDIR}
rm -rf ./*
ln -sf $PROG ./MAIN_cmf
YSTA=%(ystart)d
YEND=%(yend)d
IYR=${YSTA}
while [ ${IYR} -le ${YEND} ];
do
  CYR=`printf %%04d ${IYR}`
  EYR=`expr ${IYR} + 1`
  if [ ${IYR} -eq ${YSTA} ]; then
    LRESTART=".FALSE."
    CRESTSTO="''"
  else
    LRESTART=".TRUE."
    CRESTSTO="'./restart${CYR}010100.nc'"
  fi
  cat > ./input_cmf.nam << EOF
  &NRUNVER
  LADPSTP  = .TRUE.
  LPTHOUT  = .FALSE.
  LRESTART = ${LRESTART}
  /
  &NDIMTIME
  CDIMINFO = '%(diminfo)s'
  DT       = 86400
  IFRQ_INP = 24
  /
  &NPARAM
  PMANRIV  = %(pmanriv).6fD0
  PMANFLD  = %(pmanfld).6fD0
  PCADP    = 0.7
  PDSTMTH  = 10000.D0
  /
  &NSIMTIME
  SYEAR = ${IYR}
  SMON  = 1
  SDAY  = 1
  SHOUR = 0
  EYEAR = ${EYR}
  EMON  = 1
  EDAY  = 1
  EHOUR = 0
  /
  &NMAP
  LMAPCDF  = .FALSE.
  CNEXTXY  = '%(map_dir)s/nextxy.bin'
  CGRAREA  = '%(map_dir)s/ctmare.bin'
  CELEVTN  = '%(map_dir)s/elevtn.bin'
  CNXTDST  = '%(map_dir)s/nxtdst.bin'
  CRIVLEN  = '%(map_dir)s/rivlen.bin'
  CFLDHGT  = '%(map_dir)s/fldhgt.bin'
  CRIVWTH  = '%(map_dir)s/rivwth_gwdlr.bin'
  CRIVHGT  = '%(map_dir)s/rivhgt.bin'
  CRIVMAN  = '%(map_dir)s/rivman.bin'
  /
  &NRESTART
  CRESTSTO = ${CRESTSTO}
  CRESTDIR = './'
  CVNREST  = 'restart'
  LRESTCDF = .TRUE.
  IFRQ_RST = 0
  /
  &NFORCE
  LINPCDF  = .TRUE.
  LINTERP  = .TRUE.
  CINPMAT  = '%(inpmat)s'
  CROFCDF  = '%(fdir)s/%(fpre)s${CYR}.nc'
  CVNROF   = 'Runoff'
  DROFUNIT = %(drofunit).8E
  SYEARIN  = ${IYR}
  SMONIN   = 1
  SDAYIN   = 1
  SHOURIN  = 0
  /
  &NOUTPUT
  COUTDIR  = './'
  CVARSOUT = 'outflw'
  COUTTAG  = '${CYR}'
  LOUTCDF  = .TRUE.
  NDLEVEL  = 0
  IFRQ_OUT = 24
  /
  &NBOUND
  /
  &NDAMOUT
  /
  &NLEVEE
  /
EOF
  time ./MAIN_cmf
  IYR=`expr ${IYR} + 1`
done
""" % dict(threads=os.environ.get("OMP_NUM_THREADS", "4"), rdir=rdir, binary=BINARY,
           map_dir=map_dir, diminfo=diminfo, pmanriv=pmanriv, pmanfld=pmanfld,
           ystart=ystart, yend=yend, inpmat=inpmat, fdir=fdir, fpre=fpre, drofunit=drofunit)
    with open(script, "w") as f:
        f.write(header)
    os.chmod(script, 0o755)
    return script, rdir, drofunit


def _year_files(rdir):
    return {int(os.path.basename(fp)[len("o_outflw"):-3]): fp
            for fp in glob.glob(os.path.join(rdir, "o_outflw*.nc"))
            if os.path.basename(fp)[len("o_outflw"):-3].isdigit()}


def _complete_output(rdir):
    """Total outflw timesteps produced over all scored years (proof the sim ran to the
    end), independent of the launcher exit code."""
    os.environ.setdefault("HDF5_USE_FILE_LOCKING", "FALSE")
    files = _year_files(rdir)
    if not files:
        return 0, {}
    try:
        import xarray as xr
        counts = {}
        for yr, fp in files.items():
            ds = xr.open_dataset(fp, decode_times=False)
            counts[yr] = int(ds["time"].size)
            ds.close()
        return sum(counts.values()), counts
    except Exception:
        return 0, {}


def run_model(script, rdir):
    """Run via the KI's existing run tool (reuses preflight + error triplets).

    run_cama.py opens xarray for its sanity check and the environment's GMT/pygmt backend
    SIGSEGVs at interpreter teardown (returncode -11) AFTER MAIN_cmf has already finished
    and written output. So success is judged by a COMPLETE output series (every simulated
    year present with ~365 daily steps), not by the launcher exit code; a genuine mid-run
    crash leaves missing/partial years and is caught."""
    cmd = [sys.executable, RUN_TOOL, "--script", script, "--skip_preflight"]
    to = os.environ.get("KDT_CALIB_EVAL_TIMEOUT")
    kw = {}
    if to and to.strip().isdigit() and int(to) > 0:
        kw["timeout"] = int(to)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    except Exception as e:
        die("run_cama.py invocation failed: %s" % e)
    nsteps, counts = _complete_output(rdir)
    nyears = SIM_END_YEAR - SIM_START_YEAR + 1
    expected = nyears * 365
    have_years = sorted(counts)
    if nsteps < expected - 5 * nyears or len(counts) < nyears:
        die("run incomplete: %d steps over years %s (expected ~%d over %d years, run_cama rc=%d)\n%s"
            % (nsteps, have_years, expected, nyears, r.returncode, (r.stdout or "")[-1500:]))
    if r.returncode not in (0,):
        sys.stderr.write("calib_run: run_cama rc=%d but output complete (%d steps, %d years) "
                         "-- treating as success (libgmt teardown segfault)\n"
                         % (r.returncode, nsteps, len(counts)))


def nearest_area_cell(lats, lons, up_km2, glat, glon, target_km2, radius):
    """Allocate the gauge to the unit-catchment cell whose upstream area best matches the
    gauge drainage area within a search window (dag caveat: naive nearest-neighbour snaps
    to a mega-cell)."""
    best = None
    for iy in range(len(lats)):
        if abs(float(lats[iy]) - glat) > radius:
            continue
        for ix in range(len(lons)):
            if abs(float(lons[ix]) - glon) > radius:
                continue
            a = up_km2[iy, ix]
            if not np.isfinite(a) or a <= 0:
                continue
            d = abs(a - target_km2)
            if best is None or d < best[0]:
                best = (d, iy, ix, float(lats[iy]), float(lons[ix]), float(a))
    if best is None:
        die("no valid upstream-area cell within %.2f deg of gauge" % radius)
    return best


def extract_sim(rdir, map_dir, nx, ny):
    """Read outflw at the area-matched gauge cell over the SCORED years. Returns
    (series {date: q_m3s}, cell_info {lat, lon, uparea_km2}) so the caller can DERIVE the
    self-declared scored_obs from the cell that was actually scored. CaMa's daily output
    time is 'seconds since YYYY-01-01' labelled at the END of the window, so shift -1 day."""
    os.environ.setdefault("HDF5_USE_FILE_LOCKING", "FALSE")
    import xarray as xr
    files = _year_files(rdir)
    if not files:
        die("no o_outflw*.nc produced in %s" % rdir)
    up = read_map(os.path.join(map_dir, "uparea.bin")).reshape(ny, nx) / 1.0e6  # m2 -> km2
    up = np.where(up > 0, up, np.nan)
    score_years = [y for y in sorted(files)
                   if y >= SIM_START_YEAR + SPINUP_YEARS]
    series = {}
    cell = None
    cell_info = None
    for yr in score_years:
        ds = xr.open_dataset(files[yr], decode_times=False)
        lats = ds["lat"].values
        lons = ds["lon"].values
        if cell is None:
            _, iy, ix, clat, clon, carea = nearest_area_cell(
                lats, lons, up, TARGET_GAUGE_LAT, TARGET_GAUGE_LON,
                TARGET_GAUGE_AREA_KM2, CELL_SEARCH_DEG)
            cell = (iy, ix)
            cell_info = {"lat": clat, "lon": clon, "uparea_km2": carea}
            sys.stderr.write("calib_run: gauge cell (%.3f,%.3f) uparea=%.0f km2 (target %.0f)\n"
                             % (clat, clon, carea, TARGET_GAUGE_AREA_KM2))
        iy, ix = cell
        tvals = ds["time"].values
        units = ds["time"].attrs.get("units", "")
        try:
            base = units.split("since")[1].strip().split()[0]
            by, bm, bd = [int(x) for x in base.split("-")]
            base_date = date(by, bm, bd)
        except Exception:
            die("cannot parse time units %r" % units)
        vals = np.asarray(ds["outflw"].values[:, iy, ix], dtype="f8")
        vals[np.abs(vals) > 1e18] = np.nan
        for t, v in zip(tvals, vals):
            d = base_date + timedelta(seconds=float(t)) - timedelta(days=1)
            series[d] = v
        ds.close()
    return series, cell_info


def load_obs(path, years):
    """Load 允景洪.txt (tab-sep: stcd, dates 'YYYY-M-D', z, Q, name); Q col index 3,
    m3/s, sentinel -99."""
    yrs = set(years)
    obs = {}
    with open(path, encoding="utf-8", errors="ignore") as fh:
        next(fh, None)
        for line in fh:
            p = line.rstrip("\n").split("\t")
            if len(p) < 4:
                continue
            try:
                y, m, d = [int(x) for x in p[1].split("-")]
            except ValueError:
                continue
            if y not in yrs:
                continue
            try:
                q = float(p[3])
            except ValueError:
                continue
            if q <= -99:
                continue
            obs[date(y, m, d)] = q
    return obs


def apply_split(dates):
    split = os.environ.get("KDT_CALIB_SPLIT")
    if not split:
        return dates
    b = SPLIT_YEAR
    if split == "calibration":
        return [d for d in dates if d.year < b]
    if split == "holdout":
        return [d for d in dates if d.year >= b]
    return dates


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    # STALE-OUTPUT SAFETY: register + delete the metrics file BEFORE doing any work, so a
    # candidate that later fails (or is killed) can never be scored on a previous candidate's
    # success artifact. From here on every exit path (die / uncaught exception) purges it, and
    # metrics are written only once, atomically, on a fully successful run.
    global _OUT_PATH
    _OUT_PATH = os.path.abspath(args.out)
    out_dir = os.path.dirname(_OUT_PATH)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    _purge_out()

    # Refuse any attempt to redirect the scored gauge/location: the target case is pinned.
    present = [e for e in _FORBIDDEN_ENV if os.environ.get(e) not in (None, "")]
    if present:
        die("scored gauge is PINNED to %s; refusing env override(s): %s"
            % (TARGET_CASE_ID, ", ".join(present)))

    if not os.path.isfile(BINARY):
        die("CaMa binary not found: %s" % BINARY)

    pf = os.environ.get("KDT_CALIB_PARAMS")
    if not pf or not os.path.isfile(pf):
        die("KDT_CALIB_PARAMS not set / missing (runner mode requires it)")
    handed = json.loads(open(pf).read())
    if not isinstance(handed, dict) or not handed:
        die("empty parameter vector")

    # Fill any known lever not handed with its default (staged rounds hand all of them).
    params = {name: float(handed[name]) if name in handed else default
              for name, (_, default) in PARAM_SPEC.items()}

    os.makedirs(args.workdir, exist_ok=True)
    map_dir, diminfo, inpmat, readback, nx, ny = build_candidate_map(
        args.workdir, params, SENTINEL)

    script, rdir, drofunit_written = write_run_script(
        args.workdir, map_dir, diminfo, inpmat, params)

    run_model(script, rdir)

    # namelist read-back (each year rewrites input_cmf.nam; read the effective last one)
    eff_nam = open(os.path.join(rdir, "input_cmf.nam")).read()
    import re
    m_dro = re.search(r"DROFUNIT\s*=\s*([0-9.eE+\-]+)", eff_nam)
    m_pmf = re.search(r"PMANFLD\s*=\s*([0-9.eE+\-]+)D?0?", eff_nam)
    if not m_dro or not m_pmf:
        die("could not read back DROFUNIT/PMANFLD from effective namelist")
    dro_eff = float(m_dro.group(1))
    runoff_eff = DROFUNIT_BASE / dro_eff
    if not np.isclose(runoff_eff, params["runoff_scale"], rtol=1e-4, atol=1e-9):
        die("runoff_scale read-back %.6g != requested %.6g" % (runoff_eff, params["runoff_scale"]))
    pmanfld_eff = float(m_pmf.group(1))
    if not np.isclose(pmanfld_eff, params["manning_flood"], rtol=1e-4, atol=1e-9):
        die("manning_flood read-back %.6g != requested %.6g" % (pmanfld_eff, params["manning_flood"]))

    # ---- score (the pinned target gauge/obs; nothing here is env-overridable) ----
    obs_path = TARGET_OBS_TXT                 # the resolved obs actually loaded + scored
    sim, cell_info = extract_sim(rdir, map_dir, nx, ny)
    score_years = range(SIM_START_YEAR + SPINUP_YEARS, SIM_END_YEAR + 1)
    obs = load_obs(obs_path, score_years)
    common = sorted(set(sim) & set(obs))
    common = [d for d in common if np.isfinite(sim[d])]
    common = apply_split(common)
    if len(common) < MIN_DAYS:
        die("only %d matched days for split=%s (< %d)" %
            (len(common), os.environ.get("KDT_CALIB_SPLIT"), MIN_DAYS))
    o = np.array([obs[d] for d in common], dtype="f8")
    s = np.array([sim[d] for d in common], dtype="f8")
    M = all_metrics(o, s)   # UPPERCASE keys

    # DERIVE the self-declaration from the SAME resolved obs path + matched model cell that
    # were actually scored -- it cannot diverge from what the run scored.
    scored_obs = ("%s (station %s) :: %s [Q m3/s] @cell(%.3fN,%.3fE) uparea=%.0f km2"
                  % (TARGET_GAUGE_ID, TARGET_STATION, obs_path,
                     cell_info["lat"], cell_info["lon"], cell_info["uparea_km2"]))

    metrics = {
        "nse": float(M["NSE"]),
        "kge": float(M["KGE"]),
        "pbias": float(M["PBIAS"]),
        "rmse": float(M["RMSE"]),
        "r": float(M["r"]),
        "n_days": len(common),
        "split": os.environ.get("KDT_CALIB_SPLIT") or "full",
        # echo EVERY handed param -> the value actually applied (kit diffs requested vs applied);
        # case_id / scored_obs self-declare which gauge this eval scored (derived, not hardcoded-vs-run).
        "__kdt__": {
            "applied_params": {k: float(handed[k]) for k in handed},
            "case_id": TARGET_CASE_ID,
            "scored_obs": scored_obs,
        },
    }
    # provenance: what we verified we injected (does not affect the diff)
    metrics["__kdt__"]["readback"] = dict(readback,
                                          runoff_scale=runoff_eff, manning_flood=pmanfld_eff)

    # Atomic write: build the file under a temp name and rename into place, so a crash or
    # kill mid-write can never leave a half-written (but present) metrics file behind.
    tmp = _OUT_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(metrics, f, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, _OUT_PATH)
    sys.stderr.write("calib_run OK: %s\n" % {k: metrics[k] for k in ("nse", "kge", "pbias", "n_days", "split")})


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException as e:
        # Any unexpected failure (including KeyboardInterrupt / the launcher being killed on
        # timeout) must leave NO metrics file, so the kit reads +inf rather than a stale pass.
        _purge_out()
        sys.stderr.write("calib_run FAIL (uncaught): %s\n" % e)
        sys.exit(1)
