#!/usr/bin/env python3
"""Preflight check for the GIFMod knowledge infrastructure."""

import json
import os
import py_compile
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


MODEL_ID = "GIFMod"
KI_DIR = Path(__file__).resolve().parent
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"
SOURCE_DIR = Path(os.environ["GIFMOD_SOURCE_DIR"]) if os.environ.get("GIFMOD_SOURCE_DIR") else None
BINARY_ENV = os.environ.get("GIFMOD_BINARY")
# REAL engine = patched fork with a headless driver (SKILL.md "Real engine"). Same lookup as
# tools/run_gifmod_engine.py: $GIFMOD_BINARY (direct) -> $GIFMOD_HEADLESS (wrapper) -> server wrapper.
HEADLESS_ENV = os.environ.get("GIFMOD_HEADLESS")
DEFAULT_WRAPPER = Path("KISSPATH_HOME/engine_builds_20261006/gifmod/install/gifmod_headless.sh")
RUN_ENGINE = KI_DIR / "tools" / "run_gifmod_engine.py"
DRIVER_MARK = b"HEADLESS: running forward model"


def fix(message):
    return f"{message}; see {DIAGNOSTICS} for recovery diagnostics"


def check(kind, subject, critical, passed, fix_text=""):
    subject = str(subject)
    status = "pass" if passed else "fail"
    shown = "WARN" if not passed and not critical else status.upper()
    print(f"  {shown:<5} {kind:<8} {subject}")
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
        with tempfile.TemporaryDirectory(prefix="gifmod_pyc_") as tmp:  # keep __pycache__ out of the KI
            py_compile.compile(str(path), cfile=str(Path(tmp) / "x.pyc"), doraise=True)
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


def check_source_available(critical=False):
    """Upstream source tree: only needed to REBUILD; the run uses the installed patched engine."""
    source_dir = first_source_dir()
    if source_dir is None:
        searched = [str(p) for p in candidate_source_dirs()]
        return None, check(
            "data",
            "GIFMod source repository (rebuild only)",
            critical,
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
            critical,
            False,
            fix("Set GIFMOD_SOURCE_DIR to the existing USEPA GIFMod source repository"),
        )
    if not (source_dir / "GIFMod.pro").is_file():
        return source_dir, check(
            "data",
            source_dir.resolve(),
            critical,
            False,
            fix("Set GIFMOD_SOURCE_DIR to the repository root containing GIFMod.pro"),
        )
    return source_dir, check("data", source_dir.resolve(), critical, True)


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


