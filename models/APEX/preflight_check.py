#!/usr/bin/env python3
"""Preflight checks for the APEX v0806 KI.

The gate requires a final PREFLIGHT_REPORT= JSON line. Keep the human-readable
status lines useful, but make the JSON report the authoritative contract.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MODEL_ID = "APEX"
KI_ROOT = Path(__file__).resolve().parent
TOOLS_DIR = KI_ROOT / "tools"
REFERENCE_DIR = KI_ROOT / "reference"
EXAMPLE_DIR = KI_ROOT / "examples" / "ex1_RiselTX"
DIAGNOSTICS = KI_ROOT / "diagnostics" / "triplets.yaml"
BINARY = REFERENCE_DIR / "APEX0806.exe"
PYTHON_ENV = Path("KISSPATH_PYTHON_ENV/bin/python3")
KDT_COMMON = Path("KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect_multi_agent")

REQUIRED_TOOLS = [
    "quickstart.py",
    "s1_setup_workspace.py",
    "s2_convert_forcing.py",
    "s3_build_soil.py",
    "s4_update_site.py",
    "s5_update_control.py",
    "s6_run_apex.py",
    "s7_parse_output.py",
    "s8_update_operations.py",
    "s9_generate_crop_opc.py",
]

REQUIRED_EXAMPLE_FILES = [
    "APEXFILE.DAT",
    "APEXRUN.DAT",
    "APEXCONT.DAT",
    "APEXDIM.DAT",
    "SITECOM.DAT",
    "SUBACOM.DAT",
    "SOILCOM.DAT",
    "OPSCCOM.DAT",
    "CROPCOM.DAT",
    "TILLCOM.DAT",
    "FERTCOM.DAT",
    "TR55COM.DAT",
    "PARM0806.DAT",
    "PRNT0806.DAT",
    "MLRN0806.DAT",
    "HERD0604.DAT",
    "WDLSTCOM.DAT",
    "PSOCOM.DAT",
    "RFDTLST.DAT",
    "SIT0002.SIT",
    "SUB0002.SUB",
    "Heiden.SOL",
    "HoustonB.SOL",
    "HOUSTON.SOL",
    "Y10.OPC",
    "RNGE.OPC",
    "Y6.OPC",
    "Y8.OPC",
    "A48309.dly",
    "109.WP1",
    "25.WND",
]

IMPORT_MODULES = [
    "numpy",
    "pandas",
    "ki_tools_common.soil_utils",
    "s1_setup_workspace",
    "s2_convert_forcing",
    "s3_build_soil",
    "s4_update_site",
    "s5_update_control",
    "s6_run_apex",
    "s7_parse_output",
    "s8_update_operations",
    "s9_generate_crop_opc",
]


def add_check(
    checks: list[dict],
    *,
    kind: str,
    subject: str | Path,
    critical: bool,
    status: bool,
    fix: str = "",
) -> None:
    check = {
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": "pass" if status else "fail",
        "fix": "" if status else (fix or f"See {DIAGNOSTICS} for recovery steps."),
    }
    checks.append(check)
    label = "OK" if status else "FAIL"
    print(f"[{label}] {kind}: {check['subject']}")
    if not status:
        print(f"      Fix: {check['fix']}")


def emit_report(checks: list[dict]) -> None:
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": MODEL_ID, "checks": checks}, sort_keys=True))
    failed_critical = [c for c in checks if c["critical"] and c["status"] != "pass"]
    sys.exit(1 if failed_critical else 0)


def read_manifest_binary_path() -> str | None:
    manifest = KI_ROOT / "knowledge_infrastructure.yaml"
    if not manifest.is_file():
        return None
    lines = manifest.read_text(errors="replace").splitlines()
    for idx, line in enumerate(lines):
        if line.strip() == "binary:":
            for subline in lines[idx + 1 : idx + 8]:
                stripped = subline.strip()
                if stripped.startswith("path:"):
                    return stripped.split(":", 1)[1].strip()
    return None


def check_binary(checks: list[dict]) -> None:
    binary_realpath = Path(os.path.realpath(BINARY))
    add_check(
        checks,
        kind="binary",
        subject=binary_realpath,
        critical=True,
        status=BINARY.is_file(),
        fix=f"Restore the APEX0806 PE32 binary at {BINARY}; see {DIAGNOSTICS}.",
    )
    if not BINARY.is_file():
        return

    try:
        header = BINARY.read_bytes()[:2]
    except OSError:
        header = b""
    add_check(
        checks,
        kind="binary",
        subject=f"{binary_realpath} PE/MZ header",
        critical=True,
        status=header == b"MZ",
        fix=f"{BINARY} is not a valid Windows PE executable; restore reference/APEX0806.exe.",
    )

    manifest_binary = read_manifest_binary_path()
    add_check(
        checks,
        kind="data",
        subject="knowledge_infrastructure.yaml binary.path",
        critical=True,
        status=manifest_binary == str(BINARY),
        fix=(
            f"Set package.implementation binary.path to {BINARY} "
            f"(currently {manifest_binary!r}); see {DIAGNOSTICS}."
        ),
    )


def check_wine_and_start(checks: list[dict]) -> None:
    wine = shutil.which("wine")
    add_check(
        checks,
        kind="binary",
        subject="wine",
        critical=True,
        status=wine is not None,
        fix=f"Install Wine or put it on PATH so APEX0806.exe can run; see {DIAGNOSTICS}.",
    )
    if wine is None or not BINARY.is_file():
        return

    try:
        proc = subprocess.run(
            [wine, str(BINARY)],
            cwd=tempfile.gettempdir(),
            input="\n",
            capture_output=True,
            text=True,
            timeout=6,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        started = (
            "APEXRUN.DAT IS MISSING" in output
            or "RUN #" in output
            or "YEAR" in output
            or "Fortran Pause" in output
        )
        fix = f"`wine {BINARY}` did not reach APEX startup; inspect Wine/APEX errors and {DIAGNOSTICS}."
    except subprocess.TimeoutExpired as exc:
        output = ((exc.stdout or b"") if isinstance(exc.stdout, bytes) else (exc.stdout or ""))
        output += ((exc.stderr or b"") if isinstance(exc.stderr, bytes) else (exc.stderr or ""))
        if isinstance(output, bytes):
            output = output.decode(errors="replace")
        started = "APEXRUN.DAT IS MISSING" in output or "Fortran Pause" in output
        fix = f"`wine {BINARY}` timed out before recognizable startup; inspect Wine/APEX errors and {DIAGNOSTICS}."
    except Exception as exc:  # noqa: BLE001 - report every blocker, do not crash.
        started = False
        fix = f"`wine {BINARY}` raised {type(exc).__name__}: {exc}; see {DIAGNOSTICS}."

    add_check(
        checks,
        kind="run",
        subject=f"wine starts {Path(os.path.realpath(BINARY))}",
        critical=True,
        status=started,
        fix=fix,
    )


def check_files(checks: list[dict]) -> None:
    add_check(
        checks,
        kind="data",
        subject=EXAMPLE_DIR,
        critical=True,
        status=EXAMPLE_DIR.is_dir(),
        fix=f"Restore the validated v0806 Riesel example directory at {EXAMPLE_DIR}; see {DIAGNOSTICS}.",
    )

    missing_example = [name for name in REQUIRED_EXAMPLE_FILES if not (EXAMPLE_DIR / name).is_file()]
    add_check(
        checks,
        kind="data",
        subject=f"{EXAMPLE_DIR} required input files ({len(REQUIRED_EXAMPLE_FILES)})",
        critical=True,
        status=not missing_example,
        fix=f"Restore missing v0806 example files: {missing_example}; see {DIAGNOSTICS}.",
    )

    missing_tools = [name for name in REQUIRED_TOOLS if not (TOOLS_DIR / name).is_file()]
    add_check(
        checks,
        kind="data",
        subject=f"{TOOLS_DIR} pipeline tools ({len(REQUIRED_TOOLS)})",
        critical=True,
        status=not missing_tools,
        fix=f"Restore missing KI tool files: {missing_tools}; see {DIAGNOSTICS}.",
    )

    for required in [
        KI_ROOT / "SKILL.md",
        KI_ROOT / "knowledge_infrastructure.yaml",
        KI_ROOT / "dag.yaml",
        REFERENCE_DIR / "apex_formats.json",
        REFERENCE_DIR / "apexeditorrev2203.xlsm",
        DIAGNOSTICS,
    ]:
        add_check(
            checks,
            kind="data",
            subject=required,
            critical=required == DIAGNOSTICS,
            status=required.is_file(),
            fix=f"Restore {required}; recovery guidance starts at {DIAGNOSTICS}.",
        )


def check_imports(checks: list[dict]) -> None:
    interpreter = PYTHON_ENV if PYTHON_ENV.is_file() else Path(sys.executable)
    add_check(
        checks,
        kind="import",
        subject=f"python interpreter {interpreter}",
        critical=True,
        status=interpreter.is_file(),
        fix=f"Restore the HydroCraft Python environment at {PYTHON_ENV}; see {DIAGNOSTICS}.",
    )
    if not interpreter.is_file():
        return

    code = (
        "import json, sys\n"
        f"sys.path.insert(0, {str(TOOLS_DIR)!r})\n"
        f"sys.path.insert(0, {str(KDT_COMMON)!r})\n"
        f"mods = {IMPORT_MODULES!r}\n"
        "results = []\n"
        "for mod in mods:\n"
        "    try:\n"
        "        __import__(mod)\n"
        "        results.append({'module': mod, 'ok': True, 'error': ''})\n"
        "    except Exception as exc:\n"
        "        results.append({'module': mod, 'ok': False, 'error': f'{type(exc).__name__}: {exc}'})\n"
        "print(json.dumps(results))\n"
    )
    try:
        proc = subprocess.run(
            [str(interpreter), "-c", code],
            cwd=str(KI_ROOT),
            capture_output=True,
            text=True,
            timeout=20,
        )
        results = json.loads((proc.stdout or "[]").strip().splitlines()[-1])
    except Exception as exc:  # noqa: BLE001 - report every blocker, do not crash.
        add_check(
            checks,
            kind="import",
            subject=f"{interpreter} import probe",
            critical=True,
            status=False,
            fix=f"Import probe failed with {type(exc).__name__}: {exc}; see {DIAGNOSTICS}.",
        )
        return

    for result in results:
        module = result["module"]
        add_check(
            checks,
            kind="import",
            subject=f"{interpreter} imports {module}",
            critical=module.startswith("s") or module in {"numpy", "pandas", "ki_tools_common.soil_utils"},
            status=bool(result["ok"]),
            fix=f"Fix Python import for {module}: {result['error']}; see {DIAGNOSTICS}.",
        )


def main() -> None:
    print(f"APEX KI preflight: {KI_ROOT}")
    checks: list[dict] = []
    check_binary(checks)
    check_wine_and_start(checks)
    check_files(checks)
    check_imports(checks)
    emit_report(checks)


if __name__ == "__main__":
    main()
