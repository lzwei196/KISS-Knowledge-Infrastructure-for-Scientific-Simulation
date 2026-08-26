#!/usr/bin/env python
"""
dissect_space_ssc_q_rating.py
-----------------------------
Parameterized, NON-DEGENERATE SPACE Qs-Q rating validation for ANY USGS
suspended-sediment site (generalises the Atchafalaya-hardcoded
dissect_atchafalaya_ssc_q_surrogate.py).

WHY THIS TOOL EXISTS
====================
The dag (outputs[sediment__outflux].observability) and triplets dt_020/dt_021
state the ONLY non-degenerate test for `sediment__outflux (SPACE Qs)`:

    Fit log(Qs) vs log(Q) directly (Qs ~ Q^b).  Do NOT fit SSC = Qs/Q vs Q
    (always negatively sloped), and do NOT build a load-space time series
    Qs_sim = a*Q_obs^b_sim and score NSE/KGE/PBIAS against observed loads:
    that series derives ALL of its temporal variance from observed Q and its
    PBIAS is forced to ~0 by mean-matching the coefficient `a`. Such metrics
    are degenerate (shared-Q variance + fitted magnitude) and are NOT a model
    verdict.

The model's genuine, unfitted quantity is the SPACE rating EXPONENT b_sim
(from the SpaceLargeScaleEroder binary). The verdict keys on:

    PASS  iff  b_sim in [EXPONENT_MIN, EXPONENT_MAX]  AND  r_sim >= EXPONENT_R_MIN

and the site-specific comparison is the exponent gap b_sim vs the OBSERVED
Qs-Q exponent b_obs (a real, non-degenerate PBIAS-on-exponent), which exposes
the documented SPACE supply-limited-alluvial-river limitation (dt_016) when the
observed exponent exceeds the transport-limited ceiling (~1.0-1.2).

USAGE
=====
    python dissect_space_ssc_q_rating.py \
        --site-id USGS-07374000 \
        --ssc-csv  KISSPATH_OBS/sediment/usgs_suspended_sediment/wqp_pcode80154_louisiana.csv \
        --flow-rdb KISSPATH_OBS/sediment/usgs_suspended_sediment/07374000_Mississippi_daily_flow.rdb \
        --label "Mississippi River at St. Francisville, LA"

Output:
    outputs/landlab_space_ssc_q/<site>/metrics.json   (scored quantity = exponent)
    Exit 0 on PASS, 1 on FAIL.
"""

import argparse
import json
import pathlib
import sys

import numpy as np
from scipy import stats

# Reuse the validated, byte-identical SPACE binary driver + USGS loaders from
# the Atchafalaya tool (same directory). Importing only binds functions; the
# Atchafalaya main() is __main__-guarded and does not run.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from dissect_atchafalaya_ssc_q_surrogate import (  # noqa: E402
    load_ssc,
    load_daily_q,
    merge_ssc_q,
    run_space_qscaling,
    EXPONENT_MIN,
    EXPONENT_MAX,
    EXPONENT_R_MIN,
)

OUT_ROOT = pathlib.Path(
    "KISSPATH_OUTPUTS/landlab_space_ssc_q"
)


