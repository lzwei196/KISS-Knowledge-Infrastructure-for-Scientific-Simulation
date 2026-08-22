"""Calibration kit — main entry. Sibling module to the self-improve KI: it tunes a
correct-running model's PARAMETERS to fit its dag-defined obs. (Data assimilation is
a separate sibling module — sequential state estimation, OpenDA-based.)

Flow: load calibration.yaml + dag.yaml -> objectives from gate-valid metric_families
-> PREFLIGHT every parameter address (exists + round-trips) -> build evaluator
(apply->run->score) -> pick backend by cost_class/objective structure -> optimize
-> apply best params back -> (holdout validation: to build) -> report.
"""
from __future__ import annotations
import ast
import math
import operator
import os
import tempfile
import shutil
from pathlib import Path


def _load_contract(ki_path):
    import yaml
    f = Path(ki_path) / "calibration.yaml"
    if not f.is_file():
        raise FileNotFoundError(f"no calibration.yaml at {f} — model has no calibration "
                                f"contract yet (run the calibration-contract campaign)")
    return yaml.safe_load(f.read_text())


def _validate_transforms(params):
    """Build name -> (to_search, from_search) and VALIDATE transform domains
    against the declared range (codex calib.py:33). Returns (fwd, inv) or raises
    ValueError with a precise message — an invalid range must abort, not crash mid-run."""
    fwd, inv = {}, {}
    for p in params:
        n = p["name"]; t = p.get("transform", "identity")
        ptype = p.get("type", "continuous")
        if ptype == "categorical":
            # categorical needs an explicit index<->category encoder/sampler that the
            # current continuous Problem doesn't model — fail fast (codex spotpy:50).
            raise ValueError(f"param {n}: categorical type not yet supported "
                             f"(continuous/integer/bool only)")
        lo, hi = float(p["range"][0]), float(p["range"][1])
        if not (lo < hi):
            raise ValueError(f"param {n}: range lower {lo} must be < upper {hi}")
        if t == "log":
            if lo <= 0:
                raise ValueError(f"param {n}: log transform requires range > 0 (got {lo})")
            fwd[n] = math.log; inv[n] = math.exp
        elif t == "logit":
            if not (0 < lo and hi < 1):
                raise ValueError(f"param {n}: logit transform requires range in (0,1) "
                                 f"(got [{lo},{hi}])")
            fwd[n] = lambda v: math.log(v / (1 - v))
            inv[n] = lambda z: 1 / (1 + math.exp(-z))
        elif t in (None, "identity"):
            fwd[n] = lambda v: v; inv[n] = lambda v: v
        else:
            raise ValueError(f"param {n}: unknown transform {t!r}")
    return fwd, inv


def _preflight_addresses(params, workdir):
    """Enforce schema C1 (address file exists) + C7 (write/read round-trips) on a
    SCRATCH COPY before optimizing (codex calib.py:72). A lossy or mis-targeted
    writer would otherwise silently calibrate the wrong field for every eval.
    Returns a list of problems (empty == ok)."""
    from .applicator import verify_roundtrip
    problems = []
    scratch = Path(tempfile.mkdtemp(prefix="calib_preflight_"))
    try:
        from .applicator import _resolve
        # mirror just the files the addresses touch, resolving the REAL target the
        # SAME way the applicator does (absolute / explicit root / workdir), then
        # round-trip a SCRATCH-RELATIVE copy of the address so preflight can never
        # mutate the live input (codex calib.py:76).
        for p in params:
            addr = p.get("address") or {}
            f = addr.get("file")
            if not f:
                problems.append(f"{p['name']}: address has no 'file'"); continue
            src = _resolve(addr, workdir)            # exact target the run would edit
            if not src.is_file():
                problems.append(f"{p['name']}: address file missing on disk: {src}"); continue
            rel = f"{p['name']}__{Path(src).name}"   # flat unique name in scratch
            dst = scratch / rel
            shutil.copy2(src, dst)
            scratch_addr = dict(addr)                 # rewrite to point at the scratch copy
            scratch_addr["file"] = rel
            scratch_addr.pop("root", None)
            lo, hi = float(p["range"][0]), float(p["range"][1])
            probe = (lo + hi) / 2.0
            try:
                if not verify_roundtrip(scratch_addr, probe, str(scratch)):
                    problems.append(f"{p['name']}: address write/read did NOT round-trip "
                                    f"(would corrupt the search): {addr}")
            except Exception as e:
                problems.append(f"{p['name']}: address not usable ({type(e).__name__}: {e})")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return problems


# Map a DETERMINING metric to the ONE metric_family it natively grades. A determining
# metric overrides ONLY its own family (never a sibling), so we can't clobber another
# family's native metric (e.g. spatial's `csi` or ranking's `spearman`) with a temporal
# `r` — Codex review. objectives_from_dag only applies an override for a family that is
# actually present for the (var, obs_shape), so a metric aimed at a family the case
# doesn't expose is simply a no-op.
_METRIC_NATIVE_FAMILY = {
    "r": "temporal_pattern_match", "nse": "temporal_pattern_match",
    "kge": "temporal_pattern_match", "r2": "temporal_pattern_match",
    "nse_log": "temporal_pattern_match", "rho": "temporal_pattern_match",
    "pearson_r": "temporal_pattern_match",
    "csi": "spatial_pattern_match",
    "spearman": "ranking_quality",
    "pbias": "magnitude_accuracy", "bias": "magnitude_accuracy",
}


def _effective_metric_overrides(contract, determining_metric):
    """The per-obs DETERMINING metric (the gate/model_obs_map headline, threaded by
    readiness) is what the FIELD grades — e.g. groundwater & soil-moisture headline is
    `r`, NOT the family-default `nse`. If the contract didn't declare `metric_overrides`,
    synthesize a SINGLE-family override from the determining metric so BOTH the objective
    and the calibratability triage optimize/judge the headline instead of a
    silently-different default (Bug #1: determining_metric was dropped before the engine).

    Explicit contract overrides always win — including an explicit empty `{}` (author's
    intent = keep family defaults), so we test key PRESENCE, not truthiness (Codex review).
    The override is keyed to the metric's OWN native family only (never a sibling), and
    the loss fn for that family is unchanged (only metric_key differs), so it's sound.
    An unknown metric is NOT guessed — keep the family defaults."""
    if "metric_overrides" in contract:
        return contract.get("metric_overrides")          # explicit (incl. {} / null) wins
    dm = str(determining_metric or "").lower()
    fam = _METRIC_NATIVE_FAMILY.get(dm)
    return {fam: dm} if fam else None


def _load_reference_run(ki_path):
    """Durable reference of the VALIDATED KI run (calib/reference_run.json), captured from
    self_improve_runs — NOT the ephemeral real_case_result.json (which later runs overwrite).
    Returns the dict or None (then certification is skipped — backward compatible)."""
    import json
    f = Path(ki_path) / "calib" / "reference_run.json"
    if not f.is_file():
        return None
    try:
        return json.loads(f.read_text())
    except Exception:
        return None


from .evaluator import split_authority as _ev_split_authority


