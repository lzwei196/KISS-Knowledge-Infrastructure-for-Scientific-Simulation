#!/usr/bin/env python3
"""Preflight check for the GeoClaw KI."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


MODEL_ID = "GeoClaw"
KI_DIR = Path(__file__).resolve().parent
# GeoClaw is Clawpack source + gfortran + a Python with clawpack; xgeoclaw is compiled
# per case by `make .exe`. Lookup, same as the official test cases: $CLAW_PYTHON / $CLAW
# -> the server's Clawpack venv / source tree. Explicit values are used as-is (no
# fallback). The venv python is executed as given (not its realpath).
GEOCLAW_WORK = "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/GeoClaw"


def env_path(name: str, default: str) -> Path:
    """Default only when unset; a set value is used as given; set-but-empty fails later."""
    value = os.environ.get(name)
    if value is None:
        return Path(default)
    if not value:
        return Path(f"<{name} is set but empty>")
    return Path(os.path.abspath(value))


CLAW_PYTHON = env_path("CLAW_PYTHON", GEOCLAW_WORK + "/venv/bin/python")
CLAW_DIR = env_path("CLAW", GEOCLAW_WORK + "/clawpack")
# run_geoclaw.py runs [$FC, "--version"] (FC default gfortran), so FC is one executable.
FC = os.environ.get("FC", "gfortran")
# clawutil Makefile.common: CLAW_FC ?= $(FC) compiles, LINK ?= $(CLAW_FC) links. `?=` keeps
# an explicitly set (even empty) value, so only an unset variable takes the default.
CLAW_FC = os.environ.get("CLAW_FC", FC)
LINK = os.environ.get("LINK", CLAW_FC)
# What `make .exe` needs from $CLAW: (relative path, is_directory)
CLAW_SOURCES = [
    ("clawutil/src/Makefile.common", False),
    ("clawutil/src/check_src.py", False),
    ("geoclaw/src/2d/shallow/Makefile.geoclaw", False),
    ("amrclaw/src/2d", True),
    ("riemann/src/rpn2_geoclaw.f", False),
    ("riemann/src/rpt2_geoclaw.f", False),
    ("riemann/src/geoclaw_riemann_utils.f", False),
]
MAKEFILE_LIBS = {"$(AMRLIB)": "amrclaw/src/2d", "$(GEOLIB)": "geoclaw/src/2d/shallow"}
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"
DEFAULT_BINARY = Path(
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/GeoClaw/source/repo/"
    "examples/tsunami/chile2010/xgeoclaw"
)


def fix_text(message: str) -> str:
    return f"{message}; recovery details: {DIAGNOSTICS}"


def emit_report(model_id: str, checks: list[dict[str, object]]) -> None:
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    has_failed_critical = any(c["status"] == "fail" and c.get("critical") for c in checks)
    sys.exit(1 if has_failed_critical else 0)


def make_check(kind: str, subject: str, critical: bool, ok: bool, fix: str = "") -> dict[str, object]:
    return {
        "kind": kind,
        "subject": subject,
        "critical": critical,
        "status": "pass" if ok else "fail",
        "fix": "" if ok else fix,
    }


def read_manifest_binary() -> Path:
    manifest = KI_DIR / "knowledge_infrastructure.yaml"
    if not manifest.is_file():
        return DEFAULT_BINARY

    in_binary = False
    for raw_line in manifest.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if stripped == "binary:":
            in_binary = True
            continue
        if in_binary and stripped.startswith("path:"):
            value = stripped.split(":", 1)[1].strip().strip("'\"")
            return Path(value)
        if in_binary and raw_line and not raw_line.startswith(" "):
            break
    return DEFAULT_BINARY


def check_file(
    path: Path, label: str, critical: bool = True, executable: bool = False, keep_path: bool = False
) -> dict[str, object]:
    real_subject = str(path) if keep_path else os.path.realpath(path)
    if not path.is_file():
        print(f"  FAIL  {label}: not found at {path}")
        return make_check(
            "binary" if executable else "data",
            real_subject,
            critical,
            False,
            fix_text(f"Restore or update required path: {path}"),
        )
    if executable and not os.access(path, os.X_OK):
        print(f"  FAIL  {label}: exists but is not executable: {path}")
        return make_check(
            "binary",
            real_subject,
            critical,
            False,
            fix_text(f"Run chmod +x {path} or rebuild the GeoClaw executable"),
        )

    print(f"  OK    {label}: {real_subject}")
    return make_check("binary" if executable else "data", real_subject, critical, True)


def makefile_geoclaw_sources() -> list[str]:
    """Every $(AMRLIB)/... and $(GEOLIB)/... source file Makefile.geoclaw compiles."""
    makefile = CLAW_DIR / "geoclaw/src/2d/shallow/Makefile.geoclaw"
    try:
        text = makefile.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    found = []
    for token in re.findall(r"\$\((?:AMRLIB|GEOLIB)\)/[A-Za-z0-9_./-]+", text):
        lib, rel = token.split("/", 1)
        path = f"{MAKEFILE_LIBS[lib]}/{rel}"
        if path not in found:
            found.append(path)
    return found


def check_claw_sources() -> dict[str, object]:
    try:
        missing = [
            rel for rel, is_dir in CLAW_SOURCES
            if not ((CLAW_DIR / rel).is_dir() if is_dir else (CLAW_DIR / rel).is_file())
        ]
        listed = makefile_geoclaw_sources()
        missing += [rel for rel in listed if not (CLAW_DIR / rel).is_file()]
    except OSError as exc:
        missing, listed = [f"(cannot inspect: {exc})"], []
    if not missing and not listed:
        missing = ["source list in geoclaw/src/2d/shallow/Makefile.geoclaw (none found)"]
    if len(missing) > 8:
        missing = missing[:8] + [f"... {len(missing) - 8} more"]
    subject = f"Clawpack source tree {CLAW_DIR}"
    if missing:
        print(f"  FAIL  Clawpack source tree ($CLAW): missing {', '.join(missing)} under {CLAW_DIR}")
        return make_check(
            "data",
            subject,
            True,
            False,
            fix_text(
                f"make .exe compiles xgeoclaw from $CLAW; missing {', '.join(missing)} under "
                f"{CLAW_DIR}. Set CLAW to a Clawpack source tree (server default "
                f"{GEOCLAW_WORK}/clawpack; see its setup_env.sh)"
            ),
        )
    print(f"  OK    Clawpack source tree ($CLAW): {CLAW_DIR} ({len(listed)} Makefile.geoclaw sources present)")
    return make_check("data", subject, True, True)


def check_python_import(module: str, critical: bool = True) -> dict[str, object]:
    subject = f"{CLAW_PYTHON} import {module}"
    if not CLAW_PYTHON.is_file() or not os.access(CLAW_PYTHON, os.X_OK):
        print(f"  FAIL  Python interpreter: {CLAW_PYTHON} missing or not executable")
        return make_check(
            "import",
            subject,
            critical,
            False,
            fix_text(
                f"Restore the Clawpack Python at {CLAW_PYTHON} or set CLAW_PYTHON to a Python with clawpack"
            ),
        )

    try:
        proc = subprocess.run(
            [str(CLAW_PYTHON), "-c", f"import {module}"],
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        print(f"  FAIL  Clawpack Python import: {module}: {exc}")
        return make_check(
            "import", subject, critical, False,
            fix_text(f"Import of {module} with {CLAW_PYTHON} did not finish: {exc}"),
        )
    if proc.returncode == 0:
        print(f"  OK    Clawpack Python import: {module}")
        return make_check("import", subject, critical, True)

    err = (proc.stderr or proc.stdout or "").strip().splitlines()
    detail = err[-1] if err else f"return code {proc.returncode}"
    print(f"  FAIL  Clawpack Python import: {module}: {detail}")
    package = module.split(".", 1)[0]
    return make_check(
        "import",
        subject,
        critical,
        False,
        fix_text(
            f"Install {package} into {CLAW_PYTHON} ({CLAW_PYTHON} -m pip install {package}) "
            "or set CLAW_PYTHON to a Python with clawpack"
        ),
    )


def check_binary_starts(binary: Path, critical: bool = True) -> dict[str, object]:
    subject = os.path.realpath(binary)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        return make_check(
            "run",
            subject,
            critical,
            False,
            fix_text(f"Restore executable GeoClaw binary before start probe: {binary}"),
        )

    try:
        with tempfile.TemporaryDirectory(prefix="geoclaw_preflight_") as run_dir:
            proc = subprocess.run(
                [str(binary)],
                cwd=run_dir,
                capture_output=True,
                text=True,
                timeout=5,
            )
    except subprocess.TimeoutExpired:
        print(f"  FAIL  GeoClaw start probe: timed out for {binary}")
        return make_check(
            "run",
            subject,
            critical,
            False,
            fix_text("GeoClaw executable did not return promptly when started without case data"),
        )
    except OSError as exc:
        print(f"  FAIL  GeoClaw start probe: {exc}")
        return make_check("run", subject, critical, False, fix_text(f"Rebuild or relink GeoClaw binary: {exc}"))

    combined = f"{proc.stdout}\n{proc.stderr}".lower()
    loader_failed = (
        proc.returncode == 127
        or "error while loading shared libraries" in combined
        or "cannot open shared object file" in combined
    )
    if loader_failed:
        print(f"  FAIL  GeoClaw start probe: dynamic loader failure for {binary}")
        return make_check(
            "run",
            subject,
            critical,
            False,
            fix_text("Rebuild GeoClaw or repair missing runtime libraries"),
        )

    print(f"  OK    GeoClaw start probe: process launched and returned rc={proc.returncode}")
    return make_check("run", subject, critical, True)


def check_tool_import(script: Path) -> dict[str, object]:
    subject = str(script.resolve())
    module_name = f"tools.{script.stem}"
    try:
        proc = subprocess.run(
            [str(CLAW_PYTHON), "-c", f"import {module_name}"],
            cwd=KI_DIR,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        print(f"  FAIL  KI tool import: {script}: {exc}")
        return make_check(
            "import", subject, True, False,
            fix_text(f"Import of {script} with {CLAW_PYTHON} did not finish: {exc}"),
        )
    if proc.returncode == 0:
        print(f"  OK    KI tool import: {script}")
        return make_check("import", subject, True, True)

    err = (proc.stderr or proc.stdout or "").strip().splitlines()
    detail = err[-1] if err else f"return code {proc.returncode}"
    print(f"  FAIL  KI tool import: {script}: {detail}")
    return make_check(
        "import",
        subject,
        True,
        False,
        fix_text(f"Fix import/runtime dependencies for {script}"),
    )


def check_command(argv: list[str], critical: bool, fix: str, label: str = "") -> dict[str, object]:
    """Run the full command with --version (as make / run_geoclaw.py would start it)."""
    name = label or " ".join(argv) or "(empty)"
    if not argv or not argv[0]:
        print(f"  FAIL  Command: {name}: empty command")
        return make_check("binary", name, critical, False, fix_text(f"{fix} (empty command)"))
    found = shutil.which(argv[0])
    if not found:
        print(f"  FAIL  Command: {name}: {argv[0]} not found on PATH")
        return make_check("binary", name, critical, False, fix_text(fix))
    real = os.path.realpath(found)
    try:
        # A version probe only; MAKEFLAGS/MFLAGS/GNUMAKEFLAGS are dropped so `make --version` cannot
        # expand inherited make expressions (the toolchain probe handles MAKEFLAGS itself).
        quiet_env = {k: v for k, v in os.environ.items() if k not in MAKE_FLAG_VARS}
        proc = subprocess.run([found, *argv[1:], "--version"], capture_output=True, text=True,
                              timeout=30, env=quiet_env)
        ok = proc.returncode == 0
        detail = (proc.stdout or proc.stderr or "").strip().splitlines()[:1]
        if not ok:
            detail = detail or [f"exit code {proc.returncode}"]
    except (subprocess.TimeoutExpired, OSError) as exc:
        ok, detail = False, [str(exc)]
    subject = real if len(argv) == 1 else f"{name} ({real})"
    if ok:
        print(f"  OK    Command: {name}: {real} ({detail[0] if detail else 'version ok'})")
        return make_check("binary", subject, critical, True)
    print(f"  FAIL  Command: {name}: --version failed: {' '.join(detail)}")
    return make_check("binary", subject, critical, False, fix_text(f"{fix} ({name} --version failed)"))


# A tiny case Makefile that includes the REAL $(CLAW)/clawutil/src/Makefile.common, as every
# GeoClaw case Makefile does, and builds it with `make .exe`. So make itself applies the real
# variables, flags, module/compile/link rules, check_src.py source consolidation and any
# MAKEFLAGS / environment overrides. The $(info) lines report what make actually used.
PROBE_MAKEFILE = """\
# Refuse (at parse time, before any $(shell) or recipe runs) command-line/MAKEFLAGS,
# `override` or `make -e` settings of the probe's own file lists: they could point the
# build at files outside the temp dir. `make -e` shows as "environment override" only
# after a makefile assigns the variable, so each guard sits right after the assignments:
# the input lists before Makefile.common is included (it runs check_src.py on them via
# $(shell)) and the derived object lists (placeholders here, which Makefile.common then
# reassigns; it expands them in prerequisites while it is read), and all again after it. Compiler, linker and flag overrides stay
# allowed and are what this probe tests.
override probe_refuse = $(foreach v,$(1),$(if $(or $(findstring command line,$(origin $(v))),$(findstring override,$(origin $(v)))),$(error PREFLIGHT_REFUSED $(v) is set from $(origin $(v)))))
MODULES = mods/probe_mod.f90
SOURCES = probe.f90 fixed_probe.f
COMMON_MODULES =
COMMON_SOURCES =
EXCLUDE_MODULES =
EXCLUDE_SOURCES =
OBJECTS =
MODULE_FILES =
MODULE_PATHS =
MODULE_OBJECTS =
$(call probe_refuse,MODULES SOURCES COMMON_MODULES COMMON_SOURCES EXCLUDE_MODULES EXCLUDE_SOURCES \\
  OBJECTS MODULE_FILES MODULE_PATHS MODULE_OBJECTS)
