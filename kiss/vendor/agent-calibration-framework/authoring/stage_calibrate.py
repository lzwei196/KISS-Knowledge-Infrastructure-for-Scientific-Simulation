"""stage_calibrate — the self-improve KI <-> calibration-kit integration.

Runs AFTER a model has been made to RUN CORRECTLY and validated (the loop's job).
This stage tunes the model's PARAMETERS to fit its dag-defined obs:

  A. DEVELOP calibration capability (if missing): a calib-dev agent authors, into
     the model's KI, a `calibration.yaml` contract (params + addresses + ranges +
     runner + holdout) and a `tools/calib_run.py` (programmatic run-with-current-
     params -> metrics dict, honoring KDT_CALIB_SPLIT for holdout). This is "the
     calibration dev capability added to the model's KI". The new tool is gated by
     the SAME independent codex review as any other tool-build.
  B. RUN the calibration engine (calibration_kit.calib.calibrate): the contract's
     runner is the per-eval run+score; an optimizer (DDS default / NSGA-II multi-obj
     / BoTorch surrogate for expensive) searches; best params are applied back.
  C. GATE on the holdout: only a holdout-PASS calibration is promotable; the report
     carries best_params + improved metric + holdout verdict.

Opt-in via env KDT_CALIBRATE=1 so it never disturbs the existing pipeline. Lazy
imports of orchestrator helpers avoid a circular import.
"""
from __future__ import annotations
import os
import sys
import json
import datetime
from pathlib import Path


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _agent_timeout(default_s: int = 7200) -> int:
    """Wall-clock cap for a capability-dev / repair AGENT. TIME IS NOT A CONSTRAINT when developing a
    KI's calibration capability (user directive): a complex model (SWAT+ TxtInOut/HRUs, coupled chains)
    legitimately needs longer than the old hard-coded 1800s, and a timeout there throws away a nearly
    finished authoring pass (observed: 1.8 MB of stream discarded at the 30-min wall, then a full retry
    from scratch). Default 2 h; override with KDT_CALIB_AGENT_TIMEOUT_S (0/unset-invalid -> default)."""
    v = os.environ.get("KDT_CALIB_AGENT_TIMEOUT_S", "")
    try:
        n = int(v)
        return n if n > 0 else default_s
    except (TypeError, ValueError):
        return default_s

# make the sibling calibration_kit importable
_KDT_ROOT = str(Path(__file__).resolve().parent.parent)
if _KDT_ROOT not in sys.path:
    sys.path.insert(0, _KDT_ROOT)


def enabled() -> bool:
    return os.environ.get("KDT_CALIBRATE", "") in ("1", "true", "yes")


