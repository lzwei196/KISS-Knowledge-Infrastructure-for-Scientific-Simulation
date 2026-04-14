"""s1_setup_workspace.py — Copy the validated APEX example template into a fresh workspace.

This is the first stage of the APEX KI. It implements the COPY-FIRST rule:
we never generate any APEX input file from scratch. Instead we copy the entire
shipped example dataset (USDA-ARS WRE Mesonet OK pasture, the only setup
verified to drive apex1501 to a clean 15-year completion) and let later stages
modify specific values in place.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

KI_ROOT  = Path(__file__).resolve().parents[1]
EXAMPLE  = KI_ROOT / "examples"
BINARY   = Path(
    "/home/server/knowledge-dissection-toolkit/auto_dissect_multi_agent/_work_v2/APEX/source/repo/Apex 1501 - Linux/apex1501"
)


def validate_inputs(workspace: str | os.PathLike) -> None:
    if not EXAMPLE.is_dir():
        raise FileNotFoundError(
            f"APEX example template missing at {EXAMPLE}. "
            "Re-run `git status` on the KI directory or restore from backup."
        )
    if not BINARY.is_file():
        raise FileNotFoundError(f"APEX 1501 binary missing at {BINARY}")
    if not os.access(BINARY, os.X_OK):
        raise PermissionError(f"APEX 1501 binary at {BINARY} is not executable")
    parent = Path(workspace).expanduser().resolve().parent
    if not parent.exists():
        raise FileNotFoundError(f"Parent directory of workspace does not exist: {parent}")


def setup(workspace: str | os.PathLike, *, overwrite: bool = True) -> Path:
    """Copy the shipped example into ``workspace`` and place the binary there."""
    validate_inputs(workspace)
    ws = Path(workspace).expanduser().resolve()
    if ws.exists():
        if not overwrite:
            raise FileExistsError(f"{ws} already exists (pass overwrite=True to replace)")
        shutil.rmtree(ws)
    shutil.copytree(EXAMPLE, ws)
    shutil.copy2(BINARY, ws / "apex1501")
    os.chmod(ws / "apex1501", 0o755)
    validate_outputs(ws)
    return ws


def validate_outputs(ws: Path) -> None:
    required = [
        "APEXFILE.DAT", "APEXRUN.DAT", "APEXCONT.DAT", "APEXDIM.DAT",
        "SITELIST.DAT", "SUBSLIST.DAT", "SOILLIST.DAT", "MNGTLIST.DAT",
        "WPM1LIST.DAT", "WINDLIST.DAT", "WDLYLIST.DAT", "PSOLIST.DAT",
        "SITE01.SIT", "SUBA01.SUB", "SOIL01.SOL", "OPSC01.MGT",
        "WEATHER01.dly", "WPM01.WP1", "WIND01.WND",
        "PLANTABLE.DAT", "TILLTABLE.DAT", "PESTTABLE.DAT", "FERTTABLE.DAT",
        "HERDTABLE.DAT", "APEXPARM.DAT", "APEXPRNT.DAT", "MLRNCOM.DAT",
        "TR55COM.DAT", "apex1501",
    ]
    missing = [f for f in required if not (ws / f).is_file()]
    if missing:
        raise RuntimeError(
            f"setup() left workspace incomplete — missing files: {missing}"
        )


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "/tmp/apex_ws"
    out = setup(target)
    print(f"[OK] APEX workspace ready at {out}")
    print(f"     {len(list(out.iterdir()))} files copied; binary in place.")
