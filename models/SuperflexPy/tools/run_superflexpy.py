#!/usr/bin/env python3
"""
run_superflexpy.py — Execute a SuperflexPy model and save outputs.

Wrapper that assembles a model from a configuration, loads forcing data,
runs the simulation, and saves streamflow + state time series.

Supports pre-built models (GR4J, HBV, HYMOD) and custom configurations.

Covers pipeline stages s3 (assembly), s4 (initial conditions), s5 (execution)
and s7 (calibration). s7 used to be documented as "Python API" with no tool,
which forced every agent to hand-roll a calibration loop -- and a hand-rolled
loop that omits `model.reset_states()` between trials is SILENTLY WRONG (see
dt_019). The calibration loop here is the one from the package's own shipped
example, examples/02_calibrate_a_model.ipynb:

    model.set_parameters(...); model.reset_states(); model.get_output()

Usage:
    python run_superflexpy.py --model gr4j --forcing forcing.json --output results.json
    python run_superflexpy.py --model gr4j --forcing forcing.json --params x1=300 x3=50 --output results.json
    python run_superflexpy.py --model hbv --forcing forcing.json --timestep 1.0 --output results.json
    # s2 -> s5 hand-off (consume convert_parameters.py output directly):
    python run_superflexpy.py --model gr4j --forcing forcing.json --params-json params.json --output results.json
    # s7 calibration on a held-in window, honest held-out window untouched:
    python run_superflexpy.py --model gr4j --forcing forcing.json --params-json params.json \
        --calibrate --cal-start 1981-01-01 --cal-end 1985-12-31 \
        --architecture numba --diagnostics --output results.json
    # ... or declare only the held-out window: the calibration window is then
    # the rest of the series, and the optimiser never sees 1986 onwards:
    python run_superflexpy.py --model gr4j --forcing forcing.json --params-json params.json \
        --calibrate --val-start 1986-01-01 --val-end 1990-12-31 --output results.json

--val-start/--val-end are HELD OUT, not merely annotated: they are subtracted
from the calibration mask, and an explicit --cal-start/--cal-end that overlaps
them is a hard error rather than a quietly-fitted "validation" score.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np


# ---------------------------------------------------------------------------
# Parameter aliases: the SHORT name a modeller uses (and that SKILL.md and
# convert_parameters.py both speak) -> the PREFIXED name(s) SuperflexPy
# actually exposes via get_parameters_name() (dk_004).
#
# Two traps this closes:
#   * `x4` -- SKILL.md documents x4 as GR4J's unit-hydrograph time base, but NO
#     SuperflexPy parameter is called x4. It is split across two elements as
#     `gr4j_uh1_lag-time` and `gr4j_uh2_lag-time`, and the GR4J definition is
#     uh2 = 2 * x4. The old endswith() lookup silently reported
#     "Parameter 'x4' not found" and ran the DEFAULT lag, so an agent
#     calibrating x4 was calibrating nothing.
#   * ambiguity -- endswith() took matched[0] with no check, so a short name
#     matching two prefixed parameters silently set only the first.
# Each entry maps short -> list of (prefixed_name, multiplier).
# ---------------------------------------------------------------------------
PARAM_ALIASES = {
    "gr4j": {
        "x1": [("gr4j_ps_x1", 1.0)],
        "x2": [("gr4j_rs_x2", 1.0)],
        "x3": [("gr4j_rs_x3", 1.0)],
        "x4": [("gr4j_uh1_lag-time", 1.0), ("gr4j_uh2_lag-time", 2.0)],
        "alpha": [("gr4j_ps_alpha", 1.0)],
        "beta": [("gr4j_ps_beta", 1.0)],
        "ni": [("gr4j_ps_ni", 1.0)],
        "gamma": [("gr4j_rs_gamma", 1.0)],
        "omega": [("gr4j_rs_omega", 1.0)],
    },
    "hbv": {
        "Smax": [("hbv_ur_Smax", 1.0)],
        "Ce": [("hbv_ur_Ce", 1.0)],
        "m": [("hbv_ur_m", 1.0)],
        "beta": [("hbv_ur_beta", 1.0)],
        "k": [("hbv_fr_k", 1.0)],
        "alpha": [("hbv_fr_alpha", 1.0)],
    },
}

# Which short names are free by default when --calibrate is given, in the
# sensitivity order documented in SKILL.md "Calibration Parameters".
DEFAULT_FREE_PARAMS = {
    "gr4j": ["x1", "x3", "x4", "x2"],
    "hbv": ["Smax", "beta", "k", "alpha", "Ce", "m"],
    "hymod": ["Smax", "beta", "k", "m"],
}

# `cpet` is NOT a SuperflexPy parameter: it is a multiplicative correction on
# the PET FORCING, applied before set_input(). It exists because reanalysis PET
# products (ERA5-Land in Caravan, MSWX) are biased high relative to the PET a
# lumped conceptual model is calibrated against, and GR4J -- unlike HBV, whose
# Ce does exactly this job -- has no internal PET coefficient. Left at 1.0 it
# is a no-op, so default behaviour is unchanged.
CPET_BOUNDS = (0.2, 2.0)


def validate_inputs(args):
    """Validate command-line arguments."""
    errors = []

    if args.forcing:
        forcing_path = Path(args.forcing)
        if not forcing_path.exists():
            errors.append(f"Forcing file not found: {args.forcing}")

    if args.model not in ("gr4j", "hbv", "hymod", "custom"):
        errors.append(
            f"Unknown model: {args.model}. "
            "Supported: gr4j, hbv, hymod, custom"
        )

    if args.timestep <= 0:
        errors.append(f"Timestep must be positive, got {args.timestep}")

    if args.solver not in ("implicit_euler", "explicit_euler", "runge_kutta"):
        errors.append(
            f"Unknown solver: {args.solver}. "
            "Supported: implicit_euler, explicit_euler, runge_kutta"
        )

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def build_model(args):
    """Assemble the SuperflexPy model from configuration."""
    model_type = args.model
    solver_type = args.solver
    arch = args.architecture

    # Import framework components
    if solver_type == "implicit_euler":
        if arch == "numba":
            from superflexpy.implementation.numerical_approximators.implicit_euler import ImplicitEulerNumba as Solver
            from superflexpy.implementation.root_finders.pegasus import PegasusNumba as RootFinder
        else:
            from superflexpy.implementation.numerical_approximators.implicit_euler import ImplicitEulerPython as Solver
            from superflexpy.implementation.root_finders.pegasus import PegasusPython as RootFinder
        root_finder = RootFinder()
        num_app = Solver(root_finder=root_finder)
    elif solver_type == "explicit_euler":
        from superflexpy.implementation.numerical_approximators.explicit_euler import ExplicitEulerPython as Solver
        num_app = Solver()
    elif solver_type == "runge_kutta":
        from superflexpy.implementation.numerical_approximators.runge_kutta_4 import RungeKutta4Python as Solver
        num_app = Solver()

    if model_type == "gr4j":
        from superflexpy.framework.unit import Unit
        from superflexpy.implementation.elements.gr4j import (
            FluxAggregator,
            InterceptionFilter,
            ProductionStore,
            RoutingStore,
            UnitHydrograph1,
            UnitHydrograph2,
        )
        from superflexpy.implementation.elements.structure_elements import Junction, Splitter, Transparent

        x1, x2, x3, x4 = 350.0, 0.0, 90.0, 1.7

        interception_filter = InterceptionFilter(id="ir")
        production_store = ProductionStore(
            parameters={"x1": x1, "alpha": 2.0, "beta": 5.0, "ni": 4 / 9},
            states={"S0": 10.0},
            approximation=num_app,
            id="ps",
        )
        splitter = Splitter(weight=[[0.9], [0.1]], direction=[[0], [0]], id="spl")
        uh1 = UnitHydrograph1(parameters={"lag-time": x4}, states={"lag": None}, id="uh1")
        uh2 = UnitHydrograph2(parameters={"lag-time": 2 * x4}, states={"lag": None}, id="uh2")
        routing_store = RoutingStore(
            parameters={"x2": x2, "x3": x3, "gamma": 5.0, "omega": 3.5},
            states={"S0": 10.0},
            approximation=num_app,
            id="rs",
        )
        transparent = Transparent(id="tr")
        junction = Junction(direction=[[0, None], [1, None], [None, 0]], id="jun")
        flux_agg = FluxAggregator(id="fa")

        model = Unit(
            layers=[
                [interception_filter],
                [production_store],
                [splitter],
                [uh1, uh2],
                [routing_store, transparent],
                [junction],
                [flux_agg],
            ],
            id="gr4j",
        )
        input_order = "PET,P"

    elif model_type == "hbv":
        from superflexpy.framework.unit import Unit
        from superflexpy.implementation.elements.hbv import PowerReservoir, UnsaturatedReservoir

        ur = UnsaturatedReservoir(
            parameters={"Smax": 200.0, "Ce": 1.0, "m": 0.01, "beta": 2.0},
            states={"S0": 10.0},
            approximation=num_app,
            id="ur",
        )
        fr = PowerReservoir(
            parameters={"k": 0.05, "alpha": 2.5},
            states={"S0": 0.0},
            approximation=num_app,
            id="fr",
        )

        model = Unit(layers=[[ur], [fr]], id="hbv")
        input_order = "P,PET"

    elif model_type == "hymod":
        from superflexpy.implementation.models.hymod import model

        input_order = "P,PET"

    else:
        print(json.dumps({"status": "error", "errors": ["Custom model not yet supported via CLI"]}))
        sys.exit(1)

    return model, input_order


def resolve_param_name(model_type, key, param_names):
    """Short parameter name -> list of (prefixed_name, multiplier).

    Raises ValueError on an unknown OR ambiguous name. Never silently picks the
    first of several matches (the old endswith()[0] behaviour), because a
    silently-unset parameter during calibration looks exactly like a parameter
    with no sensitivity.
    """
    aliases = PARAM_ALIASES.get(model_type, {})
    if key in aliases:
        targets = aliases[key]
        missing = [t for t, _ in targets if t not in param_names]
        if missing:
            raise ValueError(
                f"alias '{key}' maps to {missing}, absent from this model's "
                f"parameters {param_names}"
            )
        return targets
    matched = [pn for pn in param_names if pn == key or pn.endswith("_" + key)]
    if not matched:
        raise ValueError(
            f"Parameter '{key}' not found in model '{model_type}'. "
            f"Known short names: {sorted(aliases)}; full names: {param_names}"
        )
    if len(matched) > 1:
        raise ValueError(
            f"Parameter '{key}' is AMBIGUOUS -- matches {matched}. "
            "Use the full prefixed name (dk_004)."
        )
    return [(matched[0], 1.0)]


def apply_params(model, model_type, pdict):
    """Set every short-named parameter in pdict on the model. Returns the
    prefixed dict actually applied, for the record."""
    param_names = model.get_parameters_name()
    applied = {}
    for key, val in pdict.items():
        if key == "cpet":  # forcing correction, not a model parameter
            continue
        for full, mult in resolve_param_name(model_type, key, param_names):
            applied[full] = float(val) * mult
    if applied:
        model.set_parameters(applied)
    return applied


def load_params_json(path):
    """Read convert_parameters.py (s2) output -> (values, bounds).

    bounds only contains the entries convert_parameters marked NOT fixed and
    for which it gave a real min/max, so the calibration search space is the
    one s2 published rather than a range re-typed by hand.
    """
    with open(path, "r") as f:
        doc = json.load(f)
    if doc.get("status") != "success":
        raise ValueError(f"params-json {path} indicates error status")
    values = dict(doc.get("parameters", {}))
    bounds = {}
    for name, info in (doc.get("parameter_info") or {}).items():
        if info.get("fixed"):
            continue
        lo, hi = (info.get("range") or [None, None])[:2]
        if lo is not None and hi is not None:
            bounds[name] = (float(lo), float(hi))
    return values, bounds


def date_mask(dates, start, end):
    """Boolean mask over an ISO-date list for [start, end] inclusive."""
    d = np.asarray(dates, dtype="datetime64[D]")
    m = np.ones(len(d), dtype=bool)
    if start:
        m &= d >= np.datetime64(start, "D")
    if end:
        m &= d <= np.datetime64(end, "D")
    return m


def _nse(obs, sim):
    ok = np.isfinite(obs) & np.isfinite(sim)
    if ok.sum() < 2:
        return float("nan")
    o, s = obs[ok], sim[ok]
    den = np.sum((o - o.mean()) ** 2)
    if den <= 0:
        return float("nan")
    return 1.0 - np.sum((o - s) ** 2) / den


def _kge(obs, sim):
    ok = np.isfinite(obs) & np.isfinite(sim)
    if ok.sum() < 2:
        return float("nan")
    o, s = obs[ok], sim[ok]
    if o.std() <= 0 or o.mean() == 0:
        return float("nan")
    r = np.corrcoef(o, s)[0, 1]
    return 1.0 - np.sqrt(
        (r - 1) ** 2 + (s.std() / o.std() - 1) ** 2 + (s.mean() / o.mean() - 1) ** 2
    )


def run_once(model, model_type, inputs_fn, pvec_dict):
    """One full simulation with the trial parameters. THE reset_states() call
    below is load-bearing: without it a second get_output() continues from the
    previous run's storage AND lag memory, so identical parameters give
    different Q (verified: 5.45 mm/d max difference on a 500-day series) and
    the optimiser is fitting run order, not parameters (dt_019)."""
    apply_params(model, model_type, pvec_dict)
    model.set_input(inputs_fn(pvec_dict.get("cpet", 1.0)))
    model.reset_states()
    return np.asarray(model.get_output()[0], dtype=float)


def calibrate(model, model_type, inputs_fn, fixed_params, free_names, bounds,
              obs, cal_mask, args):
    """s7: differential evolution on the calibration window only.

    The validation window is never touched here -- it is not even passed in.
    """
    from scipy.optimize import differential_evolution

    lo = np.array([bounds[n][0] for n in free_names], dtype=float)
    hi = np.array([bounds[n][1] for n in free_names], dtype=float)
    obs_cal = obs[cal_mask]
    n_eval = {"n": 0}
    score_fn = _kge if args.objective == "kge" else _nse

    def objective(vec):
        n_eval["n"] += 1
        trial = dict(fixed_params)
        trial.update({n: float(v) for n, v in zip(free_names, vec)})
        try:
            q = run_once(model, model_type, inputs_fn, trial)
        except Exception:
            return 1e6
        if not np.all(np.isfinite(q)):
            return 1e6
        s = score_fn(obs_cal, q[cal_mask])
        if not np.isfinite(s):
            return 1e6
        return 1.0 - s

    t0 = time.time()
    res = differential_evolution(
        objective,
        bounds=list(zip(lo, hi)),
        maxiter=args.maxiter,
        popsize=args.popsize,
        tol=args.tol,
        seed=args.seed,
        polish=False,
        init="latinhypercube",
        workers=1,
        updating="immediate",
    )
    best = dict(fixed_params)
    best.update({n: float(v) for n, v in zip(free_names, res.x)})
    return best, {
        "algorithm": "scipy.differential_evolution",
        "objective": f"1 - {args.objective.upper()} on calibration window",
        "free_parameters": list(free_names),
        "bounds": {n: list(bounds[n]) for n in free_names},
        "n_evaluations": n_eval["n"],
        "seed": args.seed,
        "maxiter": args.maxiter,
        "popsize": args.popsize,
        f"best_{args.objective}_cal": float(1.0 - res.fun) if res.fun < 1e5 else None,
        "wall_time_s": round(time.time() - t0, 1),
        "converged": bool(res.success),
        "message": str(res.message),
    }


def collect_diagnostics(model, model_type, P, PET_used, Q_sim, dt):
    """dag outputs AET (rank 3), S (rank 4) and F (rank 5), plus a term-by-term
    water balance built from the model's OWN internal fluxes rather than from a
    residual (a residual balance always closes and proves nothing).

    GR4J's ledger, derived from the element equations:
        P = AET_interception + AET_production
            + dS_production + dS_lag1 + dS_lag2 + dS_routing
            + Q_sim + F_exchange_total
    where F_exchange_total = sum(F) + sum(min(Q2_out, F)) because GR4J applies
    the exchange flux TWICE -- once inside the routing store's ODE and once on
    the direct branch inside the FluxAggregator.
    """
    diag = {}
    if model_type == "gr4j":
        aet_ps = np.asarray(model.call_internal(id="ps", method="get_aet")[0], dtype=float)
        aet_int = np.minimum(PET_used, P)          # InterceptionFilter removal
        aet_tot = aet_int + aet_ps
        rs_out = model.call_internal(id="rs", method="get_output", solve=False)
        qr = np.asarray(rs_out[0], dtype=float)
        F = np.asarray(rs_out[1], dtype=float)      # positive == LOSS (see dt_018)
        q2_out = np.asarray(
            model.call_internal(id="uh2", method="get_output", solve=False)[0], dtype=float
        )
        uh1_out = np.asarray(
            model.call_internal(id="uh1", method="get_output", solve=False)[0], dtype=float
        )
        rout = np.asarray(
            model.call_internal(id="ps", method="get_output", solve=False)[0], dtype=float
        )
        s_ps = np.asarray(model.get_internal(id="ps", attribute="state_array"))[:, 0]
        s_rs = np.asarray(model.get_internal(id="rs", attribute="state_array"))[:, 0]
        d_s_ps = float(s_ps[-1] - 10.0)             # S0 set at build time
        d_s_rs = float(s_rs[-1] - 10.0)
        d_lag1 = float(0.9 * rout.sum() - uh1_out.sum())
        d_lag2 = float(0.1 * rout.sum() - q2_out.sum())
        f_total = float(F.sum() + np.minimum(q2_out, F).sum())
        diag = {
            "AET": aet_tot.tolist(),
            "S": (s_ps + s_rs).tolist(),
            "F": F.tolist(),
            "units": {"AET": "mm/d", "S": "mm", "F": "mm/d (positive = loss)"},
            "water_balance_terms_mm": {
                "precip": float(P.sum()),
                "aet_interception": float(aet_int.sum()),
                "aet_production_store": float(aet_ps.sum()),
                "aet_total": float(aet_tot.sum()),
                "runoff": float(np.nansum(Q_sim)),
                "delta_storage_production": d_s_ps,
                "delta_storage_routing": d_s_rs,
                "delta_storage_lag1": d_lag1,
                "delta_storage_lag2": d_lag2,
                "delta_storage_total": d_s_ps + d_s_rs + d_lag1 + d_lag2,
                "exchange_loss_total": f_total,
            },
        }
    elif model_type == "hbv":
        aet = np.asarray(model.call_internal(id="ur", method="get_AET")[0], dtype=float)
        s_ur = np.asarray(model.get_internal(id="ur", attribute="state_array"))[:, 0]
        s_fr = np.asarray(model.get_internal(id="fr", attribute="state_array"))[:, 0]
        diag = {
            "AET": aet.tolist(),
            "S": (s_ur + s_fr).tolist(),
            "F": None,
            "units": {"AET": "mm/d", "S": "mm", "F": "not applicable (no exchange element)"},
            "water_balance_terms_mm": {
                "precip": float(P.sum()),
                "aet_total": float(aet.sum()),
                "runoff": float(np.nansum(Q_sim)),
                "delta_storage_unsaturated": float(s_ur[-1] - 10.0),
                "delta_storage_fast": float(s_fr[-1] - 0.0),
                "delta_storage_total": float((s_ur[-1] - 10.0) + s_fr[-1]),
                "exchange_loss_total": 0.0,
            },
        }
    if diag:
        t = diag["water_balance_terms_mm"]
        t["residual_mm"] = (
            t["precip"] - t["aet_total"] - t["runoff"]
            - t["delta_storage_total"] - t["exchange_loss_total"]
        )
        t["residual_pct_of_precip"] = (
            100.0 * t["residual_mm"] / t["precip"] if t["precip"] else float("nan")
        )
    return diag


def process(args):
    """Load forcing, run model, collect outputs."""

    # Load forcing data
    with open(args.forcing, "r") as f:
        forcing = json.load(f)

    if forcing.get("status") != "success":
        return {"status": "error", "errors": ["Forcing file indicates error status"]}

    P = np.array(forcing["P"], dtype=float)
    PET_raw = np.array(forcing["PET"], dtype=float)
    n_timesteps = len(P)
    dates = forcing.get("dates")

    # Build model
    model, input_order = build_model(args)

    # Set timestep
    model.set_timestep(args.timestep)

    def inputs_fn(cpet):
        pet = PET_raw * float(cpet)
        return [pet, P] if input_order == "PET,P" else [P, pet]

    # ---- s2 -> s5 hand-off: start from convert_parameters.py's values/ranges
    pvals = {}
    pbounds = {}
    if args.params_json:
        try:
            pvals, pbounds = load_params_json(args.params_json)
        except Exception as e:
            return {"status": "error", "errors": [f"Failed to read --params-json: {e}"]}

    # Override parameters if provided on the command line
    if args.params:
        for kv in args.params:
            key, val = kv.split("=")
            pvals[key] = float(val)

    if args.cpet is not None:
        pvals["cpet"] = float(args.cpet)

    try:
        apply_params(model, args.model, pvals)
    except ValueError as e:
        return {"status": "error", "errors": [str(e)]}

    # ---- s7 calibration (optional) -----------------------------------------
    calibration_report = None
    if args.calibrate:
        if "Q_obs" not in forcing:
            return {"status": "error", "errors": ["--calibrate needs Q_obs in the forcing file"]}
        if not dates:
            return {"status": "error", "errors": ["--calibrate needs a 'dates' array in the forcing file"]}
        obs = np.array(forcing["Q_obs"], dtype=float)

        # The validation window is HELD OUT, not merely recorded. Without this
        # block, `--calibrate --val-start X --val-end Y` and no --cal-start/
        # --cal-end went through date_mask(dates, None, None), which is
        # all-True: the optimiser trained on the exact window the output then
        # labelled "RECORDED ONLY - never optimised on". Two closures, no
        # silent third case:
        #   * an EXPLICIT calibration window that overlaps the validation
        #     window -> hard error; the command line contradicts itself and
        #     only the caller can say which window was meant.
        #   * NO explicit calibration window -> the calibration window is the
        #     complement of the validation window, and that derivation is
        #     written into the output rather than assumed.
        val_mask = None
        if args.val_start or args.val_end:
            val_mask = date_mask(dates, args.val_start, args.val_end)
        cal_mask = date_mask(dates, args.cal_start, args.cal_end)
        cal_explicit = bool(args.cal_start or args.cal_end)
        cal_window_label = (
            f"{args.cal_start or '(series start)'}..{args.cal_end or '(series end)'}"
        )
        val_window_label = (
            f"{args.val_start or '(series start)'}..{args.val_end or '(series end)'}"
        )
        if val_mask is not None:
            n_overlap = int(np.sum(cal_mask & val_mask))
            if cal_explicit:
                if n_overlap:
                    return {
                        "status": "error",
                        "errors": [
                            f"Calibration window {cal_window_label} overlaps the "
                            f"validation window {val_window_label} on {n_overlap} "
                            "timesteps. --val-start/--val-end are held out and are "
                            "never optimised on; narrow one of the two windows."
                        ],
                    }
            else:
                cal_mask = cal_mask & ~val_mask
                cal_window_label = (
                    f"{cal_window_label} MINUS held-out validation {val_window_label}"
                )
        if cal_mask.sum() < 30:
            return {
                "status": "error",
                "errors": [
                    f"Calibration window {cal_window_label} has only "
                    f"{int(cal_mask.sum())} timesteps"
                ],
            }
        if np.sum(np.isfinite(obs[cal_mask])) < 30:
            return {
                "status": "error",
                "errors": [
                    f"Calibration window {cal_window_label} has < 30 finite observations"
                ],
            }

        free_names = args.free_params or DEFAULT_FREE_PARAMS.get(args.model, [])
        bounds = dict(pbounds)
        bounds["cpet"] = CPET_BOUNDS
        missing = [n for n in free_names if n not in bounds]
        if missing:
            return {
                "status": "error",
                "errors": [
                    f"No calibration bounds for {missing}. Supply them via "
                    "--params-json (convert_parameters.py publishes min/max per "
                    "parameter) or drop them from --free-params."
                ],
            }
        fixed = {k: v for k, v in pvals.items() if k not in free_names}
        try:
            pvals, calibration_report = calibrate(
                model, args.model, inputs_fn, fixed, free_names, bounds,
                obs, cal_mask, args,
            )
        except Exception as e:
            return {"status": "error", "errors": [f"Calibration failed: {e}"]}
        # Say exactly which timesteps the optimiser saw, so the held-out claim
        # is auditable from the output file alone.
        calibration_report["calibration_window"] = cal_window_label
        calibration_report["n_calibration_timesteps"] = int(cal_mask.sum())
        calibration_report["validation_window_held_out"] = (
            val_window_label if val_mask is not None else None
        )
        calibration_report["n_validation_timesteps_excluded"] = (
            int(np.sum(val_mask)) if val_mask is not None else 0
        )
        print(
            f"Calibrated {args.model}: {json.dumps({k: round(v, 4) for k, v in pvals.items()})}",
            file=sys.stderr,
        )

    # ---- final run with the parameters we will report ----------------------
    cpet_used = float(pvals.get("cpet", 1.0))
    t_start = time.time()
    try:
        Q = run_once(model, args.model, inputs_fn, pvals)
        t_elapsed = time.time() - t_start
    except Exception as e:
        return {
            "status": "error",
            "errors": [f"Model execution failed: {str(e)}"],
        }
    PET = PET_raw * cpet_used

    # Collect outputs
    Q_arr = np.asarray(Q[0] if isinstance(Q, list) else Q, dtype=float)
    Q_sim = Q_arr.tolist()

    diagnostics = None
    if args.diagnostics:
        try:
            diagnostics = collect_diagnostics(model, args.model, P, PET, Q_arr, args.timestep)
        except Exception as e:  # diagnostics must never sink a good run
            diagnostics = {"error": f"{type(e).__name__}: {e}"}

    # Get final states
    states = model.get_states()
    states_serializable = {}
    for k, v in states.items():
        if v is None:
            states_serializable[k] = None
        elif np.isscalar(v):
            states_serializable[k] = float(v)
        else:
            arr = np.array(v)
            states_serializable[k] = arr.tolist()

    result = {
        "status": "success",
        "model": args.model,
        "n_timesteps": n_timesteps,
        "timestep_d": args.timestep,
        "solver": args.solver,
        "architecture": args.architecture,
        "runtime_s": round(t_elapsed, 3),
        "output_units": {"Q": "mm/d"},
        "Q_sim": Q_sim,
        "statistics": {
            "Q_mean": float(np.mean(Q_sim)),
            "Q_max": float(np.max(Q_sim)),
            "Q_min": float(np.min(Q_sim)),
            "Q_total": float(np.sum(Q_sim)),
            "P_total": float(np.sum(P)),
            "runoff_ratio": float(np.sum(Q_sim) / max(np.sum(P), 1e-10)),
        },
        "final_states": states_serializable,
        "parameters_used": {k: float(v) for k, v in pvals.items()},
        "parameters_applied_prefixed": {
            k: float(v) for k, v in apply_params(model, args.model, pvals).items()
        },
        "cpet": cpet_used,
    }

    if calibration_report is not None:
        result["calibration"] = calibration_report
        # The window the optimiser actually scored -- not a re-print of the
        # flags, which read "None..None" when the window was derived.
        result["period_calibration"] = calibration_report["calibration_window"]
    if args.val_start or args.val_end:
        # Held out of the calibration mask above, then scored separately by
        # parse_output.py; never seen by the optimiser.
        result["period_validation"] = (
            f"{args.val_start or '(series start)'}..{args.val_end or '(series end)'}"
        )
    if diagnostics is not None:
        result["diagnostics"] = diagnostics

    # Include forcing provenance
    for key in ("gauge_id", "source_file", "area_km2", "source_format"):
        if key in forcing:
            result[f"forcing_{key}"] = forcing[key]

    # Include dates if available
    if "dates" in forcing:
        result["dates"] = forcing["dates"]

    # Include observed Q for comparison
    if "Q_obs" in forcing:
        result["Q_obs"] = forcing["Q_obs"]

    return result


def validate_outputs(result):
    """Validate model outputs for common problems."""
    if result["status"] != "success":
        return result

    warnings = []
    Q = np.array(result["Q_sim"])

    # Check for negative streamflow (dt_010)
    if np.any(Q < 0):
        n_neg = int(np.sum(Q < 0))
        warnings.append(
            f"WARNING: {n_neg} negative Q values detected — "
            "may indicate explicit solver instability (dt_010)"
        )

    # Check for NaN
    if np.any(np.isnan(Q)):
        warnings.append("WARNING: NaN values in simulated Q — solver may have diverged")

    # Check runoff ratio
    rr = result["statistics"]["runoff_ratio"]
    if rr > 1.5:
        warnings.append(
            f"WARNING: Runoff ratio = {rr:.2f} > 1.5 — "
            "model is generating more water than it receives"
        )
    if rr < 0.01:
        warnings.append(
            f"WARNING: Runoff ratio = {rr:.4f} — "
            "almost no runoff generated, check parameters"
        )

    # Check for unrealistic peaks
    if np.max(Q) > 1000:
        warnings.append(
            f"WARNING: Max Q = {np.max(Q):.1f} mm/d seems extreme — "
            "check input units and parameters"
        )

    # Internal-flux water balance (only present with --diagnostics). A non-zero
    # residual here is a FLUX-ACCOUNTING error in the tool or a solver failure,
    # not a calibration issue: every term comes from the model's own equations.
    terms = (result.get("diagnostics") or {}).get("water_balance_terms_mm")
    if terms and abs(terms.get("residual_pct_of_precip", 0.0)) > 1.0:
        warnings.append(
            f"WARNING: internal water-balance residual = "
            f"{terms['residual_pct_of_precip']:.2f}% of precipitation — "
            "the flux ledger does not close; suspect a solver divergence or a "
            "structure change that collect_diagnostics() does not account for"
        )

    if warnings:
        result["warnings"] = warnings
        for w in warnings:
            print(w, file=sys.stderr)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Execute SuperflexPy model and save outputs"
    )
    parser.add_argument("--model", type=str, required=True, help="Model type: gr4j, hbv, hymod")
    parser.add_argument("--forcing", type=str, required=True, help="Path to forcing JSON file")
    parser.add_argument("--output", type=str, default=None, help="Output JSON file path")
    parser.add_argument("--timestep", type=float, default=1.0, help="Timestep in days")
    parser.add_argument("--solver", type=str, default="implicit_euler", help="ODE solver")
    parser.add_argument("--architecture", type=str, default="python", help="python or numba")
    parser.add_argument("--params", nargs="*", default=None, help="Parameter overrides as key=value")
    parser.add_argument(
        "--params-json", type=str, default=None,
        help="s2 hand-off: convert_parameters.py output JSON (values + calibration ranges)",
    )
    parser.add_argument(
        "--cpet", type=float, default=None,
        help="Multiplicative PET-forcing correction applied before set_input (1.0 = off). "
             "Use for reanalysis PET products biased high; HBV's Ce does this internally.",
    )
    parser.add_argument("--diagnostics", action="store_true",
                        help="Also emit dag outputs AET, S, F and a term-by-term water balance")
    # --- s7 calibration ---
    parser.add_argument("--calibrate", action="store_true", help="Calibrate before the final run (s7)")
    parser.add_argument("--free-params", nargs="*", default=None,
                        help="Short parameter names to calibrate (default: model's documented set)")
    parser.add_argument("--cal-start", type=str, default=None, help="Calibration window start YYYY-MM-DD")
    parser.add_argument("--cal-end", type=str, default=None, help="Calibration window end YYYY-MM-DD")
    parser.add_argument("--val-start", type=str, default=None,
                        help="Validation window start (HELD OUT - excluded from the "
                             "calibration mask, never optimised on)")
    parser.add_argument("--val-end", type=str, default=None,
                        help="Validation window end (held out, never optimised on)")
    parser.add_argument("--objective", type=str, default="nse", choices=("nse", "kge"))
    parser.add_argument("--maxiter", type=int, default=60)
    parser.add_argument("--popsize", type=int, default=20)
    parser.add_argument("--tol", type=float, default=1e-4)
    parser.add_argument("--seed", type=int, default=42)

    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    output_json = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w") as f:
            f.write(output_json)
        print(f"Results written to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
