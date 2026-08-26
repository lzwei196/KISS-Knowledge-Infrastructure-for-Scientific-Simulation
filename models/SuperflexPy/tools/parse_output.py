#!/usr/bin/env python3
"""
parse_output.py — Parse SuperflexPy output to standardized CSV and compute metrics.

Reads JSON output from run_superflexpy.py (or raw numpy arrays) and produces:
- Standardized CSV with dates, simulated Q, observed Q
- Hydrological performance metrics (NSE, KGE, PBIAS, RMSE)
- Summary statistics

Metrics come from `ki_tools_common.metrics.all_metrics` — the shared,
deterministic scorer every KI is graded with — so a SuperflexPy number is
comparable with every other model's. The local compute_* functions below are
kept only as a fallback for an environment where ki_tools_common is not
USABLE, and the fallback is REPORTED in the output (`metrics_source`, plus the
verbatim failure in `metrics_source_reason`) rather than being silently
substituted.

"Not usable" is deliberately wider than "not installed": ki_tools_common pulls
in binary extensions (numpy/scipy/pandas ABI), so an installed-but-broken copy
raises AttributeError / ValueError / RuntimeError at import, not ImportError.
Catching only ImportError there would kill this tool at module import and take
the whole pipeline down — a state the pre-edit file never had, because it did
not depend on ki_tools_common at all. So every non-exiting exception is caught,
the local scorer takes over, and the reason travels with the numbers.

Usage:
    python parse_output.py --input results.json --output streamflow.csv
    python parse_output.py --input results.json --output streamflow.csv --warmup 365
    python parse_output.py --input results.json --metrics-only
    python parse_output.py --input results.json --output series.csv \
        --cal-start 1981-01-01 --cal-end 1985-12-31 \
        --val-start 1986-01-01 --val-end 1990-12-31
"""

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

# The shared scorer lives outside this KI. It is normally pip-installed; when
# the model's own venv predates it, allow the canonical checkout path.
KI_TOOLS_COMMON_CHECKOUT = "KISSPATH_KI_TOOLS_COMMON"


def _load_shared_all_metrics():
    """-> (all_metrics_or_None, failure_report_or_None).

    Importing an optional cross-KI dependency must NEVER be able to stop this
    tool from running. A broken-but-present ki_tools_common (mismatched numpy
    C-ABI, half-migrated pandas) raises AttributeError / ValueError /
    RuntimeError while executing its transitive imports — none of which are
    ImportError — so a narrow `except ImportError` lets that propagate out of
    module scope and `parse_output.py` dies before argparse ever runs.

    Both attempts are recorded so the caller can report WHY it fell back
    instead of silently substituting a different scorer.
    """
    attempts = []
    for extra_path in (None, KI_TOOLS_COMMON_CHECKOUT):
        where = "installed" if extra_path is None else extra_path
        if extra_path is not None and extra_path not in sys.path:
            sys.path.insert(0, extra_path)
        try:
            from ki_tools_common.metrics import all_metrics
            return all_metrics, None
        except Exception as exc:  # noqa: BLE001 - see docstring; never fatal here
            attempts.append(f"{where}: {type(exc).__name__}: {exc}")
    return None, " | ".join(attempts)


_shared_all_metrics, _SHARED_METRICS_IMPORT_ERROR = _load_shared_all_metrics()


