"""Calibratability triage — decide whether calibration is even the RIGHT TOOL
before spending hours tuning (user's insight, 2026-06-27).

Calibration only moves what parameters can move: volume bias (PBIAS/beta) and,
partly, variability (alpha/flashiness). It CANNOT fix a wrong hydrograph SHAPE or
TIMING — that is the correlation term `r`, and a poor `r` means the *setup* is off
(forcing, routing, basin delineation, gauge->channel mapping, units, missing
reservoir ops), not the parameter values. So:

  * If baseline `r` is poor  -> calibration is the wrong tool -> DIAGNOSE THE SETUP.
  * If parameters don't move the metric at all -> either the driver isn't applying
    them (good baseline, broken plumbing) or the model is unresponsive at this site.
  * If baseline is already above target -> calibration is low-value -> SKIP.

This pairs with the sensitivity screen (Morris mu*/n_effects): the screen says
whether parameters CAN move the metric; this module says whether they SHOULD, given
the baseline error decomposition. Together they route the self-improve loop to one
of {calibrate, fix_driver, diagnose_setup, already_adequate} instead of blindly
optimizing. The KGE/Gupta decomposition (r, alpha, beta) is the rigorous form of
"check the R values first."
"""
from __future__ import annotations


# default-target metric direction: higher is better for these, lower for these
_HIGHER_BETTER = {"NSE", "KGE", "R", "R2", "NSE_LOG", "SPEARMAN", "CSI"}


def _ci_get(d: dict, *keys):
    """case-insensitive lookup across candidate keys; returns first finite hit."""
    if not isinstance(d, dict):
        return None
    low = {str(k).lower(): v for k, v in d.items()}
    for k in keys:
        v = low.get(str(k).lower())
        if v is None:
            continue
        try:
            f = float(v)
            if f == f and abs(f) != float("inf"):   # finite
                return f
        except (TypeError, ValueError):
            continue
    return None


def metrics_for_var(metrics: dict, var: str) -> dict:
    """The var-scoped sub-dict wins (multi-target); else the flat dict is this var's
    metrics. Mirrors objectives.Objective._metrics_for_var so the triage reads the
    SAME numbers the optimizer scored."""
    if isinstance(metrics, dict) and isinstance(metrics.get(var), dict):
        return metrics[var]
    return metrics or {}


