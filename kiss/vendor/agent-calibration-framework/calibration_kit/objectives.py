"""Derive calibration OBJECTIVES from the model's dag.yaml — never hardcode NSE.

Per codex: keep the dag gate as HARD FEASIBILITY, then derive a SMALL number of
normalized losses from the gate-valid metric_families for the calibration targets.
Use Pareto (multi-objective) only when there's a real scientific trade-off; otherwise
scalarize a weighted sum. This avoids the granularity trap (one objective per
metric-per-site-per-window).

A "loss" is always something to MINIMIZE in [0, +inf), 0 == perfect.

Metrics dict may be FLAT (single scored var: {"nse":.., "pbias":..}) or VAR-SCOPED
(multi-target: {"TWSO": {"pbias":..}, "LAI": {"nse":..}}). Objective.loss reads the
var-scoped entry when present so multi-target calibrations don't collide on a shared
bare key (codex bug objectives.py:20).
"""
from __future__ import annotations
import math
from dataclasses import dataclass

# metric_family -> (metric key to read, function mapping metric value to a [0,inf) loss)
_FAMILY_LOSS = {
    "temporal_pattern_match": ("nse",   lambda v: max(0.0, 1.0 - v)),
    "magnitude_accuracy":     ("pbias", lambda v: abs(v) / 100.0),
    "trend_match":            ("trend_error", lambda v: abs(v)),
    "timing_accuracy":        ("day_bias", lambda v: abs(v) / 30.0),
    "spatial_pattern_match":  ("csi",   lambda v: max(0.0, 1.0 - v)),
    "ranking_quality":        ("spearman", lambda v: max(0.0, 1.0 - v)),
}

# Which families answer "did we get the STRUCTURE/PATTERN right" (shape, timing,
# spatial correspondence, ranking, trend) vs "is the MAGNITUDE/bias right". This is
# the gate-driven generalization of "check r first": calibration can move magnitude
# but CANNOT fix a wrong pattern — a failing pattern family is a STRUCTURAL/setup
# problem (the self-improve loop's job), not a tuning one. Both sets are subsets of
# the dag's declared metric_families for a (var, obs_shape) — we never invent a family
# the dag didn't sanction.
PATTERN_FAMILIES = frozenset({"temporal_pattern_match", "spatial_pattern_match",
                              "ranking_quality", "timing_accuracy", "trend_match"})
MAGNITUDE_FAMILIES = frozenset({"magnitude_accuracy"})


def family_losses(valid_families, metrics_for_var, metric_overrides=None):
    """Map each gate-valid family to (normalized_loss|None, metric_key, raw_value).
    Loss is None when the run didn't report that family's metric. Only families the
    dag declared (valid_families) AND that we know how to score are considered.

    `metric_overrides` (2026-06-29): the per-obs DETERMINING metric carried by the gate /
    model_obs_map — e.g. {'temporal_pattern_match': 'r'} for soil moisture (R is the headline),
    instead of the hardcoded default 'nse'. The loss_fn (1 - v) is identical for any higher-is-
    better pattern metric (NSE/R/KGE/CSI/Spearman), so swapping the metric_key is sound."""
    out = {}
    mo = {k: str(v).lower() for k, v in (metric_overrides or {}).items() if v}
    for fam in valid_families:
        if fam not in _FAMILY_LOSS:
            continue
        key, fn = _FAMILY_LOSS[fam]
        if fam in mo:
            key = mo[fam]                       # honor the resolved determining metric
        v = (metrics_for_var or {}).get(key)
        loss = None
        if v is not None:
            try:
                loss = float(fn(float(v)))
            except (TypeError, ValueError):
                loss = None
        out[fam] = (loss, key, v)
    return out


def calibration_verdict(valid_families, metrics_for_var,
                        pattern_tol: float = 0.5, mag_tol: float = 0.1,
                        metric_overrides=None) -> dict:
    """GATE-DRIVEN 'is it calibration time' for ONE variable, using ONLY the dag's
    declared metric_families for this (var, obs_shape). Decision:

      * any PATTERN family with a known loss > pattern_tol  -> "structural"
        (the pattern/shape/timing is wrong — setup/code problem, NOT calibration).
      * else, a PATTERN family is observed-passing AND a MAGNITUDE family loss > mag_tol
        -> "calibrate" (structure is right, only level/bias needs tuning).
      * a MAGNITUDE family is off but NO pattern family is observed-passing
        -> "undetermined" (can't confirm structure is sound; don't fire blindly).
      * nothing failing -> "adequate".
      * no scorable families at all -> "undetermined".

    pattern_tol=0.5 means e.g. NSE>=0.5 / CSI>=0.5 / Spearman>=0.5 "pattern aligned"
    (the family-general form of r>=0.5); mag_tol=0.1 means |PBIAS|<=10% "adequate".
    Returns {decision, families:{fam:{loss,metric,value}}, why}."""
    fl = family_losses(valid_families, metrics_for_var, metric_overrides=metric_overrides)
    fam_view = {f: {"loss": fl[f][0], "metric": fl[f][1], "value": fl[f][2]} for f in fl}
    pattern = {f: fl[f] for f in fl if f in PATTERN_FAMILIES}
    mag = {f: fl[f] for f in fl if f in MAGNITUDE_FAMILIES}

    failing_pattern = [f for f, (loss, *_ ) in pattern.items()
                       if loss is not None and loss > pattern_tol]
    if failing_pattern:
        return {"decision": "structural", "families": fam_view,
                "why": f"pattern family/families {failing_pattern} above tol={pattern_tol} "
                       f"— structure/shape wrong; fix the KI, do not calibrate"}

    observed_pattern_pass = [f for f, (loss, *_ ) in pattern.items()
                             if loss is not None and loss <= pattern_tol]
    failing_mag = [f for f, (loss, *_ ) in mag.items()
                   if loss is not None and loss > mag_tol]

    if failing_mag and observed_pattern_pass:
        return {"decision": "calibrate", "families": fam_view,
                "why": f"pattern OK ({observed_pattern_pass}) but magnitude {failing_mag} "
                       f"above tol={mag_tol} — calibration territory"}
    if failing_mag and not observed_pattern_pass:
        return {"decision": "undetermined", "families": fam_view,
                "why": f"magnitude {failing_mag} off but no pattern family is "
                       f"observed-passing — can't confirm structure; don't fire"}
    if not fam_view or all(v["loss"] is None for v in fam_view.values()):
        return {"decision": "undetermined", "families": fam_view,
                "why": "no scorable gate-valid families reported"}
    return {"decision": "adequate", "families": fam_view,
            "why": "all observed gate-valid families within tolerance"}


