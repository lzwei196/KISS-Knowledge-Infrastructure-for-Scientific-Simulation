#!/usr/bin/env python3
"""
pySTEPS synthetic-advection diagnostic.

Builds a sequence of 2-D precipitation fields where a Gaussian rainfall blob
translates at constant velocity, runs real pysteps motion + extrapolation
nowcast on the first frames, and scores the nowcast against the held-out
future frames using pysteps.verification.

This exercises the real pysteps code paths (proesmans motion, extrapolation
nowcast, det_cat_fct, fss). It is not a scientific skill-score benchmark.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

try:
    import importlib.metadata as ilm
    PYSTEPS_VERSION = ilm.version("pysteps")
except Exception:
    PYSTEPS_VERSION = "unknown"

from pysteps import motion, nowcasts
from pysteps.verification import det_cat_fct, fss


def synth_sequence(
    n_frames: int = 9,
    nx: int = 200,
    ny: int = 200,
    u: float = 2.0,
    v: float = 1.0,
    sigma: float = 18.0,
    peak_rate: float = 8.0,
    x0: float = 60.0,
    y0: float = 60.0,
) -> np.ndarray:
    """Sequence of Gaussian blobs translating at (u,v) px/frame."""
    yy, xx = np.mgrid[0:ny, 0:nx].astype(np.float64)
    out = np.empty((n_frames, ny, nx), dtype=np.float64)
    for t in range(n_frames):
        cx = x0 + u * t
        cy = y0 + v * t
        out[t] = peak_rate * np.exp(
            -((xx - cx) ** 2 + (yy - cy) ** 2) / (2.0 * sigma ** 2)
        )
    return out


def main() -> int:
    out_dir = Path(__file__).resolve().parent
    t_start = time.time()

    n_past = 4
    n_lead = 5
    seq = synth_sequence(n_frames=n_past + n_lead)
    past = seq[:n_past]
    truth = seq[n_past:]

    # Motion field via Proesmans (compiled Cython). Takes exactly 2 frames,
    # requires float64 buffers.
    proesmans = motion.get_method("proesmans")
    t0 = time.time()
    motion_field = proesmans(past[-2:].astype(np.float64))
    motion_time = time.time() - t0

    # Extrapolation nowcast
    extrapolate = nowcasts.get_method("extrapolation")
    t0 = time.time()
    nowcast = extrapolate(past[-1], motion_field, n_lead)
    nowcast_time = time.time() - t0

    nowcast_scored = np.where(np.isnan(nowcast), 0.0, nowcast)

    thr = 0.5
    scale_px = 20
    per_lead = []
    for i in range(n_lead):
        cat = det_cat_fct(nowcast_scored[i], truth[i], thr=thr)
        fss_score = fss(nowcast_scored[i], truth[i], thr=thr, scale=scale_px)
        per_lead.append(
            {
                "lead": i + 1,
                "CSI": float(cat["CSI"]),
                "POD": float(cat["POD"]),
                "FAR": float(cat["FAR"]),
                "FSS": float(fss_score),
                "max_nowcast_mmh": float(nowcast_scored[i].max()),
                "max_truth_mmh": float(truth[i].max()),
            }
        )

    mean_csi = float(np.mean([d["CSI"] for d in per_lead]))
    mean_fss = float(np.mean([d["FSS"] for d in per_lead]))

    result = {
        "pysteps_version": PYSTEPS_VERSION,
        "grid": list(seq.shape[1:]),
        "n_past_frames": n_past,
        "n_lead_frames": n_lead,
        "threshold_mmh": thr,
        "fss_scale_px": scale_px,
        "motion_method": "proesmans",
        "nowcast_method": "extrapolation",
        "motion_time_s": round(motion_time, 3),
        "nowcast_time_s": round(nowcast_time, 3),
        "total_time_s": round(time.time() - t_start, 3),
        "mean_CSI": mean_csi,
        "mean_FSS": mean_fss,
        "per_lead": per_lead,
    }

    (out_dir / "last_run.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
