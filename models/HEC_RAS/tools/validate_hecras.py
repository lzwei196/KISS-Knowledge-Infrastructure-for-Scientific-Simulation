#!/usr/bin/env python3
"""
validate_hecras.py -- Validate REAL HEC-RAS computed water-surface profiles
against observed water-surface elevations.

Observed WS ships inside steady flow files (.fNN) as 'Observed WS=' lines (one
per cross section). This tool:
  1. parses the computed WS from the results HDF (parse_output_hecras),
  2. parses Observed WS from the .fNN flow file,
  3. computes NSE/KGE/PBIAS/RMSE/r via ki_tools_common.metrics.all_metrics,
  4. optionally writes a comparison figure (observed=black, simulated=#2563EB).

This is the real-tier validation entry point for the KI.

Usage:
  python3 validate_hecras.py --hdf <results.hdf> --flow MIXED.f01 \
      --profile-index 0 --figure s8_validation.png
"""
import argparse
import json
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parse_output_hecras as parse


def read_observed_ws(flow_path):
    """Return observed WS list in file order (one per cross section)."""
    obs = []
    with open(flow_path) as fh:
        for line in fh:
            if line.startswith("Observed WS="):
                # Observed WS=<reach>,<reach>,<RS>,,<value>,
                parts = line.split("=", 1)[1].split(",")
                for tok in parts:
                    tok = tok.strip()
                    if re.fullmatch(r"[-+]?\d*\.?\d+", tok):
                        # the WS value is the last numeric field before trailing comma
                        pass
                # value is the field after the empty 4th field
                vals = [p.strip() for p in parts]
                num = None
                for p in reversed(vals):
                    if re.fullmatch(r"[-+]?\d*\.?\d+", p):
                        num = float(p)
                        break
                if num is not None:
                    obs.append(num)
    return obs


def validate(hdf_path, flow_path, profile_index=0, figure=None):
    parsed = parse.parse(hdf_path)
    profiles = parsed["summary"]["profiles"]
    prof = profiles[profile_index]
    comp = [r["ws"] for r in parsed["records"]
            if r["profile"] == prof and "ws" in r]
    obs = read_observed_ws(flow_path)
    n = min(len(comp), len(obs))
    if n == 0:
        # No observed water-surface elevations -> fidelity is N/A by domain.
        # Steady HEC-RAS CONSUMES discharge (forcing) and PRODUCES stage; a
        # discharge-only obs site (e.g. Bengbu) has nothing to compare WS against.
        # Use UNSTEADY (needs Wine Mono) for Q-vs-Q routing fidelity.
        return {"status": "N/A_domain", "NSE": None, "KGE": None,
                "RMSE": None, "PBIAS": None, "r": None, "n": 0,
                "reason": "no observed water-surface elevation (Observed WS= lines); "
                          "obs variable is discharge, which steady HEC-RAS consumes as "
                          "forcing. Validate against a stage gauge, or use unsteady (Wine Mono)."}
    comp = np.array(comp[:n], float)
    obs = np.array(obs[:n], float)

    try:
        from ki_tools_common.metrics import all_metrics
        metrics = all_metrics(obs, comp)
    except Exception:  # noqa  -- minimal fallback
        err = comp - obs
        rmse = float(np.sqrt(np.mean(err ** 2)))
        nse = float(1 - np.sum(err ** 2) / np.sum((obs - obs.mean()) ** 2))
        metrics = {"NSE": nse, "RMSE": rmse, "PBIAS": float(100 * err.sum() / obs.sum()),
                   "r": float(np.corrcoef(obs, comp)[0, 1]), "KGE": None}
    metrics = {k: (round(v, 5) if isinstance(v, float) else v) for k, v in metrics.items()}
    metrics["max_abs_err_ft"] = round(float(np.max(np.abs(comp - obs))), 4)
    metrics["n"] = int(n)
    metrics["profile"] = prof

    if figure:
        _plot(obs, comp, metrics, figure)
        metrics["figure"] = figure
    return metrics


def _plot(obs, comp, metrics, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    x = np.arange(len(obs))
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(x, obs, "o-", color="black", label="Observed WS", lw=1.5, ms=4)
    ax.plot(x, comp, "s--", color="#2563EB", label="HEC-RAS computed WS", lw=1.5, ms=4)
    ax.set_xlabel("Cross section (downstream →)")
    ax.set_ylabel("Water surface elevation (ft)")
    ax.set_title("HEC-RAS steady profile vs observed water surface")
    ax.legend(loc="best")
    txt = "\n".join(f"{k} = {metrics[k]}" for k in ("NSE", "KGE", "RMSE",
                                                    "PBIAS", "r", "max_abs_err_ft")
                    if k in metrics and metrics[k] is not None)
    ax.text(0.02, 0.02, txt, transform=ax.transAxes, va="bottom", ha="left",
            fontsize=9, family="monospace",
            bbox=dict(boxstyle="round", fc="white", ec="#2563EB", alpha=0.9))
    fig.tight_layout()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fig.savefig(path, dpi=130)
    plt.close(fig)


def validate_outputs(metrics):
    if metrics.get("status") == "N/A_domain":
        return None, metrics.get("reason", "metric N/A by domain (no observed stage)")
    if metrics.get("NSE") is None:
        return False, "NSE not computed"
    if metrics["NSE"] < 0:
        return False, f"poor fit NSE={metrics['NSE']}"
    return True, f"NSE={metrics['NSE']}, RMSE={metrics.get('RMSE')} ft, n={metrics['n']}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hdf", required=True)
    ap.add_argument("--flow", required=True, help=".fNN flow file with Observed WS")
    ap.add_argument("--profile-index", type=int, default=0)
    ap.add_argument("--figure", default=None)
    a = ap.parse_args()
    metrics = validate(a.hdf, a.flow, profile_index=a.profile_index, figure=a.figure)
    ok, msg = validate_outputs(metrics)
    print(json.dumps({"metrics": metrics, "validation": {"ok": ok, "detail": msg}}, indent=2))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
