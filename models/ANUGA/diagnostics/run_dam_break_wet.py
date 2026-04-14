"""ANUGA dam-break wet-bed benchmark.

Runs ANUGA's 1D Stoker dam-break and compares modeled stage at t=finaltime
to the closed-form (Stoker) analytical solution along the centerline.

Writes a test-result JSON to the path given by $OUTPUT_JSON (default: ./tester_result.json).
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
import tempfile
import warnings

import numpy as np

warnings.simplefilter("ignore")

import anuga
from anuga import Domain


# ----- Stoker analytical solution (vendored from validation_tests/...) -----
def _wu(h2, h0, h1):
    h21 = h2 / h1
    h01 = h0 / h1
    sqrth21 = math.sqrt(h21)
    return h21 * (sqrth21 * (sqrth21 * (h21 - 9 * h01) + 16.0 * h01)
                  - h01 * (h01 + 8.0)) + h01 ** 3


def _calc_h2(h0, h1):
    assert h1 > 0.0 and 0.0 <= h0 <= h1
    if h0 / h1 >= 1 - 1.0e-4:
        return 0.5 * (h0 + h1)
    from scipy.optimize import brentq
    return brentq(_wu, h0, h1, args=(h0, h1))


def vec_dam_break(x, t, h0=1.0, h1=10.0, g=9.81):
    h2 = _calc_h2(h0, h1)
    u2 = 2.0 * (math.sqrt(g * h1) - math.sqrt(g * h2))
    try:
        s = u2 * h2 / (h2 - h0)
    except ZeroDivisionError:
        s = math.sqrt(g * h2)
    c1 = math.sqrt(g * h1)
    c2 = math.sqrt(g * h2)
    condlist = [x < -t * c1, x < t * (u2 - c2), x < s * t]
    hchoice = [h1,
               1.0 / g * (2.0 / 3.0 * c1 - 1.0 / 3.0 * x / t) ** 2,
               h2]
    return np.select(condlist, hchoice, default=h0)


# ----- Run ANUGA dam-break wet -----
def run_model(output_dir: str) -> tuple[str, float]:
    dx, dy = 1.0, 1.0
    L = 1000.0
    W = 5 * dx
    h0, h1 = 1.0, 10.0

    def height(x, y):
        z = np.zeros(len(x), float)
        z[x <= 0.0] = h1
        z[x > 0.0] = h0
        return z

    points, vertices, boundary = anuga.rectangular_cross(
        int(L / dx), int(W / dy), L, W, (-L / 2.0, -W / 2.0)
    )
    domain = Domain(points, vertices, boundary)
    domain.set_name("dam_break")
    domain.set_datadir(output_dir)
    domain.set_flow_algorithm("DE0")

    domain.set_quantity("elevation", 0.0)
    domain.set_quantity("friction", 0.0)
    domain.set_quantity("stage", height)

    Bt = anuga.Transmissive_boundary(domain)
    Br = anuga.Reflective_boundary(domain)
    domain.set_boundary({"left": Bt, "right": Bt, "top": Br, "bottom": Br})

    t0 = time.time()
    for _ in domain.evolve(yieldstep=0.5, finaltime=50.0):
        pass
    wall = time.time() - t0

    try:
        domain.sww_merge(delete_old=True)
    except Exception:
        pass

    sww_path = os.path.join(output_dir, "dam_break.sww")
    return sww_path, wall


# ----- Read back centerline stage from SWW at final time -----
def sample_centerline_stage(sww_path: str, xs: np.ndarray, y: float = 0.0):
    from anuga.file.netcdf import NetCDFFile
    nc = NetCDFFile(sww_path, "r")
    try:
        x = np.asarray(nc.variables["x"][:], dtype=float)
        yv = np.asarray(nc.variables["y"][:], dtype=float)
        stage = np.asarray(nc.variables["stage"][-1, :], dtype=float)  # last time slice
        xllcorner = float(getattr(nc, "xllcorner", 0.0))
        yllcorner = float(getattr(nc, "yllcorner", 0.0))
    finally:
        nc.close()

    x_abs = x + xllcorner
    y_abs = yv + yllcorner

    # Pick vertices in a thin band around y=0 and interpolate to xs using nearest-x
    # fall-back via np.interp on sorted-by-x subset.
    band = np.abs(y_abs - y) < 1.5  # dy=1 so ±1.5 captures the center row
    xb = x_abs[band]
    sb = stage[band]
    order = np.argsort(xb)
    xb = xb[order]
    sb = sb[order]
    # de-duplicate x
    unique_x, idx = np.unique(xb, return_index=True)
    sb_u = np.array([sb[xb == ux].mean() for ux in unique_x])
    return np.interp(xs, unique_x, sb_u)


# ----- Metrics -----
def nse(obs, mod):
    obs = np.asarray(obs, float); mod = np.asarray(mod, float)
    denom = np.sum((obs - obs.mean()) ** 2)
    if denom == 0:
        return float("nan")
    return float(1.0 - np.sum((obs - mod) ** 2) / denom)


def pearson_r(obs, mod):
    obs = np.asarray(obs, float); mod = np.asarray(mod, float)
    if obs.std() == 0 or mod.std() == 0:
        return float("nan")
    return float(np.corrcoef(obs, mod)[0, 1])


def kge(obs, mod):
    obs = np.asarray(obs, float); mod = np.asarray(mod, float)
    r = pearson_r(obs, mod)
    if np.isnan(r):
        return float("nan")
    alpha = mod.std() / obs.std() if obs.std() != 0 else float("nan")
    beta = mod.mean() / obs.mean() if obs.mean() != 0 else float("nan")
    return float(1.0 - math.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2))


def main():
    workdir = tempfile.mkdtemp(prefix="anuga_dambreak_")
    try:
        sww_path, wall = run_model(workdir)

        # Sample the central wave region where the Riemann fan is
        xs = np.linspace(-400.0, 400.0, 161)
        modeled = sample_centerline_stage(sww_path, xs, y=0.0)
        analytical = vec_dam_break(xs, t=50.0, h0=1.0, h1=10.0, g=9.81)

        result = {
            "model_id": "ANUGA",
            "status": "completed",
            "test_runs": [
                {
                    "variable_compared": "stage",
                    "variable_unit": "m",
                    "comparison_type": "analytical",
                    "obs_source_detail": (
                        "Stoker wet-bed dam-break analytical solution "
                        "(h_left=10 m, h_right=1 m, g=9.81, t=50 s). "
                        "Benchmark runner: knowledge_infrastructure/diagnostics/run_dam_break_wet.py. "
                        f"Walltime={wall:.2f}s, SWW={sww_path}."
                    ),
                    "model_actually_produced": 1,
                    "location": "1D dam-break centerline, x in [-400, 400] m, 161 pts, y=0",
                    "nse": nse(analytical, modeled),
                    "r": pearson_r(analytical, modeled),
                    "kge": kge(analytical, modeled),
                    "n_samples": int(xs.size),
                    "wall_seconds": wall,
                }
            ],
        }

        out_json = os.environ.get("OUTPUT_JSON", "tester_result.json")
        with open(out_json, "w") as f:
            json.dump(result, f, indent=2)
        print(json.dumps(result, indent=2))
    finally:
        # Keep the sww for inspection; just print location
        pass


if __name__ == "__main__":
    main()
