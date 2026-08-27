#!/usr/bin/env python3
"""Preflight check for the GIFMod knowledge infrastructure."""

import json
import os
import py_compile
import shutil
import subprocess
import sys
from pathlib import Path


MODEL_ID = "GIFMod"
KI_DIR = Path(__file__).resolve().parent
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"
SOURCE_DIR = Path(os.environ["GIFMOD_SOURCE_DIR"]) if os.environ.get("GIFMOD_SOURCE_DIR") else None
BINARY_ENV = os.environ.get("GIFMOD_BINARY")


def fix(message):
    return f"{message}; see {DIAGNOSTICS} for recovery diagnostics"


def check(kind, subject, critical, passed, fix_text=""):
    subject = str(subject)
    status = "pass" if passed else "fail"
    print(f"  {status.upper():<5} {kind:<8} {subject}")
    if not passed and fix_text:
        print(f"        Fix: {fix_text}")
    return {
        "kind": kind,
        "subject": subject,
        "critical": bool(critical),
        "status": status,
        "fix": "" if passed else fix_text,
    }


def check_file(path, label, critical=True, executable=False, nonempty=False):
    path = Path(path)
    subject = path.resolve() if path.exists() else path
    if not path.is_file():
        return check("data", subject, critical, False, fix(f"Restore required file: {label}"))
    if executable and not os.access(path, os.X_OK):
        return check("binary", subject.resolve(), critical, False, fix(f"Run chmod +x {path}"))
    if nonempty and path.stat().st_size == 0:
        return check("data", subject.resolve(), critical, False, fix(f"Populate required file: {label}"))
    return check("binary" if executable else "data", subject.resolve(), critical, True)


def check_dir(path, label, critical=True, nonempty=True):
    path = Path(path)
    subject = path.resolve() if path.exists() else path
    if not path.is_dir():
        return check("data", subject, critical, False, fix(f"Restore required directory: {label}"))
    if nonempty and not any(path.iterdir()):
        return check("data", subject.resolve(), critical, False, fix(f"Populate required directory: {label}"))
    return check("data", subject.resolve(), critical, True)


def check_import(module, critical=True):
    try:
        __import__(module)
    except ImportError as exc:
        return check("import", module, critical, False, fix(f"Install Python module {module}: {exc}"))
    return check("import", module, critical, True)


def check_tool_compiles(path):
    path = Path(path)
    subject = path.resolve() if path.exists() else path
    if not path.is_file():
        return check("data", subject, True, False, fix(f"Restore KI tool {path}"))
    try:
        py_compile.compile(str(path), doraise=True)
    except py_compile.PyCompileError as exc:
        return check("import", subject.resolve(), True, False, fix(f"Fix Python syntax/importability: {exc.msg}"))
    return check("import", subject.resolve(), True, True)