def assess(baseline_metrics: dict, target_var: str, valid_families, mu_star, n_effects,
           *, pattern_tol: float = 0.5, mag_tol: float = 0.1, sens_eps: float = 1e-6,
           metric_overrides=None) -> dict:
    """GATE-DRIVEN triage (2026-06-27): uses the SAME family-partition verdict the loop
    uses to fire calibration (`objectives.calibration_verdict`), so the in-module check
    speaks one language with the loop — NO hardcoded r. `valid_families` are the dag's
    sanctioned metric_families for this target's (var, obs_shape).

    Returns {route, status, reason, baseline, family_verdict, sensitive, screen_ok}.
    route in {calibrate, calibrate_caution, fix_driver, diagnose_setup,
              already_adequate, screen_failed, undetermined}. Only calibrate/
    calibrate_caution proceed to optimization; the rest are early-exit signals (the key
    one, diagnose_setup, says the SETUP/structure is wrong, not the parameters).

    Combines the gate verdict (is the structure right? is it calibration territory?) with
    the sensitivity screen (do the params actually move the metric?):
      structural + insensitive -> diagnose_setup   (setup wrong AND params can't fix it)
      structural + sensitive   -> calibrate_caution (structure off but params move it; probe)
      calibrate  + sensitive   -> calibrate          (the happy path)
      calibrate  + insensitive -> fix_driver         (magnitude off but params don't move it)
      adequate                 -> already_adequate
    """
    from .objectives import calibration_verdict

    m = metrics_for_var(baseline_metrics or {}, target_var)
    base = {"r": _ci_get(m, "r", "correlation", "pearson_r"),
            "nse": _ci_get(m, "NSE", "nse"), "kge": _ci_get(m, "KGE", "kge"),
            "pbias": _ci_get(m, "PBIAS", "pbias")}

    mu = list(mu_star or [])
    ne = list(n_effects or [])
    sensitive = bool(mu) and max(abs(x) for x in mu) > sens_eps
    any_effects = bool(ne) and max(ne) > 0

    # --- 0) the screen itself produced no finite effects -> runs are failing -------
    if mu and max(abs(x) for x in mu) < 1e-9 and not any_effects:
        return {**_base(base), "route": "screen_failed",
                "status": "screen_runs_failing", "sensitive": False, "screen_ok": False,
                "family_verdict": None,
                "reason": "sensitivity screen recorded NO finite losses — perturbed runs "
                          "failed / wrote no metrics (often model instability at the "
                          "parameter-box corners). Fix the runner / clamp the ranges so the "
                          "model evaluates before calibrating; if it fails everywhere, the "
                          "SETUP is broken, not the parameters."}

    # --- gate-driven structural/magnitude verdict on the BASELINE ------------------
    fv = calibration_verdict(valid_families or [], m,
                             pattern_tol=pattern_tol, mag_tol=mag_tol,
                             metric_overrides=metric_overrides)
    dec = fv["decision"]

    if dec == "adequate":
        return {**_base(base), "route": "already_adequate", "status": "baseline_meets_target",
                "sensitive": sensitive, "screen_ok": True, "family_verdict": fv,
                "reason": f"baseline already adequate ({fv['why']}) — calibration is "
                          f"low-value here; spend the budget on a model that needs it."}

    if dec == "structural":
        # a PATTERN family is failing — the structure/shape is wrong, not the params
        if sensitive:
            return {**_base(base), "route": "calibrate_caution",
                    "status": "poor_pattern_params_sensitive", "sensitive": True,
                    "screen_ok": True, "family_verdict": fv,
                    "reason": f"pattern family failing ({fv['why']}) but params DO move the "
                              f"metric — calibration may shift bias/variance yet likely chases "
                              f"noise; proceed only as a probe. Real fix is upstream "
                              f"(forcing/routing/setup)."}
        return {**_base(base), "route": "diagnose_setup",
                "status": "poor_pattern_params_insensitive", "sensitive": False,
                "screen_ok": True, "family_verdict": fv,
                "reason": f"pattern family failing ({fv['why']}) AND no parameter moves the "
                          f"metric — the SETUP is wrong (forcing / routing / basin "
                          f"delineation / gauge->channel mapping / units / missing ops), not "
                          f"the parameters. Calibration cannot fix this; the self-improve "
                          f"loop should re-examine inputs & model setup."}

    if dec == "calibrate":
        # pattern OK, magnitude off — the happy path IF params move the metric
        if sensitive:
            return {**_base(base), "route": "calibrate", "status": "calibratable",
                    "sensitive": True, "screen_ok": True, "family_verdict": fv,
                    "reason": f"structure OK, magnitude off ({fv['why']}) and parameters are "
                              f"sensitive — calibrate the bias/variance."}
        return {**_base(base), "route": "fix_driver",
                "status": "runner_not_parameter_responsive", "sensitive": False,
                "screen_ok": True, "family_verdict": fv,
                "reason": "structure OK and magnitude is off, but NO parameter moves the "
                          "metric — the calib_run.py driver isn't applying the parameters "
                          "(broken candidate isolation / fixed or stale output). Fix the "
                          "driver so a parameter change changes the scored series."}

    # dec == "undetermined": can't tell structure from this baseline. Defer to the screen.
    if sensitive:
        return {**_base(base), "route": "calibrate_caution", "status": "undetermined_but_sensitive",
                "sensitive": True, "screen_ok": True, "family_verdict": fv,
                "reason": f"gate verdict undetermined ({fv['why']}) but params move the metric "
                          f"— proceed cautiously as a probe."}
    return {**_base(base), "route": "undetermined", "status": "undetermined",
            "sensitive": False, "screen_ok": True, "family_verdict": fv,
            "reason": f"gate verdict undetermined ({fv['why']}) and params don't move the "
                      f"metric — neither calibration nor a clear setup verdict; gather the "
                      f"missing pattern/magnitude metric before deciding."}


def _base(base):
    return {"baseline": base}
