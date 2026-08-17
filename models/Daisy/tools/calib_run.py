#!/usr/bin/env python3
"""calib_run.py -- Programmatic run+score for Daisy calibration (NOT an agent).

Reproduces the validated US-Ne3 (Mead, NE) Evapotranspiration real case and
scores Daisy's daily Actual ET against FLUXNET2015 energy-balance-closed
LE_CORR.  The calibration kit's applicator has already written the candidate
parameter values into `crop_params.dai` (the address file in calibration.yaml)
before this script is invoked; this script just runs Daisy with whatever is
currently in that file and returns the gate-valid metrics dict.

Usage:
    python calib_run.py --workdir <wd> --out <metrics.json>

Behaviour:
  * The calibration kit edits the CANONICAL address file
    calibration_assets/crop_params.dai (the `text_token` addresses in
    calibration.yaml point there).  This script reads its tunable values back
    from that SAME canonical file and re-seeds them into <workdir> on EVERY
    invocation (always overwriting crop_params.dai), so the kit's edits are
    honoured even if the kit reuses a workdir across evaluations (no stale-copy
    race).  Static, non-parameter inputs are seeded only when missing.
  * Runs one 2-year Daisy simulation (1-yr spinup + 1 maize target year) per
    scored year, parses field_water.dlf "Actual evapotranspiration" (mm/d),
    aligns it to the daily LE_CORR-derived obs, and computes NSE/KGE/PBIAS/r/RMSE
    with ki_tools_common.metrics.all_metrics (the dag-gated metric family).
  * Honours env KDT_CALIB_SPLIT in ("calibration","holdout"): scores the
    calibration year(s) vs an independent held-out maize year (years holdout).
    Unset -> "calibration".
  * Writes the metrics dict as JSON to --out.  On any failure it writes nothing
    and exits non-zero (the kit treats a missing metrics file as +inf).

Fast: a single 2-year Daisy run is ~1-2 s.  The default calibration split runs
two such sims (~3-4 s); the holdout split runs one.
"""

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

KI_DIR = Path(__file__).resolve().parent.parent
ASSETS = KI_DIR / "calibration_assets"
TOOLS = KI_DIR / "tools"

# Real Daisy binary + library search path (matches the validated real case).
DAISY_BIN = "KISSPATH_KI_ROOT/Daisy/bin/daisy"
DAISY_REPO = "KISSPATH_KI_ROOT/Daisy/source/repo"

# W/m^2 (daily mean latent heat flux) -> mm/d ET, lambda = 2.45 MJ/kg.
LE_TO_MM = 0.035265

# Maize target years available in usne3.dwf / usne3_obs_et.csv.
CALIBRATION_YEARS = [2005, 2007]   # includes the validated 2005 year
HOLDOUT_YEARS = [2003]             # independent out-of-sample maize year

# Static (non-parameter) seed files copied into the workdir if absent.
STATIC_SEEDS = ["usne3.dwf", "usne3_soil.dai", "main_template.dai", "usne3_obs_et.csv"]
# Parameter-bearing file == the calibration.yaml address file the kit edits.
# Always re-seeded from ASSETS so a reused workdir can never read stale params.
PARAM_SEED = "crop_params.dai"

# text_token regexes (mirror calibration.yaml addresses) for read-back logging.
PARAM_PATTERNS = {
    "SpLAI": re.compile(r"\(SpLAI\s+([0-9.eE+-]+)\)"),
    "EPext": re.compile(r"\(EPext\s+([0-9.eE+-]+)\)"),
    "MaxPen": re.compile(r"\(MaxPen\s+([0-9.eE+-]+)\)"),
}

sys.path.insert(0, str(TOOLS))