def certify_runner(contract, run_model, reference, workdir, expected_case_id=None):
    """MODULE-CERTIFICATION gate (2026-07-10, GPT-5.5 design). The framework auto-generates a
    calibration function for a validated, working process-based KI; this proves the generated
    function actually EXECUTES THE KI CORRECTLY by REPRODUCING the validated reference run —
    BEFORE any objective probe / Morris screen / triage. It injects the reference params, runs
    the module once at the reference split, and requires a finite headline metric within
    tolerance of the validated value (+ run-signature match when both sides report it). A module
    that omits prepare/routing/staging, or drifts from the validated execution, produces None or
    a wrong metric -> NOT certified, stopped CHEAPLY (no screen, no nested repair agent).
    Returns {certified: bool, reason, observed}."""
    import json as _json
    params = reference.get("params") or {}
    headline = str(reference.get("headline_metric") or "nse").lower()
    ref_val = (reference.get("metrics") or {}).get(headline, reference.get("headline_value"))
    tol = reference.get("tolerance") or {}
    split = reference.get("reference_split")
    ref_sig = reference.get("signature") or {}
    inj_mode = (contract.get("injection", {}) or {}).get("mode", "applicator")

    _auth_cm = None                      # in-process split authority for the reference replay
    prev_params = os.environ.get("KDT_CALIB_PARAMS")
    prev_split = os.environ.get("KDT_CALIB_SPLIT")
    try:
        # INJECT the reference param state — FAIL-CLOSED (Codex): certification is worthless if
        # we didn't actually inject the validated params, so ANY setup/write failure (bad address,
        # mkdir/write error, applicator import, malformed contract) => NOT certified, never a
        # falsely-passing run on stale/partial params.
        try:
            if inj_mode == "runner":
                pf = Path(workdir) / "kdt_certify_params.json"
                pf.parent.mkdir(parents=True, exist_ok=True)
                pf.write_text(_json.dumps(params, default=str))
                os.environ["KDT_CALIB_PARAMS"] = str(pf)
            else:
                from .applicator import write_param
                for p in contract.get("parameters", []):
                    if isinstance(p, dict) and p.get("name") in params:
                        write_param(p["address"], params[p["name"]], workdir)   # raises => fail-closed
            # reference replay is a LEGITIMATE split director -> declare in-process authority
            # (codex round-4) instead of raw-setting the env outside holdout._eval_split.
            # NOTE: entered here, EXITED in the outer finally — an unbalanced __enter__ would leave
            # the thread-local authority flag ON and make later TRAINING evals trust a stale env.
            if split and split != "full":
                _auth_cm = _ev_split_authority(split)
                _auth_cm.__enter__()
            else:
                os.environ.pop("KDT_CALIB_SPLIT", None)
        except Exception as e:
            return {"certified": False, "observed": None,
                    "reason": f"could not inject the validated reference param state "
                              f"(cannot certify without it): {e}"}
        try:
            metrics = run_model() or {}
        except Exception as e:
            return {"certified": False, "observed": None,
                    "reason": f"module raised while running at the reference params: {e}"}
    finally:
        if _auth_cm is not None:                  # release in-process split authority (see above)
            try:
                _auth_cm.__exit__(None, None, None)
            except Exception:
                pass
        if prev_params is None:
            os.environ.pop("KDT_CALIB_PARAMS", None)
        else:
            os.environ["KDT_CALIB_PARAMS"] = prev_params
        if prev_split is None:
            os.environ.pop("KDT_CALIB_SPLIT", None)
        else:
            os.environ["KDT_CALIB_SPLIT"] = prev_split

    if not metrics:
        return {"certified": False, "observed": None,
                "reason": "module produced NO metrics at the reference params — likely missing "
                          "prepare/staging/routing; cannot reproduce the validated KI run"}
    # WRONG-GAUGE GUARD (codex round-6): certification is a direct run_model() path, so a runner that
    # scores a DIFFERENT gauge could pass on a coincidentally-matching headline. For a pinned case in
    # runner mode, the module MUST self-declare __kdt__.case_id AND it must match — else NOT certified,
    # for the wrong-gauge reason (before the headline/signature checks can falsely pass it).
    if expected_case_id and inj_mode == "runner":
        _dc = (metrics.get("__kdt__") or {}).get("case_id")
        if _dc is None or str(_dc) != str(expected_case_id):
            return {"certified": False, "observed": metrics,
                    "reason": f"module scored case '{_dc if _dc is not None else '<undeclared>'}' but the "
                              f"target case is '{expected_case_id}' — certified against the WRONG gauge/obs"}
    obs = metrics.get(headline)
    try:
        obs = float(obs)
    except (TypeError, ValueError):
        obs = None
    if obs is None or not math.isfinite(obs):
        return {"certified": False, "observed": metrics,
                "reason": f"module did not emit a finite headline metric {headline!r}"}
    if ref_val is None:
        return {"certified": False, "observed": metrics,
                "reason": f"reference_run.json has no {headline!r} value to certify against"}
    htol = float(tol.get(headline, 0.02))
    if abs(obs - float(ref_val)) > htol:
        return {"certified": False, "observed": metrics,
                "reason": f"headline {headline}={obs:.4f} differs from validated {float(ref_val):.4f} "
                          f"by > tol {htol} — module does not reproduce the validated KI run"}
    sig = metrics.get("__kdt__") or {}
    for k in ("n_paired_days", "n_cells"):
        if k in ref_sig and k in sig:
            try:
                if int(sig[k]) != int(ref_sig[k]):
                    return {"certified": False, "observed": metrics,
                            "reason": f"run-signature {k}={sig[k]} != reference {ref_sig[k]} — the module "
                                      "scores a different window/domain than the validated run"}
            except (TypeError, ValueError):
                pass
    return {"certified": True, "observed": metrics,
            "reason": f"reproduced validated {headline}={obs:.4f} (ref {float(ref_val):.4f}, tol {htol})"}


def _holdout_band_ceilings(objs, headline_objectives):
    """PRAGMATIC convention pass-band -> per-objective HOLDOUT loss ceiling (metric-match,
    unambiguous-only — user's choice 2026-07-09). `headline_objectives` is
    {dag_variable: [{metric, target, direction, ...}]} from the validation convention
    (re-keyed to the model's own output names in the 2026-08-15 obs-map rewire; a direct
    variable->objective match is now possible and can replace this metric-match later).
    Today we still match a convention headline to a calibration objective BY METRIC, and apply
    the band ONLY when that metric has a SINGLE unambiguous numeric target across all the
    convention's quantities. If the metric's target is absent or ambiguous (e.g. discharge
    pbias 25 vs ET pbias 10), we add NO band and fall back to the non-degradation gate — a
    wrong band is worse than none. Returns {objective_name: max_loss}."""
    from .objectives import _FAMILY_LOSS
    if not headline_objectives:
        return {}
    by_metric = {}                                  # metric -> {numeric targets across quantities}
    for _q, entries in (headline_objectives or {}).items():
        for e in (entries or []):
            m = str(e.get("metric") or "").lower()
            t = e.get("target")
            # a finite numeric target only — NaN/inf must NOT synthesize a bogus band
            # (isinstance(float('nan'), float) is True); bool is not a target (Codex review).
            if m and isinstance(t, (int, float)) and not isinstance(t, bool) and math.isfinite(t):
                by_metric.setdefault(m, set()).add(float(t))
    ceilings = {}
    for o in objs:
        targets = by_metric.get(str(o.metric_key).lower())
        if not targets or len(targets) != 1:        # absent or ambiguous -> non-degradation only
            continue
        fam = _FAMILY_LOSS.get(o.family)
        if not fam:
            continue
        _key, loss_fn = fam
        try:
            ceilings[o.name] = float(loss_fn(next(iter(targets))))
        except Exception:
            continue
    return ceilings


