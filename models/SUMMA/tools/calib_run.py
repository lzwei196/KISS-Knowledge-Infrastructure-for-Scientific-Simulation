#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Calibration Driver (programmatic, NOT an agent)
==========================================================================
Tool ID:      calib_run
Stage:        calibration
Description:  Run SUMMA once for ONE candidate parameter vector and score it
              against the TARGET CASE observations, emitting the dag-gate-valid
              metrics as JSON.

TARGET CASE (PINNED -- this driver scores this gauge and no other)
------------------------------------------------------------------
  case_id      : OBS:hydat
  obs          : HYDAT:08NH120  MOYIE RIVER ABOVE NEGRO CREEK (BC, 239 km2)
  source       : Environment and Climate Change Canada HYDAT national archive
                 /mnt/disk4/Hydat_sqlite3_20260116/Hydat.sqlite3  (DLY_FLOWS)
  target var   : scalarTotalRunoff (dag.outputs, point_time_series) ->
                 SUMMA's own sub-grid time-delay routing of it,
                 averageRoutedRunoff (subRouting = timeDlay), x basin area
  metric       : nse (determining), plus kge / pbias / r / rmse
  provenance   : SUMMA_20260629T153311Z, validated full-period NSE 0.611
                 (cal 0.5445 / val 0.6467, KGE 0.755, PBIAS -5.04)

The gauge/obs is NOT read from any overridable environment variable.  The
station number is a module constant; every identity field (name, lat, lon,
gross drainage area) is read back from the HYDAT catalog and ASSERTED, and the
basin area used to convert routed runoff (m/s) to discharge (m3/s) is DERIVED
from that same HYDAT row -- so `__kdt__.scored_obs` / `case_id` cannot diverge
from what was actually scored.

Injection mode: RUNNER (calibration.yaml `injection.mode: runner`).
The KI regenerates trialParams.nc on every run, so the kit does NOT pre-write
parameters.  This driver reads the candidate vector from $KDT_CALIB_PARAMS,
injects it through the KI's OWN s4 tool (set_trial_parameters.py, both
--parameters for the HRU-scope block and --basin_parameters for the GRU-scope
routing block), reads every value BACK out of the trialParams.nc that SUMMA
actually opens, and fails closed if any value cannot be written+read.

Usage:  python3 calib_run.py --workdir <wd> --out <metrics.json>
Env:    KDT_CALIB_PARAMS  path to {"name": value, ...} for this candidate
        KDT_CALIB_SPLIT   "calibration" | "holdout"  (anything else -> calibration,
                          matching calibration_kit.evaluator.resolve_train_split)
        KDT_CALIB_EVAL_ID per-eval id (used only to name the scratch dir)
        KDT_CALIB_KEEP_EVAL=1  keep the per-eval scratch dir on success

On ANY failure: nothing is written to --out and the exit code is nonzero, so a
missing metrics file scores +inf.  Never a fake pass.

Exit codes: 0=success, 1=input/contract error, 2=run error, 3=scoring error
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import numpy as np
import netCDF4 as nc

sys.path.insert(0, "/mnt/disk1/Hydrocraft_server/models/ki_tools_common")
from ki_tools_common.metrics import all_metrics  # noqa: E402

# ---------------------------------------------------------------------------
# PINNED case + validated-run recipe (all constants, no env overrides)
# ---------------------------------------------------------------------------
KI = Path("/mnt/disk1/Hydrocraft_server/models/SUMMA/knowledge_infrastructure")
TOOLS = KI / "tools"
SUMMA_EXE = "/mnt/disk1/Hydrocraft_server/model/summa/bin/summa.exe"
BASE_SETTINGS = Path("/mnt/disk1/Hydrocraft_server/model/summa/case_study/base_settings")

# Staged upstream inputs of the VALIDATED run (forcing + domain + decisions +
# cold state + the trialParams.nc the NSE-0.611 run consumed).
CASE_DIR = Path("/mnt/disk1/Hydrocraft_server/outputs/moyie_08nh120_summa")
CASE_SETTINGS = CASE_DIR / "site_settings"
CASE_FORCING = CASE_DIR / "forcing"
FORCING_NC = "forcing_moyie.nc"

HYDAT_DB = "/mnt/disk4/Hydat_sqlite3_20260116/Hydat.sqlite3"