def has_driver(binary):
    tail = b""
    with open(binary, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            if DRIVER_MARK in tail + chunk:
                return True
            tail = chunk[-len(DRIVER_MARK):]
    return False


def wrapper_target(wrapper):
    """Same literal grammar as tools/run_gifmod_engine.py: bash/sh shebang, comments, literal
    'export NAME=value ...' / 'unset NAME ...' (no OMP_* etc.), ONE final 'exec /abs/binary "$@"'.
    Returns (binary or None, reason)."""
    import re
    shebang = re.compile(r"^#!(/bin/bash|/bin/sh|/usr/bin/env bash)\s*$")
    export = re.compile(r"^export( [A-Za-z_][A-Za-z0-9_]*=[A-Za-z0-9_./:,+-]*)+$")
    unset = re.compile(r"^unset( [A-Za-z_][A-Za-z0-9_]*)+$")
    exec_line = re.compile(r'^exec (/[A-Za-z0-9_./+-]+) "\$@"$')
    forbidden = re.compile(r"^(OMP_|GOMP_|KMP_|OPENBLAS_|MKL_)")
    try:
        lines = Path(wrapper).read_text(errors="replace").splitlines()
    except OSError as exc:
        return None, f"cannot read wrapper: {exc}"
    if not lines or not shebang.match(lines[0]):
        return None, "first line must be #!/bin/bash, #!/bin/sh or #!/usr/bin/env bash"
    body = [l.rstrip() for l in lines[1:] if l.strip() and not l.lstrip().startswith("#")]
    if not body:
        return None, "wrapper has no exec line"
    for l in body[:-1]:
        if export.match(l):
            names = [w.split("=", 1)[0] for w in l.split()[1:]]
        elif unset.match(l):
            names = l.split()[1:]
        else:
            return None, f"unsupported wrapper line (only literal export/unset before exec): {l!r}"
        if any(forbidden.match(n) for n in names):
            return None, "wrapper may not set thread variables (OMP_* etc.)"
    m = exec_line.match(body[-1])
    if not m:
        return None, f'last line must be exactly: exec /absolute/binary "$@" (found {body[-1]!r})'
    return Path(m.group(1)), ""


def check_real_engine():
    """The REAL (patched-fork, headless) engine: critical -- this KI has no other run path."""
    checks = []
    if BINARY_ENV:
        mode, launch, src = "direct", Path(BINARY_ENV).expanduser().absolute(), "$GIFMOD_BINARY"
    elif HEADLESS_ENV:
        mode, launch, src = "wrapper", Path(HEADLESS_ENV).expanduser().absolute(), "$GIFMOD_HEADLESS"
    else:
        mode, launch, src = "wrapper", DEFAULT_WRAPPER, "server default"
    hint = ("Install the patched headless GIFMod (SKILL.md 'Real engine') or set GIFMOD_BINARY / "
            "GIFMOD_HEADLESS to it")
    c = check_file(launch, f"GIFMod {mode} ({src})", critical=True, executable=True)
    checks.append(c)
    if c["status"] != "pass":
        return checks
    if mode == "direct":
        binary, why = launch, ""
    else:
        binary, why = wrapper_target(launch)
    if binary is None or not Path(binary).is_file():
        checks.append(check("binary", f"wrapper target of {launch}: {binary}", True, False,
                            fix(f"wrapper not accepted ({why or 'target missing'}); {hint}")))
        return checks
    binary = Path(binary)
    c = check_file(binary, "patched GIFMod binary", critical=True, executable=True)
    checks.append(c)
    if c["status"] != "pass":
        return checks
    checks.append(check_ldd(binary))
    ok = has_driver(binary)
    checks.append(check("binary", f"headless driver in {binary.resolve()}", True, ok,
                        "" if ok else fix(f"binary has no headless driver (unpatched upstream is GUI-only); {hint}")))
    for res in ("formulas.txt", "GIFModGUIPropList.csv", "templates/Simple_pond.wiz"):
        checks.append(check_file(binary.parent / res, f"GIFMod runtime resource {res}", critical=True, nonempty=True))
    if not all(c["status"] == "pass" for c in checks):
        return checks
    checks.append(check_smoke_run(launch if mode == "wrapper" else None, binary if mode == "direct" else None))
    return checks


def check_smoke_run(wrapper, binary):
    """End-to-end proof: official Simple_pond template, 30 days, through tools/run_gifmod_engine.py."""
    subject = "smoke run: run_gifmod_engine.py --wizard Simple_pond (30 days)"
    with tempfile.TemporaryDirectory(prefix="gifmod_preflight_") as tmp:
        cmd = [sys.executable, str(RUN_ENGINE), "--wizard", "Simple_pond",
               "--param", "project_start_date=1/1/2020 12:00 AM", "--param", "project_end_date=1/31/2020 12:00 AM",
               "--param", "ini_Depth=1", "--param", "Area=100", "--run-dir", str(Path(tmp) / "run"),
               "--timeout", "150"]
        cmd += ["--wrapper", str(wrapper)] if wrapper else ["--binary", str(binary)]
        # the tool has its own 150 s limit and kills its engine; on our watchdog (or Ctrl-C) it gets
        # SIGTERM so it can still clean up its engine processes by PID.
        p = subprocess.Popen(cmd, cwd=tmp, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            out, err = p.communicate(timeout=240)
        except BaseException as exc:
            p.terminate()
            try:
                p.communicate(timeout=60)
            except subprocess.TimeoutExpired:
                p.kill()
                p.communicate()
            if isinstance(exc, subprocess.TimeoutExpired):
                return check("run", subject, True, False, fix("smoke run did not finish within 240 s"))
            raise
        if p.returncode != 0:
            last = (err or out).strip().splitlines()[:2]
            return check("run", subject, True, False, fix(f"smoke run exit {p.returncode}: {' | '.join(last)[:300]}"))
        try:
            st = json.loads((Path(tmp) / "run" / "gifmod_engine_summary.json").read_text())["stats"]["experiment1"]["hydro"]
            good = (st["S_Pond"]["n"] == 3002 and st["S_Pond"]["min"] == st["S_Pond"]["max"] == 100.0
                    and st["H_Pond"]["min"] == st["H_Pond"]["max"] == 1.0)
        except (OSError, KeyError, ValueError) as exc:
            return check("run", subject, True, False, fix(f"smoke summary unreadable: {exc}"))
        return check("run", subject, True, good,
                     "" if good else fix("smoke run finished but pond storage/head are not 100 m3 / 1 m"))


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
        RUN_ENGINE,
    ):
        checks.append(check_tool_compiles(tool))
        checks.append(check_tool_help(tool))

    print("\n  REAL engine (patched fork, headless driver) -- critical:")
    engine_checks = check_real_engine()
    checks.extend(engine_checks)

    print("\n  Rebuild-only checks (non-critical):")
    source_dir, source_check = check_source_available(critical=False)
    checks.append(source_check)
    if source_dir is not None and source_check["status"] == "pass":
        checks.append(check_file(source_dir / "GIFMod.pro", "GIFMod qmake project", critical=False, nonempty=True))
        checks.append(check_dir(source_dir / "src", "GIFMod source tree", critical=False, nonempty=True))
        checks.append(check_dir(source_dir / "src" / "GUI", "GIFMod GUI source tree", critical=False, nonempty=True))
    checks.append(check_build_helper("make", "Install build-essential/make for GIFMod rebuilds"))
    checks.append(check_qmake())

    passed = sum(1 for c in checks if c["status"] == "pass")
    critical_failed = sum(1 for c in checks if c["status"] != "pass" and c.get("critical"))
    warned = len(checks) - passed - critical_failed
    engine_ok = all(c["status"] == "pass" for c in engine_checks)
    print(f"\n  Results: {passed} passed, {critical_failed} critical failed, {warned} warnings")
    print(f"  REAL engine (tools/run_gifmod_engine.py): {'READY' if engine_ok else 'NOT READY'}")
    if critical_failed:
        print(f"  STATUS: PREFLIGHT FAILED - fix blockers above; start with {DIAGNOSTICS}")
    elif warned:
        print("  STATUS: PREFLIGHT PASSED WITH WARNINGS - engine ready; WARN lines only matter for rebuilding")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with GIFMod execution")
    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
