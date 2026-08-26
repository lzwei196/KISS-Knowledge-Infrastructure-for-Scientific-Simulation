"""The shared model-agnostic EVALUATOR: parameter vector -> dag-valid metrics.

The ONE per-model integration surface. Reuses the self-improve KI's machinery:
applicator.write_param to set parameters, the KI run path (run_model) to run+score,
and objectives to turn metrics into losses. The optimizer only sees
Problem.evaluate(x) -> losses; everything model-specific lives here. evaluate()
NEVER raises into the optimizer — a failed/infeasible run returns +inf losses.
"""
from __future__ import annotations
import contextlib as _contextlib
import math
import os
import threading as _threading
from dataclasses import dataclass, field
from pathlib import Path
from .applicator import write_param, read_param
from .objectives import Objective


#: the ONLY authoritative explicit splits — exactly what holdout.py sets for its two comparison runs.
VALID_SPLITS = ("calibration", "holdout")
#: IN-PROCESS split authority (codex round-4). Provenance must NOT itself be an env value: a parent
#: carrying both KDT_CALIB_SPLIT=holdout AND an owner sentinel would be inherited and trusted, letting
#: commissioning/screen/DDS score the VALIDATION window. Authority is therefore a thread-local flag that
#: only the `split_authority()` context manager sets — it cannot cross a process boundary.
_AUTH = _threading.local()


def _authority_active() -> bool:
    return getattr(_AUTH, "active", False)


@_contextlib.contextmanager
def split_authority(split: str):
    """The ONLY legitimate way to direct a run's split (holdout validation, reference replay). Sets
    IN-PROCESS authority + the KDT_CALIB_SPLIT env the subprocess runner reads, and restores both."""
    prev_flag = _authority_active()
    prev_env = os.environ.get("KDT_CALIB_SPLIT")
    _AUTH.active = True
    os.environ["KDT_CALIB_SPLIT"] = split
    try:
        yield
    finally:
        _AUTH.active = prev_flag
        if prev_env is None:
            os.environ.pop("KDT_CALIB_SPLIT", None)
        else:
            os.environ["KDT_CALIB_SPLIT"] = prev_env


def split_is_authoritative(env_value) -> bool:
    """True only inside a `split_authority(...)` block AND for a valid value. An inherited env — even
    KDT_CALIB_SPLIT=holdout with any sentinel — is NOT authoritative across a process boundary."""
    return _authority_active() and (env_value or "").strip().lower() in VALID_SPLITS


def resolve_train_split(env_value) -> str:
    """Resolve the split a run must score. ONLY a holdout-validator-stamped split wins (provenance, not
    just a valid value); unset, blank, 'full', garbage, OR a stale inherited 'calibration'/'holdout'
    without the owner sentinel all fall back to "calibration". Trusting the value alone let a stale env
    make the screen/commissioning/DDS score the FULL record (or worse, the VALIDATION window) — exactly
    the contamination this contract exists to prevent."""
    if split_is_authoritative(env_value):
        return (env_value or "").strip().lower()
    return "calibration"


def decode_value(param: dict, xi, inv_fn) -> object:
    """Single source of truth for search-vector -> model-value decode (codex
    calib.py:198): inverse-transform, then type-quantize (int round / bool
    threshold). Used for BOTH scoring and the final best-apply so the workdir is
    never left at a raw float that was never actually evaluated."""
    v = inv_fn(xi)
    t = param.get("type", "continuous")
    if t == "integer":
        return int(round(v))
    if t == "bool":
        return bool(v > 0.5)
    return v


