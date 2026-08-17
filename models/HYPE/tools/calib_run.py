#!/usr/bin/env python3
"""
HYPE calibration driver — programmatic run+score for ONE candidate parameter vector.

TARGET CASE (pinned, not configurable):
    case_id      OBS:grdc_asia_discharge_daily_20260511
    gauge / obs  GRDC 2178951 — CHANGTAIGUAN, HUAI HE, CN (32.314167N, 114.060556E),
                 catchment 3090.0 km2; GRDC Asia-Region Daily Discharge Export
                 (250 stations, 2026-05-11 download)
    obs file     <DATA>/china_data/GRDC_asia_discharge_daily_20260511/2178951_Q_Day.Cmd.txt
    quantity     discharge — dag var `cout`, obs_shape point_time_series, metric NSE
    provenance   HYPE_20260717T014155Z  (validated real_case: full NSE 0.1404)

Usage:
    python3 calib_run.py --workdir <wd> --out <metrics.json>

INJECTION MODE: runner (calibration.yaml `injection.mode: runner`).
The candidate vector is read from the JSON at env KDT_CALIB_PARAMS, injected into
HYPE's par.txt (a model-specific class-indexed text deck that this driver REGENERATES
from scratch every eval — a value written before the run would be overwritten), read
BACK out of the par.txt the HYPE binary actually opens, and echoed in __kdt__.

The model itself is run through the KI's OWN tools — nothing is reimplemented:
    tools/s10_calibration/setup_calibration.py :: read_geoclass   (nlanduse / nsoil)
    tools/s7_execution/run_hype.py            :: run_hype         (execute the binary)
    tools/s8_output_analysis/parse_hype_output.py :: parse_hype_timeseries (read timeCOUT)
    ki_tools_common.metrics                   :: all_metrics      (gate metrics)

Splits (env KDT_CALIB_SPLIT), identical to the validated run's windows:
    "calibration" -> 1981-01-01 .. 1985-12-31
    "holdout"     -> 1986-01-01 .. 1990-12-31
    unset / "full"-> 1981-01-01 .. 1990-12-31   (the window the 0.1404 headline scored)
1980 is HYPE warmup and is never scored.

FAIL-CLOSED: any obs-contract violation, staging problem, non-normal HYPE termination,
missing/short/NaN output, or a parameter that does not read back EXACTLY as requested
=> no metrics file is written and the process exits nonzero (the kit scores +inf).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------- fixed paths
ROOT = "KISSPATH_ROOT"
KI = f"{ROOT}/models/HYPE/knowledge_infrastructure"
TOOLS = f"{KI}/tools"
HYPE_BIN = f"{ROOT}/model/hype/hype"

# canonical ki_tools_common FIRST (a kdt-release copy elsewhere on sys.path would shadow it)
for _p in (f"{ROOT}/models/ki_tools_common",
           "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect_multi_agent"):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from ki_tools_common.metrics import all_metrics          # noqa: E402

# ------------------------------------------------------------- TARGET CASE (pinned)
CASE_ID = "OBS:grdc_asia_discharge_daily_20260511"
OBS_DATASET = "grdc_asia_discharge_daily_20260511"
OBS_FILE = (f"{ROOT}/data/china_data/GRDC_asia_discharge_daily_20260511/"
            "2178951_Q_Day.Cmd.txt")

# --- the obs ENVELOPE this contract declares; every field below is ASSERTED on load,
#     so a changed / corrupted / substituted series for the same station cannot be
#     silently scored (see calibration.yaml `obs_contract`).
OBS_GRDC_NO = 2178951
OBS_RIVER = "HUAI HE"
OBS_STATION = "CHANGTAIGUAN"
OBS_COUNTRY = "CN"
OBS_LAT = 32.314167
OBS_LON = 114.060556
OBS_AREA_KM2 = 3090.0
OBS_UNIT = "m3/s"                 # header carries the latin-1 superscript form
OBS_CONTENT = "MEAN DAILY DISCHARGE (Q)"
OBS_MISSING = -999.0
OBS_DATA_LINES = 7183             # "# Data lines:" in the header == rows actually parsed
OBS_ENVELOPE = {                  # over 1981-01-01..1990-12-31, missing days dropped
    "n_valid_days": 3652,
    "min": 0.0,
    "max": 2930.0,
    "mean": 36.9363,
    "sum": 134891.2,
}
OBS_ENV_TOL = {"min": 1e-6, "max": 1e-6, "mean": 5e-3, "sum": 5.0}

# --- the model domain this case's staged deck must describe
SUBID = 1
AREA_M2 = 3.09e9
WARMUP_START = "1980-01-01"       # HYPE bdate; never scored
SIM_START = "1980-12-31"          # HYPE cdate (first output row)
SIM_END = "1990-12-31"
SPLITS = {
    "full":        ("1981-01-01", "1990-12-31"),
    "calibration": ("1981-01-01", "1985-12-31"),
    "holdout":     ("1986-01-01", "1990-12-31"),
}
N_SIM_ROWS = 3653                 # 1980-12-31 .. 1990-12-31 inclusive

# --- staged deck produced by the validated real_case run (one-time prepare, never per eval)
TEMPLATE_CANDIDATES = [
    os.environ.get("KDT_HYPE_TEMPLATE") or "",
    "KISSPATH_HOME/hype_changtaiguan_run",
]

READBACK_RTOL = 1e-9

# ------------------------------------------------------------- parameter definition
# (name, kind) — kind decides how many values the par.txt line carries.
#   'landuse' -> nlanduse values, 'soil' -> nsoil values, 'general' -> 1 value.
# Each calibrated scalar is written IDENTICALLY into every class of its line
# (scope: global in calibration.yaml) and read back from column 1.
PARAM_KIND = {
    "ttmp": "landuse", "cmlt": "landuse", "cevp": "landuse", "srrcs": "landuse",
    "wcfc": "soil", "wcwp": "soil", "wcep": "soil", "rrcs1": "soil", "rrcs2": "soil",
    "rrcs3": "general", "lp": "general", "rivvel": "general", "damp": "general",
    "cevpam": "general", "cevpph": "general",
}
# par.txt line order (HYPE is order-insensitive; kept identical to the validated deck)
PAR_ORDER = ["ttmp", "cmlt", "srrcs", "cevp",
             "wcfc", "wcwp", "wcep", "rrcs1", "rrcs2",
             "rrcs3", "lp", "rivvel", "damp", "cevpam", "cevpph"]

# DEFAULTS — the validated real_case par.txt collapsed to one value per parameter by
# SLC-area weighting (see calibration.yaml `parameters[].default`). MUST stay in sync
# with calibration.yaml.
DEFAULTS = {
    "ttmp": 0.0,
    "cmlt": 3.75,
    "srrcs": 0.029,
    "cevp": 0.286,
    "wcfc": 0.295,
    "wcwp": 0.108,
    "wcep": 0.438,
    "rrcs1": 0.0264,
    "rrcs2": 0.00215,
    "rrcs3": 0.0004,
    "lp": 0.9,
    "rivvel": 1.0,
    "damp": 0.5,
    "cevpam": 0.42,
    "cevpph": 30.0,
}


class Fail(RuntimeError):
    """Any condition that must produce NO metrics file and a nonzero exit."""


def log(msg):
    print(f"[calib_run] {msg}", flush=True)


# ------------------------------------------------------------- KI tool loading
def _load_ki_module(name, relpath):
    spec = importlib.util.spec_from_file_location(name, f"{TOOLS}/{relpath}")
    if spec is None or spec.loader is None:
        raise Fail(f"cannot load KI tool {relpath}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------- obs (READ-ONLY)
def load_obs():
    """Read the pinned GRDC series and ASSERT every declared obs-envelope field.

    The file is an immutable data source and is opened READ-ONLY ("r"); nothing here
    writes to it. Returns (series_over_1981_1990, header_dict).
    """
    if not os.path.isfile(OBS_FILE):
        raise Fail(f"obs file missing: {OBS_FILE}")

    header, dates, vals, n_lines = {}, [], [], 0
    with open(OBS_FILE, "r", encoding="latin-1") as fh:          # READ-ONLY
        for line in fh:
            line = line.rstrip("\r\n")
            if line.startswith("#"):
                body = line[1:].strip()
                if ":" in body:
                    k, _, v = body.partition(":")
                    header.setdefault(k.strip(), v.strip())
                continue
            if not line.strip() or line.startswith("YYYY"):
                continue
            parts = line.split(";")
            if len(parts) < 3:
                continue
            n_lines += 1
            try:
                d = pd.Timestamp(parts[0].strip())
                v = float(parts[2])
            except (ValueError, TypeError):
                raise Fail(f"unparseable GRDC data row: {line!r}")
            dates.append(d)
            vals.append(np.nan if v <= OBS_MISSING else v)

    def _hdr(key):
        v = header.get(key)
        if v is None:
            raise Fail(f"obs header field {key!r} absent — obs contract cannot be verified")
        return v

    def _num(key):
        try:
            return float(_hdr(key))
        except ValueError:
            raise Fail(f"obs header field {key!r} is not numeric: {_hdr(key)!r}")

    # --- station identity ----------------------------------------------------
    if int(_num("GRDC-No.")) != OBS_GRDC_NO:
        raise Fail(f"obs GRDC-No. {_hdr('GRDC-No.')} != target {OBS_GRDC_NO}")
    if _hdr("River").upper() != OBS_RIVER:
        raise Fail(f"obs River {_hdr('River')!r} != target {OBS_RIVER!r}")
    if _hdr("Station").upper() != OBS_STATION:
        raise Fail(f"obs Station {_hdr('Station')!r} != target {OBS_STATION!r}")
    if _hdr("Country").upper() != OBS_COUNTRY:
        raise Fail(f"obs Country {_hdr('Country')!r} != target {OBS_COUNTRY!r}")

    # --- georeference + catchment area ---------------------------------------
    if abs(_num("Latitude (DD)") - OBS_LAT) > 1e-4:
        raise Fail(f"obs latitude {_hdr('Latitude (DD)')} != target {OBS_LAT}")
    if abs(_num("Longitude (DD)") - OBS_LON) > 1e-4:
        raise Fail(f"obs longitude {_hdr('Longitude (DD)')} != target {OBS_LON}")
    area_key = next((k for k in header if k.startswith("Catchment area")), None)
    if area_key is None:
        raise Fail("obs header has no 'Catchment area' field")
    if abs(float(header[area_key]) - OBS_AREA_KM2) > 0.5:
        raise Fail(f"obs catchment area {header[area_key]} != target {OBS_AREA_KM2} km2")

    # --- quantity + units ----------------------------------------------------
    content = _hdr("Data Set Content").upper()
    if OBS_CONTENT not in content:
        raise Fail(f"obs content {content!r} is not {OBS_CONTENT!r}")
    unit_raw = _hdr("Unit of measure")
    if unit_raw.replace("\xb3", "3").replace("^3", "3").strip() != OBS_UNIT:
        raise Fail(f"obs unit {unit_raw!r} != target {OBS_UNIT!r}")

    # --- record completeness --------------------------------------------------
    declared = int(_num("Data lines"))
    if declared != OBS_DATA_LINES or n_lines != OBS_DATA_LINES:
        raise Fail(f"obs record size changed: header declares {declared}, parsed "
                   f"{n_lines}, contract expects {OBS_DATA_LINES}")

    s = pd.Series(vals, index=pd.DatetimeIndex(dates)).sort_index()
    if s.index.duplicated().any():
        raise Fail("obs series has duplicated dates")
    s = s.dropna()
    w = s[(s.index >= SPLITS["full"][0]) & (s.index <= SPLITS["full"][1])]

    # --- the exact scored series envelope -------------------------------------
    got = {"n_valid_days": int(len(w)), "min": float(w.min()) if len(w) else float("nan"),
           "max": float(w.max()) if len(w) else float("nan"),
           "mean": float(w.mean()) if len(w) else float("nan"),
           "sum": float(w.sum()) if len(w) else float("nan")}
    if got["n_valid_days"] != OBS_ENVELOPE["n_valid_days"]:
        raise Fail(f"obs valid-day count {got['n_valid_days']} != declared "
                   f"{OBS_ENVELOPE['n_valid_days']} over {SPLITS['full']}")
    for k, tol in OBS_ENV_TOL.items():
        if not math.isfinite(got[k]) or abs(got[k] - OBS_ENVELOPE[k]) > tol:
            raise Fail(f"obs envelope {k}={got[k]} != declared {OBS_ENVELOPE[k]} "
                       f"(tol {tol}) — the scored series is not the validated one")

    header["_resolved_grdc_no"] = OBS_GRDC_NO
    header["_resolved_station"] = OBS_STATION
    header["_resolved_river"] = OBS_RIVER
    header["_resolved_lat"] = OBS_LAT
    header["_resolved_lon"] = OBS_LON
    header["_envelope"] = got
    return w, header


# ------------------------------------------------------------- staging
def _read_geodata(path):
    df = pd.read_csv(path, sep="\t", dtype=str)
    if len(df) != 1:
        raise Fail(f"{path}: expected the lumped 1-subbasin deck, got {len(df)} rows")
    return df


def resolve_template():
    """Find the staged, validated HYPE deck and PROVE it describes the target gauge."""
    tried = []
    for cand in TEMPLATE_CANDIDATES:
        if not cand:
            continue
        tried.append(cand)
        gd = Path(cand) / "modelfiles" / "GeoData.txt"
        if not gd.is_file():
            continue
        df = _read_geodata(gd)
        lat, lon = float(df.loc[0, "LATITUDE"]), float(df.loc[0, "LONGITUDE"])
        area, sub = float(df.loc[0, "AREA"]), int(float(df.loc[0, "SUBID"]))
        # A template supplied via env MUST be this case's basin — never let the
        # environment redirect the run to a different site.
        if abs(lat - OBS_LAT) > 1e-3 or abs(lon - OBS_LON) > 1e-3:
            raise Fail(f"staged deck {cand} is at {lat},{lon} but the target case "
                       f"{CASE_ID} is GRDC {OBS_GRDC_NO} at {OBS_LAT},{OBS_LON}")
        if abs(area - AREA_M2) > 1e6 or sub != SUBID:
            raise Fail(f"staged deck {cand}: AREA {area} m2 / SUBID {sub} != target "
                       f"{AREA_M2} m2 / SUBID {SUBID}")
        return Path(cand)
    raise Fail("no staged HYPE deck for the target case. Expected modelfiles/GeoData.txt "
               f"under one of {tried}. Regenerate it once with "
               f"`python3 {ROOT}/models/HYPE/run_and_score.py` (resumable), or point "
               "KDT_HYPE_TEMPLATE at the deck for GRDC 2178951.")


def stage_case(workdir, template, obs):
    """Copy the validated deck into this eval's workdir (once) and rewrite Qobs from
    the PINNED obs. Everything except par.txt is identical to the validated run."""
    run = Path(workdir) / "hype_case"
    for sub in ("modelfiles", "forcingdir", "resultdir", "logdir"):
        (run / sub).mkdir(parents=True, exist_ok=True)

    stamp = run / ".staged_from"
    already = stamp.is_file() and stamp.read_text().strip() == str(template)
    if not already:
        for rel in ("modelfiles/GeoClass.txt", "modelfiles/GeoData.txt",
                    "forcingdir/Pobs.txt", "forcingdir/Tobs.txt",
                    "forcingdir/ForcKey.txt", "info.txt"):
            src = template / rel
            if not src.is_file():
                if rel.endswith("ForcKey.txt"):
                    continue                      # optional for a 1-subbasin deck
                raise Fail(f"staged deck is incomplete: {src} missing")
            shutil.copy2(src, run / rel)
        stamp.write_text(str(template))

    # forcing must cover the whole simulation window — HYPE does not gap-fill
    for f in ("Pobs.txt", "Tobs.txt"):
        d = pd.read_csv(run / "forcingdir" / f, sep="\t")
        idx = pd.to_datetime(d["DATE"])
        if idx.min() > pd.Timestamp(WARMUP_START) or idx.max() < pd.Timestamp(SIM_END):
            raise Fail(f"{f} covers {idx.min().date()}..{idx.max().date()}, needs "
                       f"{WARMUP_START}..{SIM_END}")

    # Qobs rebuilt from the pinned GRDC series every stage, so the deck the binary
    # reads can only ever carry THIS gauge's observations.
    with open(run / "forcingdir" / "Qobs.txt", "w") as fh:
        fh.write(f"DATE\t{SUBID}\n")
        for d, q in zip(obs.index, obs.values):
            fh.write(f"{d.strftime('%Y-%m-%d')}\t{q:.3f}\n")
    return run


# ------------------------------------------------------------- par.txt inject/read-back
def _fmt(v):
    """Full-precision, round-trippable text for a par.txt value."""
    return f"{float(v):.10g}"


def write_par(run, values, nlanduse, nsoil):
    lines = ["!! par.txt written by knowledge_infrastructure/tools/calib_run.py",
             f"!! target case {CASE_ID} — GRDC {OBS_GRDC_NO} {OBS_STATION}, {OBS_RIVER}",
             "!! one calibrated scalar per parameter, replicated over every "
             "land-use / soil class (scope: global)"]
    for name in PAR_ORDER:
        kind = PARAM_KIND[name]
        n = {"landuse": nlanduse, "soil": nsoil, "general": 1}[kind]
        lines.append("\t".join([name] + [_fmt(values[name])] * n))
    (run / "modelfiles" / "par.txt").write_text("\n".join(lines) + "\n")


def read_par(run):
    """Read the values back out of the EXACT par.txt the HYPE binary opens."""
    out = {}
    path = run / "modelfiles" / "par.txt"
    if not path.is_file():
        raise Fail("par.txt vanished before read-back")
    for line in path.read_text().splitlines():
        if line.startswith("!!") or not line.strip():
            continue
        cols = line.split()
        if len(cols) < 2 or cols[0] not in PARAM_KIND:
            continue
        vals = [float(c) for c in cols[1:]]
        if len(set(vals)) != 1:
            raise Fail(f"par.txt {cols[0]} is not uniform across classes: {vals}")
        out[cols[0]] = vals[0]
    return out


# ------------------------------------------------------------- run health
def run_model(run):
    """Execute HYPE through the KI's own s7 run tool and FAIL CLOSED on any
    run-health diagnostic that is missing or negative."""
    runner = _load_ki_module("hype_run_tool", "s7_execution/run_hype.py")
    for stale in (run / "resultdir").glob("time*.txt"):
        stale.unlink()
    for stale in list(run.glob("hyss_*.log")) + list((run / "logdir").glob("hyss_*.log")):
        stale.unlink()

    t0 = time.time()
    ok, msg = runner.run_hype(str(run) + "/", hype_binary=HYPE_BIN, timeout=1800)
    if not ok:
        raise Fail(f"HYPE run failed: {msg}")

    # normal termination — HYPE writes 'Job finished date:' only on a clean exit.
    log_path = runner.find_latest_log(str(run))
    if not log_path:
        raise Fail("HYPE produced no hyss_*.log — cannot verify normal termination")
    text = Path(log_path).read_text(errors="replace")
    if "Job finished date:" not in text:
        raise Fail(f"HYPE log {log_path} has no 'Job finished date:' — abnormal termination")
    errors, _warn = runner.parse_log_for_errors(log_path)
    if errors:
        raise Fail(f"HYPE log reports errors: {errors[:3]}")
    log(f"HYPE ok in {time.time() - t0:.1f}s")
    return log_path


def load_sim(run):
    parser = _load_ki_module("hype_parse_tool", "s8_output_analysis/parse_hype_output.py")
    f = run / "resultdir" / "timeCOUT.txt"
    if not f.is_file():
        raise Fail("timeCOUT.txt not produced")
    df, meta = parser.parse_hype_timeseries(str(f))     # (DataFrame[DATE index], header meta)
    if df is None or len(df) == 0:
        raise Fail("timeCOUT.txt parsed empty")
    if str(meta.get("variable", "cout")).lower() != "cout":
        raise Fail(f"timeCOUT.txt declares variable={meta.get('variable')!r}, expected 'cout'")
    if str(meta.get("unit", "m3/s")).lower() not in ("m3/s", "m^3/s"):
        raise Fail(f"timeCOUT.txt declares unit={meta.get('unit')!r}, expected m3/s")
    if str(SUBID) in df.columns:
        s = df[str(SUBID)]
    elif SUBID in df.columns:
        s = df[SUBID]
    else:
        cols = [c for c in df.columns if str(c).upper() != "DATE"]
        if len(cols) != 1:
            raise Fail(f"cannot identify SUBID {SUBID} column in timeCOUT.txt: {list(df.columns)}")
        s = df[cols[0]]
    s = pd.Series(np.asarray(s, dtype=float), index=pd.DatetimeIndex(df.index)).sort_index()

    if len(s) != N_SIM_ROWS:
        raise Fail(f"timeCOUT.txt has {len(s)} rows, expected {N_SIM_ROWS} "
                   f"({SIM_START}..{SIM_END})")
    if s.index[0] != pd.Timestamp(SIM_START) or s.index[-1] != pd.Timestamp(SIM_END):
        raise Fail(f"timeCOUT.txt spans {s.index[0].date()}..{s.index[-1].date()}, "
                   f"expected {SIM_START}..{SIM_END}")
    if not np.isfinite(s.values).all():
        raise Fail("simulated discharge contains non-finite values")
    if float(np.nanmax(s.values)) <= 0.0:
        raise Fail("simulated discharge is everywhere <= 0 — degenerate run")
    return s


# ------------------------------------------------------------- scoring
def score(obs, sim, a, b):
    m = pd.DataFrame({"obs": obs, "sim": sim}).dropna()
    m = m[(m.index >= pd.Timestamp(a)) & (m.index <= pd.Timestamp(b))]
    if len(m) < 30:
        raise Fail(f"only {len(m)} paired days in {a}..{b}")
    r = all_metrics(m["obs"].values, m["sim"].values)
    return {"nse": float(r["NSE"]), "kge": float(r["KGE"]), "pbias": float(r["PBIAS"]),
            "rmse": float(r["RMSE"]), "r": float(r["r"]), "n": int(len(m))}


# ------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    out = Path(args.out)
    if out.exists():
        out.unlink()                     # never let a stale file be read as this eval

    # 1) candidate vector -----------------------------------------------------
    handed = {}
    pf = os.environ.get("KDT_CALIB_PARAMS")
    if pf:
        if not os.path.isfile(pf):
            raise Fail(f"KDT_CALIB_PARAMS points at a missing file: {pf}")
        with open(pf, "r") as fh:                              # READ-ONLY
            handed = json.load(fh)
        if not isinstance(handed, dict):
            raise Fail("KDT_CALIB_PARAMS JSON is not an object")
    unknown = sorted(set(handed) - set(PARAM_KIND))
    if unknown:
        raise Fail(f"unknown parameter name(s) handed to the runner: {unknown}")

    values = dict(DEFAULTS)
    requested = {}
    for k, v in handed.items():
        try:
            fv = float(v)
        except (TypeError, ValueError):
            raise Fail(f"parameter {k} is not numeric: {v!r}")
        if not math.isfinite(fv):
            raise Fail(f"parameter {k} is not finite: {v!r}")
        values[k] = fv
        requested[k] = fv
    if not requested:                    # probe/baseline path: env unset -> true defaults
        requested = dict(DEFAULTS)

    split = (os.environ.get("KDT_CALIB_SPLIT") or "full").strip().lower()
    if split not in SPLITS:
        split = "full"
    log(f"split={split} params={ {k: round(v, 6) for k, v in requested.items()} }")

    # 2) obs (read-only) + contract assertions --------------------------------
    obs, hdr = load_obs()

    # 3) stage the validated deck, inject, run --------------------------------
    template = resolve_template()
    run = stage_case(args.workdir, template, obs)

    gc = _load_ki_module("hype_optpar_tool", "s10_calibration/setup_calibration.py")
    nlanduse, nsoil = gc.read_geoclass(str(run / "modelfiles" / "GeoClass.txt"))
    if nlanduse < 1 or nsoil < 1:
        raise Fail(f"GeoClass.txt gave nlanduse={nlanduse}, nsoil={nsoil}")

    write_par(run, values, nlanduse, nsoil)
    applied = read_par(run)

    # 4) read-back guard — every HANDED key must apply EXACTLY ----------------
    missing = sorted(set(requested) - set(applied))
    if missing:
        raise Fail(f"parameters not present in the par.txt HYPE reads: {missing}")
    for k, want in requested.items():
        got = applied[k]
        if not math.isclose(got, want, rel_tol=READBACK_RTOL, abs_tol=1e-12):
            raise Fail(f"read-back mismatch for {k}: requested {want!r}, par.txt has {got!r}")

    run_model(run)
    sim = load_sim(run)

    # 5) score ----------------------------------------------------------------
    a, b = SPLITS[split]
    headline = score(obs, sim, a, b)
    per_split = {name: score(obs, sim, *win) for name, win in SPLITS.items()}

    metrics = {
        "nse": headline["nse"], "kge": headline["kge"], "pbias": headline["pbias"],
        "rmse": headline["rmse"], "r": headline["r"],
        "nse_full": per_split["full"]["nse"], "nse_cal": per_split["calibration"]["nse"],
        "nse_val": per_split["holdout"]["nse"],
        "pbias_full": per_split["full"]["pbias"],
        "kge_full": per_split["full"]["kge"],
        "__kdt__": {
            # ECHO every key handed to this runner (staged rounds hand frozen params too)
            "applied_params": {k: applied[k] for k in requested},
            # DERIVED from the same resolved gauge the obs loader validated and scored —
            # these cannot diverge from what was actually read.
            "case_id": CASE_ID,
            "scored_obs": (f"GRDC:{hdr['_resolved_grdc_no']} "
                           f"({hdr['_resolved_station']}, {hdr['_resolved_river']}, "
                           f"{hdr['_resolved_lat']}N {hdr['_resolved_lon']}E) "
                           f"[{OBS_DATASET}] {OBS_FILE}"),
            "scored_var": "cout",
            "split": split,
            "scored_window": [a, b],
            "n_paired_days": headline["n"],
            "obs_envelope": hdr["_envelope"],
            "template": str(template),
            "hype_binary": HYPE_BIN,
        },
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(metrics, indent=2))
    log(f"WROTE {out}  nse={metrics['nse']:.4f} kge={metrics['kge']:.4f} "
        f"pbias={metrics['pbias']:.2f} n={headline['n']}")


if __name__ == "__main__":
    try:
        main()
    except Fail as e:
        print(f"[calib_run] FAIL (no metrics written): {e}", file=sys.stderr, flush=True)
        sys.exit(1)
    except Exception as e:                    # never write a metrics file on a crash
        import traceback
        traceback.print_exc()
        print(f"[calib_run] FAIL (no metrics written): {e}", file=sys.stderr, flush=True)
        sys.exit(1)