CALIB_DEV_PROMPT = """# Calibration-Capability Dev Agent: {model_id}

The model already RUNS CORRECTLY and was validated (metric below). Your job is to
add CALIBRATION capability to its KI so a generic optimizer can tune its parameters
to better fit the dag-defined obs. Author TWO files into the KI and nothing else.

## TARGET CASE — you MUST build for THIS gauge/obs (not another site)
{case_block}
CRITICAL: the KI's SKILL.md / docs may showcase a DIFFERENT validated site (a worked
example on another basin). You must calibrate the case named above, scoring ITS gauge/obs.
Find this case's OWN run recipe by matching the case_id/obs to the model's run scripts and
staged outputs (e.g. grep the model dir for the case name; the case's already-produced
upstream inputs — forcing / land-model runoff / delineation — are typically staged under
`outputs/<case>*/`). If you cannot locate this case's inputs/recipe, return a BLOCKER that
names exactly what's missing — do NOT silently fall back to a different site that happens to
be runnable. Scoring the wrong gauge is a FAILED capability, not a success.

## Validated run (what calibration must reproduce + improve)
- KI: {ki_path}
- dag.yaml outputs + the obs it was scored against (read dag.yaml + SKILL.md).
- Prior validated metric: {prior_metric}
- The run+score recipe the loop already used: read real_case_result.json / the KI's
  run tool(s). Calibration must run the SAME model+obs, just with varied parameters.

## 1) `{ki_path}/calibration.yaml` — the contract
Follow calibration_kit/CALIBRATION_YAML_SCHEMA.md EXACTLY. Declare a POOL of the
plausibly-relevant CALIBRATABLE parameters. SEED THE POOL FROM THE DAG's influence
edges (`{ki_path}/dag.yaml` → influence.edges): the edges with `sensitivity_grade`
HIGH/MEDIUM are the params the model's OWN sensitivity-analysis literature already
identified as controlling — carry them + their `citations` into each param's `cite`
(literature is the PRIOR; the kit's Morris screen confirms on THIS site, and residual
params stay screenable — never pruned). Include the parameters that could control the
model's error mode, NOT just an arbitrary 3-4;
e.g. if a volume bias is the issue, include the recharge/baseflow lever even if it
lives in a different input file).

### PARAMETER RANGES MUST BE GROUNDED IN THE MODEL'S OWN DOCUMENTATION / LITERATURE — not guessed
A guessed-wide range is the #1 cause of a `screen_failed` calibration: the sensitivity screen samples the
BOX CORNERS, and a bound outside the model's physically-valid region makes the model CLAMP the value
(e.g. a depth/width multiplier that pushes a channel below the model's HMIN/WMIN floor, or a Manning's n
past its stable band). A clamped value ≠ the requested value, so the runner's read-back guard rejects the
eval → the whole screen returns no finite metrics. DERIVE each range from sources, in this order:
  1. The model's OFFICIAL documentation/manual — read the KI's `docs/REFERENCES.md` for the manual URL +
     key papers, any manual shipped on disk (e.g. under the model package's `doc/`), and `docs/
     gathered_papers.json` / `docs/papers_index.md`. These give the parameter's PHYSICAL bounds + the
     model's internal floors/ceilings (HMIN, WMIN, valid Manning band, empirical W=WC·Q^WP / H=HC·Q^HP
     coefficients, etc.).
  2. The dag.yaml param `notes` + `citations` — they often already state the default, the floor, and the
     coefficient the model uses.
  3. Peer calibration studies (the KI's gathered papers) — the range other studies actually VARIED the
     parameter over is the calibration range; use it.
Set `range: [lo,hi]` = the LITERATURE calibration range, kept STRICTLY INSIDE the model's clamp-free,
physically-valid region (so the value applies EXACTLY at both bounds). Put the source in each param's `cite`.
If the literature gives no range for a lever, bound it conservatively around the documented default so it
never trips the model's floors. VERIFY in COMMISSIONING (below) that the param reads back == requested at
BOTH range bounds — a bound that clamps is WRONG; tighten it.

For each parameter capture:
  name, type, units, range [lo,hi] (literature-grounded + clamp-free, see above), default, transform,
  scope (+ zone_key if not global). In APPLICATOR mode also give each param an edit
  `address` (yaml_path / json_path / ini_key / text_token / table_cell / namelist —
  the GENERIC formats; pointing at the EXACT token; may use different files per param).
  In RUNNER mode `address` is OPTIONAL documentation — calib_run.py injects via
  `KDT_CALIB_PARAMS` (use runner mode for model-specific formats: modflow_pkg / swmm_inp /
  api, or when the KI regenerates its inputs each run).
  `targets` = the dag output var(s) you calibrate toward (the variable the FORCED obs
  of THIS run measures — score THAT gauge/site, not a different validated one).
  `runner`: kind=subprocess, command runs `tools/calib_run.py` (below) -> metrics JSON.
  `strategy`: cost_class, max_evaluations, a MANDATORY `holdout` (years|sites|regions,
  fraction), `staged: true` (+ optional staged_start / staged_step) so the kit does
  sensitivity-screen -> calibrate-few -> escalate, and Constraints if params have ordering relations.
  OPTIMIZER — you must REASON this choice from THIS problem; do NOT default. Set BOTH
  `default_algorithm` AND a 1-2 sentence `algorithm_rationale` that justifies it from the
  parameter dimensionality (count), the `cost_class` (cheap/moderate/expensive per eval),
  the objective structure implied by your `targets` (single- vs multi-objective), and whether
  posterior UNCERTAINTY / parameter intervals are the goal. Options:
    - `dds`   — cheap, smooth / low-gradient SINGLE-objective search (few params, tight budget)
    - `sceua` — rugged / MULTIMODAL single-objective response surface
    - `dream` — when posterior UNCERTAINTY / parameter intervals are wanted (single-objective, Bayesian)
    - `nsga2` — MULTI-OBJECTIVE: when `targets` span >=2 distinct variables (Pareto trade-off)
  The `algorithm_rationale` is a REQUIRED audit record of your reasoning — write why THIS
  optimizer fits THIS problem, not a generic description. The choice must be yours, grounded
  in the above — never a fixed default.
  NOTE: the kit auto-keeps only the metric families your runner actually emits, so
  it's fine if the dag declares an extra family (e.g. timing) you don't compute.

## 2) `{ki_path}/tools/calib_run.py` — programmatic run+score (NOT an agent)
`python calib_run.py --workdir <wd> --out <metrics.json>`. It MUST run the model via the KI's
EXISTING run tools (reuse them; NEVER reimplement the model), compute the gate-valid metrics
(nse/kge/pbias — the same the dag gates on; ki_tools_common.metrics.all_metrics if available), and
write them as JSON to --out. On any failure: write nothing / exit nonzero (a missing metrics file =
+inf, never a fake pass). Honor env KDT_CALIB_SPLIT ("calibration"|"holdout") to score the right
subset (if it can't split, score both — the kit marks holdout inconclusive, which is correct). Keep
it FAST — called 100s of times in a FRESH per-candidate workdir; do NOT re-download/re-setup per eval
(that is a one-time prepare step).

### Parameter injection depends on `injection.mode` in calibration.yaml:
- **applicator mode (default):** the kit has ALREADY written this candidate's params into the inputs
  (via each param's `address`). calib_run.py just READS the current inputs and runs. Use this ONLY when
  the model consumes stable files directly.
- **runner mode (required if the KI REGENERATES its inputs each run, or params live in a model-specific
  format — MODFLOW/SWMM/API):** the kit did NOT write params. calib_run.py MUST:
    1. read the candidate vector from the JSON at env `KDT_CALIB_PARAMS` ({{"name": value, ...}});
    2. INJECT each value the model's OWN way (native lib — flopy for MODFLOW, pyswmm for SWMM — or KI
       tools), AFTER any input-regeneration step so it isn't overwritten;
    3. read each value BACK from the effective artifact the model consumes; if any can't be written+read,
       exit nonzero with NO metrics;
    4. include a reserved block in the output JSON:
       `"__kdt__": {{"applied_params": {{"name": <value you actually applied>, ...}},
                    "case_id": "<the TARGET CASE case_id above>",
                    "scored_obs": "<the gauge/obs id + file you scored against>"}}` — the kit diffs
       requested vs applied EVERY eval and scores +inf on any mismatch (a non-injecting runner is never trusted).
       ECHO EVERY param you were handed — i.e. ALL keys present in the KDT_CALIB_PARAMS JSON, including any held
       at their default (staged rounds hand you frozen params too); omitting a handed key fails the eval closed.
       The `case_id` / `scored_obs` fields SELF-DECLARE which gauge this eval scored — they MUST name the TARGET
       CASE gauge above, so scoring the wrong site is detectable (a mismatch is a FAILED capability).
       CRITICAL — the declaration must be HONEST, not a hardcoded label:
         * PIN the scored gauge/obs to the TARGET CASE. Do NOT read the gauge/obs/lat/lon/area from
           overridable env vars that could redirect scoring to a DIFFERENT gauge. If you must read a
           location from the environment, VALIDATE it equals the target case and exit nonzero otherwise.
         * DERIVE `scored_obs` (and `case_id`) from the SAME resolved gauge/obs the run actually scored —
           set them from the variables you used to read the obs + extract the model cell, so the declaration
           CANNOT diverge from what was scored. A hardcoded literal that a code path can contradict is a
           REJECTED capability (a review will look for exactly this divergence).

### DRIVER ROBUSTNESS CONTRACT — a review REQUIRES all of the below (recurring REQUEST_CHANGES):
  * ENFORCE WHATEVER THE OBS CONTRACT EXPLICITLY DECLARES — and only those, domain-appropriate fields; do not
    just read a value column, and do not invent/require fields the contract does not declare. For every
    obs-envelope field the TARGET CASE / calibration.yaml explicitly states (e.g. for a groundwater-level
    series: station identity, reference surface elevation, the exact month/date set, the observed
    min/max/range/mean), the obs loader MUST read and ASSERT it (exit nonzero, no metrics, on mismatch) so a
    changed or corrupted series for the SAME station cannot be silently scored. Reading only the value column +
    identity when MORE is declared is a REJECTED capability.
  * FAIL-CLOSED RUN-HEALTH. For any run-health diagnostic the model actually produces/claims (e.g. MODFLOW's
    `convergence_failures` / `max_budget_error_pct` / normal-termination), a MISSING or None value must FAIL the
    eval closed — never default it to a passing value via `or 0`. Do not fabricate diagnostics a model doesn't
    emit; but a diagnostic that is required/claimed and then absent/None = fail closed (no metrics, nonzero exit).
  * OPEN READ-ONLY SOURCES READ-ONLY. Any immutable obs/catalog source (an sqlite DB, a data file) MUST be opened
    read-only so scoring works on a read-only mount and in a read-only review sandbox: sqlite ->
    `sqlite3.connect(f"file:{{path}}?mode=ro", uri=True)`; text files -> open(path, "r"), binary/library-backed
    data -> "rb" or the library's own read-only mode. Opening an obs catalog in
    sqlite's default read/write/create mode fails on a read-only source (`unable to open database file`) — REJECTED.

COMMISSIONING (MANDATORY before you finish): run at the default vector, then a clearly-perturbed vector,
in separate workdirs; show applied_params and that the metric MOVES. If nothing moves, the injection isn't
reaching the scored run — return a BLOCKER, not "authored".
ALSO — RANGE-BOUND read-back check (this is what makes a screen SUCCEED, not just move): for EACH
parameter, run once at its range `lo` and once at its `hi` and confirm `__kdt__.applied_params[name]`
reads back EQUAL to the requested bound (within the runner's own read-back tolerance). A bound where the
model CLAMPS the value (applied ≠ requested) will make the sensitivity-screen corner eval fail closed —
if you see that, TIGHTEN the range to the clamp-free region and re-test, do NOT ship the wide range. Only
finish when every parameter applies exactly at BOTH of its bounds.

Your FINAL message is a JSON object: {{"status":"authored","calibration_yaml":true,"calib_run":true,
"injection_mode":"applicator|runner","params":[...names...],"notes":"..."}}
"""