@dataclass
class Objective:
    name: str                 # e.g. "TWSO:magnitude_accuracy"
    var: str                  # dag output var
    family: str               # gate-valid metric_family
    metric_key: str           # which key to read from the metrics dict
    weight: float = 1.0       # already split across a var's families (codex :58)

    def _metrics_for_var(self, metrics: dict) -> dict:
        # var-scoped dict wins (multi-target); else the flat dict is this var's metrics
        if isinstance(metrics, dict) and isinstance(metrics.get(self.var), dict):
            return metrics[self.var]
        return metrics or {}

    def loss(self, metrics: dict) -> float:
        m = self._metrics_for_var(metrics)
        v = m.get(self.metric_key)
        if v is None:
            return float("inf")
        _, fn = _FAMILY_LOSS[self.family]
        try:
            fv = float(v)
            # a NON-FINITE metric (nan/inf) is INFEASIBLE, never "perfect": e.g. nse=nan would
            # give max(0,1-nan)=0.0 and be scored as a perfect calibration (and cached). Guard it.
            if not math.isfinite(fv):
                return float("inf")
            r = float(fn(fv))
            return r if math.isfinite(r) else float("inf")
        except (TypeError, ValueError):
            return float("inf")


def objectives_from_dag(dag: dict, targets: list[dict] | None,
                        obs_shape_by_var: dict[str, str],
                        metric_overrides=None) -> list[Objective]:
    """Build the objective list from dag.outputs[var].observability for the chosen
    obs_shape per var. `targets` (from calibration.yaml) selects vars + weights;
    if None, use all observable outputs. The obs_shape per var comes from the
    model_obs_map join (the same obs_shape the gate scores).

    Codex fixes:
      :58  a target's weight is SPLIT across its derived families (not copied to each),
           so a var with 3 families doesn't get 3x the influence of a 1-family var.
      :62  the obs_shape MUST match explicitly; we never fall back to the first shape
           by file order. A var with no matching/declared shape is SKIPPED (and if all
           are skipped the caller sees an empty list -> no_objectives).
    """
    objs: list[Objective] = []
    outs = {o.get("var"): o for o in (dag.get("outputs") or []) if isinstance(o, dict)}
    chosen = (targets or [{"var": v, "weight": 1.0} for v in outs])
    for t in chosen:
        var = t["var"]; w = float(t.get("weight", 1.0))
        o = outs.get(var)
        if not o:
            continue
        shape = obs_shape_by_var.get(var)
        if not shape:
            # The contract may target a dag var whose NAME differs from the scored var
            # recorded by self-improve (var aliasing — e.g. MODFLOW 'hydraulic_head' vs
            # 'water_table_elevation', both point_time_series). If the case recorded ONE
            # unambiguous obs_shape, apply it here; the explicit comparable-shape match
            # below still guards it (a var that doesn't declare that shape is skipped),
            # so this never guesses across DISTINCT shapes (codex :62 stays honored).
            _shapes_seen = set(obs_shape_by_var.values())
            if len(_shapes_seen) == 1:
                shape = next(iter(_shapes_seen))
            else:
                continue
        shapes = (o.get("observability") or {}).get("comparable_obs_shapes", [])
        match = next((s for s in shapes if s.get("obs_shape") == shape), None)
        if not match:
            continue
        fams = [f for f in (match.get("metric_families") or []) if f in _FAMILY_LOSS]
        if not fams:
            continue
        w_each = w / len(fams)        # split the target weight across its families
        mo = {k: str(v).lower() for k, v in (metric_overrides or {}).items() if v}
        for fam in fams:
            key, _ = _FAMILY_LOSS[fam]
            # honor the per-obs DETERMINING metric (codex gap #2, 2026-06-29): an r-determined
            # case must optimize r, not the family-default nse. The loss fn (1-v) is identical for
            # any same-direction pattern metric, so swapping only the metric_key is sound.
            if fam in mo:
                key = mo[fam]
            objs.append(Objective(name=f"{var}:{fam}", var=var, family=fam,
                                  metric_key=key, weight=w_each))
    return objs


def scalarize(objs: list[Objective], metrics: dict) -> float:
    """Weighted-sum scalar loss for single-objective backends (DDS/SCE-UA)."""
    if not objs:
        return float("inf")
    total = sum(o.weight for o in objs) or 1.0
    return sum(o.weight * o.loss(metrics) for o in objs) / total