CASE_ID = "OBS:hydat"
STATION_NUMBER = "08NH120"
STATION_NAME = "MOYIE RIVER ABOVE NEGRO CREEK"
STATION_LAT = 49.4221
STATION_LON = -115.9413
DRAINAGE_AREA_KM2 = 239.0          # HYDAT STATIONS.DRAINAGE_AREA_GROSS
COORD_TOL_DEG = 0.01

SIM_START = dt.datetime(2005, 1, 1, 1, 0)
SIM_END = dt.datetime(2015, 12, 31, 23, 0)
OUTPUT_PREFIX = "moyie"
SPINUP_THROUGH = dt.date(2005, 12, 31)   # 2005 is cold-start spinup, never scored

# Blocked-temporal split of the scored record (identical to the validated run's
# period_calibration / period_validation).
SPLITS = {
    "calibration": (dt.date(2006, 1, 1), dt.date(2010, 12, 31)),
    "holdout": (dt.date(2011, 1, 1), dt.date(2015, 12, 31)),
}

# ---------------------------------------------------------------------------
# OBS ENVELOPE CONTRACT -- every field is READ and ASSERTED before any metric is
# computed, so a changed/corrupted HYDAT series for the SAME station can never be
# silently scored.  Mirrors calibration.yaml `case.obs_contract`.
# ---------------------------------------------------------------------------
OBS_CONTRACT = {
    "calibration": {
        "start": "2006-01-01", "end": "2010-12-31", "n": 1826,
        "mean": 3.819237135, "min": 0.119000, "max": 67.099998,
        "std": 7.298766785, "sum": 6973.927008,
    },
    "holdout": {
        "start": "2011-01-01", "end": "2015-12-31", "n": 1826,
        "mean": 5.218852687, "min": 0.092000, "max": 70.000000,
        "std": 9.332155319, "sum": 9529.625006,
    },
}
OBS_RTOL = 1e-6

# ---------------------------------------------------------------------------
# Parameter registry.  scope decides WHERE in trialParams.nc the value lands:
#   "hru" -> hru-dimension variable (SUMMA local/HRU parameter)
#   "gru" -> gru-dimension variable (SUMMA basin parameter; routingGamma*)
# `source` is where the value the VALIDATED run used comes from, so the default
# vector reproduces that run bit-for-bit.
#   "trial"  -> the staged validated trialParams.nc
#   "local"  -> localParamInfo.txt default (var absent from trialParams.nc)
#   "basin"  -> basinParamInfo.txt default
# ---------------------------------------------------------------------------
PARAM_REGISTRY = {
    "k_soil":             {"scope": "hru", "source": "trial"},
    "theta_sat":          {"scope": "hru", "source": "trial"},
    "vGn_alpha":          {"scope": "hru", "source": "trial"},
    "vGn_n":              {"scope": "hru", "source": "trial"},
    "qSurfScale":         {"scope": "hru", "source": "trial"},
    "aquiferScaleFactor": {"scope": "hru", "source": "trial"},
    "rootingDepth":       {"scope": "hru", "source": "trial"},
    "critSoilTranspire":  {"scope": "hru", "source": "trial"},
    "tempCritRain":       {"scope": "hru", "source": "local"},
    "frozenPrecipMultip": {"scope": "hru", "source": "local"},
    "albedoDecayRate":    {"scope": "hru", "source": "local"},
    "albedoMaxVisible":   {"scope": "hru", "source": "local"},
    "routingGammaShape":  {"scope": "gru", "source": "basin"},
    "routingGammaScale":  {"scope": "gru", "source": "basin"},
}
READBACK_RTOL = 1e-9

# Output variables SUMMA writes.  averageRoutedRunoff is the scored series;
# the rest are the dag target var + the water-balance terms kept for diagnosis.
OUTPUT_CONTROL_VARS = [
    "averageRoutedRunoff", "scalarTotalRunoff", "pptrate",
    "scalarTotalET", "scalarSWE",
]

SUMMA_OK_MARKER = "FORTRAN STOP: finished simulation successfully."


class Fail(Exception):
    """Any condition that must produce NO metrics file."""

    def __init__(self, msg, code=1):
        super().__init__(msg)
        self.code = code


# ---------------------------------------------------------------------------
# SUMMA parameter-info parsing (the model's own documented defaults)
# ---------------------------------------------------------------------------
_PARAMINFO_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\|(.+)$")


def _fortran_float(tok: str) -> float:
    return float(tok.strip().replace("d", "e").replace("D", "E"))