def validate_inputs(args):
    """Validate command-line arguments."""
    errors = []

    input_path = Path(args.input)
    if not input_path.exists():
        errors.append(f"Input file not found: {args.input}")

    if args.warmup < 0:
        errors.append(f"Warmup must be non-negative, got {args.warmup}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def compute_nse(obs, sim):
    """Nash-Sutcliffe Efficiency."""
    obs = np.array(obs, dtype=float)
    sim = np.array(sim, dtype=float)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    if len(obs) == 0:
        return float("nan")
    numerator = np.sum((obs - sim) ** 2)
    denominator = np.sum((obs - np.mean(obs)) ** 2)
    if denominator == 0:
        return float("nan")
    return 1.0 - numerator / denominator


def compute_kge(obs, sim):
    """Kling-Gupta Efficiency (2009 formulation)."""
    obs = np.array(obs, dtype=float)
    sim = np.array(sim, dtype=float)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    if len(obs) < 2:
        return float("nan")

    r = np.corrcoef(obs, sim)[0, 1]
    alpha = np.std(sim) / np.std(obs) if np.std(obs) > 0 else float("nan")
    beta = np.mean(sim) / np.mean(obs) if np.mean(obs) > 0 else float("nan")

    if math.isnan(r) or math.isnan(alpha) or math.isnan(beta):
        return float("nan")

    return 1.0 - math.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)


def compute_pbias(obs, sim):
    """Percent Bias. Positive = model overestimates."""
    obs = np.array(obs, dtype=float)
    sim = np.array(sim, dtype=float)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    if len(obs) == 0 or np.sum(obs) == 0:
        return float("nan")
    return 100.0 * np.sum(sim - obs) / np.sum(obs)


def compute_rmse(obs, sim):
    """Root Mean Square Error."""
    obs = np.array(obs, dtype=float)
    sim = np.array(sim, dtype=float)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    if len(obs) == 0:
        return float("nan")
    return float(np.sqrt(np.mean((obs - sim) ** 2)))


def compute_r(obs, sim):
    """Pearson correlation coefficient."""
    obs = np.array(obs, dtype=float)
    sim = np.array(sim, dtype=float)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    if len(obs) < 2:
        return float("nan")
    return float(np.corrcoef(obs, sim)[0, 1])


def score(obs, sim, dates=None, label="headline"):
    """One paired-series score. ALL FIVE metrics or none — they come from the
    same paired arrays, so reporting `r` while leaving `NSE` null is never a
    real state of affairs, it is a bug."""
    obs = np.asarray(obs, dtype=float)
    sim = np.asarray(sim, dtype=float)
    ok = np.isfinite(obs) & np.isfinite(sim)
    if ok.sum() < 2:
        return {
            "NSE": None, "KGE": None, "PBIAS": None, "RMSE": None, "r": None,
            "n_paired": int(ok.sum()),
            "metrics_null_reason": "fewer than 2 timesteps where sim and obs are both finite",
        }
    o, s = obs[ok], sim[ok]
    d = None
    if dates is not None:
        d = list(np.asarray(dates)[ok])
    fallback_reason = _SHARED_METRICS_IMPORT_ERROR
    m = None
    if _shared_all_metrics is not None:
        try:
            m = dict(_shared_all_metrics(o, s, dates=d, label=label))
            m["metrics_source"] = "ki_tools_common.metrics.all_metrics"
        except Exception as exc:  # noqa: BLE001 - fall back, but say so
            # The scorer imported but could not score (lazy transitive import,
            # ABI mismatch surfacing on first use). Same rule as the import:
            # fall back, never crash, and REPORT it.
            m = None
            fallback_reason = f"call failed: {type(exc).__name__}: {exc}"
    if m is None:
        m = {
            "NSE": compute_nse(o, s),
            "KGE": compute_kge(o, s),
            "PBIAS": compute_pbias(o, s),
            "RMSE": compute_rmse(o, s),
            "r": compute_r(o, s),
            "metrics_source": "LOCAL FALLBACK - ki_tools_common not usable",
            "metrics_source_reason": fallback_reason or "ki_tools_common not importable",
        }
    m["n_paired"] = int(ok.sum())
    if d:
        m["period_start"] = str(d[0])
        m["period_end"] = str(d[-1])
    return m


def window_mask(dates, start, end):
    """Boolean mask over an ISO-date list. All-True when no window is given."""
    if not start and not end:
        return np.ones(len(dates), dtype=bool)
    d = np.asarray(dates, dtype="datetime64[D]")
    m = np.ones(len(d), dtype=bool)
    if start:
        m &= d >= np.datetime64(start, "D")
    if end:
        m &= d <= np.datetime64(end, "D")
    return m