def _is_multi_objective(contract, objs):
    """Pareto mode ONLY when there's a real trade-off (codex calib.py:92): an explicit
    strategy.multi_objective flag, OR >=2 DISTINCT target VARS. Multiple families of
    the SAME var are scalarized (their weights already split in objectives.py)."""
    # runtime override (operator/testing): KDT_CALIB_MULTIOBJ=1 forces Pareto mode even for a
    # single-var, multi-family case (the families become separate objectives); =0 forces scalar.
    env_mo = (os.environ.get("KDT_CALIB_MULTIOBJ") or "").strip().lower()
    if env_mo in ("1", "true", "yes"):
        return True
    if env_mo in ("0", "false", "no"):
        return False
    strat = contract.get("strategy", {}) or {}
    if "multi_objective" in strat:
        return bool(strat["multi_objective"])
    return len({o.var for o in objs}) >= 2


_SPOTPY_ALGOS = ("dds", "sceua", "dream")     # scalar (single-objective) backends
_PYMOO_ALGOS = ("nsga2", "nsga3", "moead")    # multi-objective (Pareto) backends


def _pick_backend(contract, multi, n_distinct_vars):
    # runtime override (operator/testing): KDT_CALIB_ALGO forces the optimizer without editing the
    # (hash-pinned) calibration.yaml. Resolution order: env override -> yaml default_algorithm ->
    # mode default (nsga2 if multi else dds). An unrecognized env value is ignored.
    env_algo = (os.environ.get("KDT_CALIB_ALGO") or "").strip().lower()
    strat = contract.get("strategy", {}) or {}
    if env_algo in _SPOTPY_ALGOS + _PYMOO_ALGOS:
        algo = env_algo
    else:
        algo = strat.get("default_algorithm") or ("nsga2" if multi else "dds")
    # COMPATIBILITY FENCE (codex): spotpy algos are scalar-only and pymoo algos need >=2 objectives, so
    # an incompatible (algo, multi) pair would raise inside backend.optimize() and crash the run. Coerce
    # to the mode-appropriate default instead — whether the mismatch came from the env override OR a
    # yaml default that disagrees with multi_objective.
    if multi and algo in _SPOTPY_ALGOS:
        print(f"  [calib] algo {algo!r} is scalar-only but multi_objective=True -> using nsga2", flush=True)
        algo = "nsga2"
    elif (not multi) and algo in _PYMOO_ALGOS:
        print(f"  [calib] algo {algo!r} needs >=2 objectives but the problem is scalar -> using dds", flush=True)
        algo = "dds"
    return algo


def _probe_runner_metrics(run_model, inj_mode, params, workdir):
    """Run the runner ONCE at DEFAULT params to see which metrics it actually emits. A RUNNER-mode
    driver REQUIRES KDT_CALIB_PARAMS, so the probe MUST set it to a defaults file — otherwise the
    driver dies, the probe reads {}, the un-producible-objective drop is skipped, and every eval
    scalarizes to +inf because a declared-but-unemitted family (e.g. timing_accuracy/day_bias) stays
    in the objective set (the CaMa screen_failed root cause, 2026-07-19). Returns the metrics dict."""
    import json as _json
    prev = os.environ.get("KDT_CALIB_PARAMS")
    prev_split = os.environ.get("KDT_CALIB_SPLIT")
    try:
        if inj_mode == "runner":
            wd = Path(workdir); wd.mkdir(parents=True, exist_ok=True)
            pf = wd / "kdt_probe_params.json"
            defaults = {p["name"]: p.get("default") for p in params if p.get("default") is not None}
            pf.write_text(_json.dumps(defaults, default=str))
            os.environ["KDT_CALIB_PARAMS"] = str(pf)
        # SCORE THE CALIBRATION WINDOW (2026-07-19): with the split UNSET a runner scores its FULL
        # record, so the triage baseline (which reuses this probe) judged adequacy on data the optimizer
        # will not train on — a SWAT+ case whose calibration window is NSE -0.47 was routed
        # `already_adequate` off a full-period NSE 0.585. Triage must judge the window being optimized.
        from .evaluator import resolve_train_split, split_is_authoritative
        if not split_is_authoritative(prev_split):      # unset / blank / inherited 'full' -> we own it
            os.environ["KDT_CALIB_SPLIT"] = resolve_train_split(prev_split)
        return run_model() or {}
    except Exception:
        return {}
    finally:
        if prev is None:
            os.environ.pop("KDT_CALIB_PARAMS", None)
        else:
            os.environ["KDT_CALIB_PARAMS"] = prev
        if prev_split is None:
            os.environ.pop("KDT_CALIB_SPLIT", None)
        else:
            os.environ["KDT_CALIB_SPLIT"] = prev_split


def _filter_objectives_by_probe(objs, probe, expected_case_id, inj_mode):
    """Using a probe metrics dict: (1) enforce the pinned case (wrong/undeclared -> error), and
    (2) DROP objectives whose metric the runner didn't produce (so a declared-but-unemitted family
    can't poison every eval to +inf). Returns (kept_objs, error_dict_or_None)."""
    if not probe:
        return objs, None                       # probe couldn't run -> no info, keep all
    if expected_case_id and inj_mode == "runner":
        pcase = (probe.get("__kdt__") or {}).get("case_id")
        if pcase is None or str(pcase) != str(expected_case_id):
            return objs, {"status": "runner_wrong_case", "injection_mode": "runner",
                          "expected_case_id": expected_case_id,
                          "declared_case_id": str(pcase) if pcase is not None else "<undeclared>",
                          "reason": f"objective probe scored case "
                                    f"'{pcase if pcase is not None else '<undeclared>'}' but the target "
                                    f"case is '{expected_case_id}' — capability built for the wrong gauge"}
    def _present(o):
        mm = probe.get(o.var) if isinstance(probe.get(o.var), dict) else probe
        return (mm or {}).get(o.metric_key) is not None
    kept = [o for o in objs if _present(o)]
    dropped = [o.name for o in objs if not _present(o)]
    if dropped and kept:
        print(f"  [calib] objective family probe: keeping {[o.name for o in kept]}, "
              f"dropping (metric not produced by runner) {dropped}", flush=True)
        return kept, None
    if not kept:
        return objs, {"status": "runner_emits_no_objective_metric",
                      "reason": f"runner produced {list(probe.keys())[:8]} but none match "
                                f"the dag objectives {[o.name for o in objs]}"}
    return kept, None