def read_param_info(path: Path) -> dict:
    """{name: (default, lower, upper)} from a SUMMA *ParamInfo.txt table."""
    out = {}
    for line in path.read_text().splitlines():
        line = line.split("!")[0]
        m = _PARAMINFO_RE.match(line)
        if not m:
            continue
        cols = [c for c in (c.strip() for c in m.group(2).split("|")) if c]
        if len(cols) < 3:
            continue
        try:
            out[m.group(1)] = tuple(_fortran_float(c) for c in cols[:3])
        except ValueError:
            continue
    return out


# ---------------------------------------------------------------------------
# Observations -- HYDAT sqlite, opened READ-ONLY (works on a read-only mount)
# ---------------------------------------------------------------------------
def _connect_hydat():
    if not Path(HYDAT_DB).is_file():
        raise Fail(f"HYDAT catalog missing: {HYDAT_DB}")
    # mode=ro: never create/lock/write the immutable obs catalog.
    return sqlite3.connect(f"file:{HYDAT_DB}?mode=ro", uri=True)


def resolve_station(conn, station_number: str) -> dict:
    """Identity of the gauge THIS run scores, read back from the catalog."""
    row = conn.execute(
        "SELECT STATION_NUMBER, STATION_NAME, LATITUDE, LONGITUDE, DRAINAGE_AREA_GROSS "
        "FROM STATIONS WHERE STATION_NUMBER = ?", (station_number,)).fetchone()
    if row is None:
        raise Fail(f"HYDAT has no station {station_number!r}")
    num, name, lat, lon, area_km2 = row
    if str(num) != station_number:
        raise Fail(f"HYDAT returned station {num!r} for query {station_number!r}")
    if str(name).strip().upper() != STATION_NAME:
        raise Fail(f"station {num} name {name!r} != expected {STATION_NAME!r}")
    for label, got, want in (("latitude", lat, STATION_LAT), ("longitude", lon, STATION_LON)):
        if got is None or abs(float(got) - want) > COORD_TOL_DEG:
            raise Fail(f"station {num} {label} {got} != expected {want} (+/-{COORD_TOL_DEG})")
    if area_km2 is None or abs(float(area_km2) - DRAINAGE_AREA_KM2) > 1e-6:
        raise Fail(f"station {num} gross drainage area {area_km2} != expected "
                   f"{DRAINAGE_AREA_KM2} km2")
    return {"station_number": str(num), "station_name": str(name).strip(),
            "latitude": float(lat), "longitude": float(lon),
            "drainage_area_km2": float(area_km2)}


def load_daily_flows(conn, station_number: str, start: dt.date, end: dt.date) -> dict:
    """{date: Q m3/s} from DLY_FLOWS for [start, end]."""
    cols = ",".join("FLOW%d" % i for i in range(1, 32))
    rows = conn.execute(
        f"SELECT YEAR, MONTH, {cols} FROM DLY_FLOWS "
        "WHERE STATION_NUMBER = ? AND YEAR BETWEEN ? AND ? ORDER BY YEAR, MONTH",
        (station_number, start.year, end.year)).fetchall()
    obs = {}
    for r in rows:
        year, month = int(r[0]), int(r[1])
        for i in range(31):
            val = r[2 + i]
            if val is None:
                continue
            try:
                day = dt.date(year, month, i + 1)
            except ValueError:
                continue
            if start <= day <= end:
                obs[day] = float(val)
    return obs


def assert_obs_contract(obs: dict, split: str) -> dict:
    """ENFORCE every declared obs-envelope field.  Mismatch -> no metrics."""
    spec = OBS_CONTRACT[split]
    days = sorted(obs)
    if not days:
        raise Fail(f"{split}: no HYDAT observations for {STATION_NUMBER}")
    got = {
        "start": days[0].isoformat(), "end": days[-1].isoformat(), "n": len(days),
    }
    vals = np.array([obs[d] for d in days], dtype=float)
    got.update({"mean": float(vals.mean()), "min": float(vals.min()),
                "max": float(vals.max()), "std": float(vals.std(ddof=0)),
                "sum": float(vals.sum())})
    for key in ("start", "end", "n"):
        if got[key] != spec[key]:
            raise Fail(f"obs contract [{split}] {key}: got {got[key]!r}, "
                       f"contract {spec[key]!r}")
    for key in ("mean", "min", "max", "std", "sum"):
        if not math.isclose(got[key], spec[key], rel_tol=OBS_RTOL, abs_tol=0.0):
            raise Fail(f"obs contract [{split}] {key}: got {got[key]!r}, "
                       f"contract {spec[key]!r}")
    # Contiguity: the declared window must be gap-free (blocked temporal split).
    expected_n = (SPLITS[split][1] - SPLITS[split][0]).days + 1
    if len(days) != expected_n:
        raise Fail(f"obs contract [{split}]: {len(days)} days present but the "
                   f"window spans {expected_n} days (gaps not allowed)")
    return got


