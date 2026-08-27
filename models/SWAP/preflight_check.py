#!/usr/bin/env python3
"""Contract-compliant preflight check for the SWAP KI."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


MODEL_ID = "SWAP"
PINNED_SWAP_BINARY = (
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/"
    "_work/SWAP/source/repo/builddir/swap"
)
PINNED_SWAP_SHA256 = (
    "a696efc5344daa53b3ddeebd3664656d0822959a5b2f4f863efc710469f1cf97"
)
PYTHON_ENV = "KISSPATH_PYTHON_ENV/bin/python"

KI_DIR = Path(__file__).resolve().parent
MODEL_ROOT = KI_DIR.parent
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"

CHECKS = []


def add_check(kind, subject, critical, status, fix):
    CHECKS.append(
        {
            "kind": kind,
            "subject": str(subject),
            "critical": bool(critical),
            "status": status,
            "fix": fix,
        }
    )


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    sys.exit(0 if all(c["status"] == "pass" or not c.get("critical") for c in checks) else 1)


def fix_hint(action):
    return f"{action}; then check {TRIPLETS} for matching recovery guidance."


def check_file(path, label, *, kind="data", critical=True, executable=False):
    path = Path(path)
    subject = path.resolve(strict=False)
    if not path.is_file():
        print(f"  FAIL  {label}: NOT FOUND at {path}")
        add_check(kind, subject, critical, "fail", fix_hint(f"restore or create {path}"))
        return False
    if executable and not os.access(path, os.X_OK):
        print(f"  FAIL  {label}: exists but is not executable: {path}")
        add_check(kind, subject, critical, "fail", fix_hint(f"chmod +x {path}"))
        return False
    print(f"  OK    {label}: {path}")
    add_check(kind, subject, critical, "pass", "")
    return True


def check_dir(path, label, *, critical=True, min_items=1):
    path = Path(path)
    subject = path.resolve(strict=False)
    if not path.is_dir():
        print(f"  FAIL  {label}: directory NOT FOUND at {path}")
        add_check("data", subject, critical, "fail", fix_hint(f"restore directory {path}"))
        return False
    n_items = len(list(path.iterdir()))
    if n_items < min_items:
        print(f"  FAIL  {label}: directory is empty at {path}")
        add_check("data", subject, critical, "fail", fix_hint(f"populate directory {path}"))
        return False
    print(f"  OK    {label}: {path} ({n_items} items)")
    add_check("data", subject, critical, "pass", "")
    return True


def check_import(module, label, *, critical=True):
    interpreter = PYTHON_ENV if Path(PYTHON_ENV).is_file() else sys.executable
    subject = f"{interpreter}:import {module}"
    try:
        result = subprocess.run(
            [interpreter, "-c", f"import {module}"],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except subprocess.TimeoutExpired:
        print(f"  FAIL  {label}: {subject}: timed out")
        add_check(
            "import",
            subject,
            critical,
            "fail",
            fix_hint(f"repair hanging Python dependency import {module!r} in {interpreter}"),
        )
        return False
    except OSError as exc:
        print(f"  FAIL  {label}: {subject}: {exc}")
        add_check(
            "import",
            subject,
            critical,
            "fail",
            fix_hint(f"repair Python interpreter/dependency path for {module!r}: {exc}"),
        )
        return False

    if result.returncode == 0:
        print(f"  OK    {label}: {subject}")
        add_check("import", subject, critical, "pass", "")
        return True
    err = (result.stderr or result.stdout or "").strip()
    print(f"  FAIL  {label}: {subject}: {err}")
    add_check(
        "import",
        subject,
        critical,
        "fail",
        fix_hint(f"install/repair Python dependency {module!r} in {interpreter}"),
    )
    return False


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def check_swap_binary():
    path = Path(PINNED_SWAP_BINARY)
    realpath = Path(os.path.realpath(path))
    ok = True

    if not check_file(path, "SWAP binary", kind="binary", critical=True, executable=True):
        return False

    try:
        with open(path, "rb") as f:
            magic = f.read(4)
        if magic != b"\x7fELF":
            print(f"  FAIL  SWAP binary format: expected ELF, got {magic!r}")
            add_check(
                "binary",
                realpath,
                True,
                "fail",
                fix_hint("rebuild SWAP v4.2.0 with Meson so builddir/swap is an ELF executable"),
            )
            ok = False
        else:
            print(f"  OK    SWAP binary format: ELF executable")
            add_check("binary", realpath, True, "pass", "")
    except OSError as exc:
        print(f"  FAIL  SWAP binary readable: {exc}")
        add_check("binary", realpath, True, "fail", fix_hint(f"repair readable executable {path}"))
        ok = False

    if path.is_file():
        digest = sha256(path)
        if digest == PINNED_SWAP_SHA256:
            print(f"  OK    SWAP binary sha256: {digest}")
            add_check("binary", f"{realpath}:sha256", True, "pass", "")
        else:
            print(f"  FAIL  SWAP binary sha256: {digest}")
            add_check(
                "binary",
                f"{realpath}:sha256",
                True,
                "fail",
                fix_hint("restore the pinned SWAP build or update the KI pin after validation"),
            )
            ok = False

    return ok


def check_swap_starts():
    case_dir = MODEL_ROOT / "work" / "devcase_hupselbrook"
    required = [
        "swap.swp",
        "283.met",
        "grassd.crp",
        "maizes.crp",
        "potatod.crp",
        "swap.dra",
    ]
    missing = [name for name in required if not (case_dir / name).is_file()]
    subject = f"{os.path.realpath(PINNED_SWAP_BINARY)} starts on {case_dir}"
    if missing:
        print(f"  FAIL  SWAP smoke case: missing {', '.join(missing)}")
        add_check(
            "run",
            subject,
            True,
            "fail",
            fix_hint(f"restore Hupselbrook smoke-case files in {case_dir}"),
        )
        return False

    with tempfile.TemporaryDirectory(prefix="swap_preflight_") as tmp:
        tmp_path = Path(tmp)
        for name in required:
            shutil.copy2(case_dir / name, tmp_path / name)
        try:
            result = subprocess.run(
                [PINNED_SWAP_BINARY],
                cwd=tmp_path,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except subprocess.TimeoutExpired:
            print("  FAIL  SWAP smoke run: timed out after 15s")
            add_check(
                "run",
                subject,
                True,
                "fail",
                fix_hint("run tools/run_swap.py on the Hupselbrook case and inspect timestep/input diagnostics"),
            )
            return False
        except OSError as exc:
            print(f"  FAIL  SWAP smoke run: could not start: {exc}")
            add_check("run", subject, True, "fail", fix_hint(f"repair executable start failure: {exc}"))
            return False

        log_text = ""
        log_file = tmp_path / "swap_swap.log"
        if log_file.is_file():
            log_text = log_file.read_text(errors="replace")
        combined = "\n".join([result.stdout or "", result.stderr or "", log_text]).lower()
        success = result.returncode in (0, 100) and (
            "swap simulation okay" in combined
            or "normal completion" in combined
            or (tmp_path / "swap.ok").is_file()
        )
        if success:
            print(f"  OK    SWAP smoke run: started and completed, rc={result.returncode}")
            add_check("run", subject, True, "pass", "")
            return True

        tail = combined[-500:].replace("\n", " ")
        print(f"  FAIL  SWAP smoke run: rc={result.returncode}; tail={tail}")
        add_check(
            "run",
            subject,
            True,
            "fail",
            fix_hint("run tools/run_swap.py on the Hupselbrook case and inspect diagnostics/triplets.yaml"),
        )
        return False


def main():
    print(f"{' PREFLIGHT: SWAP ':=^60}")
    print()

    check_dir(KI_DIR / "tools", "KI tools directory", critical=True, min_items=7)
    for rel in [
        "SKILL.md",
        "knowledge_infrastructure.yaml",
        "dag.yaml",
        "diagnostics/triplets.yaml",
        "tools/run_swap.py",
        "tools/assemble_swap_config.py",
        "tools/convert_forcing_to_swap.py",
        "tools/convert_soil_to_swap.py",
        "tools/parse_swap_output.py",
        "tools/plot_swap_results.py",
        "tools/score_swap_point_obs.py",
    ]:
        check_file(KI_DIR / rel, rel, critical=True)

    print()
    check_swap_binary()
    check_swap_starts()

    print()
    check_import("numpy", "NumPy", critical=True)
    check_import("matplotlib", "Matplotlib", critical=True)
    check_import("ki_tools_common.load_forcing", "HydroCraft forcing loader", critical=True)
    check_import("ki_tools_common.soil_utils", "HydroCraft soil lookup", critical=True)
    check_import("ki_tools_common.metrics", "HydroCraft metrics", critical=True)

    print()
    for rel in [
        "work/devcase_hupselbrook/swap.swp",
        "work/devcase_hupselbrook/283.met",
        "work/devcase_hupselbrook/grassd.crp",
        "work/devcase_hupselbrook/maizes.crp",
        "work/devcase_hupselbrook/potatod.crp",
        "work/devcase_hupselbrook/swap.dra",
    ]:
        check_file(MODEL_ROOT / rel, rel, critical=True)

    passed = sum(1 for c in CHECKS if c["status"] == "pass")
    failed = sum(1 for c in CHECKS if c["status"] == "fail")
    print(f"\n  Results: {passed} passed, {failed} failed")
    if failed:
        print(f"  STATUS: PREFLIGHT FAILED. Fix failures above; recovery hints are in {TRIPLETS}.")
    else:
        print("  STATUS: PREFLIGHT PASSED. Safe to proceed with the real SWAP model.")

    emit_report(MODEL_ID, CHECKS)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"  FAIL  preflight_check.py crashed: {exc}")
        add_check(
            "run",
            Path(__file__).resolve(),
            True,
            "fail",
            fix_hint(f"repair preflight_check.py crash: {exc}"),
        )
        emit_report(MODEL_ID, CHECKS)