def _has_contract(ki_path) -> bool:
    return (Path(ki_path) / "calibration.yaml").is_file() \
        and (Path(ki_path) / "tools" / "calib_run.py").is_file()


def _capability_case_path(ki_path) -> Path:
    return Path(ki_path) / "calib" / "capability_case.json"


def _file_sha(path) -> str | None:
    import hashlib
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]
    except Exception:
        return None


def _contract_shas(ki_path) -> dict:
    return {"calibration_yaml_sha": _file_sha(Path(ki_path) / "calibration.yaml"),
            "calib_run_sha": _file_sha(Path(ki_path) / "tools" / "calib_run.py")}


def _capability_matches_case(ki_path, case) -> bool:
    """A PRESENT contract is reusable ONLY if it was authored AND codex-APPROVED for THIS case
    AND the on-disk files are byte-identical to what was approved. File existence alone is not
    enough (codex 2026-07-18): a Bengbu-authored contract must not be reused for a Jinghong run,
    a rejected/unreviewed contract must never be reused, and a driver MUTATED after approval
    (e.g. by the driver-repair agent) must be re-reviewed, not silently trusted. Provenance +
    content hashes live in calib/capability_case.json, written ONLY on APPROVE."""
    if not case or not case.get("case_id"):
        return True                       # no case pinned -> don't force redev on identity
    p = _capability_case_path(ki_path)
    if not p.is_file():
        return False                      # unknown provenance -> redevelop (fail closed)
    try:
        rec = json.loads(p.read_text())
    except Exception:
        return False
    if rec.get("approved") is not True or str(rec.get("case_id")) != str(case.get("case_id")):
        return False
    # EXECUTED-OBS DRIFT (codex 2026-08-02): the review is now authoritative on the executed obs /
    # integrity flag. If either changed for this case since approval (e.g. a mislabel was backfilled),
    # the prior approval predates the executed-obs-aware review — re-review rather than reuse.
    if str(rec.get("resolved_obs") or "") != str((case or {}).get("resolved_obs") or "") or \
       str(rec.get("integrity_note") or "") != str((case or {}).get("integrity_note") or ""):
        return False
    # content must match what was approved (a post-approval edit invalidates reuse). BOTH hashes are
    # MANDATORY — a legacy/partial sidecar missing either hash can't prove the files are unchanged, so
    # it must redevelop (codex round-3: an absent hash previously fell through to reuse). Fail closed.
    cur = _contract_shas(ki_path)
    for k in ("calibration_yaml_sha", "calib_run_sha"):
        if not rec.get(k) or not cur.get(k) or rec.get(k) != cur.get(k):
            return False
    return True