# ---------------------------------------------------------------------------
# Candidate vector
# ---------------------------------------------------------------------------
def load_candidate() -> dict:
    path = os.environ.get("KDT_CALIB_PARAMS")
    if not path:
        return {}
    try:
        raw = json.loads(Path(path).read_text())
    except Exception as exc:
        raise Fail(f"cannot read KDT_CALIB_PARAMS={path!r}: {exc}")
    if not isinstance(raw, dict):
        raise Fail(f"KDT_CALIB_PARAMS={path!r} is not a JSON object")
    unknown = sorted(set(raw) - set(PARAM_REGISTRY))
    if unknown:
        raise Fail(f"handed parameter(s) this driver cannot inject: {unknown}")
    out = {}
    for name, val in raw.items():
        try:
            fval = float(val)
        except (TypeError, ValueError):
            raise Fail(f"parameter {name} value {val!r} is not numeric")
        if not math.isfinite(fval):
            raise Fail(f"parameter {name} value {val!r} is not finite")
        out[name] = fval
    return out


def build_baseline(local_info: dict, basin_info: dict) -> tuple[dict, dict]:
    """(hru_baseline, gru_baseline) -- the parameter state of the VALIDATED run."""
    trial = CASE_SETTINGS / "trialParams.nc"
    if not trial.is_file():
        raise Fail(f"validated trialParams.nc missing: {trial}")
    hru = {}
    with nc.Dataset(trial) as ds:
        n_hru = len(ds.dimensions["hru"])
        for name, var in ds.variables.items():
            if name in ("hruId", "gruId") or var.dimensions != ("hru",):
                continue
            arr = np.asarray(var[:], dtype=float)
            if arr.size != n_hru:
                raise Fail(f"{trial}: {name} has {arr.size} values for {n_hru} HRUs")
            if float(arr.max() - arr.min()) != 0.0:
                raise Fail(f"{trial}: {name} is not uniform across HRUs; this "
                           "driver injects lumped (uniform) values only")
            hru[name] = float(arr[0])
    for name, meta in PARAM_REGISTRY.items():
        if meta["source"] == "local" and name not in hru:
            if name not in local_info:
                raise Fail(f"localParamInfo.txt has no default for {name}")
            hru[name] = float(local_info[name][0])
    gru = {}
    for name, meta in PARAM_REGISTRY.items():
        if meta["scope"] != "gru":
            continue
        if name not in basin_info:
            raise Fail(f"basinParamInfo.txt has no default for {name}")
        gru[name] = float(basin_info[name][0])
    return hru, gru


# ---------------------------------------------------------------------------
# Workdir staging + injection through the KI's own tools
# ---------------------------------------------------------------------------
def stage_run_dir(run_dir: Path) -> tuple[Path, Path, Path]:
    settings = run_dir / "site_settings"
    forcing = run_dir / "forcing"
    output = run_dir / "output"
    for d in (settings, forcing, output):
        d.mkdir(parents=True, exist_ok=True)

    for fname in ("attributes.nc", "decisions.txt", "coldState.nc"):
        src = CASE_SETTINGS / fname
        if not src.is_file():
            raise Fail(f"validated staged input missing: {src}")
        shutil.copy2(src, settings / fname)

    for tbl in ("VEGPARM.TBL", "SOILPARM.TBL", "GENPARM.TBL", "MPTABLE.TBL",
                "localParamInfo.txt", "basinParamInfo.txt"):
        src = BASE_SETTINGS / tbl
        if not src.is_file():
            raise Fail(f"SUMMA base settings file missing: {src}")
        dst = settings / tbl
        if not dst.exists():
            dst.symlink_to(src)

    # Lean outputControl: output SELECTION is not a physics choice, and trimming
    # it cuts ~20 s of NetCDF write per evaluation.
    (settings / "outputControl.txt").write_text(
        "! outputControl.txt -- calibration driver (calib_run.py)\n"
        + "".join(f"{v:<26}| 1\n" for v in OUTPUT_CONTROL_VARS))

    src_forcing = CASE_FORCING / FORCING_NC
    if not src_forcing.is_file():
        raise Fail(f"validated forcing missing: {src_forcing}")
    link = forcing / FORCING_NC
    if not link.exists():
        link.symlink_to(src_forcing)
    (settings / "forcingFileList.txt").write_text(f"! forcing file list\n{FORCING_NC}\n")
    return settings, forcing, output


