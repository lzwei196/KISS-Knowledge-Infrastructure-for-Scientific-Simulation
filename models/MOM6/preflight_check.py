#!/usr/bin/env python3
"""Contract preflight check for the MOM6 knowledge infrastructure."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


MODEL_ID = "MOM6"
KI_DIR = Path(__file__).resolve().parent
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"
PYTHON_ENV = Path("KISSPATH_PYTHON_ENV/bin/python3")
BINARY = Path(
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/"
    "MOM6/source/repo/.testing/build/symmetric/MOM6"
)


def fix_hint(message):
    return f"{message}; check {TRIPLETS} for known MOM6 recovery steps."


def status_line(status, label, subject, fix=""):
    marker = "OK" if status == "pass" else "FAIL"
    print(f"  {marker:<5} {label}: {subject}")
    if status == "fail" and fix:
        print(f"        Fix: {fix}")


def add_check(checks, kind, subject, critical, passed, fix, label):
    status = "pass" if passed else "fail"
    subject = str(subject)
    check = {
        "kind": kind,
        "subject": subject,
        "critical": bool(critical),
        "status": status,
        "fix": "" if passed else fix,
    }
    checks.append(check)
    status_line(status, label, subject, check["fix"])
    return passed


def check_file(checks, path, label, critical=True, executable=False):
    path = Path(path)
    subject = path.resolve(strict=False)
    if not path.is_file():
        return add_check(
            checks,
            "binary" if executable else "data",
            subject,
            critical,
            False,
            fix_hint(f"restore or rebuild missing file {path}"),
            label,
        )
    if executable and not os.access(path, os.X_OK):
        return add_check(
            checks,
            "binary",
            subject,
            critical,
            False,
            fix_hint(f"make executable with chmod +x {path}"),
            label,
        )
    return add_check(
        checks,
        "binary" if executable else "data",
        subject,
        critical,
        True,
        "",
        label,
    )


def check_dir(checks, path, label, critical=True, nonempty=False):
    path = Path(path)
    subject = path.resolve(strict=False)
    if not path.is_dir():
        return add_check(
            checks,
            "data",
            subject,
            critical,
            False,
            fix_hint(f"restore missing directory {path}"),
            label,
        )
    if nonempty and not any(path.iterdir()):
        return add_check(
            checks,
            "data",
            subject,
            critical,
            False,
            fix_hint(f"populate required directory {path}"),
            label,
        )
    detail = f"{subject} ({len(list(path.iterdir()))} items)"
    return add_check(checks, "data", detail, critical, True, "", label)


def run_subprocess(cmd, timeout=10, cwd=None):
    try:
        return subprocess.run(
            [str(part) for part in cmd],
            cwd=str(cwd or KI_DIR),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        return exc
    except subprocess.TimeoutExpired as exc:
        return exc


def check_python_imports(checks):
    interpreter_ready = PYTHON_ENV.is_file() and os.access(PYTHON_ENV, os.X_OK)
    add_check(
        checks,
        "run",
        str(PYTHON_ENV),
        True,
        interpreter_ready,
        fix_hint(f"restore executable HydroCraft Python interpreter at {PYTHON_ENV}"),
        "HydroCraft Python interpreter",
    )
    if not interpreter_ready:
        return

    imports = ["numpy", "netCDF4", "scipy", "yaml"]
    code = "import " + ", ".join(imports)
    result = run_subprocess([PYTHON_ENV, "-c", code], timeout=15)
    passed = not isinstance(result, Exception) and result.returncode == 0
    fix = fix_hint(
        "install required Python packages into "
        f"{PYTHON_ENV.parent}: " + ", ".join(imports)
    )
    add_check(
        checks,
        "import",
        f"{PYTHON_ENV}: {', '.join(imports)}",
        True,
        passed,
        fix,
        "Python package imports",
    )
    if not passed and not isinstance(result, FileNotFoundError):
        output = getattr(result, "stdout", "") or str(result)
        print("        Import output: " + output.strip().splitlines()[-1][:240])


def check_tool_import(checks, relpath):
    tool_path = KI_DIR / relpath
    if not check_file(checks, tool_path, f"Tool file {relpath}", True, False):
        return

    code = (
        "import importlib.util, pathlib; "
        f"p=pathlib.Path({str(tool_path)!r}); "
        "spec=importlib.util.spec_from_file_location(p.stem, p); "
        "mod=importlib.util.module_from_spec(spec); "
        "spec.loader.exec_module(mod)"
    )
    result = run_subprocess([PYTHON_ENV, "-c", code], timeout=15)
    passed = not isinstance(result, Exception) and result.returncode == 0
    add_check(
        checks,
        "import",
        str(tool_path.resolve(strict=False)),
        True,
        passed,
        fix_hint(f"fix imports or syntax in {relpath}"),
        f"Import {relpath}",
    )
    if not passed and not isinstance(result, FileNotFoundError):
        output = getattr(result, "stdout", "") or str(result)
        print("        Import output: " + output.strip().splitlines()[-1][:240])


def check_binary_startup(checks):
    binary = BINARY.resolve(strict=False)
    result = run_subprocess([binary, "--help"], timeout=5)
    output = getattr(result, "stdout", "") if not isinstance(result, FileNotFoundError) else ""
    if isinstance(result, subprocess.TimeoutExpired):
        passed = False
        fix = fix_hint("MOM6 binary did not return from cheap startup check within 5s")
    elif isinstance(result, FileNotFoundError):
        passed = False
        fix = fix_hint(f"MOM6 binary cannot be executed at {binary}")
    elif "error while loading shared libraries" in output:
        passed = False
        fix = fix_hint("repair missing shared libraries for the MOM6 executable")
    else:
        # With no run directory MOM6 reaches FMS input.nml loading and exits.
        # That is enough to prove the executable starts and links cheaply.
        passed = result.returncode == 0 or "input.nml" in output or "FATAL" in output
        fix = fix_hint("run the binary from a MOM6 run directory with input.nml if this fails")

    add_check(
        checks,
        "run",
        f"{binary} --help",
        True,
        passed,
        fix,
        "MOM6 cheap startup",
    )


def check_shared_libraries(checks):
    binary = BINARY.resolve(strict=False)
    ldd = shutil.which("ldd")
    if not ldd:
        add_check(
            checks,
            "run",
            "ldd",
            False,
            False,
            "install ldd or verify MOM6 shared-library dependencies manually",
            "ldd availability",
        )
        return
    result = run_subprocess([ldd, binary], timeout=10)
    output = getattr(result, "stdout", "") if not isinstance(result, Exception) else str(result)
    passed = not isinstance(result, Exception) and result.returncode == 0 and "not found" not in output
    add_check(
        checks,
        "run",
        f"ldd {binary}",
        True,
        passed,
        fix_hint("install or expose missing MOM6 shared libraries in LD_LIBRARY_PATH"),
        "MOM6 shared libraries",
    )


def check_mpi_launcher(checks):
    found = None
    for name in ("mpirun", "mpiexec", "srun"):
        path = shutil.which(name)
        if path:
            found = Path(path).resolve(strict=False)
            break
    add_check(
        checks,
        "run",
        found or "mpirun/mpiexec/srun",
        False,
        found is not None,
        "install OpenMPI/MPICH or run serial MOM6 only",
        "MPI launcher",
    )


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    critical_failed = any(c["critical"] and c["status"] != "pass" for c in checks)
    sys.exit(1 if critical_failed else 0)


def main():
    checks = []
    print(f"{' PREFLIGHT: MOM6 ':=^60}")
    print()

    check_file(checks, KI_DIR / "SKILL.md", "KI instructions", True, False)
    check_file(checks, KI_DIR / "knowledge_infrastructure.yaml", "KI manifest", True, False)
    check_file(checks, KI_DIR / "dag.yaml", "KI DAG", True, False)
    check_file(checks, TRIPLETS, "Diagnostics triplets", True, False)
    check_dir(checks, KI_DIR / "tools", "KI tools directory", True, True)

    check_file(checks, BINARY, "MOM6 executable", True, True)
    check_shared_libraries(checks)
    check_binary_startup(checks)
    check_mpi_launcher(checks)

    check_python_imports(checks)
    for relpath in (
        "tools/run_mom6.py",
        "tools/forcing_converter.py",
        "tools/topography_converter.py",
        "tools/output_parser.py",
    ):
        check_tool_import(checks, relpath)

    failures = [c for c in checks if c["status"] != "pass"]
    critical_failures = [c for c in failures if c["critical"]]
    print()
    print(f"  Results: {len(checks) - len(failures)} passed, {len(failures)} failed")
    if critical_failures:
        print(f"  STATUS: PREFLIGHT FAILED - check {TRIPLETS} for recovery guidance.")
    else:
        print("  STATUS: PREFLIGHT PASSED - MOM6 binary and KI tooling are ready.")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