def _write_capability_case(ki_path, case, vdict) -> None:
    """Record case provenance + approved-content hashes so the contract is reusable ONLY for this
    case AND only while the files are unchanged. Called ONLY on codex APPROVE."""
    try:
        p = _capability_case_path(ki_path); p.parent.mkdir(parents=True, exist_ok=True)
        rec = {"case_id": (case or {}).get("case_id"), "obs_id": (case or {}).get("obs_id"),
               "resolved_obs": (case or {}).get("resolved_obs"),
               "integrity_note": (case or {}).get("integrity_note"),
               "approved": True, "verdict": vdict, "authored_at": _now()}
        rec.update(_contract_shas(ki_path))
        p.write_text(json.dumps(rec, indent=2, default=str))
    except Exception:
        pass


def _archive_capability(ki_path, tag) -> str | None:
    """Move a not-to-be-reused capability (rejected / unreviewed / wrong-case / post-approval-edit)
    out of the KI so a later run can't bypass review by finding stale files. Reversible (never
    deletes). The archive dir is UNIQUE (pid + microseconds) so concurrent archivals don't collide;
    a rename failure is surfaced (printed) rather than silently swallowed. Returns the archive path,
    or None if nothing was moved."""
    import os as _os
    ki = Path(ki_path)
    stamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S_%f")
    bk = ki / f".{tag}_{stamp}_p{_os.getpid()}"
    (bk / "tools").mkdir(parents=True, exist_ok=True)
    moved, failed = [], []
    for src, dst in ((ki / "calibration.yaml", bk / "calibration.yaml"),
                     (ki / "tools" / "calib_run.py", bk / "tools" / "calib_run.py"),
                     (_capability_case_path(ki), bk / "capability_case.json")):
        if not src.is_file():
            continue
        try:
            src.rename(dst); moved.append(src.name)
        except Exception as e:
            failed.append(f"{src.name}: {e}")
    if failed:      # surface, never silently proceed as if the KI is clean
        print(f"  [calib] WARNING: could not archive {failed} to {bk} — stale files may remain", flush=True)
    return str(bk) if moved else None


def _case_block(case) -> str:
    """Human-readable TARGET CASE block for the calib-dev prompt. Without this the agent
    has no signal which gauge/obs to score and may build for a different validated site
    the KI documents (the Bengbu-instead-of-Jinghong bug, 2026-07-18)."""
    if not case:
        return ("- (no explicit case supplied) — score the gauge/obs the KI's validated "
                "run_and_score recipe used for its most recent real case; if ambiguous, BLOCK.")
    c = dict(case)
    osv = c.get("obs_shape_by_var") or {}
    lines = [f"- case_id: {c.get('case_id')}",
             f"- obs / gauge id: {c.get('obs_id')}",
             f"- target quantity: {c.get('target_quantity')}  (dag var/obs_shape: "
             f"{', '.join(f'{k}->{v}' for k, v in osv.items()) or 'see dag.yaml'})",
             f"- determining metric to optimize: {c.get('determining_metric')}",
             f"- provenance of the validated coupling: {c.get('validated_run_id')}"]
    # AUTHORITATIVE executed obs (record-layer resolved evidence). When present it is what the validated
    # run ACTUALLY scored and OVERRIDES the label above if they disagree — build for the EXECUTED obs.
    if c.get("resolved_obs"):
        lines.append(f"- EXECUTED obs (AUTHORITATIVE — what the validated run actually scored): {c.get('resolved_obs')}")
    if c.get("integrity_note"):
        lines.append(f"- ⚠ INTEGRITY: {c.get('integrity_note')} Build for the EXECUTED obs, and set "
                     f"__kdt__.scored_obs/case_id from what you actually score.")
    return "\n".join(lines)


# Shared review payload + focus (codex 2026-08-02): the EXECUTED obs is authoritative over a stale
# target_quantity/obs LABEL. Both the calib-dev AND the driver-repair review MUST use these, or a
# mislabeled case that routes through fix_driver/screen_failed hits the same stale-label rejection.
_REVIEW_FOCUS_EXEC = (
    "CONFIRM the driver scores the case's gauge/obs; FLAG if it hardcodes a DIFFERENT validated site. "
    "AUTHORITY: when `executed_obs` is present it is what the validated run ACTUALLY scored and OVERRIDES "
    "the target_quantity/obs LABEL. If `integrity_note` flags a label-vs-executed mismatch, the LABEL is "
    "stale — APPROVE a driver that correctly scores the EXECUTED obs; do NOT reject it for matching the "
    "executed obs over the stale label.")


def _review_target_case(case) -> dict:
    _rc = case or {}
    return {"case_id": _rc.get("case_id"), "obs_id": _rc.get("obs_id"),
            "target_quantity": _rc.get("target_quantity"),
            "determining_metric": _rc.get("determining_metric"),
            "executed_obs": _rc.get("resolved_obs"),
            "integrity_note": _rc.get("integrity_note")}


REVISION_PROMPT = """# Calibration-Capability REVISION Agent: {model_id}

Your previously-authored `{ki_path}/calibration.yaml` + `{ki_path}/tools/calib_run.py` for the TARGET CASE
below were codex-reviewed and got {verdict}. FIX EXACTLY the issues listed by EDITING THE EXISTING two files
in place. Do NOT rewrite from scratch and do NOT change what already works — the reviewer accepted the rest,
so a regression will fail the re-review.

## TARGET CASE (unchanged — keep scoring THIS)
{case_block}

## Reviewer issues to fix (address ALL of them)
{issues}

Keep every existing guarantee: reuse the KI's OWN run tools (never reimplement the model); the honest
`__kdt__` case_id/scored_obs declaration derived from what you actually score; the DRIVER ROBUSTNESS CONTRACT
(assert the declared obs envelope; fail-closed run-health; open read-only sources read-only); and
literature-grounded, clamp-free parameter ranges (verify read-back at both bounds). Re-run your COMMISSIONING
checks after editing. Final message: {{"status":"revised","calib_run":true,"notes":"what you changed"}}.
"""


