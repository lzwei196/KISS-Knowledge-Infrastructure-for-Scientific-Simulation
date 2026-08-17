#!/usr/bin/env python3
"""validate_wgms_reference_mb.py -- OGGM Knowledge Infrastructure

Score OGGM simulated annual specific mass balance against INDEPENDENT WGMS
glaciological annual mass-balance series (WGMS Fluctuations of Glaciers).

This replaces the degenerate self-comparison (OGGM output scored vs OGGM's own
run_output_hist.nc with identical downloaded calibration parameters). Per
dag.yaml outputs[specific_mass_balance] (validation_rank 1, determining_metric
pbias): the comparable obs is a glaciological/WGMS annual MB series, and the
2000-2020 geodetic calibration period is NOT independent validation.

OGGM is calibrated to Hugonnet 2021 geodetic MB (its intrinsic mechanism, via
the prepro L3 mb_calib); the WGMS glaciological series is an *independent*
observation. Pre-2000 WGMS years fall outside the geodetic window and provide a
genuine out-of-calibration holdout.

Usage:
    python validate_wgms_reference_mb.py --working_dir KISSPATH_HOME/OGGM/wgms_ref_val_rgi13 \\
        --rgi_region 13 --min_mb_yrs 15 --out result.json
"""
import argparse, glob, json, os, sys
from pathlib import Path

SP = "KISSPATH_PYTHON_ENV/lib/python3.12/site-packages"
KI = "KISSPATH_KI_TOOLS_COMMON"
for p in (SP, KI, "KISSPATH_ROOT"):
    if p not in sys.path:
        sys.path.insert(0, p)

import numpy as np
import pandas as pd
from ki_tools_common.metrics import all_metrics

# WORKING base_url (SKILL.md quick-start Innsbruck path is stale; Bremen works)
PREPRO = ("https://cluster.klima.uni-bremen.de/~oggm/gdirs/oggm_v1.6/"
          "L3-L5_files/2023.3/elev_bands/W5E5/")


def find_links():
    hits = sorted(glob.glob(os.path.expanduser(
        "~/.oggm/oggm-sample-data-*/wgms/rgi_wgms_links_20220112.csv")))
    if not hits:
        raise SystemExit("WGMS RGI-links table not found under ~/.oggm sample-data")
    return hits[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--working_dir", default="KISSPATH_HOME/OGGM/wgms_ref_val_rgi13")
    ap.add_argument("--rgi_region", default="13")
    ap.add_argument("--min_mb_yrs", type=int, default=15)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    from oggm import cfg, workflow
    from oggm.core.massbalance import MonthlyTIModel

    cfg.initialize(logging_level="WARNING")
    cfg.PARAMS["use_multiprocessing"] = False
    Path(args.working_dir).mkdir(parents=True, exist_ok=True)
    cfg.PATHS["working_dir"] = args.working_dir

    links = pd.read_csv(find_links())
    reg = links[(links["RGI_REG"].astype(str) == str(args.rgi_region)) &
                (links["N_MB_YRS"].fillna(0) >= args.min_mb_yrs)]
    cand = sorted(reg["RGI60_ID"].dropna().unique().tolist())
    if not cand:
        raise SystemExit("No WGMS reference glaciers for region %s" % args.rgi_region)
    print("Candidate WGMS reference glaciers (region %s, N_MB_YRS>=%d): %d"
          % (args.rgi_region, args.min_mb_yrs, len(cand)))

    gdirs = workflow.init_glacier_directories(
        cand, from_prepro_level=3, prepro_base_url=PREPRO)

    rows, per_glacier = [], []
    for gd in gdirs:
        try:
            ref = gd.get_ref_mb_data()               # independent WGMS annual MB
            h, w = gd.get_inversion_flowline_hw()
            mbmod = MonthlyTIModel(gd)               # reads geodetic mb_calib
            yrs = ref.index.values.astype(int)
            sim = np.asarray(mbmod.get_specific_mb(h, w, year=yrs), dtype=float)
            obs = ref["ANNUAL_BALANCE"].values.astype(float)
            m = np.isfinite(obs) & np.isfinite(sim)
            if m.sum() < 2:
                continue
            for y, o, s in zip(yrs[m], obs[m], sim[m]):
                rows.append({"rgi_id": gd.rgi_id, "year": int(y),
                             "obs": float(o), "sim": float(s)})
            per_glacier.append({
                "rgi_id": gd.rgi_id, "n": int(m.sum()),
                "years": [int(yrs[m].min()), int(yrs[m].max())],
                "metrics": all_metrics(obs[m], sim[m])})
        except Exception as e:  # noqa: BLE001
            print("skip %s: %s" % (getattr(gd, 'rgi_id', '?'), e), file=sys.stderr)

    if not rows:
        raise SystemExit("No paired WGMS/sim points produced")

    df = pd.DataFrame(rows)
    pre = df[df["year"] < 2000]
    post = df[df["year"] >= 2000]
    out = {
        "variable": "specific_mass_balance",
        "obs_shape": "point_time_series",
        "obs_source": "WGMS FoG glaciological annual mass balance (independent)",
        "location": "RGI60-%s WGMS reference glaciers (n=%d)" % (
            args.rgi_region, len(per_glacier)),
        "n_paired": int(len(df)),
        "n_glaciers": len(per_glacier),
        "determining_metric": "pbias",
        "metrics": all_metrics(df["obs"].values, df["sim"].values),
        "metrics_holdout_pre2000": (all_metrics(pre["obs"].values, pre["sim"].values)
                                    if len(pre) >= 2 else None),
        "metrics_calibperiod_post2000": (all_metrics(post["obs"].values, post["sim"].values)
                                         if len(post) >= 2 else None),
        "per_glacier": per_glacier,
    }
    print(json.dumps(out, indent=2, default=float))
    # Two declared destinations, both honored (reviewer contract):
    #   (1) tool-owned default  <working_dir>/result.json  -- ALWAYS written
    #   (2) caller --out path                              -- ALSO written when given
    payload = json.dumps(out, indent=2, default=float)
    default_p = Path(args.working_dir) / "result.json"
    default_p.parent.mkdir(parents=True, exist_ok=True)
    default_p.write_text(payload)
    print("wrote", default_p)
    if args.out and str(Path(args.out)) != str(default_p):
        outp = Path(args.out)
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(payload)
        print("wrote", outp)


if __name__ == "__main__":
    main()
