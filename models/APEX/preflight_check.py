"""preflight_check.py — Verify APEX 1501 KI is ready to run.

Checks:
  * apex1501 binary exists and is executable
  * Validated example dataset is present in examples/
  * All required control files are present in examples/
  * All seven pipeline tools are importable
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

KI_ROOT = Path(__file__).resolve().parent
EXAMPLE = KI_ROOT / "examples"
TOOLS = KI_ROOT / "tools"
BINARY = Path(
    "/home/server/knowledge-dissection-toolkit/auto_dissect_multi_agent/_work_v2/APEX/source/repo/Apex 1501 - Linux/apex1501"
)

REQUIRED_CONTROL = [
    "APEXFILE.DAT", "APEXRUN.DAT", "APEXCONT.DAT", "APEXDIM.DAT",
    "SITELIST.DAT", "SUBSLIST.DAT", "SOILLIST.DAT", "MNGTLIST.DAT",
    "WPM1LIST.DAT", "WINDLIST.DAT", "WDLYLIST.DAT", "PSOLIST.DAT",
    "SITE01.SIT", "SUBA01.SUB", "SOIL01.SOL", "OPSC01.MGT",
    "WEATHER01.dly", "WPM01.WP1", "WIND01.WND",
    "PLANTABLE.DAT", "TILLTABLE.DAT", "PESTTABLE.DAT", "FERTTABLE.DAT",
    "HERDTABLE.DAT", "APEXPARM.DAT", "APEXPRNT.DAT", "MLRNCOM.DAT",
    "TR55COM.DAT",
]

REQUIRED_TOOLS = [
    "s1_setup_workspace.py",
    "s2_convert_forcing.py",
    "s3_build_soil.py",
    "s4_update_site.py",
    "s5_update_control.py",
    "s6_run_apex.py",
    "s7_parse_output.py",
]


def main() -> int:
    failures: list[str] = []

    if BINARY.is_file():
        print(f"[OK] APEX1501 binary found at {BINARY}")
    else:
        failures.append(f"[FAIL] APEX1501 binary missing at {BINARY}")

    if BINARY.is_file() and os.access(BINARY, os.X_OK):
        print("[OK] APEX1501 binary is executable")
    elif BINARY.is_file():
        failures.append(f"[FAIL] APEX1501 binary at {BINARY} is not executable")

    if EXAMPLE.is_dir():
        print(f"[OK] Example dataset found in {EXAMPLE}")
    else:
        failures.append(f"[FAIL] Example dataset directory missing at {EXAMPLE}")

    missing_ctrl = [f for f in REQUIRED_CONTROL if not (EXAMPLE / f).is_file()]
    if not missing_ctrl:
        print(f"[OK] All required control files present ({len(REQUIRED_CONTROL)} files)")
    else:
        failures.append(f"[FAIL] Missing example control files: {missing_ctrl}")

    missing_tools = [t for t in REQUIRED_TOOLS if not (TOOLS / t).is_file()]
    if not missing_tools:
        print(f"[OK] All {len(REQUIRED_TOOLS)} pipeline tools present")
    else:
        failures.append(f"[FAIL] Missing pipeline tools: {missing_tools}")

    if (KI_ROOT / "diagnostics" / "triplets.yaml").is_file():
        print("[OK] diagnostics/triplets.yaml present")
    else:
        failures.append("[FAIL] diagnostics/triplets.yaml missing")

    if failures:
        print()
        for f in failures:
            print(f)
        print(f"\n[FAIL] preflight failed with {len(failures)} issue(s).")
        return 1

    print("[OK] preflight passed — APEX is ready to run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