def develop_calibration_capability(model_id, ki_path, prior_metric, case=None, max_review_rounds=3):
    """Author calibration.yaml + tools/calib_run.py, codex-review, and — on REQUEST_CHANGES — feed the
    reviewer's issues back for up to `max_review_rounds` REVISION rounds (2026-08-03). The reviewer is
    strict and a complex driver (e.g. DSSAT's fixed-width FileX, MODFLOW's flopy round-trip) rarely lands
    on the first try; a one-shot gate recorded those as `capability_unavailable` even though a single fix
    round would pass. Attests + reuses ONLY on APPROVE. Returns (ok, verdict).
    `case` is threaded into the prompt so the agent scores the RIGHT gauge, not a different documented site."""
    import orchestrator as O
    from tool_reviewer import review_tool

    def _review():
        # Review BOTH attested files (codex 2026-08-03): _write_capability_case pins hashes of
        # calibration.yaml AND calib_run.py, so BOTH must be reviewed or an unreviewed/bad calibration.yaml
        # (wrong param ranges, wrong obs envelope) could be attested as approved.
        cyaml = (Path(ki_path) / "calibration.yaml").read_text()
        crun = (Path(ki_path) / "tools" / "calib_run.py").read_text()
        diff = ("--- /dev/null\n+++ b/calibration.yaml\n"
                + "".join("+" + l for l in cyaml.splitlines(keepends=True))
                + "--- /dev/null\n+++ b/tools/calib_run.py\n"
                + "".join("+" + l for l in crun.splitlines(keepends=True)))
        v = review_tool(diff=diff[:200_000],   # match review_tool's own 200k cap; 64k truncated large drivers
                        tool_summary={"tool": "calibration.yaml + tools/calib_run.py",
                                      "summary": "calibration contract + run/score driver",
                                      "origin": "calib_dev", "target_case": _review_target_case(case),
                                      "review_focus": _REVIEW_FOCUS_EXEC},
                        ki_path=ki_path, run_id=f"{model_id}_calibdev")
        return {"verdict": v.verdict, "issues": list(v.issues[:5]), "reviewer": v.reviewer}

    try:
        from ki_snapshot import take_snapshot
        take_snapshot(Path(ki_path), label=f"pre_calibdev_{model_id}")
    except Exception:
        pass

    vdict = {"verdict": "REJECT", "issues": [], "reviewer": "self"}
    # round 0 = initial authoring; rounds 1..N-1 = revisions fed the reviewer's own issues
    for rnd in range(max(1, int(max_review_rounds))):
        if rnd == 0:
            prompt = CALIB_DEV_PROMPT.format(model_id=model_id, ki_path=str(ki_path),
                                             case_block=_case_block(case),
                                             prior_metric=json.dumps(prior_metric, default=str)[:400])
        else:
            prompt = REVISION_PROMPT.format(
                model_id=model_id, ki_path=str(ki_path), case_block=_case_block(case),
                verdict=vdict.get("verdict"),
                issues="\n".join(f"  {i+1}. {x}" for i, x in enumerate(vdict.get("issues") or [])) or "  (see prior review)")
        result, output = O.run_claude_resilient(prompt, timeout=_agent_timeout(), max_turns=80)
        (Path(O.WORK_DIR) / model_id / (f"calib_dev_output{'' if rnd == 0 else f'_rev{rnd}'}.txt")).write_text(output or "")
        if not _has_contract(ki_path):
            return False, {"verdict": "REJECT", "reason": "calibration.yaml / calib_run.py not authored",
                           "reviewer": "self", "round": rnd}
        try:
            vdict = _review()
        except Exception as e:
            arch = _archive_capability(ki_path, "unreviewed_calibdev")
            return False, {"verdict": "REJECT", "reason": f"review failed: {e}", "archived_to": arch}
        vdict["round"] = rnd
        try:   # persist the latest codex verdict so a not-APPROVE outcome is recoverable
            (Path(O.WORK_DIR) / model_id / "calib_dev_review.json").write_text(json.dumps(vdict, indent=2, default=str))
        except Exception:
            pass
        if vdict["verdict"] == "APPROVE":
            _write_capability_case(ki_path, case, vdict)   # case + approved-content hashes
            return True, vdict
        if vdict["verdict"] == "WAIT":
            # WAIT = STAGED, pending HUMAN review (tool_reviewer escalation) — NOT a fixable review issue.
            # Do NOT revise or archive: leave the files staged and surface a pending verdict (codex 2026-08-03).
            vdict["pending_human"] = True
            return False, vdict
        # NOT approved (REQUEST_CHANGES / REJECT): leave the files in place so the NEXT revision round can EDIT
        # them (do not archive between rounds — the agent needs the current draft + the reviewer's issues).
        print(f"  [{model_id}] calib-dev review round {rnd}: {vdict['verdict']} ({len(vdict.get('issues') or [])} "
              f"issue(s)) — {'revising' if rnd < max_review_rounds - 1 else 'rounds exhausted'}", flush=True)

    # exhausted all rounds without APPROVE -> archive so nothing rejected/unreviewed lingers for reuse
    vdict["archived_rejected_to"] = _archive_capability(ki_path, "rejected_calibdev")
    return False, vdict


