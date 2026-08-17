#!/usr/bin/env python3
"""
SWAT+ Bengbu VERIFIER runner+scorer.

Runs the SWAT+ rev59 binary FRESH on the validated calibrated Bengbu deck
(calib/run_txtinout: 11-param calibration.cal, Huai @ 51080, 121330 km2),
extracts outlet discharge via the KI's s9 extract_discharge tool, scores
against the Bengbu gauge, closes the water balance, writes the VERIFIER JSON.
"""
import sys, os, json, subprocess, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT      = "KISSPATH_ROOT"
TXTINOUT  = Path(ROOT) / "models/SWAT+/knowledge_infrastructure/calib/run_txtinout"
BINARY    = Path(ROOT) / "models/SWAT+/bin/swatplus_rev59"
OBS       = Path(ROOT) / "data/obs/BB/51080_bengbu.txt"
KI        = Path(ROOT) / "models/SWAT+/knowledge_infrastructure"
OUTDIR    = Path(ROOT) / "models/SWAT+/detached/verify_1"
RESULT    = OUTDIR / "result.json"

sys.path.insert(0, str(KI / "tools/s9"))
sys.path.insert(0, "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect_multi_agent")
sys.path.insert(0, "KISSPATH_INTERNAL_NOT_SHIPPED")

from extract_discharge import find_channel_file, parse_channel_day, load_obs
from ki_tools_common.metrics import all_metrics
from ki_tools_common.validation import validate_water_balance
from auto_dissect_multi_agent.validators.standard_calval import compute_calval_metrics


def run_binary():
    # force a genuine fresh run: clear stale channel output
    for n in ("channel_sd_day.txt", "channel_day.txt"):
        p = TXTINOUT / n
        if p.exists():
            p.unlink()
    print("[run] launching swatplus_rev59 (calibrated deck) ...")
    t0 = time.time()
    r = subprocess.run([str(BINARY.resolve())], cwd=str(TXTINOUT),
                       capture_output=True, text=True, timeout=7200)
    print(f"[run] exit={r.returncode} elapsed={time.time()-t0:.1f}s")
    print(r.stdout[-400:])
    if r.returncode != 0:
        print(r.stderr[-1000:])
        raise RuntimeError(f"SWAT+ binary failed exit={r.returncode}")


def water_balance():
    f = TXTINOUT / "basin_wb_yr.txt"
    lines = f.read_text().strip().split("\n")
    cols = lines[1].split()
    rows = []
    for ln in lines[3:]:
        p = ln.split()
        if len(p) < len(cols):
            continue
        rows.append(dict(zip(cols, p)))
    df = pd.DataFrame(rows)
    for c in ("yr", "precip", "et", "wateryld", "perc", "sw"):
        df[c] = df[c].astype(float)
    ev = df[df["yr"] >= 1981].copy()
    P, ET, WY = ev["precip"].sum(), ev["et"].sum(), ev["wateryld"].sum()
    PERC = ev["perc"].sum()
    dSW = ev["sw"].iloc[-1] - ev["sw"].iloc[0]
    ndays = int((pd.Timestamp("1990-12-31") - pd.Timestamp("1981-01-01")).days + 1)
    wb = validate_water_balance(precip_mm=P, et_mm=ET, runoff_mm=WY,
                                delta_storage_mm=PERC + dSW, period_days=ndays)
    wb["_components"] = {"P_mm": round(P,1), "ET_mm": round(ET,1),
                         "WY_mm": round(WY,1), "perc_mm": round(PERC,1),
                         "dSW_mm": round(dSW,1)}
    return wb


def main():
    OUTDIR.mkdir(parents=True, exist_ok=True)
    run_binary()

    chan = find_channel_file(TXTINOUT)
    print(f"[extract] {chan}")
    sim = parse_channel_day(chan, outlet_gis_id=None, txtinout_dir=TXTINOUT)
    obs = load_obs(OBS)
    merged = obs.join(sim, how="inner").dropna()
    print(f"[extract] paired days: {len(merged)} ({merged.index.min()}..{merged.index.max()})")

    o = merged["Q_obs"].values
    s = merged["Q_sim"].values
    m = all_metrics(o, s)
    cv = compute_calval_metrics(
        merged.index.values, o, s,
        cal_start="1981-01-01", cal_end="1985-12-31",
        val_start="1986-01-01", val_end="1990-12-31")
    wb = water_balance()
    wb_resid_pct = round(float(wb.get("residual_pct", 0.0)), 3)

    period = f"{pd.Timestamp(merged.index.min()).date()}..{pd.Timestamp(merged.index.max()).date()}"
    metrics = {
        "nse": round(float(m["NSE"]), 4),
        "kge": round(float(m["KGE"]), 4),
        "pbias": round(float(m["PBIAS"]), 4),
        "r":   round(float(m["r"]), 4),
        "period": period + " daily",
        "nse_cal": round(float(cv["calibration"]["NSE"]), 4),
        "nse_val": round(float(cv["validation"]["NSE"]), 4),
        "kge_val": round(float(cv["validation"]["KGE"]), 4),
    }
    result = {
        "model_id": "SWAT+",
        "this_location": "Bengbu",
        "obs_source": "ObservedQ",
        "status": "completed",
        "tools_used": ["tools/s8/run_swatplus.py (swatplus_rev59 binary)",
                       "tools/s9/extract_discharge.py",
                       "ki_tools_common.metrics.all_metrics",
                       "ki_tools_common.validation.validate_water_balance",
                       "validators/standard_calval.compute_calval_metrics"],
        "tools_failed": [],
        "metrics": metrics,
        "water_balance": {"status": wb["status"], "residual_pct": wb_resid_pct},
        "notes": (
            f"SWAT+ rev59 FRESH run on calibrated Bengbu deck (calib/run_txtinout, "
            f"11-param calibration.cal: cn2 pctchg -20, esco 0.15, alpha 0.05; Huai @ "
            f"51080, 121330 km2). Outlet via channel.con topology, flo_out ha-m/d->m3/s. "
            f"Paired {len(merged)} daily values {period}. Full NSE={metrics['nse']}, "
            f"KGE={metrics['kge']}, PBIAS={metrics['pbias']}%, r={metrics['r']}; "
            f"cal NSE={metrics['nse_cal']}, val NSE={metrics['nse_val']}, "
            f"val KGE={metrics['kge_val']}. WB {wb['status']} (residual {wb_resid_pct}%)."),
    }
    RESULT.write_text(json.dumps(result, indent=2))
    print("[done] wrote", RESULT)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
