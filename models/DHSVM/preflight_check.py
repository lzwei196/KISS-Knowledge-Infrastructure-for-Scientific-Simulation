#!/usr/bin/env python3
"""Preflight check for DHSVM KI."""

import json
import os
import py_compile
import subprocess
import sys
from pathlib import Path


MODEL_ID = "DHSVM"
KI_DIR = Path(__file__).resolve().parent
MODEL_ROOT = KI_DIR.parent
HYDRO_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python3")
PYTHON_SITE = Path("KISSPATH_PYTHON_ENV/lib/python3.12/site-packages")
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"

BINARY_CANDIDATES = [
    MODEL_ROOT / "source" / "repo" / "build" / "DHSVM" / "sourcecode" / "DHSVM",
    MODEL_ROOT / "source" / "repo" / "build_fresh" / "DHSVM" / "sourcecode" / "DHSVM",
    MODEL_ROOT / "source" / "build" / "DHSVM" / "sourcecode" / "DHSVM",
]

REQUIRED_FILES = [
    KI_DIR / "SKILL.md",
    KI_DIR / "knowledge_infrastructure.yaml",
    KI_DIR / "dag.yaml",
    DIAGNOSTICS,
    KI_DIR / "docs" / "format_spec.yaml",
]

TOOL_FILES = [
    KI_DIR / "tools" / "build_terrain.py",
    KI_DIR / "tools" / "build_stream_network.py",
    KI_DIR / "tools" / "convert_forcing.py",
    KI_DIR / "tools" / "convert_soil_params.py",
    KI_DIR / "tools" / "generate_config.py",
    KI_DIR / "tools" / "parse_output.py",
    KI_DIR / "tools" / "run_dhsvm.py",
]

REQUIRED_IMPORTS = [
    ("numpy", "numpy arrays for terrain/forcing/soil tools"),
    ("pandas", "table IO for forcing/soil/output tools"),
    ("matplotlib", "plotting dependency listed for DHSVM KI tools"),
    ("yaml", "PyYAML for KI YAML metadata and diagnostics"),
    ("rasterio", "raster IO for terrain builder"),
    ("pysheds", "flow accumulation for stream-network builder"),
    ("pyflwdir", "flow-direction topology for stream-network builder"),
]


checks = []


def add_check(kind, subject, critical, status, fix=""):
    checks.append(
        {
            "kind": kind,
            "subject": str(subject),
            "critical": bool(critical),
            "status": status,
            "fix": fix,
        }
    )


def print_result(status, label, detail="", fix=""):
    prefix = "OK" if status == "pass" else "FAIL"
    print(f"  {prefix:<5} {label}{': ' + detail if detail else ''}")
    if status != "pass" and fix:
        print(f"        Fix: {fix}")