FIX_DRIVER_PROMPT = """# Calibration-Driver Repair Agent: {model_id}

The calibration sensitivity screen found that the model's scored metric **does not
change when parameters change** (route={route}). That means `{ki_path}/tools/calib_run.py`
is NOT applying the calibration parameters to the run it scores — calibration is
impossible until this is fixed. Triage detail:
  baseline metrics: {baseline}
  reason: {reason}
  family verdict: {family_verdict}
  prior validated metric: {prior_metric}

## Your job (fix the DRIVER, not the science)
1. Read `{ki_path}/calibration.yaml` (the parameters + their edit `address`es) and
   `{ki_path}/tools/calib_run.py`.
2. Find WHY a parameter change doesn't change the scored series. Usual causes:
   - the driver scores a FIXED canonical run dir / cached output instead of re-running
     with the candidate's params (broken candidate isolation);
   - it writes params to a copy the model run doesn't actually read (wrong path / the
     address points at the wrong file or a non-effective field);
   - it ignores `--workdir` so concurrent candidates collide;
   - the run silently reuses a previous result.
3. FIX `tools/calib_run.py` (and, if an `address` is wrong, `calibration.yaml`) so that
   running calib_run.py at two DIFFERENT parameter vectors produces DIFFERENT metrics.
4. PROVE it: run calib_run.py at the default params and at a perturbed vector, and show
   the scored metric differs. Do NOT fake this — if you cannot make params take effect,
   say so and explain the blocker.

For {route}=screen_failed the symptom is instead that perturbed runs FAIL (no finite
metrics) — tighten the physically-valid ranges in calibration.yaml and/or make
calib_run.py robust (write metrics only on a successful run), then show calib_run.py
succeeds at 3 random in-range vectors.

## MANDATORY requirements (a prior repair was REJECTED by codex for missing these):
1. HONOR `--workdir`: run the model inside the per-candidate `--workdir` the calibration
   kit passes (copy the canonical TxtInOut into `<workdir>/run/` and run there). Do NOT
   rewrite a single shared run dir — concurrent/retried candidates MUST be isolated.
2. STALE-OUTPUT SAFETY: delete the `--out` metrics file BEFORE running, AND ensure the
   exception/early-exit paths never leave a previous candidate's metrics behind. A failed
   run must write NOTHING (so the kit reads +inf), never a stale success artifact.
3. Prove (1) by running two candidates concurrently in different workdirs and showing
   they don't clobber each other; prove metric responsiveness by showing two different
   param vectors give two different metrics.

Edit ONLY `tools/calib_run.py` and `calibration.yaml`. Your FINAL message is JSON:
{{"status":"fixed"|"could_not_fix","what_was_wrong":"...","verification":"<the two runs + their differing metrics + the isolation proof>","files_changed":[...]}}
"""

DIAGNOSE_SETUP_PROMPT = """# Calibration Setup-Diagnosis Agent: {model_id}

Calibration was attempted but the gate's PATTERN family is failing for the calibration
target — the model's hydrograph/field SHAPE is wrong here, which parameters CANNOT fix.
This is a SETUP/INPUT problem, not a tuning one. Triage detail:
  baseline metrics: {baseline}
  reason: {reason}
  family verdict: {family_verdict}
  prior validated metric (elsewhere): {prior_metric}

## Your job (INVESTIGATE — do not fabricate, do not "fix" by changing metrics)
1. Read `{ki_path}/calibration.yaml` `targets` (which var/site/obs the calibration
   scores), `{ki_path}/tools/calib_run.py`, the KI's run recipe, and the obs the run is
   compared against (model_obs_map / the obs file the driver reads).
2. Determine the ROOT CAUSE of the broken pattern. Candidates: forcing source/period/
   frequency mismatch; basin delineation / drainage-area wrong; an INTERIOR gauge scored
   against the OUTLET (gauge→channel/cell mapping missing); unit error; routing/lag not
   set; obs–model location mismatch in model_obs_map; calibrating a different site than
   was validated.
3. Write findings to `{work_dir}/setup_diagnosis.md` (root cause + evidence paths +
   the concrete change that would fix the setup) and, if a learning-proposals queue is
   available, queue it as an out-of-scope proposal.

Your FINAL message is JSON:
{{"root_cause":"...","evidence":["path:line", ...],"recommended_fix":"...","in_scope_for_loop":true|false}}
"""


