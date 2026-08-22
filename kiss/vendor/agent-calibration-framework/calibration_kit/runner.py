"""Build the `run_model` callable the Evaluator calls per evaluation.

Calibration does 100s–1000s of evaluations, so a run MUST be programmatic and cheap
— NOT a claude agent per eval (that's the self-improve KI's structural-correctness
job, done once). So each model's KI declares a `runner` in calibration.yaml: a
script or callable that runs the model with the CURRENT input files (the applicator
has already written this candidate's parameters) and returns the gate-valid metrics
dict (nse / pbias / trend_error / continuity_error / …). objectives.py maps those
metrics to losses.

Runner kinds:
  python:     import "module:callable"; call(workdir) -> metrics dict
  subprocess: run a command that writes a metrics JSON; we read it back
  detached:   launch via kdt_detached_run.py + poll result.json (for the
              moderately-expensive class where one eval is minutes). For TRULY
              expensive models (PCSE national), use the subset/surrogate strategy
              instead — direct per-eval running is infeasible no matter the runner.

run_model() returns {} (falsy) on any failure/timeout, so Evaluator scores +inf
and the optimizer rejects that candidate without crashing.
"""
from __future__ import annotations
import json
import os
import subprocess
from pathlib import Path


def _subst(s, mapping):
    for k, v in mapping.items():
        s = s.replace("{" + k + "}", str(v))
    return s


def make_run_model(runner_spec: dict, ki_path: str, workdir: str):
    """Return a zero-arg callable -> metrics dict (or {} on failure)."""
    kind = (runner_spec or {}).get("kind", "python")
    ki_path = str(ki_path); workdir = str(workdir)

    if kind == "python":
        # "module.sub:callable" imported relative to ki_path on sys.path.
        target = runner_spec["callable"]
        mod_name, _, fn_name = target.partition(":")

        def _run():
            import importlib, sys
            if ki_path not in sys.path:
                sys.path.insert(0, ki_path)
            try:
                mod = importlib.import_module(mod_name)
                fn = getattr(mod, fn_name)
                m = fn(workdir)
                return m if isinstance(m, dict) else {}
            except Exception:
                return {}
        return _run

    if kind == "subprocess":
        mapping = {"workdir": workdir, "ki_path": ki_path,
                   "metrics_json": os.path.join(workdir, "calib_metrics.json")}
        cmd = [_subst(c, mapping) for c in runner_spec["command"]]
        metrics_file = _subst(runner_spec.get("metrics_file", mapping["metrics_json"]),
                              mapping)
        # TIME IS NEVER A CONSTRAINT (2026-07): developing a KI's calibration must run the
        # REAL binary to completion, however long it takes — a full model run is never killed
        # for being slow (that used to score a legit-but-slow eval as +inf and get misdiagnosed
        # as "model instability"). Default = NO timeout (unbounded). Only an EXPLICIT opt-in
        # hang-catcher (env KDT_CALIB_EVAL_TIMEOUT seconds) ever bounds a run; the per-KI yaml
        # `timeout` is treated as a soft hint and ignored by default.
        _env_to = os.environ.get("KDT_CALIB_EVAL_TIMEOUT")
        timeout = int(_env_to) if (_env_to and _env_to.strip().isdigit() and int(_env_to) > 0) else None
        cwd = _subst(runner_spec.get("cwd", ki_path), mapping)

        def _run():
            try:
                if os.path.exists(metrics_file):
                    os.unlink(metrics_file)     # never read a stale metrics file
            except OSError:
                pass
            try:
                r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                                   timeout=timeout)
            except (subprocess.TimeoutExpired, OSError):
                return {}
            # A crashed child that still left a partial/cached metrics file must NOT
            # be scored as a valid eval (codex runner.py:74) — require rc 0.
            if r.returncode != 0:
                return {}
            try:
                return json.loads(Path(metrics_file).read_text())
            except Exception:
                return {}
        return _run

    if kind == "detached":
        # Moderately-expensive: launch via the KI detached runner + poll result.json.
        # Reuses orchestrator.poll_detached_run so a long single eval can't be cut off.
        runner_path = runner_spec["runner"]            # script the detached job runs
        interp = runner_spec.get("interpreter",
                                 os.path.join(ki_path, "venv/bin/python"))
        _DETACHED = str(Path(__file__).resolve().parent.parent /
                        "auto_dissect_multi_agent" / "kdt_detached_run.py")

        def _run():
            try:
                import sys, shutil as _sh
                # UNIQUE state dir per eval (codex runner.py:88) — a fixed dir lets a
                # prior candidate's result.json be read as the current score. Key it
                # on the per-eval id the evaluator sets; clear any stale state first.
                eid = os.environ.get("KDT_CALIB_EVAL_ID", "0")
                state_dir = os.path.join(workdir, "calib_detached", f"eval_{eid}")
                _sh.rmtree(state_dir, ignore_errors=True)
                os.makedirs(state_dir, exist_ok=True)
                admp = str(Path(__file__).resolve().parent.parent / "auto_dissect_multi_agent")
                if admp not in sys.path:
                    sys.path.insert(0, admp)
                from orchestrator import poll_detached_run
                subprocess.run(["python3", _DETACHED, state_dir, "--",
                                interp, runner_path, "--workdir", workdir],
                               capture_output=True, text=True, timeout=60)
                res = poll_detached_run(state_dir, f"calib_eval{eid}", launch_grace=300)
                return res if isinstance(res, dict) and res.get("status") != "failed" else {}
            except Exception:
                return {}
        return _run

    raise ValueError(f"unknown runner kind {kind!r}")