def _select_front_member(ev, objs, result, holdout_spec, band_ceilings,
                         probe_x, baseline_x, cap: int | None = None,
                         spread_floor: float = 1e-9):
    """MULTI-OBJECTIVE FRONT SELECTION — gate the Pareto front, don't commit one guess.

    pymoo returns a single representative = the min-normalized-SUM knee. That knee can
    commit a point that sacrifices ONE objective badly while the others are ~perfect
    (observed on CRHM: discharge NSE fell to ~0.24 while SWE calibrated near-perfectly).
    The front, however, CONTAINS balanced members. Instead of gating only the sum-knee,
    rank members by a MINIMAX (Chebyshev) criterion — smallest WORST normalized objective,
    which protects every objective — and validate them on the HELD-OUT split in that order,
    committing the FIRST member that PASSES the holdout on ALL objectives. If none of the
    gated members passes, keep the top-minimax member (a strictly better default than the
    sum-knee) and let the caller report it not-promotable.

    EXHAUSTIVE by default (codex 2026-08-20): every finite front member is gated, because
    truncating could report promotable=False while a lower-ranked member would have passed —
    and time/cost is not a constraint here. `cap` (if set) bounds the gated set and the outcome
    is explicitly flagged TRUNCATED (never silently "none passed"). Objectives whose spread
    across the front is numerically trivial are EXCLUDED from the minimax ranking, so float-noise
    normalization on a near-degenerate objective cannot dominate the worst-objective criterion.

    MUTATES result.best_x / result.best_loss to the chosen member; records the choice in
    result.notes. Returns (chosen_idx, holdout_dict) or (None, None) if there is no usable front.
    """
    import numpy as np
    from .holdout import validate_holdout
    X = result.pareto_x or []
    F = result.pareto_f or []
    if not X or not F or len(X) != len(F):
        return None, None                       # no front (or pre-pareto_f engine) -> caller keeps knee
    Fa = np.asarray(F, float)
    fin = [i for i in range(len(Fa)) if np.all(np.isfinite(Fa[i]))]
    if not fin:
        return None, None
    Fa = Fa[fin]; X = [X[i] for i in fin]; F = [F[i] for i in fin]
    # minimax knee over DISCRIMINATING objectives only: an objective with trivial spread across
    # the front doesn't separate members — including it would let float noise, blown up to [0,1]
    # by normalization, dominate the worst-objective criterion (codex 2026-08-20).
    span = np.ptp(Fa, axis=0)
    scale = np.maximum(np.abs(Fa).max(0), 1e-12)
    disc = (span > spread_floor) & (span > 1e-6 * scale)
    if disc.any():
        Fd = Fa[:, disc]
        Fn = (Fd - Fd.min(0)) / (np.ptp(Fd, axis=0) + 1e-12)
        crit = Fn.max(1)                        # worst discriminating (normalized) objective
    else:
        crit = Fa.sum(1)                        # all objectives degenerate -> fall back to sum
    order = list(np.argsort(crit))              # most-balanced (smallest worst-obj) first
    gated = order if not cap else order[:cap]
    truncated = bool(cap and len(gated) < len(order))
    if truncated:                               # NEVER a silent cap
        print(f"  [calib] front-select: TRUNCATED to {len(gated)}/{len(order)} members "
              f"(cap={cap}); remaining lower-ranked members NOT gated", flush=True)
    top_holdout = None
    for rank, idx in enumerate(gated):
        hd = validate_holdout(ev, objs, list(X[idx]), holdout_spec, probe_x=probe_x,
                              band_ceilings=band_ceilings, baseline_x=baseline_x)
        if rank == 0:
            top_holdout = hd
        if hd.get("passed") is True:
            result.best_x = list(X[idx]); result.best_loss = list(F[idx])
            result.notes = (result.notes or "") + (
                f" | front-select: committed member {idx} (minimax-rank {rank} of "
                f"{len(order)}) PASSED holdout; exhaustive={not truncated}")
            print(f"  [calib] front-select: member #{idx} (minimax-rank {rank}) PASSES holdout "
                  f"on all objectives -> committing", flush=True)
            return idx, hd
    idx = order[0]
    result.best_x = list(X[idx]); result.best_loss = list(F[idx])
    status = "TRUNCATED-none-in-cap-passed" if truncated else "exhaustive-none-passed"
    result.notes = (result.notes or "") + (
        f" | front-select: NO member passed holdout ({status}, {len(gated)}/{len(order)} gated); "
        f"kept minimax knee {idx}")
    print(f"  [calib] front-select: no member passed holdout ({status}); keeping minimax knee "
          f"#{idx} (better-balanced than sum-knee, still not promotable)", flush=True)
    return idx, top_holdout