def act_on_calibration_blocker(model_id, ki_path, work_dir, report, prior_metric, case=None):
    """Turn a non-calibrate triage route into an ACTION (2026-06-27):
      fix_driver / screen_failed -> spawn a driver-repair agent, then codex-review the
        patched tools/calib_run.py (it runs the model 100s of times).
      diagnose_setup            -> spawn a setup-diagnosis agent that investigates the
        forcing/routing/gauge-mapping/obs-map mismatch and writes findings (no fabrication).
    Returns an action dict. Never raises (caller wraps), but guards internally too."""
    import orchestrator as O
    route = report.get("route")
    ki_path = str(ki_path)
    fmt = dict(model_id=model_id, ki_path=ki_path, work_dir=str(work_dir), route=route,
               baseline=json.dumps(report.get("baseline"), default=str)[:300],
               reason=str(report.get("reason"))[:500],
               family_verdict=json.dumps(report.get("family_verdict"), default=str)[:400],
               prior_metric=json.dumps(prior_metric, default=str)[:200])

    if route in ("fix_driver", "screen_failed"):
        prompt = FIX_DRIVER_PROMPT.format(**fmt)
        print(f"  [{model_id}] TRIAGE-ACTION: spawning driver-repair agent ({route})...", flush=True)
        try:
            _res, output = O.run_claude_resilient(prompt, timeout=_agent_timeout(), max_turns=70)
        except Exception as e:
            return {"route": route, "action": "fix_driver", "status": "agent_error", "reason": str(e)}
        (Path(work_dir) / "calib_driver_fix_output.txt").write_text(output or "")
        # independent codex review of the patched driver
        review = {"verdict": "SKIPPED"}
        try:
            from tool_reviewer import review_tool
            # review BOTH attested files (codex 2026-08-03): the repair may edit calibration.yaml too, and
            # _write_capability_case pins both hashes — reviewing only calib_run.py could attest an
            # unreviewed calibration.yaml.
            cyaml = (Path(ki_path) / "calibration.yaml").read_text()
            crun = (Path(ki_path) / "tools" / "calib_run.py").read_text()
            diff = ("--- a/calibration.yaml\n+++ b/calibration.yaml\n"
                    + "".join("+" + l for l in cyaml.splitlines(keepends=True))
                    + "--- a/tools/calib_run.py\n+++ b/tools/calib_run.py\n"
                    + "".join("+" + l for l in crun.splitlines(keepends=True)))
            v = review_tool(diff=diff[:200_000],   # match review_tool's own 200k cap (was 64k, truncated large drivers)
                            tool_summary={"tool": "calibration.yaml + tools/calib_run.py",
                                          "summary": "calibration contract + driver (repaired)",
                                          "origin": "calib_driver_fix",
                                          "target_case": _review_target_case(case),
                                          "review_focus": "The repaired driver must STILL score the case's "
                                          "gauge/obs. " + _REVIEW_FOCUS_EXEC},
                            ki_path=ki_path, run_id=f"{model_id}_driverfix")
            review = {"verdict": v.verdict, "issues": v.issues[:3], "reviewer": v.reviewer}
        except Exception as e:
            review = {"verdict": "REVIEW_ERROR", "reason": str(e)}
        # the repair MUTATED calib_run.py, so any prior approved sidecar no longer matches its hash
        # (_capability_matches_case already forces re-review). On APPROVE re-record the sidecar (same case,
        # new hash). WAIT = STAGED pending HUMAN review — leave staged, do NOT archive. Otherwise ARCHIVE
        # so nothing rejected/unreviewed lingers.
        if review.get("verdict") == "APPROVE":
            _write_capability_case(ki_path, case, review)
        elif review.get("verdict") == "WAIT":
            review["pending_human"] = True
        else:
            review["archived_to"] = _archive_capability(ki_path, "rejected_driverfix")
        print(f"  [{model_id}] TRIAGE-ACTION: driver-repair done; codex={review.get('verdict')}", flush=True)
        return {"route": route, "action": "driver_repair", "status": "ran",
                "review": review, "output_tail": (output or "")[-600:]}

    if route == "diagnose_setup":
        prompt = DIAGNOSE_SETUP_PROMPT.format(**fmt)
        print(f"  [{model_id}] TRIAGE-ACTION: spawning setup-diagnosis agent...", flush=True)
        try:
            _res, output = O.run_claude_resilient(prompt, timeout=_agent_timeout(), max_turns=60)
        except Exception as e:
            return {"route": route, "action": "diagnose_setup", "status": "agent_error", "reason": str(e)}
        (Path(work_dir) / "calib_setup_diagnosis_output.txt").write_text(output or "")
        # best-effort: queue an out-of-scope proposal so the finding isn't lost
        queued = False
        try:
            from learning_proposals import propose_out_of_scope_finding
            propose_out_of_scope_finding(
                model_id=model_id, run_id=f"{model_id}_calib_setup",
                diagnosis={"fix_class": "requires_setup_fix", "in_scope": False,
                           "diagnosis": report.get("reason"),
                           "fix_description": (output or "")[-1500:]},
                test_result={"calibration_triage": report.get("family_verdict")})
            queued = True
        except Exception as e:
            print(f"  [{model_id}] TRIAGE-ACTION: proposal queue failed (non-fatal): {e}", flush=True)
        print(f"  [{model_id}] TRIAGE-ACTION: setup-diagnosis done; proposal_queued={queued}", flush=True)
        return {"route": route, "action": "setup_diagnosis", "status": "ran",
                "proposal_queued": queued, "output_tail": (output or "")[-600:]}

    return {"route": route, "action": "none", "status": "no_action_for_route"}


