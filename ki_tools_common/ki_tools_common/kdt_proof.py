"""kdt_proof — the ONE implementation of the `kdt-target-proof/1` record every KI driver emits.

Why this exists (2026-09-14, calibration-kit gap fix, plan v2):
The calibration kit used to decide whether a parameter reached the model by whether the SCORE
moved. Scores are rounded (NSE to 4 dp), so a real weak parameter can leave them untouched and a
dead parameter cannot be told from a weak one. Three WRF-Hydro parameters wrote into a file the
model never opened and passed every check for two months. The kit now compares the RAW scored
series instead — and this record is how a driver hands that series over.

Why it is here and not in each driver: fifteen runner-mode drivers each write their own
`__kdt__` block. Fifteen hand-written copies of a hashing routine is fifteen chances to get the
canonicalisation wrong in a way the kit would then misjudge. One implementation, tested once.

Usage in a driver, after it has the aligned arrays it scores:

    from ki_tools_common.kdt_proof import target_proof
    payload["__kdt__"]["target_proofs"] = [
        target_proof(sim_values, index, target="streamflow", unit="m3/s",
                     split=split_name, window=(start, end), source="CHRTOUT feature idx=31 ...")
    ]

The kit validates the record (`Evaluator._proof_valid`): schema, n == len(values) == len(index),
recomputed hashes match, every value finite. Emit exactly what was scored — the same array the
metrics were computed from — or the kit will judge something the score did not see.
"""
from __future__ import annotations
import hashlib
from typing import Iterable, Sequence

import numpy as np

SCHEMA = "kdt-target-proof/1"


def _index_strings(index: Iterable) -> list[str]:
    out = []
    for d in index:
        s = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
        out.append(s)
    return out


def target_proof(sim_values: Sequence[float], index: Iterable, *, target: str, unit: str,
                 split: str, window: Sequence[str], source: str = "") -> dict:
    """Build a kdt-target-proof/1 record from the scored simulation series.

    sim_values : the model values that were scored, aligned 1:1 with `index`, full precision.
    index      : dates (datetime-like) or labels, same length.
    target     : the calibration target name as declared in calibration.yaml `targets[].var`.
    unit       : the physical unit of sim_values.
    split      : 'calibration' | 'holdout' | 'full' — the split the driver ran.
    window     : (start, end) of the scored window, as strings.
    source     : free text — where the series came from (feature id, extraction tool, join).

    Raises on non-finite values or a length mismatch: a proof that could not be validated by the
    kit must not be emitted at all, because the kit would then mark the box UNPROVEN and the
    driver author should know why.
    """
    vals = np.asarray(sim_values, dtype=np.float64)
    idx = _index_strings(index)
    if vals.ndim != 1:
        raise ValueError(f"target_proof: sim_values must be 1-D, got shape {vals.shape}")
    if len(idx) != len(vals):
        raise ValueError(f"target_proof: index has {len(idx)} entries, values {len(vals)}")
    if not np.all(np.isfinite(vals)):
        raise ValueError(f"target_proof: {int((~np.isfinite(vals)).sum())} non-finite value(s) in the "
                         f"scored series for {target!r} — emit only what was scored")
    if not target:
        raise ValueError("target_proof: target name is required")
    return {
        "schema": SCHEMA,
        "target": str(target),
        "unit": str(unit),
        "split": str(split),
        "window": [str(window[0]), str(window[1])],
        "n": int(len(vals)),
        "dtype": "float64",
        "index_hash": hashlib.sha1("\n".join(idx).encode()).hexdigest(),
        "values_hash": hashlib.sha1(vals.tobytes()).hexdigest(),
        "values": [float(v) for v in vals],
        "index": idx,
        "source": str(source),
    }


def _as_finite_number(v):
    """float(v) when v is a real finite number (bool excluded), else None."""
    if isinstance(v, bool) or not isinstance(v, (int, float, np.integer, np.floating)):
        return None
    f = float(v)
    return f if np.isfinite(f) else None


def verify_against_metrics(proof: dict, obs_values: Sequence[float], metrics_fn, metrics: dict,
                           tol: float = 1e-9) -> tuple[bool, str]:
    """Port-time self-check for a driver: recompute the metrics from the PROOF's values and the
    same obs, and confirm they equal what the driver reported. If they do not, the driver emitted a
    series the score did not see, and the kit would judge the wrong thing.

    Strict (2026-10-15, codex kiss_sync review): it passes ONLY when `metrics` is a non-empty dict,
    every reported key is also in the recomputed result, and for every key both the reported and
    the recomputed value are finite numbers within `tol`. A missing key, a NaN/inf or non-numeric
    value on either side, or an empty `metrics` fails - nothing is skipped as "not comparable"."""
    if not isinstance(metrics, dict) or not metrics:
        return False, "no reported metrics to verify (empty or not a dict)"
    try:
        m2 = metrics_fn(np.asarray(obs_values, dtype=np.float64), np.asarray(proof["values"], dtype=np.float64))
    except Exception as e:  # noqa: BLE001
        return False, f"metrics_fn failed on proof values: {e}"
    if not isinstance(m2, dict) or not m2:
        return False, f"metrics_fn returned no metrics from proof values ({type(m2).__name__})"
    bad = []
    for k, v in metrics.items():
        if k not in m2:
            bad.append(f"{k}: reported by driver but not recomputed from proof")
            continue
        rv, cv = _as_finite_number(v), _as_finite_number(m2[k])
        if rv is None:
            bad.append(f"{k}: driver value {v!r} is not a finite number")
        elif cv is None:
            bad.append(f"{k}: from-proof value {m2[k]!r} is not a finite number")
        elif not abs(cv - rv) <= tol:
            bad.append(f"{k}: driver {v!r} vs from-proof {m2[k]!r}")
    return (not bad), ("; ".join(bad) if bad else f"{len(metrics)} metric(s) reproduce from proof values")