def _run_tool(argv, what):
    proc = subprocess.run(argv, capture_output=True, text=True)
    if proc.returncode != 0:
        raise Fail(f"KI tool {what} failed rc={proc.returncode}\n"
                   f"STDOUT: {proc.stdout[-2000:]}\nSTDERR: {proc.stderr[-2000:]}", code=2)
    return proc


def inject_parameters(settings: Path, hru_vals: dict, gru_vals: dict) -> Path:
    """Write the candidate through the KI's OWN s4 tool.  Returns trialParams.nc."""
    trial = settings / "trialParams.nc"
    _run_tool([sys.executable, str(TOOLS / "s4_parameters" / "set_trial_parameters.py"),
               "--attributes_nc", str(settings / "attributes.nc"),
               "--output_nc", str(trial),
               "--parameters", json.dumps(hru_vals),
               "--basin_parameters", json.dumps(gru_vals)],
              "set_trial_parameters.py")
    if not trial.is_file():
        raise Fail("set_trial_parameters.py produced no trialParams.nc", code=2)
    return trial


def read_back(trial: Path, names) -> dict:
    """Read each parameter BACK from the artifact SUMMA opens."""
    out = {}
    with nc.Dataset(trial) as ds:
        for name in names:
            scope = PARAM_REGISTRY[name]["scope"]
            if name not in ds.variables:
                raise Fail(f"{name} absent from the written trialParams.nc")
            var = ds.variables[name]
            if var.dimensions != (scope,):
                raise Fail(f"{name} written on dims {var.dimensions}, expected ('{scope}',)")
            arr = np.asarray(var[:], dtype=float)
            if arr.size == 0:
                raise Fail(f"{name} written empty in trialParams.nc")
            if float(arr.max() - arr.min()) != 0.0:
                raise Fail(f"{name} is not uniform across the {scope} dimension")
            out[name] = float(arr[0])
    return out


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------
def run_summa(run_dir: Path, settings: Path, forcing: Path, output: Path) -> Path:
    fm = run_dir / "fileManager.txt"
    _run_tool([sys.executable, str(TOOLS / "s6_execution" / "create_file_manager.py"),
               "--settings_path", str(settings) + "/", "--forcing_path", str(forcing) + "/",
               "--output_path", str(output) + "/",
               "--sim_start", SIM_START.strftime("%Y-%m-%d %H:%M"),
               "--sim_end", SIM_END.strftime("%Y-%m-%d %H:%M"),
               "--output_prefix", OUTPUT_PREFIX, "--output_file", str(fm),
               "--decisions", "decisions.txt", "--attributes", "attributes.nc",
               "--init_cond", "coldState.nc", "--trial_params", "trialParams.nc",
               "--forcing_list", "forcingFileList.txt"],
              "create_file_manager.py")
    _run_tool([sys.executable, str(TOOLS / "s6_execution" / "validate_file_manager.py"),
               "--file_manager", str(fm)],
              "validate_file_manager.py")
    # No --log_file: run_summa.py only inspects SUMMA's return code / STOP codes
    # when it is NOT redirecting to a log, so we keep that check live and capture
    # the transcript ourselves.
    proc = subprocess.run(
        [sys.executable, str(TOOLS / "s6_execution" / "run_summa.py"),
         "--summa_exe", SUMMA_EXE, "--file_manager", str(fm)],
        capture_output=True, text=True)
    transcript = (proc.stdout or "") + (proc.stderr or "")
    (run_dir / "summa_run.log").write_text(transcript)
    if proc.returncode != 0:
        raise Fail(f"run_summa.py failed rc={proc.returncode}; "
                   f"tail:\n{transcript[-2000:]}", code=2)
    # FAIL-CLOSED run health: SUMMA's own normal-termination marker must be
    # present.  Absent/unreadable is a failure, never defaulted to "fine".
    if SUMMA_OK_MARKER not in transcript:
        raise Fail("SUMMA did not report normal termination "
                   f"({SUMMA_OK_MARKER!r} absent from the run transcript)", code=2)
    outs = sorted(output.glob(f"{OUTPUT_PREFIX}_*.nc"))
    if len(outs) != 1:
        raise Fail(f"expected exactly 1 SUMMA output NetCDF in {output}, found "
                   f"{[p.name for p in outs]}", code=2)
    return outs[0]


