#!/usr/bin/env python3
"""Parse REAL QUINCY engine text output (run_quincy_engine.py run_dir) into dated, unit-converted tables.

Reads (whitespace tables, header line, first column `Time` = day of the 365-day year):
  vegflux_c_daily.txt       GPP, GrowthResp, MaintResp, NTransformResp, NFixationResp, NPP  [mol C m-2 day-1]
  soilflux_cdc13dc14_daily.txt  HetResp                                                  [mol C m-2 day-1]
  vegflux_energy_daily.txt  Rnet, Qh, Qle, Qg [MJ m-2 day-1, upward positive for Qh/Qle]; fPAR
  vegflux_h2o_daily.txt     Precip, Evaporation (bare soil), Transpiration, Interception,
                            SrfRunoff, Drainage, GwRunoff [mm day-1]
  veg_diagnostics_daily.txt LAI [m2 m-2];  soil_physics_daily.txt RootZoneSoilMoisture
  *_spinup_yearly.txt       spin-up trajectory (yearly sums / states)
Units were read from mo_qs_output_txt.f90: fluxes are SUMMED over the output interval
(µmol s-1 * dtime / 1e6 -> mol per day; W m-2 * dtime / 1e6 -> MJ per day).

Writes into --out_dir:
  quincy_daily.csv   date + GPP, NPP, Ra, Rh, Reco, NEE in µmol CO2 m-2 s-1 (daily mean, FLUXNET units)
                     and *_gC in g C m-2 day-1; LE, H, Rnet, G in W m-2; ET, P, Q in mm day-1; LAI; SM
                     (Ra = growth + maintenance + N-transform + N-fixation respiration; Reco = Ra + Rh;
                      NEE = Reco - GPP, positive = source; ET = Evaporation + Transpiration + Interception,
                      snow sublimation is NOT in the water files)
  quincy_spinup_yearly.csv, quincy_summary.json (annual means, water balance, LE-vs-ET check,
  spin-up drift of total ecosystem C over the last 50 spin-up years).

Dates: engine day i of the run = i-th day from 1 Jan <first_output_year> skipping Feb 29.
Exit codes: 0 ok, 2 missing/short files or non-daily output, 3 a consistency check failed
(NaN in outputs, LE/(lambda ET) outside 0.7-1.5, or |P - ET - Q| > 50 % of P = a unit-size error).
Warnings only (the balance written here has no storage term and ET lacks snow sublimation, so
short windows or snowy sites legitimately miss closure): |P - ET - Q| > 10 % of P, and a 15 %
LE/ET mismatch.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _quincy_common import noleap_dates  # noqa: E402

MOL_DAY_TO_UMOL_S = 1e6 / 86400.0
MJ_DAY_TO_W = 1e6 / 86400.0
GC_PER_MOL = 12.011
LAMBDA_MJ_KG = 2.45  # latent heat of vaporisation, MJ kg-1 (= MJ per mm)


def read(run_dir: Path, stem: str) -> pd.DataFrame:
    p = run_dir / f"{stem}.txt"
    if not p.exists():
        raise FileNotFoundError(f"missing {p}")
    return pd.read_csv(p, sep=r"\s+")


def parse(run_dir: Path, first_year: int):
    c, h, e = read(run_dir, "vegflux_c_daily"), read(run_dir, "vegflux_h2o_daily"), read(run_dir, "vegflux_energy_daily")
    s, v = read(run_dir, "soilflux_cdc13dc14_daily"), read(run_dir, "veg_diagnostics_daily")
    sp = read(run_dir, "soil_physics_daily")
    n = len(c)
    if not n or any(len(x) != n for x in (h, e, s, v, sp)):
        raise ValueError(f"daily files have different/zero lengths: {[len(x) for x in (c, h, e, s, v, sp)]}")
    if n % 365:
        raise ValueError(f"{n} daily rows is not a whole number of 365-day years")
    ra = c.GrowthResp + c.MaintResp + c.NTransformResp + c.NFixationResp
    d = pd.DataFrame({"date": noleap_dates(first_year, n)})
    for name, mol in (("GPP", c.GPP), ("NPP", c.NPP), ("Ra", ra), ("Rh", s.HetResp),
                      ("Reco", ra + s.HetResp), ("NEE", ra + s.HetResp - c.GPP)):
        d[name] = mol.to_numpy() * MOL_DAY_TO_UMOL_S
        d[name + "_gC"] = mol.to_numpy() * GC_PER_MOL
    d["LE"], d["H"] = e.Qle.to_numpy() * MJ_DAY_TO_W, e.Qh.to_numpy() * MJ_DAY_TO_W
    d["Rnet"], d["G"] = e.Rnet.to_numpy() * MJ_DAY_TO_W, e.Qg.to_numpy() * MJ_DAY_TO_W
    d["fPAR"] = e.fPAR.to_numpy()
    d["P"] = h.Precip.to_numpy()
    d["ET"] = (h.Evaporation + h.Transpiration + h.Interception).to_numpy()
    d["T"], d["Q"] = h.Transpiration.to_numpy(), (h.SrfRunoff + h.Drainage + h.GwRunoff).to_numpy()
    d["LAI"], d["SM_rootzone"] = v.LAI.to_numpy(), sp.RootZoneSoilMoisture.to_numpy()
    return d


def spinup(run_dir: Path):
    f = run_dir / "ecosyspool_cnp_spinup_yearly.txt"
    if not f.exists():
        return None, None
    eco = pd.read_csv(f, sep=r"\s+")
    c = read(run_dir, "vegflux_c_spinup_yearly")
    sy = pd.DataFrame({"spinup_year": np.arange(1, len(eco) + 1), "EcoC_molm2": eco.EcoC,
                       "SoilOrgC_molm2": eco.TotalSoilOrgC, "GPP_gC_yr": c.GPP[:len(eco)] * GC_PER_MOL})
    last = sy.tail(50)
    drift = None
    if len(last) >= 10:
        slope = np.polyfit(last.spinup_year, last.EcoC_molm2, 1)[0]
        drift = {"years_used": int(len(last)), "EcoC_end_molm2": float(last.EcoC_molm2.iloc[-1]),
                 "EcoC_trend_pct_per_100yr": float(100 * slope * 100 / last.EcoC_molm2.mean())}
    return sy, drift


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run_dir", required=True)
    ap.add_argument("--first_year", type=int, help="calendar year of engine output day 1 "
                    "(default: run_manifest.json first_output_year)")
    ap.add_argument("--out_dir", required=True)
    a = ap.parse_args(argv)
    run_dir, out = Path(a.run_dir), Path(a.out_dir)
    try:
        man = json.loads((run_dir / "run_manifest.json").read_text()) if (run_dir / "run_manifest.json").exists() else {}
        if man.get("status") not in (None, "ok"):
            raise ValueError(f"run_manifest.json status is {man.get('status')!r}; refusing to parse a failed run")
        if man.get("output_interval", "daily") != "daily":
            raise ValueError("only daily engine output can be dated; rerun with --output_interval daily")
        first = a.first_year or man.get("first_output_year")
        if first is None:
            raise ValueError("--first_year not given and run_manifest.json has no first_output_year")
        d = parse(run_dir, int(first))
    except (FileNotFoundError, ValueError, KeyError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)
    d.to_csv(out / "quincy_daily.csv", index=False, float_format="%.6g")
    sy, drift = spinup(run_dir)
    if sy is not None:
        sy.to_csv(out / "quincy_spinup_yearly.csv", index=False)
    from ki_tools_common.validation import validate_water_balance
    n = len(d)
    wb = validate_water_balance(d.P.sum(), d.ET.sum(), d.Q.sum(), period_days=n)
    le_et = float(d.LE.mean() * 86400 / 1e6 / LAMBDA_MJ_KG / d.ET.mean()) if d.ET.mean() > 0 else float("nan")
    yrs = n / 365.0
    summary = {
        "run_dir": str(run_dir.resolve()), "first_year": int(first), "n_days": n,
        "annual_mean": {"GPP_gC": float(d.GPP_gC.sum() / yrs), "NPP_gC": float(d.NPP_gC.sum() / yrs),
                        "Reco_gC": float(d.Reco_gC.sum() / yrs), "NEE_gC": float(d.NEE_gC.sum() / yrs),
                        "P_mm": float(d.P.sum() / yrs), "ET_mm": float(d.ET.sum() / yrs),
                        "Q_mm": float(d.Q.sum() / yrs), "LE_Wm2": float(d.LE.mean()),
                        "LAI_max": float(d.LAI.max())},
        "water_balance": {k: (float(v) if isinstance(v, (int, float, np.floating)) else v) for k, v in wb.items()},
        "LE_over_lambdaET": le_et, "spinup_drift": drift,
    }
    probs = []
    if d.drop(columns="date").isna().any().any():
        probs.append("NaN in engine output")
    resid = abs(d.P.sum() - d.ET.sum() - d.Q.sum()) / max(d.P.sum(), 1e-9)
    summary["water_balance"]["residual_frac_of_P"] = float(resid)
    summary["water_balance"]["note"] = ("P - ET - Q without storage change; ET excludes snow sublimation "
                                        "(in LE only), so this is a diagnostic, not a closure test")
    warns = []
    if resid > 0.50:
        probs.append(f"P-ET-Q residual {resid:.1%} of P (> 50 %: a unit or column error, not storage)")
    elif resid > 0.10:
        warns.append(f"P-ET-Q residual {resid:.1%} of P (> 10 %; no storage term, snow sublimation not in ET)")
    if np.isfinite(le_et) and abs(le_et - 1) > 0.15:
        # LE contains snow sublimation, the water files do not: > 1 is expected where snow lies long
        warns.append(f"LE/(lambda*ET) = {le_et:.2f}, outside 0.85-1.15 (snow sublimation is in LE only)")
    if le_et < 0.7 or le_et > 1.5:
        probs.append(f"LE/(lambda*ET) = {le_et:.2f}: energy and water outputs disagree (unit error?)")
    summary["problems"], summary["warnings"] = probs, warns
    (out / "quincy_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps({"daily_csv": str(out / "quincy_daily.csv"), **summary["annual_mean"], "problems": probs, "warnings": warns}))
    return 3 if probs else 0


if __name__ == "__main__":
    sys.exit(main())
