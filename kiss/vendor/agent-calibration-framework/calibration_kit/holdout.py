"""Holdout validation gate (codex C6 / pitfall #1: over-fitting & equifinality).

A calibration is only credible/promotable if the best parameters still perform on
data NOT used during the search. We:
  1. signal the run via env KDT_CALIB_SPLIT = "calibration" | "holdout" — the model's
     runner (calib_run.py) is responsible for scoring the right subset (years / sites
     / regions) per strategy.holdout. The kit orchestrates the split + the verdict;
     the model owns which data is in each split.
  2. evaluate the best params on BOTH splits and compare per objective.
  3. PASS iff no objective degrades beyond `max_degradation` on holdout (and holdout
     loss is finite). A failed holdout => not promotable (likely over-fit).

If the runner ignores KDT_CALIB_SPLIT (no split support), calibration and holdout
losses come out identical — we detect that and mark the holdout INCONCLUSIVE rather
than a false PASS.
"""
from __future__ import annotations
import math
import os


def _eval_split(evaluator, x, split):
    """Score `x` on an EXPLICIT split. This is the ONLY place allowed to override the TRAINING split, so
    it goes through `split_authority()` — IN-PROCESS authority (codex round-4); a bare KDT_CALIB_SPLIT
    inherited from a parent env is deliberately never trusted."""
    from .evaluator import split_authority
    with split_authority(split):
        return evaluator.evaluate(x)