def fit_obs_qs_q(merged):
    """Fit the OBSERVED sediment-flux rating exponent: Qs ~ Q^b_obs.

    Qs_obs [kg/s] = SSC [mg/L] * Q [m^3/s] * 1e-3.  Fit log10(Qs) vs log10(Q)
    directly (NOT SSC vs Q). Returns the observed Qs-Q exponent and log-space
    intercept/coefficient — a non-degenerate, model-independent quantity.
    """
    q = merged["Q_cms"].values.astype(float)
    qs = merged["ssc_mg_l"].values.astype(float) * q * 1e-3  # kg/s
    ok = (q > 0) & (qs > 0)
    q, qs = q[ok], qs[ok]
    lq, lqs = np.log10(q), np.log10(qs)
    b_obs, logA, r_obs, _, _ = stats.linregress(lq, lqs)
    return {
        "b_obs": float(b_obs),
        "a_obs": float(10 ** logA),
        "r_obs": float(r_obs),
        "n": int(len(q)),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--site-id", required=True,
                    help="WQP MonitoringLocationIdentifier, e.g. USGS-07374000")
    ap.add_argument("--ssc-csv", required=True, help="WQP pcode 80154 SSC csv (mg/L)")
    ap.add_argument("--flow-rdb", required=True, help="USGS daily-flow .rdb (cfs)")
    ap.add_argument("--label", default="", help="human-readable station label")
    ap.add_argument("--min-pairs", type=int, default=20)
    args = ap.parse_args()

    site_slug = args.site_id.replace("USGS-", "").replace("/", "_")
    out_dir = OUT_ROOT / site_slug
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 68)
    print(f"SPACE Qs-Q rating validation — {args.label or args.site_id}")
    print(f"Site: {args.site_id}")
    print("Determining quantity: SPACE rating exponent b_sim (non-degenerate)")
    print("=" * 68)

    # ── Observed Qs-Q rating exponent (site-specific, model-independent) ──
    ssc_df = load_ssc(args.ssc_csv, args.site_id)
    q_df = load_daily_q(args.flow_rdb)
    merged = merge_ssc_q(ssc_df, q_df)
    n_pairs = len(merged)
    print(f"\n[Obs] SSC={len(ssc_df)}  Q={len(q_df)}  matched pairs={n_pairs}")
    if n_pairs < args.min_pairs:
        print(f"FATAL: only {n_pairs} pairs — need >= {args.min_pairs}")
        sys.exit(1)
    obs = fit_obs_qs_q(merged)
    print(f"  Observed  Qs = {obs['a_obs']:.4g}*Q^{obs['b_obs']:.3f}  "
          f"(r={obs['r_obs']:.4f}, n={obs['n']})")

    # ── SPACE binary rating exponent (generic; the model's own output) ──
    print("\n[SPACE] Running SpaceLargeScaleEroder binary Qs-Q probe ...")
    t1 = run_space_qscaling()
    b_sim, r_sim = t1["b_sim"], t1["r_sim"]
    print(f"  SPACE binary  Qs ~ Q^{b_sim:.3f}  (log-log r={r_sim:.4f})")

    # ── Non-degenerate verdict: score the EXPONENT, not a load time series ──
    exponent_pass = (EXPONENT_MIN <= b_sim <= EXPONENT_MAX) and (r_sim >= EXPONENT_R_MIN)
    # Honest PBIAS-family number on the determining quantity (the exponent),
    # NOT a mean-matched load-space PBIAS (which is forced to 0).
    exponent_pbias = 100.0 * (b_sim - obs["b_obs"]) / obs["b_obs"]

    print("\n[Verdict] (dag determining quantity = Qs-Q rating exponent)")
    print(f"  [{'PASS' if exponent_pass else 'FAIL'}] b_sim={b_sim:.3f} "
          f"in [{EXPONENT_MIN},{EXPONENT_MAX}] and r_sim={r_sim:.3f} >= {EXPONENT_R_MIN}")
    print(f"  exponent PBIAS (b_sim vs b_obs={obs['b_obs']:.3f}): "
          f"{exponent_pbias:+.1f}%")
    if obs["b_obs"] > EXPONENT_MAX:
        print(f"  NOTE: observed b_obs={obs['b_obs']:.3f} exceeds the transport-"
              f"limited ceiling {EXPONENT_MAX}; SPACE cannot match supply-limited "
              f"large-river steepness (documented limitation dt_016).")

    metrics = {
        "site_id": args.site_id,
        "label": args.label,
        "scored_quantity": "ssc_q_rating_exponent",
        "determining_metric": "pbias_on_exponent",
        "space_binary_b_sim": float(b_sim),
        "space_binary_r_sim": float(r_sim),
        "obs_qs_q_b_obs": obs["b_obs"],
        "obs_qs_q_r_obs": obs["r_obs"],
        "n_ssc_q_pairs": n_pairs,
        "exponent_range": [EXPONENT_MIN, EXPONENT_MAX],
        "exponent_r_min": EXPONENT_R_MIN,
        "exponent_pbias_pct": float(exponent_pbias),
        "exponent_pass": bool(exponent_pass),
        "degeneracy_note": (
            "Verdict keys on SPACE's generic, unfitted rating exponent b_sim. "
            "A load-space series Qs_sim=a*Q_obs^b_sim is NOT scored: its variance "
            "is observed Q re-expressed and its PBIAS is forced ~0 by mean-matching "
            "a (degenerate per dt_020 / dag observability caveat)."
        ),
        "overall_pass": bool(exponent_pass),
    }
    mpath = out_dir / "metrics.json"
    with open(mpath, "w") as fh:
        json.dump(metrics, fh, indent=2)
    print(f"\n  Metrics: {mpath}")
    print("=" * 68)
    print(f"OVERALL: {'PASS' if exponent_pass else 'FAIL'}")
    print("=" * 68)
    sys.exit(0 if exponent_pass else 1)


if __name__ == "__main__":
    main()