def calibrate(ki_path: str, workdir: str, obs_shape_by_var: dict,
              run_model=None, budget: int | None = None, seed: int = 0,
              active_idx=None, determining_metric=None, headline_objectives=None,
              expected_case_id=None):
    """Top-level calibration. `run_model` (callable -> metrics dict) is the KI's
    programmatic run+score path; if None it is built from the contract's `runner`.
    `obs_shape_by_var` comes from the model_obs_map join. `determining_metric` (the
    per-obs headline metric from readiness/the convention) overrides the family-default
    metric when the contract didn't; `headline_objectives` (convention pass-bands) gate
    the holdout on the absolute field band. Returns a report dict."""
    from . import objectives as O
    from .backends.base import Problem
    import yaml as _yaml

    contract = _load_contract(ki_path)
    dag = _yaml.safe_load((Path(ki_path) / "dag.yaml").read_text())
    params = contract["parameters"]
    metric_overrides = _effective_metric_overrides(contract, determining_metric)
    _inj_mode = (contract.get("injection", {}) or {}).get("mode", "applicator")   # needed early (probe gate)

    if run_model is None:
        spec = contract.get("runner")
        if not spec:
            return {"status": "no_runner",
                    "reason": "no run_model passed and no `runner` in calibration.yaml"}
        from .runner import make_run_model
        run_model = make_run_model(spec, ki_path, workdir)

    # MODULE CERTIFICATION (top-level only; opt-in via calib/reference_run.json). Prove the
    # auto-generated calibration function reproduces the validated KI run BEFORE any probe /
    # Morris screen / triage — a module that doesn't execute the KI correctly (missing
    # prepare/routing/staging) is caught here in ONE run, not after an expensive screen +
    # nested driver-repair agent.
    if active_idx is None:
        _ref = _load_reference_run(ki_path)
        if _ref:
            _cert = certify_runner(contract, run_model, _ref, workdir, expected_case_id=expected_case_id)
            print(f"  [calib] runner certification: {'PASS' if _cert.get('certified') else 'FAIL'} "
                  f"— {_cert.get('reason')}", flush=True)
            if not _cert.get("certified"):
                return {"status": "runner_uncertified", "certification": _cert,
                        "reason": _cert.get("reason"),
                        "validated_run_id": _ref.get("validated_run_id")}

    # Sensitivity-driven STAGED calibration (user's strategy): screen the param pool,
    # calibrate the few most-sensitive, escalate until the holdout passes. Routed here
    # when strategy.staged is set and this isn't already a single-subset round.
    if active_idx is None and (contract.get("strategy", {}) or {}).get("staged"):
        return calibrate_staged(ki_path, workdir, obs_shape_by_var,
                                run_model=run_model, budget=budget, seed=seed,
                                determining_metric=determining_metric,
                                headline_objectives=headline_objectives,
                                expected_case_id=expected_case_id)

    objs = O.objectives_from_dag(dag, contract.get("targets"), obs_shape_by_var,
                                metric_overrides=metric_overrides)
    if not objs:
        return {"status": "no_objectives",
                "reason": "no gate-valid metric_families for the targets/obs_shapes "
                          "(check obs_shape_by_var has an entry per target var)"}

    # FAMILY AUTO-SELECTION (codex SWAT+ #1): a dag output may declare more gate-valid
    # families than the runner can emit (e.g. flo_out -> temporal+magnitude+TIMING, but
    # the runner only writes nse/pbias, not day_bias). Requiring an un-produced metric
    # makes EVERY eval score +inf. Probe the runner once at defaults and keep only the
    # objectives whose metric the runner actually produces. Skippable via
    # strategy.probe_objectives: false (then all declared families are required).
    # FAMILY AUTO-SELECTION: probe the runner AT DEFAULTS (runner mode: with KDT_CALIB_PARAMS set)
    # and drop objectives whose metric it doesn't emit — else a declared-but-unemitted family scores
    # every eval +inf. Also fail-closed on a wrong/undeclared pinned case seen in the probe.
    if (contract.get("strategy", {}) or {}).get("probe_objectives", True):
        _probe = _probe_runner_metrics(run_model, _inj_mode, params, workdir)
        objs, _perr = _filter_objectives_by_probe(objs, _probe, expected_case_id, _inj_mode)
        if _perr:
            return _perr

    try:
        fwd, inv = _validate_transforms(params)
    except ValueError as e:
        return {"status": "invalid_contract", "reason": str(e)}

    # C1/C7 preflight — abort on any mis-targeted/lossy address (codex :72). APPLICATOR mode only:
    # runner mode has no central addresses to verify (calib_run.py owns injection + its own readback), so a
    # runner KI with optional/no addresses or a runner-only kind must NOT hard-fail here.
    if _inj_mode == "applicator":
        addr_problems = _preflight_addresses(params, workdir)
        if addr_problems:
            return {"status": "address_preflight_failed", "problems": addr_problems}

    # Staged calibration: optimize only the ACTIVE param subset (others frozen at default). The SUBSET +
    # FROZEN map apply in BOTH modes; only the mechanism differs — applicator WRITES the frozen defaults into
    # the files here, runner rides them in the payload (evaluator's fixed_params merge). (Previously this whole
    # block was gated on applicator mode, so staged RUNNER rounds wrongly optimized the full pool + dropped
    # frozen params — Codex re-review.)
    if active_idx is not None:
        _params = [params[i] for i in active_idx]
        _active = {p["name"] for p in _params}
        _fixed = {p["name"]: p.get("default") for p in params
                  if p["name"] not in _active and p.get("default") is not None}
        if _inj_mode == "applicator":
            from .applicator import write_param
            for p in params:
                if p["name"] not in _active:      # fix non-active params at default in the files
                    try:
                        write_param(p["address"], p.get("default"), workdir)
                    except Exception:
                        pass
    else:
        _params = params
        _fixed = {}

    lower = [fwd[p["name"]](float(p["range"][0])) for p in _params]
    upper = [fwd[p["name"]](float(p["range"][1])) for p in _params]
    multi = _is_multi_objective(contract, objs)

    from .evaluator import Evaluator
    ev = Evaluator(ki_path=ki_path, workdir=workdir, parameters=_params,
                   objectives=objs, transform_inv=inv, run_model=run_model,
                   constraints_ok=_make_constraints(contract), base_seed=seed,
                   injection_mode=_inj_mode, fixed_params=_fixed,
                   expected_case_id=expected_case_id)

    # COMMISSIONING (runner mode): round-trip proves the value was written; this proves the delegated
    # injection actually reaches the SCORED run. Default vs a clearly-different vector — the objective must
    # move, else calib_run.py isn't injecting into the file the model reads. (applicator mode is already
    # round-trip-verified by _preflight_addresses.)
    if _inj_mode == "runner":
        _xd = [fwd[p["name"]](float(p.get("default", (float(p["range"][0]) + float(p["range"][1])) / 2.0)))
               for p in _params]
        _resp, _detail = ev.responsiveness_check(_xd, lower, upper)
        # WRONG-GAUGE GUARD (codex 2026-07-18): commissioning ran the runner at defaults, so if it
        # self-declared a case_id different from the target, abort NOW — never optimize the wrong site.
        if ev._wrong_case:
            return {"status": "runner_wrong_case", "injection_mode": "runner",
                    "expected_case_id": expected_case_id, "declared_case_id": ev._wrong_case,
                    "reason": f"runner scored case '{ev._wrong_case}' but the target case is "
                              f"'{expected_case_id}' — capability was built for the wrong gauge/obs"}
        if _resp is False:      # explicit unresponsive → abort (None = inconclusive → proceed with a warning)
            return {"status": "runner_unresponsive", "injection_mode": "runner",
                    "reason": f"delegated injection did not move any objective ({_detail}) — the params may "
                              f"not reach the scored run; fix tools/calib_run.py injection"}

    def _evaluate(x):
        losses = ev.evaluate(x)
        if not multi:                  # scalarize same-target families
            tot = sum(o.weight for o in objs) or 1.0
            return [sum(o.weight * l for o, l in zip(objs, losses)) / tot]
        return losses

    problem = Problem(
        names=[p["name"] for p in _params], lower=lower, upper=upper,
        objective_names=[o.name for o in objs] if multi else ["scalar_loss"],
        evaluate=_evaluate, is_multi_objective=multi)

    algo = _pick_backend(contract, multi, len({o.var for o in objs}))
    budget = budget or (contract.get("strategy", {}) or {}).get("max_evaluations", 200)
    backend = _make_backend(algo)
    if backend is None or not backend.available():
        return {"status": "backend_unavailable", "algorithm": algo,
                "reason": f"{algo} backend/library not importable in this env"}

    result = backend.optimize(problem, budget=budget, seed=seed)

    # All evaluations failed/infeasible -> NOT a successful calibration (codex :123).
    # Restore the original inputs (the evaluator wrote candidates as it went) so the
    # workdir isn't left at a garbage vector, and surface a failure status.
    finite_best = bool(result.best_x) and all(
        math.isfinite(v) for v in (result.best_loss or [float("inf")]))
    if not finite_best:
        ev.restore_originals()
        return {"status": "failed_no_finite_solution", "algorithm": algo,
                "n_evaluations": result.n_evaluations,
                "reason": "no evaluation produced a finite loss (all runs failed/infeasible)",
                "backend_notes": result.notes}

    # ---- HOLDOUT INPUTS (shared by front-selection and the final gate) ----
    holdout_spec = (contract.get("strategy", {}) or {}).get("holdout")
    _front_holdout = None
    if holdout_spec:
        band_ceilings = _holdout_band_ceilings(objs, headline_objectives)
        probe_x = [(lo + hi) / 2.0 for lo, hi in zip(lower, upper)]   # off-optimal probe
        baseline_x = [fwd[p["name"]](float(p.get("default",
                          (float(p["range"][0]) + float(p["range"][1])) / 2.0))) for p in _params]
        # MULTI-OBJECTIVE FRONT SELECTION (flag-gated pending codex review). Replaces the
        # min-normalized-SUM knee — which can commit a point that sacrifices one objective —
        # with a holdout-gated minimax selection over the Pareto front. MUTATES result.best_x
        # to the chosen member, so it must run BEFORE _apply_best / train_metrics below.
        if os.environ.get("KDT_CALIB_FRONT_SELECT") == "1" and multi and result.pareto_x:
            _sel_idx, _front_holdout = _select_front_member(
                ev, objs, result, holdout_spec, band_ceilings, probe_x, baseline_x)

    # Leave inputs at the BEST params (TYPED-decoded, identical to what was scored —
    # codex calib.py:198), not raw floats / last-tried.
    from .applicator import write_param
    from .evaluator import decode_value
    def _apply_best():
        out = {}
        for p, xi in zip(_params, result.best_x):
            val = decode_value(p, xi, inv[p["name"]])
            out[p["name"]] = val
            if _inj_mode == "applicator":            # runner mode: best params are case-scoped only
                try:                                 # (no central address to write; calib_run.py injects)
                    write_param(p["address"], val, workdir)
                except Exception as _e:
                    out[p["name"]] = f"<apply failed: {_e}>"
        return out
    best_named = _apply_best()

    # Capture the BEST candidate's METRICS for the record (the human-readable "after": nse/pbias/...).
    # Already computed during optimization -> read from the eval cache by best_x BEFORE the holdout
    # re-runs change the active split (2026-07-19: these were None in the DB because only best_loss was
    # surfaced). Try the optimization split, then common fallbacks.
    _train_metrics = None
    try:
        _bn = ev._named(result.best_x)
        # never trust a stale env split here (codex round-4): training resolved to "calibration"
        for _sp in ("calibration", None):
            _hit = ev._metrics_cache.get(ev._cache_key(_bn, _sp))
            if _hit:
                _train_metrics = _hit
                break
    except Exception:
        _train_metrics = None

    # HOLDOUT GATE (codex C6) — validate the best params on held-out data before
    # calling the calibration promotable. A calibration that doesn't generalize is
    # NOT promotable to the canonical KI no matter how good its calibration loss.
    # (holdout_spec / band_ceilings / probe_x / baseline_x were computed above so the
    # optional front-selection could reuse them.)
    holdout = None
    promotable = True
    if holdout_spec:
        from .holdout import validate_holdout
        # Reuse the holdout the front-selection already computed for the committed member
        # (else validate the sum-knee best_x as before).
        holdout = _front_holdout if _front_holdout is not None else validate_holdout(
            ev, objs, result.best_x, holdout_spec, probe_x=probe_x,
            band_ceilings=band_ceilings, baseline_x=baseline_x)
        _apply_best()   # re-apply best params after the holdout re-runs wrote best_x
        # promotable only if holdout explicitly PASSED (None/inconclusive => gate it)
        promotable = (holdout.get("passed") is True)
    else:
        # No holdout declared -> NOT promotable (C6 makes it mandatory for promotion).
        promotable = False

    return {"status": "completed", "algorithm": algo, "multi_objective": multi,
            "best_x": result.best_x, "best_params": best_named,
            "best_loss": result.best_loss, "train_metrics": _train_metrics,
            "pareto_x": result.pareto_x, "pareto_f": result.pareto_f, "n_evaluations": result.n_evaluations,
            "holdout": holdout,
            "holdout_validated": (holdout.get("passed") if holdout else None),
            "promotable": promotable,    # gate for writing best params to CANONICAL
            "objectives": [o.name for o in objs],
            "posterior": result.posterior,      # DREAM per-parameter posterior summary (None otherwise)
            "backend_notes": result.notes}