def emit_report(model_id, report_checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": report_checks}))
    sys.exit(
        0
        if all(c["status"] == "pass" or not c.get("critical") for c in report_checks)
        else 1
    )


def check_file(path, label, critical=True, executable=False):
    path = Path(path)
    if not path.is_file():
        fix = f"Restore {path}; check {DIAGNOSTICS} for recovery guidance."
        add_check("data", path, critical, "fail", fix)
        print_result("fail", label, f"missing at {path}", fix)
        return False
    if executable and not os.access(path, os.X_OK):
        fix = f"Run chmod +x {path}; check {DIAGNOSTICS} if the binary was rebuilt."
        add_check("binary", path.resolve(), critical, "fail", fix)
        print_result("fail", label, f"not executable at {path}", fix)
        return False
    kind = "binary" if executable else "data"
    subject = path.resolve() if executable else path
    add_check(kind, subject, critical, "pass")
    print_result("pass", label, str(subject))
    return True


def check_dir(path, label, critical=True):
    path = Path(path)
    if path.is_dir() and any(path.iterdir()):
        add_check("data", path, critical, "pass")
        print_result("pass", label, f"{path} ({len(list(path.iterdir()))} items)")
        return True
    fix = f"Restore populated directory {path}; check {DIAGNOSTICS} for recovery guidance."
    add_check("data", path, critical, "fail", fix)
    print_result("fail", label, f"missing or empty at {path}", fix)
    return False


def find_binary():
    env_binary = os.environ.get("DHSVM_BINARY")
    candidates = [Path(env_binary)] if env_binary else []
    candidates.extend(BINARY_CANDIDATES)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def check_binary_start(binary):
    subject = Path(binary).resolve() if Path(binary).exists() else Path(binary)
    if not Path(binary).is_file() or not os.access(binary, os.X_OK):
        fix = (
            f"Build DHSVM under {MODEL_ROOT / 'source' / 'repo'} or set DHSVM_BINARY "
            f"to the executable; check {DIAGNOSTICS}."
        )
        add_check("run", subject, True, "fail", fix)
        print_result("fail", "DHSVM startup", f"cannot start {binary}", fix)
        return
    try:
        proc = subprocess.run(
            [str(binary)],
            cwd=str(KI_DIR),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except subprocess.TimeoutExpired:
        fix = f"Investigate hung executable {subject}; check {DIAGNOSTICS}."
        add_check("run", subject, True, "fail", fix)
        print_result("fail", "DHSVM startup", "timed out on usage check", fix)
        return
    output = f"{proc.stdout}\n{proc.stderr}"
    if "Usage:" in output and "inputfile" in output:
        add_check("run", subject, True, "pass")
        print_result("pass", "DHSVM startup", "usage check completed")
        return
    fix = f"Expected DHSVM usage text from {subject}; rebuild or check {DIAGNOSTICS}."
    add_check("run", subject, True, "fail", fix)
    print_result("fail", "DHSVM startup", "usage text not detected", fix)


def check_import(module, label, critical=True):
    if not HYDRO_PYTHON.is_file():
        fix = f"Restore HydroCraft Python interpreter at {HYDRO_PYTHON}."
        add_check("import", module, critical, "fail", fix)
        print_result("fail", f"import {module}", f"missing interpreter {HYDRO_PYTHON}", fix)
        return
    code = (
        "import sys;"
        f"sys.path.insert(0, {str(PYTHON_SITE)!r});"
        f"__import__({module!r})"
    )
    proc = subprocess.run(
        [str(HYDRO_PYTHON), "-c", code],
        cwd=str(KI_DIR),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if proc.returncode == 0:
        add_check("import", module, critical, "pass")
        print_result("pass", f"import {module}", label)
        return
    error = (proc.stderr or proc.stdout).strip().splitlines()[-1:]
    fix = (
        f"Install {module.split('.')[0]} into {HYDRO_PYTHON}; "
        f"check {DIAGNOSTICS} for known environment fixes."
    )
    detail = error[0] if error else f"exit {proc.returncode}"
    add_check("import", module, critical, "fail", fix)
    print_result("fail", f"import {module}", detail, fix)


def check_tool_compile(path):
    path = Path(path)
    if not path.is_file():
        fix = f"Restore KI tool {path}; check {DIAGNOSTICS}."
        add_check("data", path, True, "fail", fix)
        print_result("fail", f"tool {path.name}", f"missing at {path}", fix)
        return
    try:
        py_compile.compile(str(path), doraise=True)
    except py_compile.PyCompileError as exc:
        fix = f"Fix Python syntax in {path}; check {DIAGNOSTICS}."
        add_check("import", path, True, "fail", fix)
        print_result("fail", f"tool {path.name}", str(exc), fix)
        return
    add_check("import", path, True, "pass")
    print_result("pass", f"tool {path.name}", "compiles")


def main():
    print(f"{' PREFLIGHT: DHSVM ':=^60}")
    print()

    binary = find_binary()
    check_dir(KI_DIR / "tools", "KI tools directory")
    check_file(binary, "DHSVM binary", critical=True, executable=True)
    check_binary_start(binary)

    for required_file in REQUIRED_FILES:
        check_file(required_file, required_file.relative_to(KI_DIR), critical=True)

    for tool_file in TOOL_FILES:
        check_tool_compile(tool_file)

    for module, label in REQUIRED_IMPORTS:
        check_import(module, label, critical=True)

    print()
    print(f"  INFO  Diagnostics recovery file: {DIAGNOSTICS}")

    failed = [c for c in checks if c["status"] != "pass"]
    print(f"  Results: {len(checks) - len(failed)} passed, {len(failed)} failed")
    if failed:
        print("  STATUS: PREFLIGHT FAILED - fix the issues above before running")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with model execution")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