def process(args):
    """Parse model output and compute metrics."""
    with open(args.input, "r") as f:
        data = json.load(f)

    if data.get("status") != "success":
        return {"status": "error", "errors": ["Input data indicates error"]}

    Q_sim = np.array(data["Q_sim"])
    n_total = len(Q_sim)
    warmup = min(args.warmup, n_total - 1)

    # Apply warmup
    Q_sim_eval = Q_sim[warmup:]
    dates = data.get("dates", None)
    if dates:
        dates_eval = dates[warmup:]
    else:
        dates_eval = list(range(warmup, n_total))

    result = {
        "status": "success",
        "n_timesteps_total": n_total,
        "n_timesteps_eval": len(Q_sim_eval),
        "warmup_days": warmup,
        "Q_sim_statistics": {
            "mean": float(np.nanmean(Q_sim_eval)),
            "median": float(np.nanmedian(Q_sim_eval)),
            "max": float(np.nanmax(Q_sim_eval)),
            "min": float(np.nanmin(Q_sim_eval)),
            "std": float(np.nanstd(Q_sim_eval)),
        },
    }

    # Compute metrics if observed data available
    if "Q_obs" in data:
        Q_obs = np.array(data["Q_obs"])
        Q_obs_eval = Q_obs[warmup:]

        have_dates = bool(dates)
        result["metrics"] = score(
            Q_obs_eval, Q_sim_eval,
            dates=dates_eval if have_dates else None,
            label="full",
        )

        # Date-windowed calibration / validation split. The VALIDATION number is
        # the honest one: a calibration-period score is a fitted score.
        #
        # An END alone is a complete window ("everything up to X"), exactly as
        # a START alone is ("everything from X on"). Gating on the starts made
        # `--cal-end`/`--val-end` no-ops that produced NO metrics_calibration /
        # metrics_validation block and NO error, so a run scored the full
        # series while its command line said otherwise. Every one of the four
        # flags now opens the windowed block; the per-role `not a and not b`
        # skip below still keeps an unrequested role out of the output.
        if have_dates and any(
            (args.cal_start, args.cal_end, args.val_start, args.val_end)
        ):
            for role, (a, b) in (
                ("calibration", (args.cal_start, args.cal_end)),
                ("validation", (args.val_start, args.val_end)),
            ):
                if not a and not b:
                    continue
                window_label = f"{a or '(series start)'}..{b or '(series end)'}"
                m = window_mask(dates_eval, a, b)
                if m.sum() == 0:
                    result[f"metrics_{role}"] = {
                        "metrics_null_reason": f"no timesteps in {window_label}"
                    }
                    result[f"period_{role}"] = window_label
                    continue
                result[f"metrics_{role}"] = score(
                    Q_obs_eval[m], Q_sim_eval[m],
                    dates=list(np.asarray(dates_eval)[m]),
                    label="cal" if role == "calibration" else "val",
                )
                result[f"period_{role}"] = window_label

        result["Q_obs_statistics"] = {
            "mean": float(np.nanmean(Q_obs_eval)),
            "median": float(np.nanmedian(Q_obs_eval)),
            "max": float(np.nanmax(Q_obs_eval)),
            "min": float(np.nanmin(Q_obs_eval)),
        }

        # Scored-series CSV. The header is `date,obs,sim` — the column names the
        # evidence contract expects — NOT `Q_sim_mm_d,Q_obs_mm_d`, which no
        # re-derivation step can recognise. Unit is recorded in the JSON
        # (`series_unit`) rather than smuggled into a column name.
        csv_rows = ["date,obs,sim"]
        for i, d in enumerate(dates_eval):
            q_s = f"{Q_sim_eval[i]:.6f}" if not np.isnan(Q_sim_eval[i]) else ""
            q_o = f"{Q_obs_eval[i]:.6f}" if i < len(Q_obs_eval) and not np.isnan(Q_obs_eval[i]) else ""
            csv_rows.append(f"{d},{q_o},{q_s}")
        result["csv_content"] = "\n".join(csv_rows)
        result["series_unit"] = "mm/d"
    else:
        csv_rows = ["date,sim"]
        for i, d in enumerate(dates_eval):
            q_s = f"{Q_sim_eval[i]:.6f}" if not np.isnan(Q_sim_eval[i]) else ""
            csv_rows.append(f"{d},{q_s}")
        result["csv_content"] = "\n".join(csv_rows)
        result["series_unit"] = "mm/d"

    return result


