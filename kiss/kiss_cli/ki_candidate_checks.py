"""Run a repair draft's own tests on an isolated copy and report the outcome.

This is feedback for the repair author, never acceptance: KDT verification,
adoption and native model checks remain separate gates. The draft is
agent-authored code, so it runs in a scratch copy with this KI's configured
interpreter, a bounded time, a scratch HOME and no credential variables.
That limits accidents; it is not an operating-system sandbox.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import tempfile

POLICY = "candidate-own-tests-v1"
TIMEOUT_SECONDS = 300
MAX_OUTPUT_CHARS = 12000
_SECRET_MARKERS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")


def _environment(cfg, home: Path) -> dict[str, str]:
    from . import paths
    env = {key: value for key, value in os.environ.items()
           if not any(marker in key.upper() for marker in _SECRET_MARKERS)}
    env.update(HOME=str(home), USERPROFILE=str(home), TMPDIR=str(home), TMP=str(home), TEMP=str(home),
               PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1")
    env.pop("PYTHONPATH", None)
    env = paths.with_ki_tools_common(cfg, env)
    return paths.with_python_runtime(cfg.python, env)


def _counts(runner: str, output: str) -> dict:
    if runner == "unittest":
        ran = re.findall(r"^Ran (\d+) tests?", output, re.M)
        failed = re.findall(r"failures=(\d+)", output)
        errors = re.findall(r"errors=(\d+)", output)
        return {"tests_run": int(ran[-1]) if ran else 0,
                "failed": int(failed[-1]) if failed else 0, "errors": int(errors[-1]) if errors else 0}
    def last(label):
        found = re.findall(rf"(\d+) {label}", output)
        return int(found[-1]) if found else 0
    passed, failed, errors = last("passed"), last("failed"), last("errors?")
    return {"tests_run": passed + failed + errors, "failed": failed, "errors": errors}


def run(candidate: Path, cfg, *, stop=None, redact=lambda text: text) -> dict:
    """Return {ran, ok, ...}. ok is None when there is nothing runnable to judge."""
    from . import execution, ki_copy, ki_verification
    candidate = Path(candidate)
    tests = sorted((candidate / "tests").glob("test_*.py")) if (candidate / "tests").is_dir() else []
    digest = ki_verification.content_digest(candidate)
    result = {"policy": POLICY, "candidate_digest": digest, "interpreter": str(cfg.python),
              "assurance": "feedback_only_not_acceptance"}
    if not tests:
        return {**result, "ran": False, "ok": None, "reason": "The draft has no tests/test_*.py files."}
    with tempfile.TemporaryDirectory(prefix="geoforge-candidate-tests-") as scratch:
        copy, home = Path(scratch) / "ki", Path(scratch) / "home"
        ki_copy.copytree(candidate, copy)
        home.mkdir()
        env = _environment(cfg, home)
        probe = execution.run_process([str(cfg.python), "-c", "import pytest"], cwd=copy, env=env,
                                      timeout=60, stop=stop)
        runner = "pytest" if probe.returncode == 0 else "unittest"
        command = ([str(cfg.python), "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"]
                   if runner == "pytest" else
                   [str(cfg.python), "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-v"])
        run_ = execution.run_process(command, cwd=copy, env=env, timeout=TIMEOUT_SECONDS, stop=stop)
    output = redact((run_.stdout or "") + (run_.stderr or "") + ("\n" + run_.detail if run_.detail else ""))
    counts = _counts(runner, output)
    if ki_verification.content_digest(candidate) != digest:
        raise RuntimeError("Repair draft changed while its own tests were running; run them again")
    ok = run_.status == "succeeded" and counts["tests_run"] > 0
    reason = ""
    if counts["tests_run"] == 0:
        ok = None if run_.status == "succeeded" else False
        reason = ("No tests were collected. Without pytest installed, tests must be unittest.TestCase "
                  "classes that `python -m unittest discover -s tests` can find.")
    return {**result, "ran": True, "ok": ok, "reason": reason, "runner": runner,
            "command": " ".join(command[1:]), "status": run_.status, "returncode": run_.returncode,
            **counts, "test_files": [path.name for path in tests],
            "output_tail": output[-MAX_OUTPUT_CHARS:]}
