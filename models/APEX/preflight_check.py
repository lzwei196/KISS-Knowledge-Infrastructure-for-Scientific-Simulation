"""Verify the APEX v0806 KI with the real Riesel reference run.

The public GeoForge repository does not redistribute the licensed APEX0806
executable or its reference template. Once the user has installed those into
the shared KI, GeoForge carries them into each session working copy. This
check deliberately validates v0806 -- never the incompatible v1501 binary.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


KI_ROOT = Path(__file__).resolve().parent
EXAMPLE = KI_ROOT / "examples" / "ex1_RiselTX"
TOOLS = KI_ROOT / "tools"
BINARY = KI_ROOT / "reference" / "APEX0806.exe"

REQUIRED_CONTROL = [
    "APEXFILE.DAT", "APEXRUN.DAT", "APEXCONT.DAT", "APEXDIM.DAT",
    "SITECOM.DAT", "SUBACOM.DAT", "SOILCOM.DAT", "OPSCCOM.DAT",
    "CROPCOM.DAT", "TILLCOM.DAT", "FERTCOM.DAT", "TR55COM.DAT",
]
REQUIRED_TOOLS = [f"s{i}_{name}.py" for i, name in enumerate((
    "setup_workspace", "convert_forcing", "build_soil", "update_site",
    "update_control", "run_apex", "parse_output", "update_operations",
    "generate_crop_opc",
), start=1)]


def _run(argv: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv, capture_output=True, text=True, timeout=timeout, check=False,
    )


def main() -> int:
    failures: list[str] = []

    if BINARY.is_file():
        print(f"[OK] APEX0806 binary found at {BINARY}")
        try:
            if BINARY.read_bytes()[:2] == b"MZ":
                print("[OK] APEX0806 binary has a valid PE header")
            else:
                failures.append(f"[FAIL] {BINARY} is not a PE executable")
        except OSError as exc:
            failures.append(f"[FAIL] could not read APEX0806 binary: {exc}")
    else:
        failures.append(f"[FAIL] APEX0806 binary missing at {BINARY}")

    wine = shutil.which("wine")
    if wine:
        print(f"[OK] Wine runtime found at {wine}")
    else:
        failures.append("[FAIL] Wine runtime is not installed or not on PATH")

    if EXAMPLE.is_dir():
        print(f"[OK] Riesel reference template found at {EXAMPLE}")
    else:
        failures.append(f"[FAIL] Riesel reference template missing at {EXAMPLE}")

    missing_control = [name for name in REQUIRED_CONTROL
                       if not (EXAMPLE / name).is_file()]
    if missing_control:
        failures.append(f"[FAIL] Missing v0806 reference files: {missing_control}")
    else:
        print(f"[OK] All {len(REQUIRED_CONTROL)} v0806 reference files are present")

    missing_tools = [name for name in REQUIRED_TOOLS if not (TOOLS / name).is_file()]
    if missing_tools:
        failures.append(f"[FAIL] Missing pipeline tools: {missing_tools}")
    else:
        print(f"[OK] All {len(REQUIRED_TOOLS)} s1-s9 pipeline tools are present")

    triplets = KI_ROOT / "diagnostics" / "triplets.yaml"
    if triplets.is_file():
        print("[OK] diagnostics/triplets.yaml present")
    else:
        failures.append("[FAIL] diagnostics/triplets.yaml missing")

    # Do not call the run tool when a prerequisite is absent; the resulting
    # traceback hides the one concrete action the user may need to take.
    if not failures:
        try:
            with tempfile.TemporaryDirectory(prefix="geoforge-apex-preflight-") as td:
                workspace = Path(td) / "riesel"
                setup = _run(
                    [sys.executable, str(TOOLS / "s1_setup_workspace.py"),
                     str(workspace)],
                    timeout=30,
                )
                if setup.returncode != 0:
                    failures.append(
                        "[FAIL] s1 could not prepare the Riesel workspace:\n" +
                        (setup.stderr or setup.stdout)[-4000:])
                else:
                    run = _run(
                        [sys.executable, str(TOOLS / "s6_run_apex.py"),
                         "--workspace", str(workspace), "--timeout", "120"],
                        timeout=150,
                    )
                    outputs = [p for pattern in ("*.ACY", "*.OUT")
                               for p in workspace.glob(pattern)
                               if p.is_file() and p.stat().st_size > 0]
                    if run.returncode == 0 and outputs:
                        print("[OK] Real APEX0806 Riesel run completed with fresh output")
                    else:
                        detail = (run.stderr or run.stdout)[-5000:]
                        failures.append(
                            "[FAIL] Real APEX0806 Riesel run did not complete "
                            f"(rc={run.returncode}):\n{detail}")
        except subprocess.TimeoutExpired as exc:
            failures.append(f"[FAIL] Real APEX0806 reference run timed out: {exc}")
        except OSError as exc:
            failures.append(f"[FAIL] Could not launch the APEX0806 reference run: {exc}")

    if failures:
        print()
        for failure in failures:
            print(failure)
        print(f"\n[FAIL] preflight failed with {len(failures)} issue(s).")
        return 1

    print("[OK] preflight passed — APEX0806 is installed and runnable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
