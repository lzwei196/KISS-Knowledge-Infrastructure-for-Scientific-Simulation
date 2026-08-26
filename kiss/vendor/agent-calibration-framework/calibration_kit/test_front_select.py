"""Front-selection exhaustiveness + degenerate-objective tests (codex 2026-08-20).

Guards the fix that made _select_front_member EXHAUSTIVE: the committing member may be a
LOW-minimax-rank extreme of the Pareto front, and a cap must never hide it. Also checks that a
near-degenerate (zero-spread) objective is excluded from the minimax ranking rather than
dominating it via float-noise normalization.
"""
import types
import calibration_kit.holdout as _holdout
from calibration_kit.calib import _select_front_member


def _fake_result(px, pf):
    return types.SimpleNamespace(pareto_x=px, pareto_f=pf, best_x=None, best_loss=None, notes="")


def test_exhaustive_reaches_low_ranked_extreme():
    # 20-point convex front over 2 objectives. The most-balanced (minimax-min) sits near the
    # middle; index 0 is an EXTREME (obj1=0, obj2=1) -> worst normalized = 1.0 -> LAST in minimax
    # order (rank ~19). Only that extreme passes holdout, so a cap<19 would report none-passed.
    n = 20
    px = [[float(i)] for i in range(n)]
    pf = [[i / (n - 1), 1 - i / (n - 1)] for i in range(n)]
    winner = px[0]

    def fake_validate(ev, objs, best_x, spec, probe_x=None, band_ceilings=None, baseline_x=None):
        return {"passed": best_x == winner, "per_objective": []}

    _orig = _holdout.validate_holdout
    _holdout.validate_holdout = fake_validate
    try:
        r = _fake_result(px, pf)
        idx, hd = _select_front_member(None, None, r, {}, {}, None, None)  # cap=None -> exhaustive
    finally:
        _holdout.validate_holdout = _orig
    assert idx == 0, f"expected the extreme member 0 to be committed, got {idx}"
    assert r.best_x == winner, r.best_x
    assert hd["passed"] is True
    assert "PASSED holdout" in r.notes and "exhaustive=True" in r.notes
    # and a CAP that stops before rank 19 must NOT silently claim success
    _holdout.validate_holdout = fake_validate
    try:
        r2 = _fake_result(px, pf)
        idx2, _ = _select_front_member(None, None, r2, {}, {}, None, None, cap=5)
    finally:
        _holdout.validate_holdout = _orig
    assert idx2 != 0, "capped run should miss the rank-19 extreme"
    assert "TRUNCATED" in r2.notes
    print("OK exhaustive_reaches_low_ranked_extreme")


def test_degenerate_objective_excluded():
    # obj2 is CONSTANT (zero spread) -> must be excluded from minimax; ranking driven by obj1 only.
    # Member with the smallest obj1 is the minimax-min; make ONLY it pass and confirm rank 0.
    n = 8
    px = [[float(i)] for i in range(n)]
    pf = [[i / (n - 1), 5.0] for i in range(n)]  # obj2 constant
    winner = px[0]  # smallest obj1

    def fake_validate(ev, objs, best_x, spec, probe_x=None, band_ceilings=None, baseline_x=None):
        return {"passed": best_x == winner, "per_objective": []}

    _orig = _holdout.validate_holdout
    _holdout.validate_holdout = fake_validate
    try:
        r = _fake_result(px, pf)
        idx, hd = _select_front_member(None, None, r, {}, {}, None, None)
    finally:
        _holdout.validate_holdout = _orig
    assert idx == 0, f"degenerate obj2 must not perturb obj1-driven ranking; got rank for idx {idx}"
    assert hd["passed"] is True
    print("OK degenerate_objective_excluded")


if __name__ == "__main__":
    test_exhaustive_reaches_low_ranked_extreme()
    test_degenerate_objective_excluded()
    print("ALL PASS")