@dataclass
class Evaluator:
    ki_path: str
    workdir: str
    parameters: list[dict]
    objectives: list[Objective]
    transform_inv: dict
    run_model: callable
    constraints_ok: callable | None = None
    base_seed: int = 0
    injection_mode: str = "applicator"   # "applicator" (kit writes via addresses) | "runner" (calib_run.py injects)
    param_rtol: float = 1e-6
    expected_case_id: str | None = None   # if set, the runner's __kdt__.case_id MUST match (fail-closed on a
    #                                       DECLARED-but-mismatched case — the deterministic wrong-gauge guard)
    fixed_params: dict = field(default_factory=dict)  # inactive params frozen at default (staged rounds) —
    #                                                   merged into every candidate so constraints + the runner
    #                                                   payload see them, and they aren't silently unfrozen.
    _originals: dict = field(default_factory=dict)
    _eval_id: int = 0
    _verify_fail: int = 0
    _wrong_case: str | None = None        # set to the runner-declared case_id when it != expected_case_id
    _metrics_cache: dict = field(default_factory=dict)   # (param vector, split) -> metrics (resumability)
    _last_metrics: dict = field(default_factory=dict)     # split -> most-recent full metrics (for the correlation floor)

    def __post_init__(self):
        # Persistent EVAL CACHE (resumability — time is never a constraint): a long real-binary
        # calibration must survive interruption, so every COMPLETED eval is cached by (param
        # vector, split); a restart fast-forwards over cached evals instead of re-running the
        # model (a deterministic optimizer re-proposes the same vectors -> all hits until it
        # reaches where it stopped). Also dedups repeated candidates within a single run.
        import json as _json, re as _re, hashlib as _hl
        # SCOPE the cache by CASE + SETUP fingerprint so cached metrics are never reused for a
        # different case OR after the driver/contract changed (Codex): case flip (VIC tangnaihai
        # vs harbin) via KDT_CALIB_CASE_TAG; setup drift via a hash of calibration.yaml +
        # tools/calib_run.py contents — edit either and the fingerprint changes -> fresh cache,
        # stale metrics ignored. Absent tag -> single-case default (backward compatible).
        _tag = _re.sub(r"[^A-Za-z0-9]+", "_", os.environ.get("KDT_CALIB_CASE_TAG", "")).strip("_")
        _fp = _hl.sha1()
        # SPLIT-CONTRACT VERSION (codex 2026-07-19): the fingerprint must also namespace the
        # TRAIN-SPLIT semantics, not just the contract files. Before v2 the optimizer ran with
        # KDT_CALIB_SPLIT unset (= the runner's FULL record) while _cache_key() normalized a falsy
        # split to "calibration" — so pre-v2 FULL-period metrics sit under the very key v2 uses for
        # calibration-split metrics and would be replayed as if they were in-window. Bumping this
        # constant retires every pre-v2 cache file instead of silently reusing contaminated entries.
        _fp.update(b"split-contract-v2:train=calibration")
        for _rel in ("calibration.yaml", "tools/calib_run.py"):
            try:
                _fp.update(Path(self.ki_path, _rel).read_bytes())
            except Exception:
                _fp.update(b"\x00")
        _setup = _fp.hexdigest()[:10]
        self._cache_file = Path(self.workdir) / (
            f"eval_metrics_cache_{_tag}_{_setup}.jsonl" if _tag else f"eval_metrics_cache_{_setup}.jsonl")
        try:
            if self._cache_file.is_file():
                for line in self._cache_file.read_text().splitlines():
                    try:
                        rec = _json.loads(line)
                        self._metrics_cache[rec["key"]] = rec["metrics"]
                    except Exception:
                        continue
        except Exception:
            pass
        # applicator mode: snapshot original values so restore_originals() can undo candidate writes if the
        # calibration fails. runner mode: no applicator addresses to snapshot — the runner owns injection in
        # a fresh candidate workdir, so there is nothing central to restore.
        if self.injection_mode != "applicator":
            return
        for p in self.parameters:
            try:
                self._originals[p["name"]] = read_param(p["address"], self.workdir)
            except Exception:
                self._originals[p["name"]] = None

    def restore_originals(self):
        if self.injection_mode != "applicator":
            return
        for p in self.parameters:
            v = self._originals.get(p["name"])
            if v is not None:
                try:
                    write_param(p["address"], v, self.workdir)
                except Exception:
                    pass

    def _verify_applied(self, named: dict, metrics: dict):
        """RUNNER mode: the params we requested MUST equal what calib_run.py reports it applied
        (`__kdt__.applied_params`), else the metrics describe a model that never actually changed.
        FAIL-CLOSED: EVERY param we handed the runner (active + any staged-frozen defaults) MUST
        be echoed and match — an incomplete echo could hide a misapplied frozen value, so a
        driver that omits a handed param is rejected (#5; the calib-dev prompt requires echoing
        all of KDT_CALIB_PARAMS). We allow the runner to echo EXTRA keys (ignored). In NON-staged
        mode fixed_params is empty, so `named` is exactly the optimized params. Rejects
        non-finite / clamp-to-0; math.isclose with a tiny rel_tol. (File-level proof; the
        did-the-run-consume-it proof is responsiveness_check.) Returns (ok, reason)."""
        meta = (metrics or {}).get("__kdt__") or {}
        applied = meta.get("applied_params")
        if not isinstance(applied, dict):
            return False, "runner did not echo __kdt__.applied_params"
        missing = set(named) - set(applied)              # every handed param must be echoed
        if missing:
            return False, (f"runner did not echo param(s) {sorted(missing)} it was handed "
                           "(echo ALL of KDT_CALIB_PARAMS in __kdt__.applied_params, incl. frozen)")
        for name, want in named.items():
            got = applied.get(name)
            try:
                fg, fw = float(got), float(want)
                if not (math.isfinite(fg) and math.isfinite(fw)):
                    return False, f"{name} non-finite (applied={got!r}, requested={want!r})"
                if fw != 0.0 and fg == 0.0:     # a non-zero request clamped to 0 is NOT "close" (Codex re-review)
                    return False, f"{name} clamped to 0 (requested {want})"
                if not math.isclose(fg, fw, rel_tol=self.param_rtol, abs_tol=0.0):
                    return False, f"{name} applied {got} != requested {want}"
            except (TypeError, ValueError):
                if str(got) != str(want):
                    return False, f"{name} applied {got!r} != requested {want!r}"
        return True, "ok"

    def _runner_gate(self, named, metrics) -> bool:
        """Runner-mode FAIL-CLOSED gate applied to EVERY trusted metrics payload — a fresh run AND a
        CACHE HIT (codex 2026-07-18: a cache hit must not bypass these checks, else a legacy/wrong-case
        cached payload is reused). (a) every handed param must be echoed in __kdt__.applied_params and
        match; (b) when a case is pinned, __kdt__.case_id MUST be present and equal. Records the failure
        (_verify_fail / _wrong_case) and returns False when the payload can't be trusted."""
        if self.injection_mode != "runner":
            return True
        ok, _reason = self._verify_applied(named, metrics)
        if not ok:
            self._verify_fail += 1
            return False
        if self.expected_case_id:
            _declared = ((metrics or {}).get("__kdt__") or {}).get("case_id")
            if _declared is None:
                self._wrong_case = "<undeclared>"      # pinned case but runner omitted case_id
                return False
            if str(_declared) != str(self.expected_case_id):
                self._wrong_case = str(_declared)
                return False
        return True

    def _named(self, x):
        # Typed decode via the shared helper so scoring and best-apply agree. Frozen inactive params
        # (staged rounds) are merged in FIRST so constraints that reference them and the runner payload
        # both see them; the active candidate values override.
        named = dict(self.fixed_params)
        named.update({p["name"]: decode_value(p, xi, self.transform_inv.get(p["name"], lambda v: v))
                      for p, xi in zip(self.parameters, x)})
        return named

    def _cache_key(self, named, split):
        """Stable key for (param vector, split). 10 sig figs so the round-tripped param
        value hashes identically across runs; split matters (calibration vs holdout metrics)."""
        import hashlib, json as _json
        payload = {"p": {k: (f"{float(v):.10g}" if isinstance(v, (int, float)) and not isinstance(v, bool)
                             else str(v)) for k, v in sorted(named.items())},
                   "split": split or "calibration"}
        return hashlib.sha1(_json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def _store_cache(self, key, metrics):
        self._metrics_cache[key] = metrics
        try:
            import json as _json
            with open(self._cache_file, "a") as fh:
                fh.write(_json.dumps({"key": key, "metrics": metrics}, default=str) + "\n")
        except Exception:
            pass

    def evaluate(self, x) -> list[float]:
        """Apply x -> run -> score. Returns one loss per objective (minimize).
        +inf on infeasible/failed (never raises into the optimizer)."""
        try:
            named = self._named(x)
            # hard feasibility BEFORE any run (cheap) — codex C5
            if self.constraints_ok and not self.constraints_ok(named):
                return [float("inf")] * len(self.objectives)
            # RESUMABILITY: reuse a completed real-model eval for this (param vector, split).
            # A restart of a long calibration fast-forwards over cached evals; also dedups
            # repeated candidates within a run. Only SUCCESSFUL evals are cached (below).
            # TRAIN ON THE CALIBRATION SPLIT (2026-07-19). holdout.py sets KDT_CALIB_SPLIT explicitly for
            # its two comparison runs; NOTHING set it for the screen/DDS, so with it UNSET a runner scored
            # its FULL record — the optimizer was fitting params on data that INCLUDES the holdout years,
            # making the holdout gate contaminated rather than out-of-sample. Default (only when unset) to
            # "calibration" so training and validation are genuinely disjoint.
            # Only holdout.py's explicit "calibration"/"holdout" is authoritative. Unset, blank, or an
            # inherited "full" resolves to "calibration" and WE own the env for this run (codex round-2).
            _env_raw = os.environ.get("KDT_CALIB_SPLIT")
            _split = resolve_train_split(_env_raw)
            _we_own_split = not split_is_authoritative(_env_raw)
            _ck = self._cache_key(named, _split)
            _hit = self._metrics_cache.get(_ck)
            if _hit is not None:
                # a cache hit is a trusted metrics payload -> it MUST pass the same runner-mode gate
                # as a fresh run (applied-params echo + pinned-case declaration). A legacy/invalid
                # cached entry fails closed (+inf) instead of silently bypassing the guard.
                if not self._runner_gate(named, _hit):
                    return [float("inf")] * len(self.objectives)
                self._last_metrics[_split] = _hit
                return [o.loss(_hit) for o in self.objectives]
            if self.injection_mode == "runner":
                # DELEGATED injection: hand the candidate vector to calib_run.py (via a params file +
                # env), which injects them the model's own way and echoes __kdt__.applied_params.
                import json
                pf = Path(self.workdir) / "kdt_params.json"
                pf.write_text(json.dumps(named, default=str))
                os.environ["KDT_CALIB_PARAMS"] = str(pf)
            else:
                for p in self.parameters:
                    write_param(p["address"], named[p["name"]], self.workdir)
            # Reproducibility: expose a per-eval seed + id so STOCHASTIC runners/models
            # can be deterministic (codex evaluator.py:31). Subprocess runners inherit
            # the env; python/detached runners can read it.
            # carry the resolved split into the runner subprocess (it scores FULL when unset/blank/'full')
            if _we_own_split:
                os.environ["KDT_CALIB_SPLIT"] = _split
            self._eval_id += 1
            os.environ["KDT_CALIB_EVAL_ID"] = str(self._eval_id)
            os.environ["KDT_CALIB_SEED"] = str(self.base_seed)
            try:
                metrics = self.run_model()
            finally:
                os.environ.pop("KDT_CALIB_PARAMS", None)   # never leak this eval's params into a later run
                if _we_own_split:                          # restore EXACTLY what was there (blank stays
                    if _env_raw is None:                   # blank, 'full' stays 'full')
                        os.environ.pop("KDT_CALIB_SPLIT", None)
                    else:
                        os.environ["KDT_CALIB_SPLIT"] = _env_raw
            if not metrics:
                return [float("inf")] * len(self.objectives)
            # FAIL-CLOSED runner-mode gate (applied-params echo + pinned-case declaration), applied
            # identically here and on cache hits above via _runner_gate.
            if not self._runner_gate(named, metrics):
                return [float("inf")] * len(self.objectives)
            self._last_metrics[_split] = metrics   # expose full metrics (incl. r) for the correlation floor
            # CACHE the completed real-model eval (resumability + intra-run dedup) — but ONLY when
            # every objective loss is FINITE (Codex): a truthy-but-non-finite metrics payload
            # (e.g. nan/missing key) would otherwise freeze a transient bad result into the cache
            # and be replayed forever on restart. A failed/non-finite eval must be retried, never cached.
            losses = [o.loss(metrics) for o in self.objectives]
            if all(math.isfinite(l) for l in losses):
                self._store_cache(_ck, metrics)
            return losses
        except Exception:
            return [float("inf")] * len(self.objectives)

    def responsiveness_check(self, x_default, lower, upper, min_rel_move: float = 1e-6):
        """One-time COMMISSIONING proof (esp. runner mode): round-trip proves the value was WRITTEN;
        this proves the scored run actually CONSUMED it. Perturbs ONE param at a time (a single all-params
        corner false-fails on compensation/saturation/infeasible corners) to an interior point; the model is
        RESPONSIVE if ANY finite perturbation materially moves ANY objective. Returns
        (responsive: bool|None, detail): None = inconclusive (don't hard-fail), not unresponsive."""
        l0 = self.evaluate(x_default)
        if any(math.isinf(v) for v in l0):
            return None, "default vector infeasible — inconclusive"
        n_moved = n_tested = 0
        for i in range(len(x_default)):
            mid = (lower[i] + upper[i]) / 2.0
            xp = list(x_default)
            # perturb to the FAR bound — guarantees a decoded-value change even for bool / small-int params
            # (a half-span step can round back to the same int or bool → false 'unresponsive'; Codex re-review).
            xp[i] = upper[i] if x_default[i] <= mid else lower[i]
            if xp[i] == x_default[i]:            # degenerate (zero-width range) — can't perturb this param
                continue
            li = self.evaluate(xp)
            if any(math.isinf(v) for v in li):
                continue                                   # bad corner for this param → skip (inconclusive)
            n_tested += 1
            scale = max(1.0, max(abs(v) for v in l0 + li))
            if max(abs(a - b) for a, b in zip(l0, li)) > min_rel_move * scale:
                n_moved += 1
        if n_tested == 0:
            return None, "all single-param perturbations infeasible — inconclusive"
        return (n_moved > 0), f"{n_moved}/{n_tested} params moved an objective"