def _make_backend(algo):
    if algo in ("dds", "sceua", "dream"):
        from .backends.spotpy_backend import SpotpyBackend
        return SpotpyBackend(algorithm=algo)
    if algo in ("nsga2", "nsga3", "moead"):
        from .backends.pymoo_backend import PymooBackend
        return PymooBackend(algorithm=algo)
    if algo in ("surrogate", "botorch", "smt", "bo"):
        from .backends.surrogate_backend import SurrogateBackend
        return SurrogateBackend(library="smt" if algo == "smt" else "botorch")
    if algo in ("pestpp_ies", "pestpp_glm", "ies", "glm"):
        from .backends.pestpp_backend import PestppBackend
        return PestppBackend(variant="glm" if algo in ("pestpp_glm", "glm") else "ies")
    return None


# ---- safe constraint expression evaluator (codex calib.py:163) -------------
# raw eval() is unsafe even with __builtins__ cleared. Parse a restricted AST over
# the named scalar parameters only — arithmetic + comparison + boolean, no calls,
# no attribute access, no names beyond the parameters.
_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_CMP = {ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt,
        ast.GtE: operator.ge, ast.Eq: operator.eq, ast.NotEq: operator.ne}
_BOOL = {ast.And: all, ast.Or: any}


def _safe_eval(node, names):
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body, names)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, bool)):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in names:
            raise ValueError(f"unknown name in constraint: {node.id}")
        return names[node.id]
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        return _BIN[type(node.op)](_safe_eval(node.left, names), _safe_eval(node.right, names))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _safe_eval(node.operand, names)
        return -v if isinstance(node.op, ast.USub) else +v
    if isinstance(node, ast.Compare):
        left = _safe_eval(node.left, names); ok = True
        for op, comp in zip(node.ops, node.comparators):
            right = _safe_eval(comp, names)
            if type(op) not in _CMP or not _CMP[type(op)](left, right):
                ok = False; break
            left = right
        return ok
    if isinstance(node, ast.BoolOp):
        # real Python short-circuit (codex calib.py:288) — don't eval dead branches
        if isinstance(node.op, ast.And):
            for v in node.values:
                if not _safe_eval(v, names):
                    return False
            return True
        if isinstance(node.op, ast.Or):
            for v in node.values:
                if _safe_eval(v, names):
                    return True
            return False
    raise ValueError(f"disallowed expression element: {ast.dump(node)[:60]}")


def _make_constraints(contract):
    exprs = contract.get("constraints") or []
    if not exprs:
        return None
    trees = [ast.parse(e, mode="eval") for e in exprs]   # parse once; reject bad syntax early
    def _ok(named: dict) -> bool:
        try:
            return all(bool(_safe_eval(t, named)) for t in trees)
        except Exception:
            return False
    return _ok


