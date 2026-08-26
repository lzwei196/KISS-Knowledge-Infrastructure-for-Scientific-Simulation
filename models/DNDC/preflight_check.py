#!/usr/bin/env python3
"""Preflight check for the DNDC knowledge infrastructure."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


MODEL_ID = "DNDC"
KI_DIR = Path(__file__).resolve().parent
PYTHON_ENV = Path("KISSPATH_PYTHON_ENV/bin/python")
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"
MANIFEST = KI_DIR / "knowledge_infrastructure.yaml"


def emit_report(model_id: str, checks: list[dict]) -> None:
    """Emit the required KDT preflight report as the final output line."""
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    ok = all(c["status"] == "pass" or not c.get("critical") for c in checks)
    sys.exit(0 if ok else 1)


def add_check(
    checks: list[dict],
    *,
    kind: str,
    subject: str | Path,
    critical: bool,
    status: bool,
    fix: str = "",
) -> None:
    checks.append(
        {
            "kind": kind,
            "subject": str(subject),
            "critical": bool(critical),
            "status": "pass" if status else "fail",
            "fix": "" if status else fix,
        }
    )


def check_file(
    checks: list[dict],
    path: Path,
    label: str,
    *,
    critical: bool = True,
    executable: bool = False,
) -> bool:
    path = path.resolve() if path.exists() else path
    ok = path.is_file()
    fix = f"Restore {label} at {path}; see {DIAGNOSTICS} for recovery."
    if ok and executable and not os.access(path, os.X_OK):
        ok = False
        fix = f"Make {label} executable: chmod +x {path}; see {DIAGNOSTICS}."
    print(("  OK    " if ok else "  FAIL  ") + f"{label}: {path}")
    if not ok:
        print(f"         Fix: {fix}")
    add_check(
        checks,
        kind="data",
        subject=path,
        critical=critical,
        status=ok,
        fix=fix,
    )
    return ok


def check_dir(checks: list[dict], path: Path, label: str, *, critical: bool = True) -> bool:
    ok = path.is_dir() and any(path.iterdir())
    fix = f"Restore non-empty {label} at {path}; see {DIAGNOSTICS} for recovery."
    count = len(list(path.iterdir())) if path.is_dir() else 0
    print(("  OK    " if ok else "  FAIL  ") + f"{label}: {path} ({count} items)")
    if not ok:
        print(f"         Fix: {fix}")
    add_check(
        checks,
        kind="data",
        subject=path,
        critical=critical,
        status=ok,
        fix=fix,
    )
    return ok


def manifest_binary_path() -> Path:
    """Read package.binary.path from the KI manifest."""
    try:
        import yaml

        data = yaml.safe_load(MANIFEST.read_text()) or {}
        path = data.get("package", {}).get("binary", {}).get("path")
        if path:
            return Path(path)
    except Exception:
        pass

    # Conservative fallback for this manifest's simple layout.
    in_binary = False
    for line in MANIFEST.read_text().splitlines():
        stripped = line.strip()
        if stripped == "binary:":
            in_binary = True
            continue
        if in_binary and stripped.startswith("path:"):
            return Path(stripped.split(":", 1)[1].strip())
        if in_binary and line and not line.startswith(" "):
            break
    return Path("KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/DNDC/dndc_run/DNDC95.exe")


def check_dndc_binary(checks: list[dict], exe_path: Path) -> None:
    subject = exe_path.resolve() if exe_path.exists() else exe_path
    ok = exe_path.is_file() and os.access(exe_path, os.R_OK)
    fix = f"Restore DNDC95.exe at {exe_path}; check {DIAGNOSTICS} for DNDC/Wine path fixes."
    if ok:
        try:
            head = exe_path.read_bytes()[:2]
            ok = head == b"MZ"
            fix = f"Replace {exe_path} with the real DNDC95.exe PE32 binary; see {DIAGNOSTICS}."
        except OSError as exc:
            ok = False
            fix = f"Make {exe_path} readable ({exc}); see {DIAGNOSTICS}."

    print(("  OK    " if ok else "  FAIL  ") + f"DNDC binary: {subject}")
    if not ok:
        print(f"         Fix: {fix}")
    add_check(
        checks,
        kind="binary",
        subject=subject,
        critical=True,
        status=ok,
        fix=fix,
    )


def check_wine(checks: list[dict]) -> None:
    wine = shutil.which("wine")
    ok = bool(wine)
    subject = wine or "wine"
    fix = f"Install Wine with 32-bit PE support; see {DIAGNOSTICS} dt_009."
    if ok:
        try:
            result = subprocess.run(
                [wine, "--version"],
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            ok = result.returncode == 0 and bool(result.stdout.strip() or result.stderr.strip())
            subject = str(Path(wine).resolve())
            if ok:
                print(f"  OK    Wine starts: {subject} ({(result.stdout or result.stderr).strip()})")
            else:
                fix = f"Wine did not start cleanly; reinstall Wine and check {DIAGNOSTICS} dt_009."
        except Exception as exc:
            ok = False
            fix = f"Wine failed to start ({exc}); check {DIAGNOSTICS} dt_009."
    if not ok:
        print(f"  FAIL  Wine starts: {subject}")
        print(f"         Fix: {fix}")
    add_check(
        checks,
        kind="run",
        subject=subject,
        critical=True,
        status=ok,
        fix=fix,
    )


def check_python_tool_import(checks: list[dict], tool: Path) -> None:
    code = (
        "import importlib.util, pathlib, sys\n"
        f"path = pathlib.Path({str(tool)!r})\n"
        "sys.path.insert(0, str(path.parent.parent))\n"
        "spec = importlib.util.spec_from_file_location(path.stem, path)\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
    )
    fix = (
        f"Fix imports for {tool.relative_to(KI_DIR)} under {PYTHON_ENV}; "
        f"check {DIAGNOSTICS} before changing tool behavior."
    )
    if not PYTHON_ENV.is_file():
        print(f"  FAIL  Python env: {PYTHON_ENV}")
        print(f"         Fix: Restore HydroCraft Python env at {PYTHON_ENV}; see {DIAGNOSTICS}.")
        add_check(
            checks,
            kind="import",
            subject=str(PYTHON_ENV),
            critical=True,
            status=False,
            fix=f"Restore HydroCraft Python env at {PYTHON_ENV}; see {DIAGNOSTICS}.",
        )
        return

    result = subprocess.run(
        [str(PYTHON_ENV), "-c", code],
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
        cwd=str(KI_DIR),
    )
    ok = result.returncode == 0
    print(("  OK    " if ok else "  FAIL  ") + f"Tool import via python_env: {tool.relative_to(KI_DIR)}")
    if not ok:
        detail = (result.stderr or result.stdout).strip().splitlines()[-1:]
        if detail:
            print(f"         Detail: {detail[0]}")
        print(f"         Fix: {fix}")
    add_check(
        checks,
        kind="import",
        subject=f"{PYTHON_ENV} imports {tool}",
        critical=True,
        status=ok,
        fix=fix,
    )


def main() -> None:
    checks: list[dict] = []
    print("=" * 60)
    print(f"  PREFLIGHT CHECK: {MODEL_ID}")
    print("=" * 60)
    print(f"  Recovery diagnostics: {DIAGNOSTICS}")
    print()

    check_file(checks, MANIFEST, "KI manifest", critical=True)
    check_file(checks, KI_DIR / "dag.yaml", "DAG", critical=True)
    check_file(checks, KI_DIR / "SKILL.md", "KI skill document", critical=True)
    check_file(checks, DIAGNOSTICS, "diagnostic triplets", critical=True)
    check_dir(checks, KI_DIR / "tools", "KI tools directory", critical=True)

    for rel in (
        "tools/convert_forcing_to_dndc.py",
        "tools/convert_soil_to_dndc.py",
        "tools/generate_dnd_file.py",
        "tools/parse_dndc_output.py",
        "tools/run_dndc.py",
    ):
        tool = KI_DIR / rel
        if check_file(checks, tool, rel, critical=True):
            check_python_tool_import(checks, tool)

    exe_path = manifest_binary_path()
    check_dndc_binary(checks, exe_path)
    check_wine(checks)

    failed = [c for c in checks if c["status"] == "fail"]
    print()
    print(f"  Results: {len(checks) - len(failed)} passed, {len(failed)} failed")
    if failed:
        print(f"  STATUS: PREFLIGHT FAILED - check fixes above and {DIAGNOSTICS}")
    else:
        print("  STATUS: PREFLIGHT PASSED - DNDC execution prerequisites are present")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