# The probe binary always lands in this temp dir under a fixed name.
override EXE = preflight_probe_exe
include $(CLAW)/clawutil/src/Makefile.common
$(call probe_refuse,MODULES SOURCES COMMON_MODULES COMMON_SOURCES EXCLUDE_MODULES EXCLUDE_SOURCES \\
  OBJECTS MODULE_FILES MODULE_PATHS MODULE_OBJECTS)
$(info PREFLIGHT_CLAW=$(CLAW))
$(info PREFLIGHT_CLAW_PYTHON=$(CLAW_PYTHON))
$(info PREFLIGHT_EXE=$(EXE))
$(info PREFLIGHT_SOURCES=$(SOURCES))
"""
PROBE_EXE = "preflight_probe_exe"
# Variables GNU make reads flags and variable settings from before any makefile line.
MAKE_FLAG_VARS = ("MAKEFLAGS", "MFLAGS", "GNUMAKEFLAGS")
# Inherited make flags the probe accepts: harmless option letters / job options, and plain
# settings of the build variables it tests. No escapes, quotes, $, `, ;, () or spaces.
SAFE_FLAG_LETTERS = re.compile(r"-?[BeiknqrRsStw]+")
SAFE_FLAG_OPTIONS = re.compile(
    r"-j\d*|--jobs(=\d+)?|-l[\d.]*|--load-average(=[\d.]+)?|--jobserver-auth=[A-Za-z0-9_,:./-]+"
    r"|--jobserver-fds=\d+,\d+|--no-print-directory|--print-directory|--warn-undefined-variables"
)
SAFE_FLAG_VARS = {
    "FC", "CLAW_FC", "LINK", "FFLAGS", "LFLAGS", "PPFLAGS", "INCLUDE", "ALL_FFLAGS",
    "ALL_LFLAGS", "ALL_INCLUDE", "MODULE_FLAG", "OMP_FLAG", "CLAW", "CLAW_PYTHON", "EXE",
}
SAFE_FLAG_ASSIGN = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=([A-Za-z0-9_./+,=:@%-]*)")


def unsafe_make_flags(value: str) -> str:
    """Return the first word of an inherited make-flags value outside the allowlist, or ''."""
    for word in value.split():
        if word == "--" or SAFE_FLAG_LETTERS.fullmatch(word) or SAFE_FLAG_OPTIONS.fullmatch(word):
            continue
        m = SAFE_FLAG_ASSIGN.fullmatch(word)
        if m and m.group(1) in SAFE_FLAG_VARS:
            continue
        return word
    return ""
PROBE_MODULE = "module probe_mod\n  character(len=*), parameter :: marker = 'geoclaw-fc-ok'\nend module probe_mod\n"
# Fixed-form source (comment in column 1, continuation in column 6), like GeoClaw's .f files.
PROBE_FIXED = (
    "      subroutine fixed_probe(n)\n"
    "c     fixed-form comment line\n"
    "      integer n\n"
    "      n = 1 +\n"
    "     &    1\n"
    "      end\n"
)
PROBE_PROGRAM = (
    "program probe\n  use probe_mod\n  integer :: n\n  call fixed_probe(n)\n"
    "  if (n == 2) print *, marker\nend program probe\n"
)


def check_fortran_build() -> dict[str, object]:
    """Critical: build a tiny case (module in a subfolder, free-form program, fixed-form
    routine) with `make .exe` through the real Makefile.common, then run it. CLAW /
    CLAW_PYTHON are exported as checked above (like setup_env.sh); make must end up with the
    same values. A toolchain probe, not a model build or run."""
    subject = "Fortran toolchain probe: make .exe via the real Makefile.common (module, .f90, .f)"
    make = shutil.which("make")
    if not make:
        print(f"  FAIL  {subject}: make not found on PATH")
        return make_check("run", subject, True, False, fix_text("Install make (run_geoclaw.py --use-makefile runs make .exe)"))

    def fail(detail: str) -> dict[str, object]:
        print(f"  FAIL  {subject}: {detail}")
        return make_check("run", subject, True, False, fix_text(detail))

    if not (CLAW_DIR / "clawutil/src/Makefile.common").is_file():
        return fail(f"no clawutil/src/Makefile.common under CLAW={CLAW_DIR}")
    try:
        with tempfile.TemporaryDirectory(prefix="geoclaw_fc_probe_") as tmp:
            root = Path(tmp)
            (root / "mods").mkdir()
            (root / "mods" / "probe_mod.f90").write_text(PROBE_MODULE)
            (root / "fixed_probe.f").write_text(PROBE_FIXED)
            (root / "probe.f90").write_text(PROBE_PROGRAM)
            (root / "Makefile").write_text(PROBE_MAKEFILE)
            # Caller env kept as-is (incl. MAKEFLAGS), as the real `make .exe` inherits it.
            env = dict(os.environ, CLAW=str(CLAW_DIR), CLAW_PYTHON=str(CLAW_PYTHON))
            # GNU make acts on MAKEFLAGS/MFLAGS/GNUMAKEFLAGS (and MAKEFILES) before it reads
            # any makefile line, so no makefile guard can protect against them. Only a small,
            # plain allowlist is accepted; anything else makes the probe refuse to run make.
            if env.get("MAKEFILES"):
                return fail(
                    "MAKEFILES is set (extra makefiles make would read first); the probe will "
                    "not run make with it"
                )
            for name in MAKE_FLAG_VARS:
                bad = unsafe_make_flags(env.get(name, ""))
                if bad:
                    return fail(
                        f"{name} holds {bad!r}, which is not a plain allowed make flag or "
                        "compiler/flag setting; the probe will not run make with it"
                    )

            def make_vars(proc: subprocess.CompletedProcess) -> dict[str, str]:
                seen = {}
                for line in proc.stdout.splitlines():
                    if line.startswith("PREFLIGHT_") and "=" in line:
                        key, value = line.split("=", 1)
                        seen[key] = value.strip()
                return seen

            # The probe's executable name is fixed and pinned on make's command line (it beats
            # EXE from the environment or MAKEFLAGS), so the build can only write inside this
            # temp dir. Which name the binary has does not matter for a toolchain test.
            exe = PROBE_EXE
            exe_path = root / exe
            proc = subprocess.run([make, ".exe", f"EXE={exe}"], cwd=tmp, env=env,
                                  capture_output=True, text=True, timeout=300)
            seen = make_vars(proc)
            if "PREFLIGHT_REFUSED" in (proc.stderr or "") + (proc.stdout or ""):
                refused = [ln for ln in ((proc.stderr or "") + (proc.stdout or "")).splitlines() if "PREFLIGHT_REFUSED" in ln]
                return fail(f"probe refused an override of its own file lists: {refused[0].strip()}")
            if not seen:
                lines = (proc.stderr or proc.stdout or "").strip().splitlines()
                return fail("make stopped before reading the probe Makefile: " + (" | ".join(lines[-3:]) if lines else f"exit code {proc.returncode}"))
            if seen.get("PREFLIGHT_CLAW") != str(CLAW_DIR):
                return fail(f"make sees CLAW={seen.get('PREFLIGHT_CLAW')!r}, but {CLAW_DIR} was checked (MAKEFLAGS override?)")
            if seen.get("PREFLIGHT_CLAW_PYTHON") != str(CLAW_PYTHON):
                return fail(f"make sees CLAW_PYTHON={seen.get('PREFLIGHT_CLAW_PYTHON')!r}, but {CLAW_PYTHON} was checked (MAKEFLAGS override?)")
            if sorted(seen.get("PREFLIGHT_SOURCES", "").split()) != ["fixed_probe.f", "probe.f90"]:
                return fail(f"check_src.py source consolidation via make gave {seen.get('PREFLIGHT_SOURCES')!r}")
            if proc.returncode != 0:
                lines = (proc.stderr or proc.stdout or "").strip().splitlines()
                return fail("make .exe failed: " + (" | ".join(lines[-3:]) if lines else f"exit code {proc.returncode}"))
            if seen.get("PREFLIGHT_EXE") != exe:
                return fail(f"make did not use the pinned EXE={exe} (got {seen.get('PREFLIGHT_EXE')!r})")
            run = subprocess.run([str(exe_path)], cwd=tmp, capture_output=True, text=True, timeout=60)
            if run.returncode != 0 or "geoclaw-fc-ok" not in run.stdout:
                return fail(f"built probe {exe} did not run cleanly (exit {run.returncode})")
    except (subprocess.TimeoutExpired, OSError) as exc:
        return fail(f"Fortran toolchain probe did not finish: {exc}")
    print(f"  OK    {subject}")
    return make_check("run", subject, True, True)


def main() -> None:
    print(f"{' PREFLIGHT: GeoClaw ':=^60}")
    checks: list[dict[str, object]] = []

    # Info only: the manifest binary is a prebuilt example (chile2010); GeoClaw compiles
    # xgeoclaw per case with `make .exe`, so it is not the engine for other cases.
    binary = read_manifest_binary()
    checks.append(check_file(
        binary,
        "Prebuilt example xgeoclaw (chile2010 only; GeoClaw compiles xgeoclaw per case; info only)",
        critical=False,
        executable=True,
    ))
    checks.append(check_binary_starts(binary, critical=False))

    checks.append(check_file(CLAW_PYTHON, "Clawpack Python interpreter ($CLAW_PYTHON)", critical=True, executable=True, keep_path=True))
    for module in ("clawpack", "clawpack.geoclaw", "clawpack.clawutil", "numpy"):
        checks.append(check_python_import(module, critical=True))
    checks.append(check_claw_sources())

    required_files = [
        KI_DIR / "SKILL.md",
        KI_DIR / "knowledge_infrastructure.yaml",
        KI_DIR / "dag.yaml",
        DIAGNOSTICS,
        KI_DIR / "docs" / "format_spec.yaml",
    ]
    for path in required_files:
        checks.append(check_file(path, f"Required KI file {path.relative_to(KI_DIR)}", critical=True))

    for script_name in (
        "convert_bathymetry.py",
        "generate_setrun.py",
        "run_geoclaw.py",
        "parse_geoclaw_output.py",
    ):
        script = KI_DIR / "tools" / script_name
        checks.append(check_file(script, f"KI tool {script_name}", critical=True))
        checks.append(check_tool_import(script))

    checks.append(check_command([FC], True, f"Install the Fortran compiler '{FC}' or set FC=gfortran", label=f"FC={FC}"))
    # The effective CLAW_FC / LINK commands and flags are checked by the make-driven
    # probe below, so make (not Python) expands them.
    checks.append(check_fortran_build())
    checks.append(check_command(["make"], True, "Install make (run_geoclaw.py --use-makefile runs make .exe)"))

    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = len(checks) - passed
    print(f"\n  Results: {passed} passed, {failed} failed")
    if any(check["status"] == "fail" and check.get("critical") for check in checks):
        print(f"  STATUS: PREFLIGHT FAILED - fix blockers above; check {DIAGNOSTICS} first.")
    elif failed:
        print("  STATUS: PREFLIGHT PASSED with warnings (non-critical checks failed) - required dependencies available.")
    else:
        print("  STATUS: PREFLIGHT PASSED - required dependencies available.")
    print(
        f"  Checked engine: CLAW={CLAW_DIR} CLAW_PYTHON={CLAW_PYTHON} FC={FC} "
        f"CLAW_FC={CLAW_FC} LINK={LINK} (as set; make expands them). Run the KI tools with this Python and these CLAW/CLAW_PYTHON/FC values "
        "(see clawpack/setup_env.sh)."
    )

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