def validate_outputs(result):
    """Validate parsed outputs for common issues."""
    if result["status"] != "success":
        return result

    warnings = []

    if (result.get("metrics") or {}).get("metrics_source", "").startswith("LOCAL"):
        warnings.append(
            "WARNING: metrics came from the LOCAL fallback, not "
            "ki_tools_common.metrics.all_metrics — repair ki_tools_common in "
            "this interpreter before treating the numbers as comparable. "
            "Reason: "
            + str(result["metrics"].get("metrics_source_reason", "unreported"))
        )

    # Check metrics quality
    if "metrics" in result:
        nse = result["metrics"].get("NSE", None)
        if nse is not None and not math.isnan(nse):
            if nse < 0:
                warnings.append(
                    f"WARNING: NSE = {nse:.3f} < 0 — model is worse than mean. "
                    "Check parameter values and forcing units."
                )
            elif nse < 0.5:
                warnings.append(
                    f"WARNING: NSE = {nse:.3f} — considered 'unsatisfactory'. "
                    "Consider calibration."
                )

        pbias = result["metrics"].get("PBIAS", None)
        if pbias is not None and not math.isnan(pbias):
            if abs(pbias) > 25:
                warnings.append(
                    f"WARNING: |PBIAS| = {abs(pbias):.1f}% > 25% — "
                    "large systematic bias, check units (dt_001, dt_002)"
                )

    if warnings:
        result["warnings"] = warnings
        for w in warnings:
            print(w, file=sys.stderr)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Parse SuperflexPy output to CSV and compute metrics"
    )
    parser.add_argument("--input", type=str, required=True, help="Input JSON from run_superflexpy.py")
    parser.add_argument("--output", type=str, default=None, help="Output CSV file path")
    parser.add_argument("--warmup", type=int, default=0, help="Warmup period in timesteps to exclude")
    parser.add_argument("--metrics-only", action="store_true", help="Only print metrics, no CSV")
    parser.add_argument("--cal-start", type=str, default=None, help="Calibration window start YYYY-MM-DD")
    parser.add_argument("--cal-end", type=str, default=None, help="Calibration window end YYYY-MM-DD")
    parser.add_argument("--val-start", type=str, default=None, help="Validation (held-out) window start")
    parser.add_argument("--val-end", type=str, default=None, help="Validation (held-out) window end")
    parser.add_argument("--metrics-json", type=str, default=None,
                        help="Also write the full metrics JSON (minus the CSV body) here")

    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    if args.metrics_json:
        with open(args.metrics_json, "w") as f:
            json.dump({k: v for k, v in result.items() if k != "csv_content"}, f, indent=2)

    if args.metrics_only:
        output = {
            "status": result["status"],
            "metrics": result.get("metrics", {}),
            "warnings": result.get("warnings", []),
        }
        print(json.dumps(output, indent=2))
    elif args.output and "csv_content" in result:
        with open(args.output, "w") as f:
            f.write(result["csv_content"])
        # Print metrics to stderr
        if "metrics" in result:
            print(f"Metrics: {json.dumps(result['metrics'])}", file=sys.stderr)
        print(f"CSV written to {args.output}", file=sys.stderr)
    else:
        # Print full JSON to stdout
        # Remove csv_content from JSON output to keep it manageable
        result_compact = {k: v for k, v in result.items() if k != "csv_content"}
        print(json.dumps(result_compact, indent=2))


if __name__ == "__main__":
    main()