def check_tool_help(path):
    path = Path(path)
    subject = path.resolve() if path.exists() else path
    if not path.is_file():
        return check("run", subject, True, False, fix(f"Restore KI tool {path}"))
    try:
        result = subprocess.run(
            [sys.executable, str(path), "--help"],
            cwd=str(KI_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return check("run", subject.resolve(), True, False, fix(f"{path} --help timed out"))
    except OSError as exc:
        return check("run", subject.resolve(), True, False, fix(f"Cannot start {path}: {exc}"))
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        message = detail[0] if detail else f"exit code {result.returncode}"
        return check("run", subject.resolve(), True, False, fix(f"{path} --help failed: {message}"))
    return check("run", subject.resolve(), True, True)


def candidate_source_dirs():
    candidates = []
    if SOURCE_DIR is not None:
        candidates.append(SOURCE_DIR)
    candidates.extend(
        [
            KI_DIR / "source" / "repo",
            KI_DIR / "source",
            KI_DIR.parent / "source" / "repo",
            KI_DIR.parent / "source",
            KI_DIR.parent / "repo",
        ]
    )
    return candidates


def first_source_dir():
    for candidate in candidate_source_dirs():
        if (candidate / "GIFMod.pro").is_file():
            return candidate
    return SOURCE_DIR


def binary_candidates(source_dir=None):
    candidates = []
    if BINARY_ENV:
        candidates.append(Path(BINARY_ENV))
    if source_dir:
        candidates.extend(
            [
                source_dir / "bindata" / "GIFMod",
                source_dir / "builds" / "release" / "GIFMod",
                source_dir / "build" / "GIFMod",
                source_dir / "build" / "release" / "GIFMod",
            ]
        )
    candidates.extend(
        [
            KI_DIR / "bin" / "GIFMod",
            KI_DIR / "GIFMod",
            KI_DIR.parent / "bin" / "GIFMod",
        ]
    )
    for name in ("GIFMod", "gifmod"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    return candidates


def first_binary(source_dir=None):
    for candidate in binary_candidates(source_dir):
        if not candidate:
            continue
        path = Path(candidate)
        if path.is_file():
            return path
    return None


def check_source_available():
    source_dir = first_source_dir()
    if source_dir is None:
        searched = [str(p) for p in candidate_source_dirs()]
        return None, check(
            "data",
            "GIFMod source repository",
            True,
            False,
            fix(
                "Install the USEPA GIFMod source repository in this KI/model tree, "
                f"or set GIFMOD_SOURCE_DIR to a directory containing GIFMod.pro. Searched: {searched}"
            ),
        )
    source_dir = Path(source_dir)
    if not source_dir.is_dir():
        return source_dir, check(
            "data",
            source_dir,
            True,
            False,
            fix("Set GIFMOD_SOURCE_DIR to the existing USEPA GIFMod source repository"),
        )
    if not (source_dir / "GIFMod.pro").is_file():
        return source_dir, check(
            "data",
            source_dir.resolve(),
            True,
            False,
            fix("Set GIFMOD_SOURCE_DIR to the repository root containing GIFMod.pro"),
        )
    return source_dir, check("data", source_dir.resolve(), True, True)


def check_binary_exists(source_dir=None):
    binary = first_binary(source_dir)
    if binary is None:
        searched = [str(c) for c in binary_candidates(source_dir)]
        return None, check(
            "binary",
            "GIFMod executable",
            True,
            False,
            fix(
                "Build GIFMod from the source repository and set GIFMOD_BINARY to the executable realpath. "
                f"Searched: {searched}"
            ),
        )
    subject = binary.resolve()
    if not os.access(binary, os.X_OK):
        return binary, check("binary", subject, True, False, fix(f"Run chmod +x {binary}"))
    return binary, check("binary", subject, True, True)


def check_ldd(binary):
    try:
        result = subprocess.run(
            ["ldd", str(binary)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return check("binary", binary.resolve(), True, False, fix(f"Could not inspect shared libraries: {exc}"))
    output = f"{result.stdout}\n{result.stderr}"
    if result.returncode != 0 or "not found" in output:
        missing = [line.strip() for line in output.splitlines() if "not found" in line]
        detail = "; ".join(missing) if missing else output.strip().splitlines()[0]
        return check("binary", binary.resolve(), True, False, fix(f"Resolve missing shared libraries: {detail}"))
    return check("binary", binary.resolve(), True, True)


def check_binary_starts(binary):
    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        result = subprocess.run(
            [str(binary), "--help"],
            cwd=str(binary.parent),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return check("run", binary.resolve(), True, True)
    except OSError as exc:
        return check("run", binary.resolve(), True, False, fix(f"Cannot start GIFMod executable: {exc}"))
    if result.returncode == 0:
        return check("run", binary.resolve(), True, True)
    detail_lines = (result.stderr or result.stdout).strip().splitlines()
    symbol_errors = [line for line in detail_lines if "symbol lookup error" in line]
    detail = symbol_errors[-1] if symbol_errors else (detail_lines[-1] if detail_lines else f"exit code {result.returncode}")
    return check(
        "run",
        binary.resolve(),
        True,
        False,
        fix(
            "GIFMod executable fails its cheap start check. Rebuild with the current Qt5/libstdc++ "
            f"runtime or fix LD_LIBRARY_PATH. First error: {detail}"
        ),
    )


def check_build_helper(name, install_hint):
    path = shutil.which(name)
    if path:
        return check("binary", Path(path).resolve(), False, True)
    return check("binary", name, False, False, fix(install_hint))


def check_qmake():
    for name in ("qmake-qt5", "qmake"):
        path = shutil.which(name)
        if path:
            return check("binary", Path(path).resolve(), False, True)
    return check(
        "binary",
        "qmake-qt5 or qmake",
        False,
        False,
        fix("Install qt5-qmake/qtbase5-dev or provide qmake-qt5 for GIFMod rebuilds"),
    )


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    critical_ok = all(c["status"] == "pass" or not c.get("critical") for c in checks)
    sys.exit(0 if critical_ok else 1)


def main():
    print(f"{' PREFLIGHT: GIFMod ':=^60}")
    checks = []

    checks.append(check_file(KI_DIR / "SKILL.md", "KI skill", critical=True, nonempty=True))
    checks.append(check_file(KI_DIR / "knowledge_infrastructure.yaml", "KI manifest", critical=True, nonempty=True))
    checks.append(check_file(KI_DIR / "dag.yaml", "DAG", critical=True, nonempty=True))
    checks.append(check_file(DIAGNOSTICS, "diagnostic triplets", critical=True, nonempty=True))
    checks.append(check_file(KI_DIR / "docs" / "format_spec.yaml", "format spec", critical=True, nonempty=True))
    checks.append(check_dir(KI_DIR / "tools", "KI tools directory", critical=True, nonempty=True))

    for module in ("argparse", "csv", "json", "subprocess", "datetime"):
        checks.append(check_import(module, critical=True))

    for tool in (
        KI_DIR / "tools" / "convert_forcing.py",
        KI_DIR / "tools" / "convert_soil_params.py",
        KI_DIR / "tools" / "parse_gifmod_output.py",
        KI_DIR / "tools" / "run_gifmod.py",
    ):
        checks.append(check_tool_compiles(tool))
        checks.append(check_tool_help(tool))

    source_dir, source_check = check_source_available()
    checks.append(source_check)
    if source_dir is not None and source_check["status"] == "pass":
        checks.append(check_file(source_dir / "GIFMod.pro", "GIFMod qmake project", critical=True, nonempty=True))
        checks.append(check_dir(source_dir / "src", "GIFMod source tree", critical=True, nonempty=True))
        checks.append(check_dir(source_dir / "src" / "GUI", "GIFMod GUI source tree", critical=True, nonempty=True))
    checks.append(check_build_helper("make", "Install build-essential/make for GIFMod rebuilds"))
    checks.append(check_qmake())

    binary, binary_check = check_binary_exists(source_dir if source_check["status"] == "pass" else None)
    checks.append(binary_check)
    if binary is not None and binary_check["status"] == "pass":
        checks.append(check_ldd(binary))
        checks.append(check_binary_starts(binary))

    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    print(f"\n  Results: {passed} passed, {failed} failed")
    if failed:
        print(f"  STATUS: PREFLIGHT FAILED - fix blockers above; start with {DIAGNOSTICS}")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with GIFMod execution")
    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