def extract_simulated(out_nc: Path, area_m2: float) -> dict:
    """Daily-mean discharge (m3/s) from averageRoutedRunoff x basin area."""
    expected_steps = int((SIM_END - SIM_START).total_seconds() // 3600) + 1
    with nc.Dataset(out_nc) as ds:
        n_time = len(ds.dimensions["time"])
        if n_time != expected_steps:
            raise Fail(f"SUMMA output has {n_time} timesteps, the configured "
                       f"{SIM_START}..{SIM_END} window needs {expected_steps} "
                       "-- the run did not complete", code=2)
        if "averageRoutedRunoff" not in ds.variables:
            raise Fail("averageRoutedRunoff absent from the SUMMA output "
                       "(subRouting = timeDlay is required)", code=2)
        var = ds.variables["averageRoutedRunoff"]
        if var.dimensions != ("time", "gru"):
            raise Fail(f"averageRoutedRunoff dims {var.dimensions} != ('time','gru')", code=2)
        if len(ds.dimensions["gru"]) != 1:
            raise Fail("this driver scores a single-GRU lumped domain", code=2)
        ro = np.asarray(var[:, 0], dtype=float)
        tvar = ds.variables["time"]
        times = nc.num2date(tvar[:], tvar.units,
                            calendar=getattr(tvar, "calendar", "standard"),
                            only_use_cftime_datetimes=False)
    if not np.all(np.isfinite(ro)):
        raise Fail("averageRoutedRunoff contains non-finite values", code=2)
    q = ro * area_m2                        # m s-1 * m2 -> m3 s-1
    daily_sum, daily_n = {}, {}
    for t, v in zip(times, q):
        day = dt.date(t.year, t.month, t.day)
        daily_sum[day] = daily_sum.get(day, 0.0) + float(v)
        daily_n[day] = daily_n.get(day, 0) + 1
    return {d: daily_sum[d] / daily_n[d] for d in daily_sum}


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def resolve_split() -> str:
    """Mirror calibration_kit.evaluator.resolve_train_split: only the two
    declared splits are honored; anything else trains on `calibration`."""
    raw = (os.environ.get("KDT_CALIB_SPLIT") or "").strip().lower()
    return raw if raw in SPLITS else "calibration"


def main() -> int:
    ap = argparse.ArgumentParser(description="SUMMA calibration run+score (HYDAT 08NH120)")
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out)
    if out_path.exists():
        out_path.unlink()            # never leave a stale metrics file readable

    split = resolve_split()
    local_info = read_param_info(BASE_SETTINGS / "localParamInfo.txt")
    basin_info = read_param_info(BASE_SETTINGS / "basinParamInfo.txt")

    # ---- obs first: resolve + assert the gauge and its envelope -------------
    with _connect_hydat() as conn:
        station = resolve_station(conn, STATION_NUMBER)
        w_start, w_end = SPLITS[split]
        obs = load_daily_flows(conn, station["station_number"], w_start, w_end)
    obs_stats = assert_obs_contract(obs, split)
    if w_start <= SPINUP_THROUGH:
        raise Fail(f"split {split} overlaps the {SPINUP_THROUGH.year} spinup year")

    # Discharge conversion comes from the SAME HYDAT row that supplied the obs.
    area_m2 = station["drainage_area_km2"] * 1.0e6
    scored_obs = (f"HYDAT:{station['station_number']} {station['station_name']} | "
                  f"{HYDAT_DB}:DLY_FLOWS | split={split} "
                  f"{obs_stats['start']}..{obs_stats['end']} n={obs_stats['n']}")

    # ---- candidate vector --------------------------------------------------
    candidate = load_candidate()
    hru_base, gru_base = build_baseline(local_info, basin_info)
    with nc.Dataset(CASE_SETTINGS / "attributes.nc") as ds:
        model_area_m2 = float(np.asarray(ds.variables["HRUarea"][:], dtype=float).sum())
    if not math.isclose(model_area_m2, area_m2, rel_tol=1e-6, abs_tol=0.0):
        raise Fail(f"model domain area {model_area_m2:.1f} m2 != HYDAT gross drainage "
                   f"area {area_m2:.1f} m2 for {station['station_number']}")

    hru_vals = dict(hru_base)
    gru_vals = dict(gru_base)
    for name, val in candidate.items():
        if PARAM_REGISTRY[name]["scope"] == "gru":
            gru_vals[name] = val
        else:
            hru_vals[name] = val

    # ---- stage, inject, run ------------------------------------------------
    eval_id = re.sub(r"[^A-Za-z0-9_.-]", "_", os.environ.get("KDT_CALIB_EVAL_ID", "manual"))
    run_dir = workdir / "_evals" / f"eval_{eval_id}_{os.getpid()}"
    if run_dir.exists():
        shutil.rmtree(run_dir, ignore_errors=True)
    keep = os.environ.get("KDT_CALIB_KEEP_EVAL") == "1"
    try:
        settings, forcing, output = stage_run_dir(run_dir)
        trial = inject_parameters(settings, hru_vals, gru_vals)

        # Read every value BACK from the artifact SUMMA consumes.  Echo EVERY key
        # we were handed (including staged-frozen defaults); mismatch -> no metrics.
        echo_names = sorted(candidate) if candidate else sorted(PARAM_REGISTRY)
        applied = read_back(trial, echo_names)
        requested = {n: (candidate[n] if n in candidate
                         else (gru_vals[n] if PARAM_REGISTRY[n]["scope"] == "gru"
                               else hru_vals[n]))
                     for n in echo_names}
        for name in echo_names:
            got, want = applied[name], requested[name]
            if not math.isfinite(got):
                raise Fail(f"{name} read back non-finite ({got!r})")
            if want != 0.0 and got == 0.0:
                raise Fail(f"{name} read back 0.0 for requested {want!r} (clamped)")
            if not math.isclose(got, want, rel_tol=READBACK_RTOL, abs_tol=0.0):
                raise Fail(f"{name} applied {got!r} != requested {want!r} "
                           "(value did not survive injection)")

        out_nc = run_summa(run_dir, settings, forcing, output)
        sim = extract_simulated(out_nc, area_m2)
    except Fail:
        keep = True
        raise
    finally:
        if run_dir.exists() and not keep:
            shutil.rmtree(run_dir, ignore_errors=True)

    # ---- score -------------------------------------------------------------
    days = sorted(set(sim) & set(obs))
    if len(days) != obs_stats["n"]:
        raise Fail(f"{len(days)} paired days but the {split} obs window has "
                   f"{obs_stats['n']} -- simulation does not cover the window", code=3)
    o = np.array([obs[d] for d in days], dtype=float)
    s = np.array([sim[d] for d in days], dtype=float)
    if not np.all(np.isfinite(s)):
        raise Fail("simulated series contains non-finite values", code=3)
    m = all_metrics(o, s)
    metrics = {
        "nse": float(m["NSE"]), "kge": float(m["KGE"]), "pbias": float(m["PBIAS"]),
        "r": float(m["r"]), "rmse": float(m["RMSE"]),
    }
    for key, val in metrics.items():
        if not math.isfinite(val):
            raise Fail(f"metric {key} is not finite ({val!r})", code=3)

    metrics["__kdt__"] = {
        "applied_params": applied,
        "case_id": CASE_ID,
        "scored_obs": scored_obs,
        "split": split,
        "n_paired_days": len(days),
        "target_var": "scalarTotalRunoff",
        "scored_series": "averageRoutedRunoff x basin area (m3 s-1, daily mean)",
        "station": station,
        "basin_area_m2": area_m2,
        "obs_stats": obs_stats,
        "summa_normal_termination": True,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(metrics, indent=2))
    print(json.dumps({k: v for k, v in metrics.items() if k != "__kdt__"}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Fail as exc:
        print(f"calib_run: FAIL: {exc}", file=sys.stderr)
        sys.exit(exc.code)
    except Exception as exc:  # noqa: BLE001 - any surprise must fail closed
        import traceback
        traceback.print_exc()
        print(f"calib_run: FAIL (unexpected): {exc}", file=sys.stderr)
        sys.exit(2)