def validate_holdout(evaluator, objectives, best_x, spec: dict,
                     probe_x=None, band_ceilings=None, baseline_x=None) -> dict:
    """Compare best_x on the calibration vs holdout split. PASS iff no objective
    degrades beyond max_degradation on holdout (and stays finite) AND — when a
    convention pass-band is supplied for it — the held-out loss also MEETS that
    absolute field band. `band_ceilings` maps objective.name -> max allowed holdout
    loss (from the validation convention). An objective with no band is gated on
    non-degradation only; a band makes the gate strictly harder (never weaker).

    Inconclusive detection uses a PROBE at an off-optimal point (`probe_x`): if the
    runner honors KDT_CALIB_SPLIT, an off-optimal point scores DIFFERENTLY on the two
    splits (their optima differ); if probe losses are identical across splits the
    runner ignored the split and we cannot claim generalization. (Comparing at
    best_x alone can't tell perfect-generalization from no-split — both give
    identical near-zero losses.)
    """
    # #4: default relative non-degradation tightened 0.5 -> 0.35 (a 50% holdout degradation
    # was too permissive). This relative bound is ANDed with the convention pass-band
    # (band_ceilings) when one exists — BOTH must hold — so it applies to every case, not only
    # non-convention ones; a run in the 35-50% degradation band now fails even if it meets the
    # absolute field band (conservative, since large cal->holdout degradation signals over-fit).
    # Still per-contract configurable via strategy.holdout.max_degradation.
    tol = float((spec or {}).get("max_degradation", 0.35))
    # additive tolerance so a near-PERFECT calibration (loss ~0) isn't rejected for a
    # tiny-but-still-excellent holdout loss. threshold = cal*(1+tol) + abs_tol.
    abs_tol = float((spec or {}).get("abs_tolerance", 0.05))

    # 1) split-awareness probe
    # split-awareness probe — require a MATERIAL difference on at least one objective
    # (codex holdout.py:56): tiny run-to-run noise must NOT be read as "runner splits".
    # Both probe losses must be finite AND differ by a relative margin.
    rel_margin = float((spec or {}).get("split_probe_rel", 0.02))   # >=2% difference
    if probe_x is not None:
        pc = _eval_split(evaluator, probe_x, "calibration")
        ph = _eval_split(evaluator, probe_x, "holdout")
        materially_different = any(
            math.isfinite(a) and math.isfinite(b)
            and abs(a - b) > rel_margin * max(abs(a), abs(b), 1e-9)
            for a, b in zip(pc, ph))
        if not materially_different:
            return {"passed": None, "inconclusive": True,
                    "reason": "runner did not materially honor KDT_CALIB_SPLIT (probe "
                              f"scored within {rel_margin:.0%} on both splits); cannot "
                              "validate generalization",
                    "kind": (spec or {}).get("kind"), "per_objective": []}

    # 2) real comparison at best_x — BOTH must be finite (codex holdout.py:69): if the
    # calibration rerun at best_x isn't reproducible/finite we cannot judge over-fit.
    cal = _eval_split(evaluator, best_x, "calibration")
    hold = _eval_split(evaluator, best_x, "holdout")

    # CORRELATION FLOOR (verdict-honesty audit 2026-08-05). Capture the CALIBRATED model's holdout
    # metrics (incl. r) NOW — before the baseline holdout eval below overwrites _last_metrics["holdout"].
    # A pattern/temporal objective must NOT pass on level/variance/beats-baseline while the calibrated
    # correlation is ~0 or negative (a level match is not a fit): GLM_AED (r -0.97) and MODFLOW-焦作
    # (r 0.04) both slipped through the beats-baseline path. r_floor default 0.5, per-contract overridable.
    from .objectives import MAGNITUDE_FAMILIES
    # MAGNITUDE BACKSTOP (verdict-honesty audit 2026-08-06). A magnitude objective for which NO
    # convention field-band attached falls back to beats-baseline only — which passes a model that
    # merely beats a terrible baseline while still far from any acceptable field bias (CRHM SWE:
    # 52% holdout pbias beat a 57% baseline -> spurious pass). When (and only when) no band gates the
    # objective, require the calibrated holdout loss under a generic ceiling. Default 0.30 = 30% pbias
    # (magnitude_accuracy loss = |pbias|/100) — deliberately MORE lenient than typical field bands
    # (discharge ~25%, SWE ~15%) so it never false-fails a genuine magnitude match; it only catches
    # the egregious no-band case. Per-contract overridable via strategy.holdout.mag_backstop.
    mag_backstop = float((spec or {}).get("mag_backstop", 0.30))
    # Capture the CALIBRATED model's r on BOTH splits. The floor uses the MINIMUM: a short holdout window
    # over a monotonic trend can give a trivially-high r (a declining sim correlates with a declining obs)
    # while the calibration window reveals the model never learned the dynamics (焦作: holdout r 0.965 but
    # calibration r 0.04). Requiring BOTH to clear the floor catches both under-fit (cal r low) and
    # non-generalization (holdout r low). _last_metrics["calibration"] holds best_x's calibration metrics
    # (set by the `cal` eval above); "holdout" holds best_x's (before the baseline holdout eval overwrites).
    _lm = getattr(evaluator, "_last_metrics", {}) or {}
    _cal_cal_m = dict(_lm.get("calibration") or {})
    _cal_hold_m = dict(_lm.get("holdout") or {})
    r_floor = float((spec or {}).get("corr_floor", 0.5))

    def _r_from(metrics, var):
        m = metrics.get(var) if isinstance(metrics.get(var), dict) else metrics
        if not isinstance(m, dict):
            return None
        try:
            v = m.get("r")
            v = float(v) if v is not None else None
        except (TypeError, ValueError):
            return None
        return v if (v is None or math.isfinite(v)) else None

    def _split_rs(var):
        # the calibrated Pearson r on (calibration, holdout) — either may be None if the runner
        # did not report r on that split. The floor is FAIL-CLOSED (codex 2026-08-08): a missing r
        # is NOT treated as "clear" — the caller fails the objective when either is None.
        return _r_from(_cal_cal_m, var), _r_from(_cal_hold_m, var)

    # BASELINE COMPARISON on the HELD-OUT split (2026-07-20). The two checks above ask whether the
    # calibrated model is self-consistent (holdout ~ its own calibration) and meets an absolute band.
    # NEITHER asks the question that actually matters for promotion: *did calibrating beat NOT
    # calibrating on unseen data?* A calibration can be internally consistent and still be WORSE than
    # the untouched defaults out-of-sample — observed on HBV @ Wangjiaba, which passed while its
    # held-out NSE fell 0.732 -> 0.588 (KGE 0.579 -> 0.419). Score the DEFAULT vector on the SAME
    # held-out split and require the calibrated model to be no worse, per objective.
    base_hold = None
    if baseline_x is not None:
        try:
            base_hold = _eval_split(evaluator, baseline_x, "holdout")
        except Exception:
            base_hold = None
    # allow a hair of numerical slack so an effectively-tied result isn't failed on float noise
    base_tol = float((spec or {}).get("baseline_abs_tolerance", 1e-6))

    bands = band_ceilings or {}
    per_obj, passed = [], True
    for i, (o, c, h) in enumerate(zip(objectives, cal, hold)):
        band = bands.get(o.name)                       # convention field-band loss ceiling (or None)
        b = base_hold[i] if (base_hold is not None and i < len(base_hold)) else None
        _corr_fail_r = None                             # set when the correlation floor trips on a low r
        _corr_missing = False                           # set when the correlation floor fails CLOSED (r absent)
        _mag_fail = None                                # set when the magnitude backstop trips this objective
        if not (math.isfinite(c) and math.isfinite(h)):
            ok = False
            passed = False
        else:
            ok_band = (band is None) or (h <= band + 1e-9)   # meet the absolute field band
            have_base = (b is not None and math.isfinite(b))
            ok_vs_base = (h <= b + base_tol) if have_base else True
            ok_degrade = h <= c * (1.0 + tol) + abs_tol
            # PROMOTION RULE (option A, 2026-07-20). The BASELINE comparison is the authoritative
            # over-fit test — "did calibrating beat NOT calibrating on UNSEEN data?". When a baseline
            # is available, promotion = meets absolute band AND beats baseline; the relative
            # non-degradation rule is DROPPED because it misfires whenever the optimizer fits the
            # calibration window well: a near-zero calibration_loss makes the c*(1+tol)+abs_tol
            # threshold shrink to ~abs_tol, so a genuinely-good holdout reads as huge "degradation".
            # That wrongly failed HBV (held-out NSE 0.73->0.76) and WRF-Hydro (held-out NSE 0.17->0.61),
            # both of which beat their baseline on EVERY objective. With NO baseline to compare against,
            # fall back to the old self-consistency (non-degradation) guard.
            if have_base:
                ok = ok_band and ok_vs_base
            else:
                ok = ok_band and ok_degrade
            # CORRELATION FLOOR: for a PATTERN family, a calibrated holdout r below the floor fails the
            # objective no matter how band/beats-baseline scored — the calibrated model does not
            # reproduce the dynamics (a level/variance match is not a fit). Magnitude-only objectives
            # (yield/PBIAS, no r) are unaffected.
            _fam = str(o.name).rsplit(":", 1)[-1]
            # CORRELATION FLOOR, FAIL-CLOSED. Scoped to temporal_pattern_match — the only pattern family
            # whose natural evidence is Pearson r (the others are scored by csi/day_bias/trend_error/
            # spearman and legitimately carry no r, so requiring one would false-fail them). A temporal
            # pass must show r >= floor on BOTH splits: taking min() of only the PRESENT values would let
            # calibration_r=None + holdout_r=0.96 pass (the trend-inflation hole) or, with r missing on
            # both, skip the guard and pass on NSE/baseline with no correlation evidence (codex 2026-08-08).
            # So r missing/non-finite on EITHER split, OR min(both) < floor => fail the objective.
            if _fam == "temporal_pattern_match":
                _rc, _rh = _split_rs(getattr(o, "var", None))
                if _rc is None or _rh is None:
                    ok = False
                    _corr_missing = True
                elif min(_rc, _rh) < r_floor:
                    ok = False
                    _corr_fail_r = min(_rc, _rh)
            # MAGNITUDE BACKSTOP: only when NO band gates it (a band is the domain-correct ceiling and
            # already applied via ok_band). Catches the beats-a-weak-baseline-but-far-from-field case.
            elif band is None and _fam in MAGNITUDE_FAMILIES:
                if math.isfinite(h) and h > mag_backstop:
                    ok = False
                    _mag_fail = h
            passed = passed and ok
        rec = {"objective": o.name, "calibration_loss": c, "holdout_loss": h, "ok": ok}
        if _corr_fail_r is not None:
            rec["corr_floor_r"] = round(_corr_fail_r, 4)
            rec["corr_floor"] = r_floor
        if _corr_missing:
            rec["corr_floor_missing"] = True            # temporal pass rejected: r absent on a split (fail-closed)
            rec["corr_floor"] = r_floor
        if _mag_fail is not None:
            rec["mag_backstop_loss"] = round(_mag_fail, 4)
            rec["mag_backstop"] = mag_backstop
        if band is not None:
            rec["band_ceiling"] = band
            rec["meets_band"] = (math.isfinite(h) and h <= band + 1e-9)
        if b is not None:
            rec["baseline_holdout_loss"] = b
            rec["beats_baseline"] = (math.isfinite(b) and math.isfinite(h) and h <= b + base_tol)
        per_obj.append(rec)
    if any(not math.isfinite(c) for c in cal):
        return {"passed": None, "inconclusive": True,
                "reason": "calibration rerun at best_x not reproducible/finite",
                "kind": (spec or {}).get("kind"), "per_objective": per_obj}

    return {"passed": passed, "inconclusive": False,
            "kind": (spec or {}).get("kind"), "fraction": (spec or {}).get("fraction"),
            "max_degradation": tol, "per_objective": per_obj}
