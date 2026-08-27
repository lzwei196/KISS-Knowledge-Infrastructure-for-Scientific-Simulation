#!/usr/bin/env python3
"""
DayCent preflight check.

Verifies the actual DDcentEVI rev491 binaries, KI support files, wrapper
imports, and tool syntax before a DayCent run is attempted.
"""

import json
import os
import py_compile
import subprocess
import sys
from pathlib import Path

MODEL_ID = "DayCent"
MODEL_NAME = "DayCent (DDcentEVI rev 491)"

KI_DIR = Path(__file__).resolve().parent
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"

BIN_DIR = Path(
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect_multi_agent/"
    "_work_v2/DayCent/source/repo/Linux_Version_491"
)
DDCENT = BIN_DIR / "DDcentEVI_rev491"
DDLIST = BIN_DIR / "DDlist100_rev491"

PYTHONPATH_ROOTS = [
    "KISSPATH_KI_ROOT",
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect",
]

checks = []


def add_check(kind, subject, critical, status, fix=""):
    check = {
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": status,
        "fix": fix if status == "fail" else "",
    }
    checks.append(check)
    prefix = "OK" if status == "pass" else "FAIL"
    print(f"  {prefix:<5} {kind}: {subject}")
    if status == "fail":
        print(f"        Fix: {check['fix']}")
    return status == "pass"


def diagnostics_fix(detail):
    return f"{detail}; then check {DIAGNOSTICS} for matching recovery triplets."


def check_file(path, label, *, kind="data", critical=True, executable=False):
    path = Path(path)
    subject = path.resolve() if path.exists() else path
    if not path.is_file():
        return add_check(
            kind,
            subject,
            critical,
            "fail",
            diagnostics_fix(f"Restore required file: {path}"),
        )
    if executable and not os.access(path, os.X_OK):
        return add_check(
            kind,
            path.resolve(),
            critical,
            "fail",
            diagnostics_fix(f"Make executable with: chmod +x {path}"),
        )
    return add_check(kind, path.resolve(), critical, "pass")


def check_import(module, *, critical=True):
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    roots = [p for p in PYTHONPATH_ROOTS if p]
    if existing:
        roots.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(roots)

    code = f"import {module}"
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=20,
        env=env,
    )
    if proc.returncode == 0:
        return add_check("import", module, critical, "pass")
    detail = (proc.stderr or proc.stdout or "").strip().splitlines()
    err = detail[-1] if detail else f"import {module} failed"
    return add_check(
        "import",
        module,
        critical,
        "fail",
        diagnostics_fix(
            f"Install/fix Python dependency for {sys.executable}: {err}"
        ),
    )


def check_py_compile(path, *, critical=True):
    path = Path(path)
    if not path.is_file():
        return check_file(path, path.name, critical=critical)
    try:
        py_compile.compile(str(path), doraise=True)
    except py_compile.PyCompileError as exc:
        return add_check(
            "import",
            path.resolve(),
            critical,
            "fail",
            diagnostics_fix(f"Fix Python syntax/compile error: {exc.msg}"),
        )
    return add_check("import", path.resolve(), critical, "pass")


def check_binary_starts(path, expected_text, label, *, critical=True, allow_rc=None):
    path = Path(path)
    subject = path.resolve() if path.exists() else path
    if not path.is_file() or not os.access(path, os.X_OK):
        return add_check(
            "run",
            subject,
            critical,
            "fail",
            diagnostics_fix(f"Cannot smoke-test {label}; executable is missing or not executable"),
        )
    try:
        proc = subprocess.run(
            [str(path)],
            capture_output=True,
            timeout=10,
        )
    except Exception as exc:
        return add_check(
            "run",
            path.resolve(),
            critical,
            "fail",
            diagnostics_fix(f"{label} did not start: {exc}"),
        )

    raw = (proc.stdout or b"") + (proc.stderr or b"")
    output = raw.decode("utf-8", errors="replace")
    rc_ok = allow_rc is None or proc.returncode in allow_rc
    if rc_ok and expected_text in output:
        return add_check("run", path.resolve(), critical, "pass")
    return add_check(
        "run",
        path.resolve(),
        critical,
        "fail",
        diagnostics_fix(
            f"{label} started with rc={proc.returncode}, but expected banner text was not confirmed"
        ),
    )


def emit_report(model_id, report_checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": report_checks}))
    critical_failed = any(c["critical"] and c["status"] != "pass" for c in report_checks)
    sys.exit(1 if critical_failed else 0)


def main():
    print(f"=== preflight: {MODEL_NAME} ===")
    print(f"KI root: {KI_DIR}")
    print(f"Diagnostics: {DIAGNOSTICS}")

    print("\n[1] DayCent binaries")
    check_file(DDCENT, "DDcentEVI_rev491", kind="binary", critical=True, executable=True)
    check_file(DDLIST, "DDlist100_rev491", kind="binary", critical=True, executable=True)
    check_binary_starts(
        DDCENT,
        "DAILYDAYCENT SOIL ORGANIC MATTER",
        "DDcentEVI_rev491",
        critical=True,
        allow_rc={0},
    )
    check_binary_starts(
        DDLIST,
        "CENTURY List100",
        "DDlist100_rev491",
        critical=True,
        allow_rc={0, 2},
    )

    print("\n[2] KI files and diagnostics")
    for rel in (
        "SKILL.md",
        "knowledge_infrastructure.yaml",
        "dag.yaml",
        "diagnostics/triplets.yaml",
        "docs/format_spec.yaml",
        "tools/convert_forcing_to_daycent.py",
        "tools/convert_soil_to_daycent.py",
        "tools/run_daycent.py",
        "tools/parse_daycent_output.py",
    ):
        check_file(KI_DIR / rel, rel, critical=True)

    print("\n[3] Python imports used by KI tools")
    for module in (
        "numpy",
        "yaml",
        "ki_tools_common.load_forcing",
        "ki_tools_common.soil_utils",
        "ki_tools_common.validation",
    ):
        check_import(module, critical=True)

    print("\n[4] Tool syntax")
    for rel in (
        "tools/convert_forcing_to_daycent.py",
        "tools/convert_soil_to_daycent.py",
        "tools/run_daycent.py",
        "tools/parse_daycent_output.py",
    ):
        check_py_compile(KI_DIR / rel, critical=True)

    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    print(f"\n=== summary: {passed}/{len(checks)} passed, {failed} failed ===")
    if failed:
        print(f"Some preflight checks failed. Check {DIAGNOSTICS} for known fixes.")
    else:
        print("All preflight checks passed. Safe to proceed with real DayCent execution.")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