def calibrate_staged(ki_path, workdir, obs_shape_by_var, run_model=None,
                     budget=None, seed=0, determining_metric=None,
                     headline_objectives=None, expected_case_id=None):
    """Sensitivity-driven STAGED calibration (the principled strategy):
      1. screen the WHOLE param pool by sensitivity (Morris elementary effects);
      2. calibrate the few most-sensitive params (others fixed at default);
      3. if not promotable, ESCALATE — add the next most-sensitive params, re-calibrate;
      4. stop on the first promotable round, or when all params are active.
    Avoids equifinality/over-fit (start small) and finds the params that actually
    control the error mode (codex's SWAT+ #2: the contract was tuning the wrong levers).
    """
    import yaml as _yaml
    from . import objectives as O
    from .sensitivity import morris_screen
    from .evaluator import Evaluator

    contract = _load_contract(ki_path)
    params = contract["parameters"]
    n = len(params)
    strat = contract.get("strategy", {}) or {}
    dag = _yaml.safe_load((Path(ki_path) / "dag.yaml").read_text())
    metric_overrides = _effective_metric_overrides(contract, determining_metric)

    if run_model is None:
        from .runner import make_run_model
        run_model = make_run_model(contract.get("runner") or {}, ki_path, workdir)

    objs = O.objectives_from_dag(dag, contract.get("targets"), obs_shape_by_var,
                                metric_overrides=metric_overrides)
    if not objs:
        return {"status": "no_objectives", "staged": True}
    # FAMILY AUTO-SELECTION for the STAGED path too (2026-07-19): the screen scalarizes all objectives,
    # so a declared-but-unemitted family (e.g. timing_accuracy/day_bias the runner never writes) makes
    # EVERY screen eval +inf -> n_effects all 0 -> screen_failed. Probe the runner at defaults (runner
    # mode: with KDT_CALIB_PARAMS set) and drop objectives it doesn't produce. Was previously only done
    # in the non-staged calibrate(), so every staged runner-mode model silently screen_failed.
    # RUNNER mode only (codex 2026-07-19): _probe_runner_metrics writes DEFAULTS + sets KDT_CALIB_PARAMS
    # for runner drivers, so it's a true default-params run. Applicator mode has no such defaults-writing
    # here (probing whatever is currently in the workdir files could drop objectives off stale state), so
    # the staged objective-drop is runner-only — applicator keeps its prior no-probe behavior (no regression;
    # staged had NO probe at all before). The probe result is also REUSED as the triage baseline below.
    _inj_staged = (contract.get("injection", {}) or {}).get("mode", "applicator")
    _probe = {}
    if _inj_staged == "runner" and strat.get("probe_objectives", True):
        _probe = _probe_runner_metrics(run_model, _inj_staged, params, workdir)
        objs, _perr = _filter_objectives_by_probe(objs, _probe, expected_case_id, _inj_staged)
        if _perr:
            return {**_perr, "staged": True}
    try:
        fwd, inv = _validate_transforms(params)
    except ValueError as e:
        return {"status": "invalid_contract", "reason": str(e), "staged": True}

    # --- 1) sensitivity screen over the full pool (cheap) ----------------------
    ev = Evaluator(ki_path=ki_path, workdir=workdir, parameters=params,
                   objectives=objs, transform_inv=inv, run_model=run_model,
                   constraints_ok=_make_constraints(contract), base_seed=seed,
                   injection_mode=(contract.get("injection", {}) or {}).get("mode", "applicator"),
                   expected_case_id=expected_case_id)   # wrong-gauge guard MUST apply to the screen too
    def _scalar(x):
        L = ev.evaluate(x)
        tot = sum(o.weight for o in objs) or 1.0
        return sum(o.weight * l for o, l in zip(objs, L)) / tot
    lower = [fwd[p["name"]](float(p["range"][0])) for p in params]
    upper = [fwd[p["name"]](float(p["range"][1])) for p in params]
    # COMMISSIONING before the screen (runner mode): the Morris screen/triage below trust the objective —
    # if delegated injection isn't reaching the run, screen every knob as insensitive is meaningless.
    if (contract.get("injection", {}) or {}).get("mode", "applicator") == "runner":
        _xd = [fwd[p["name"]](float(p.get("default", (float(p["range"][0]) + float(p["range"][1])) / 2.0)))
               for p in params]
        _resp, _detail = ev.responsiveness_check(_xd, lower, upper)
        # WRONG-GAUGE GUARD (codex 2026-07-18): commissioning ran the runner at defaults — if it
        # self-declared a different (or, for a pinned case, missing) case_id, abort BEFORE the
        # Morris screen + triage, which would otherwise early-return already_adequate/diagnose_setup
        # on the wrong site.
        if ev._wrong_case:
            return {"status": "runner_wrong_case", "staged": True, "injection_mode": "runner",
                    "expected_case_id": expected_case_id, "declared_case_id": ev._wrong_case,
                    "reason": f"runner scored case '{ev._wrong_case}' but the target case is "
                              f"'{expected_case_id}' — capability was built for the wrong gauge/obs"}
        if _resp is False:
            return {"status": "runner_unresponsive", "staged": True, "injection_mode": "runner",
                    "reason": f"delegated injection did not move any objective ({_detail}); fix tools/calib_run.py"}
    R = int(strat.get("screen_trajectories", 4))
    screen = morris_screen(_scalar, lower, upper, R=R, seed=seed)
    ev.restore_originals()                      # undo the screen's writes -> defaults
    ranking = screen["ranking"]

    # --- 1b) CALIBRATABILITY TRIAGE (2026-06-27): is calibration even the right tool?
    # Capture the BASELINE metrics at default params and route via the SAME gate-driven
    # family-partition verdict the loop uses (pattern vs magnitude), combined with the
    # screen's mu*/n_effects. A failing PATTERN family means the structure/setup is wrong
    # (calibration can't fix that → DIAGNOSE THE SETUP). Only calibrate/calibrate_caution
    # proceed. NO hardcoded r — `valid_families` are the dag's sanctioned families.
    from . import calibratability as _CB
    if _inj_staged == "runner":
        # BASELINE for runner mode ALWAYS comes from a DEFAULT-params run — DECOUPLED from the objective
        # probe (codex 2026-07-19 round-2): a runner-mode ev.run_model() with KDT_CALIB_PARAMS popped DIES
        # -> {} -> corrupts triage. Reuse the objective probe if it ran (probe_objectives on + succeeded);
        # otherwise (probe disabled or empty) run _probe_runner_metrics here so the baseline is still a real
        # default-params run, never the dying {} path.
        _baseline_metrics = dict(_probe) if _probe else _probe_runner_metrics(run_model, _inj_staged, params, workdir)
    else:
        # APPLICATOR baseline also bypasses Evaluator.evaluate(), so it must set the CALIBRATION split
        # itself (codex 2026-07-19) — otherwise it scores the FULL record and mis-routes triage exactly
        # like the runner path did.
        from .evaluator import resolve_train_split as _rts, split_is_authoritative as _sia
        _prev_bsplit = os.environ.get("KDT_CALIB_SPLIT")
        _bsplit_unset = not _sia(_prev_bsplit)         # unset / blank / inherited 'full' -> we own it
        try:
            os.environ.pop("KDT_CALIB_PARAMS", None)   # baseline must run at TRUE defaults, not a stale candidate
            if _bsplit_unset:
                os.environ["KDT_CALIB_SPLIT"] = _rts(_prev_bsplit)
            _baseline_metrics = ev.run_model() or {}
            ev.restore_originals()
        except Exception:
            _baseline_metrics = {}
        finally:
            if _bsplit_unset:
                if _prev_bsplit is None:
                    os.environ.pop("KDT_CALIB_SPLIT", None)
                else:
                    os.environ["KDT_CALIB_SPLIT"] = _prev_bsplit
    # WRONG-GAUGE GUARD (codex round-4): abort BEFORE triage can early-return (already_adequate /
    # diagnose_setup / ...) on a wrong-site model. Two sources are covered: (a) the Morris screen ran
    # the runner many times, each evaluate() through the case gate, accumulating ev._wrong_case; (b) the
    # baseline above uses ev.run_model() directly (bypasses evaluate()), so re-check its declared case
    # here. Runner mode + pinned case only (applicator baselines have no __kdt__.case_id and must not
    # false-trigger).
    if (contract.get("injection", {}) or {}).get("mode", "applicator") == "runner" and expected_case_id \
            and _baseline_metrics:
        _bcase = (_baseline_metrics.get("__kdt__") or {}).get("case_id")
        if _bcase is None or str(_bcase) != str(expected_case_id):
            ev._wrong_case = ev._wrong_case or (str(_bcase) if _bcase is not None else "<undeclared>")
    if ev._wrong_case:
        return {"status": "runner_wrong_case", "staged": True, "injection_mode": "runner",
                "expected_case_id": expected_case_id, "declared_case_id": ev._wrong_case,
                "reason": f"runner scored case '{ev._wrong_case}' but the target case is "
                          f"'{expected_case_id}' — capability was built for the wrong gauge/obs"}
    # FAIL-CLOSED baseline (codex 2026-07-19 round-3/4): a runner-mode default-params run must yield at
    # least one REAL objective metric before triage. A {} baseline (driver crash) OR a truthy-but-
    # metric-less dict (e.g. only {"__kdt__":{...}} / metadata) would otherwise route as a misleading
    # 'undetermined'/'calibrate_caution'. Require a finite value for at least one of THIS run's objectives.
    def _baseline_has_objective_metric():
        for o in objs:
            _mm = _baseline_metrics.get(o.var) if isinstance(_baseline_metrics.get(o.var), dict) else _baseline_metrics
            _v = (_mm or {}).get(o.metric_key)
            try:
                if _v is not None and math.isfinite(float(_v)):
                    return True
            except (TypeError, ValueError):
                pass
        return False
    if _inj_staged == "runner" and not _baseline_has_objective_metric():
        return {"status": "screen_failed", "staged": True, "route": "screen_failed", "promotable": False,
                "reason": "runner produced NO finite objective metric at DEFAULT params — the module cannot "
                          "establish a baseline (driver/setup broken); calibration impossible",
                "baseline": _baseline_metrics}
    _tgt_var = (contract.get("targets") or [{}])[0].get("var") or (objs[0].var if objs else "")
    _valid_families = sorted({o.family for o in objs})   # dag-declared families for targets
    _strat_t = strat.get("triage", {}) or {}
    triage = _CB.assess(
        _baseline_metrics, _tgt_var, _valid_families,
        screen.get("mu_star"), screen.get("n_effects"),
        pattern_tol=float(_strat_t.get("pattern_tol", 0.5)),
        mag_tol=float(_strat_t.get("mag_tol", 0.1)),
        metric_overrides=metric_overrides)   # judge the HEADLINE metric (Bug #1), not the family default
    print(f"  [calib] calibratability triage: route={triage['route']} "
          f"baseline={triage['baseline']} sensitive={triage.get('sensitive')} "
          f"-> {triage['reason']}", flush=True)
    if triage["route"] not in ("calibrate", "calibrate_caution"):
        # early-exit signal for the self-improve loop (diagnose_setup / fix_driver /
        # already_adequate / screen_failed) — NOT a calibration, by design.
        return {"status": triage["status"], "staged": True, "promotable": False,
                "route": triage["route"], "reason": triage["reason"],
                "baseline": triage["baseline"], "n_effects": list(screen.get("n_effects") or []),
                "sensitivity_ranking": [params[i]["name"] for i in ranking],
                "mu_star": {params[i]["name"]: float(screen.get("mu_star", [0]*n)[i])
                            for i in range(n)}}

    # --- 2-4) escalation rounds ------------------------------------------------
    start = max(1, int(strat.get("staged_start", min(3, n))))
    step = max(1, int(strat.get("staged_step", 2)))
    sizes, k = [], min(start, n)
    while True:
        sizes.append(k)
        if k >= n:
            break
        k = min(k + step, n)

    # #3 BUDGET SPLIT: `max_evaluations` (or the passed budget) is the TOTAL eval budget for
    # the whole staged run, NOT a per-round quota — running the full budget every round
    # multiplied model runs by up to len(sizes)x (e.g. 4x300=1200 for a 4-round escalation).
    # Split it across the planned rounds, weighted by active-set size (bigger param sets need
    # more DDS evals). A per-round floor keeps DDS from being starved, but the floor must NOT
    # push the SUM over the total (Codex): so first cap the number of rounds we can afford at
    # the floor, then split the total EXACTLY (drift onto the last, largest round). Early-stop
    # on the first promotable round still applies, so most runs use far less than the total.
    total_budget = int(budget or strat.get("max_evaluations", 200))
    floor = max(1, int(strat.get("min_round_evaluations", 25)))
    n_afford = max(1, min(len(sizes), total_budget // floor))
    sizes = sizes[:n_afford]                     # can't afford more rounds than budget/floor
    sum_k = sum(sizes) or 1
    round_budgets = [max(1, int(total_budget * k / sum_k)) for k in sizes]
    round_budgets[-1] += total_budget - sum(round_budgets)   # absorb rounding drift -> sum == total
    print(f"  [calib-staged] budget split (total={total_budget}) over rounds {sizes} "
          f"-> {round_budgets} (sum={sum(round_budgets)})", flush=True)

    rounds, best = [], None
    for k, rb in zip(sizes, round_budgets):
        active = sorted(ranking[:k])
        res = calibrate(ki_path, workdir, obs_shape_by_var, run_model=run_model,
                        budget=rb, seed=seed, active_idx=active,
                        determining_metric=determining_metric,
                        headline_objectives=headline_objectives,
                        expected_case_id=expected_case_id)
        rounds.append({"k": k, "active": [params[i]["name"] for i in active],
                       "status": res.get("status"),
                       "promotable": res.get("promotable"),
                       "holdout_validated": res.get("holdout_validated"),
                       "best_loss": res.get("best_loss")})
        print(f"  [calib-staged] round k={k} active={[params[i]['name'] for i in active]} "
              f"-> {res.get('status')} promotable={res.get('promotable')}", flush=True)
        best = res
        if res.get("promotable"):
            break
        # TERMINAL, non-recoverable statuses must NOT escalate (escalating just re-runs the same
        # broken runner at more params): a wrong-gauge / uncertified / no-runner capability is fatal.
        if res.get("status") in ("runner_wrong_case", "runner_uncertified", "no_runner",
                                 "backend_unavailable"):
            break

    return {**(best or {"status": "no_rounds"}), "staged": True,
            "baseline": triage.get("baseline"),   # surface the pre-calibration metrics for the record
            "sensitivity_ranking": [params[i]["name"] for i in ranking],
            "mu_star": {params[i]["name"]: round(screen["mu_star"][i], 4) for i in range(n)},
            "rounds": rounds}