def run_stage(model_id, ki_path, work_dir, obs_shape_by_var, prior_metric=None,
              budget=None, determining_metric=None, headline_objectives=None, case=None):
    """Develop-if-missing + run calibration + gate. Returns a report dict (or a
    skip dict). Never raises into the pipeline. `determining_metric` /
    `headline_objectives` (from readiness/the convention) let the engine optimize +
    triage the field HEADLINE metric instead of the family default."""
    if not enabled():
        return {"status": "skipped", "reason": "KDT_CALIBRATE not set"}
    ki_path = str(ki_path)
    try:
        print(f"  [{model_id}] CALIBRATE: tuning parameters to fit dag obs "
              f"(prior metric: {prior_metric})", flush=True)
        # A. ensure calibration capability exists AND was approved for THIS case (develop if not).
        # File existence alone is unsafe (codex 2026-07-18): a contract authored/approved for a
        # DIFFERENT gauge must be archived + redeveloped, never reused for this case.
        _has = _has_contract(ki_path)
        if _has and not _capability_matches_case(ki_path, case):
            arch = _archive_capability(ki_path, "mismatched_case_calibdev")
            print(f"  [{model_id}] CALIBRATE: existing capability was authored for a DIFFERENT case "
                  f"(archived → {arch}) — redeveloping for {(case or {}).get('case_id')}", flush=True)
            _has = False
        if not _has:
            print(f"  [{model_id}] CALIBRATE: no matching calibration.yaml — developing "
                  f"calibration capability for case {(case or {}).get('case_id')} "
                  f"(agent + codex review)...", flush=True)
            ok, verdict = develop_calibration_capability(model_id, ki_path, prior_metric, case=case)
            if not ok:
                return {"status": "calibration_capability_unavailable",
                        "review": verdict}
            print(f"  [{model_id}] CALIBRATE: capability APPROVED "
                  f"({verdict.get('reviewer')})", flush=True)

        # B. run the calibration engine (pass the target case_id so the engine can FAIL-CLOSED
        # if the runner self-declares a different gauge — the deterministic wrong-gauge guard)
        from calibration_kit import calib
        _expected_case = (case or {}).get("case_id")
        report = calib.calibrate(ki_path=ki_path, workdir=str(work_dir),
                                 obs_shape_by_var=obs_shape_by_var, budget=budget,
                                 determining_metric=determining_metric,
                                 headline_objectives=headline_objectives,
                                 expected_case_id=_expected_case)
        # C. report + gate
        status = report.get("status")
        promotable = report.get("promotable")
        # CALIBRATABILITY TRIAGE routes (2026-06-27): the engine may decide calibration
        # is the WRONG tool and exit early. Surface that as a distinct, actionable signal
        # — especially diagnose_setup, which means the basin SETUP/INPUTS are wrong (the
        # self-improve loop should re-examine forcing/routing/mapping), NOT a tuning miss.
        route = report.get("route")
        if route in ("diagnose_setup", "fix_driver", "screen_failed", "already_adequate",
                     "undetermined"):
            banner = {"diagnose_setup": "SETUP/INPUT PROBLEM — not a calibration miss",
                      "fix_driver": "DRIVER not applying params (calib_run.py bug)",
                      "screen_failed": "screen runs failing (model unstable / no metrics)",
                      "already_adequate": "baseline already meets target",
                      "undetermined": "gate undetermined — missing pattern/magnitude metric"}[route]
            print(f"  [{model_id}] CALIBRATE TRIAGE -> {route}: {banner}\n"
                  f"      baseline={report.get('baseline')}\n"
                  f"      {report.get('reason')}", flush=True)
            # NO MISDIAGNOSIS (2026-07): if the module was CERTIFIED (reference_run.json exists,
            # so certify_runner reproduced the validated run before the screen), the model
            # PROVABLY executes the KI correctly. A fix_driver/screen_failed AFTER certification
            # is therefore NOT a driver bug or "model instability" — it is a cost/sensitivity
            # artifact (evals slow/insensitive, never a broken driver). Do NOT spawn the flaky
            # nested driver-repair agent; record it honestly and stop. (Time is never a
            # constraint: with the per-eval timeout removed, slow evals complete instead of
            # scoring +inf, so this path should rarely trigger at all.)
            _certified = (Path(ki_path) / "calib" / "reference_run.json").is_file()
            if _certified and route in ("fix_driver", "screen_failed"):
                report["triage_action"] = {
                    "status": "skipped_certified", "action": "none", "route": route,
                    "reason": "module certified against the validated run (certify_runner "
                              "reproduced it); a screen_failed/fix_driver after certification is a "
                              "cost/sensitivity artifact, not a driver bug — no repair agent spawned"}
                print(f"  [{model_id}] CALIBRATE: module is CERTIFIED — treating {route} as a "
                      f"cost/sensitivity artifact, NOT a driver bug (no repair agent).", flush=True)
            elif route in ("diagnose_setup", "fix_driver", "screen_failed"):
                try:
                    report["triage_action"] = act_on_calibration_blocker(
                        model_id, ki_path, work_dir, report, prior_metric, case=case)
                except Exception as _ae:
                    report["triage_action"] = {"status": "action_error", "reason": str(_ae)}
                    print(f"  [{model_id}] CALIBRATE triage-action error (non-fatal): {_ae}", flush=True)
                # LAND THE REPAIR (2026-06-28): if the driver-repair was codex-APPROVED,
                # re-run calibration ONCE so a now-isolated runner actually calibrates.
                # Single-shot (no loop) — guarded by the APPROVE verdict.
                _ta = report.get("triage_action") or {}
                if (route in ("fix_driver", "screen_failed")
                        and _ta.get("action") == "driver_repair"
                        and (_ta.get("review") or {}).get("verdict") == "APPROVE"):
                    print(f"  [{model_id}] CALIBRATE: driver repair APPROVED → re-running "
                          f"calibration once on the fixed runner...", flush=True)
                    try:
                        report2 = calib.calibrate(ki_path=ki_path, workdir=str(work_dir),
                                                  obs_shape_by_var=obs_shape_by_var, budget=budget,
                                                  determining_metric=determining_metric,
                                                  headline_objectives=headline_objectives,
                                                  expected_case_id=_expected_case)
                        report["recalibration"] = report2
                        print(f"  [{model_id}] CALIBRATE (post-repair): status={report2.get('status')} "
                              f"route={report2.get('route')} best_loss={report2.get('best_loss')} "
                              f"holdout={report2.get('holdout_validated')} "
                              f"promotable={report2.get('promotable')}", flush=True)
                        # if the re-run actually calibrated, surface THAT as the report
                        if report2.get("route") not in ("diagnose_setup", "fix_driver",
                                                        "screen_failed", "undetermined"):
                            report = {**report2, "driver_was_repaired": True,
                                      "triage_action": _ta}
                    except Exception as _re:
                        report["recalibration"] = {"status": "error", "reason": str(_re)}
                        print(f"  [{model_id}] CALIBRATE post-repair re-run error: {_re}", flush=True)
            try:
                (Path(work_dir) / "calibration_report.json").write_text(
                    json.dumps(report, indent=2, default=str))
            except Exception:
                pass
            return report
        print(f"  [{model_id}] CALIBRATE: {status} | algo={report.get('algorithm')} "
              f"| best_loss={report.get('best_loss')} | holdout="
              f"{report.get('holdout_validated')} | promotable={promotable}", flush=True)
        try:
            (Path(work_dir) / "calibration_report.json").write_text(
                json.dumps(report, indent=2, default=str))
        except Exception:
            pass
        return report
    except Exception as e:
        print(f"  [{model_id}] CALIBRATE: stage error (non-fatal): {e}", flush=True)
        return {"status": "error", "reason": str(e)}