def seed_workdir(workdir: Path):
    """Populate the workdir with run assets.

    Static inputs are copied once (if absent).  The parameter-bearing
    crop_params.dai is the calibration.yaml address file the kit edits in
    ASSETS, so it is ALWAYS re-copied from ASSETS -> a workdir reused across
    evaluations can never serve a stale candidate.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    for name in STATIC_SEEDS:
        dst = workdir / name
        if not dst.exists():
            shutil.copy2(ASSETS / name, dst)
    shutil.copy2(ASSETS / PARAM_SEED, workdir / PARAM_SEED)   # always honour kit edits


def read_current_params(workdir: Path) -> dict:
    """Read the CURRENT tunable values from the canonical (kit-edited) address
    file calibration_assets/crop_params.dai."""
    text = (ASSETS / PARAM_SEED).read_text()
    out = {}
    for name, pat in PARAM_PATTERNS.items():
        m = pat.search(text)
        out[name] = float(m.group(1)) if m else None
    return out


def run_year(workdir: Path, year: int) -> pd.DataFrame:
    """Run one 2-year Daisy sim (spinup year-1 .. target year) and return the
    daily Actual-ET series (datetime, et_mm) for the target year."""
    import run_daisy
    from parse_daisy_output import parse_dlf

    rundir = workdir / f"run_{year}"
    rundir.mkdir(exist_ok=True)
    # link the shared inputs into the per-year run dir
    for name in ("usne3.dwf", "usne3_soil.dai", "crop_params.dai"):
        tgt = rundir / name
        if tgt.exists():
            tgt.unlink()
        shutil.copy2(workdir / name, tgt)

    template = (workdir / "main_template.dai").read_text()
    dai = (template
           .replace("__SPINUP_START__", str(year - 1))
           .replace("__STOP_YEAR__", str(year)))
    dai_path = rundir / "ne3_et.dai"
    dai_path.write_text(dai)

    # DAISYPATH so the library .dai files (crop/maize/tillage/log/fertilizer)
    # resolve (documented SKILL.md issue: run_daisy does not export it).
    os.environ["DAISYPATH"] = f".:{DAISY_REPO}/lib:{DAISY_REPO}/sample"

    result = run_daisy.process(
        dai_file=str(dai_path),
        work_dir=str(rundir),
        binary_path=DAISY_BIN,
        timeout=300,
        source_dir=DAISY_REPO,
    )
    if result["exit_code"] != 0:
        raise RuntimeError(f"daisy failed for {year}: exit {result['exit_code']}")

    fw = rundir / "field_water.dlf"
    if not fw.is_file():
        raise RuntimeError(f"no field_water.dlf for {year}")
    parsed = parse_dlf(str(fw))
    df = parsed["dataframe"]
    et_col = next((c for c in df.columns if "Actual evapotranspiration" in c), None)
    if et_col is None:
        et_col = next((c for c in df.columns
                       if "evapotranspiration" in c.lower() and "potential" not in c.lower()),
                      None)
    if et_col is None:
        raise RuntimeError(f"Actual ET column not found in {list(df.columns)}")
    if "datetime" not in df.columns:
        raise RuntimeError("parsed field_water.dlf has no datetime column")
    out = df[["datetime", et_col]].rename(columns={et_col: "et_mm"}).dropna()
    out = out[out["datetime"].dt.year == year].reset_index(drop=True)
    return out


def load_obs(year: int) -> pd.DataFrame:
    obs = pd.read_csv(ASSETS / "usne3_obs_et.csv", parse_dates=["date"])
    obs = obs[obs["yr"] == year][["date", "et_mm"]].dropna()
    return obs.rename(columns={"date": "datetime", "et_mm": "obs_mm"})


def score_year(workdir: Path, year: int):
    """Return paired (obs, sim) daily ET arrays for a year."""
    sim = run_year(workdir, year)
    obs = load_obs(year)
    merged = pd.merge(
        sim.assign(d=sim["datetime"].dt.normalize()),
        obs.assign(d=obs["datetime"].dt.normalize()),
        on="d", how="inner",
    )
    return merged["obs_mm"].to_numpy(float), merged["et_mm"].to_numpy(float)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    from ki_tools_common.metrics import all_metrics

    workdir = Path(args.workdir).resolve()
    seed_workdir(workdir)
    params = read_current_params(workdir)

    split = os.environ.get("KDT_CALIB_SPLIT", "calibration")
    years = HOLDOUT_YEARS if split == "holdout" else CALIBRATION_YEARS

    obs_all, sim_all = [], []
    per_year = {}
    for y in years:
        o, s = score_year(workdir, y)
        if len(o) >= 30:
            obs_all.append(o)
            sim_all.append(s)
            per_year[str(y)] = all_metrics(o, s)
    if not obs_all:
        raise RuntimeError("no scorable year produced paired ET data")

    obs = np.concatenate(obs_all)
    sim = np.concatenate(sim_all)
    m = all_metrics(obs, sim)

    out = {
        "nse": m["NSE"],
        "kge": m["KGE"],
        "pbias": m["PBIAS"],
        "r": m["r"],
        "rmse": m["RMSE"],
        "n": int(len(obs)),
        "split": split,
        "years": years,
        "per_year": per_year,
        "params": params,
        "obs_mean_mm": float(np.mean(obs)),
        "sim_mean_mm": float(np.mean(sim)),
    }
    # Write only on success; nonzero exit on failure leaves no file (kit -> +inf).
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(json.dumps({k: out[k] for k in ("nse", "kge", "pbias", "r", "n", "split", "params")}))


if __name__ == "__main__":
    main()
