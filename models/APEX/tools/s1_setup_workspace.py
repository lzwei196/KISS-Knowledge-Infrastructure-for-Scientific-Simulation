"""s1_setup_workspace.py — Copy the validated APEX example template into a fresh workspace.

This is the first stage of the APEX KI. It implements the COPY-FIRST rule:
we never generate any APEX input file from scratch. Instead we copy the entire
shipped example dataset and let later stages modify specific values in place.

IMPORTANT: Uses APEX v0806 (Riesel TX cropland example), NOT v1501.
v1501 has a confirmed issue where annual crops produce zero biomass (BIOM=0.01)
with persistent P stress regardless of soil P concentration or PARM settings.
Exhaustive testing showed: 25 out-of-range PARMs fixed, soil P set to 50 ppm,
Century C/N pools initialized, S-curve convergence fixed — still zero yield.
v0806 produces 4.46 t/ha corn with the same Riesel example.
The v0806 binary is a PE32 Windows executable run via Wine.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

KI_ROOT  = Path(__file__).resolve().parents[1]
EXAMPLE  = KI_ROOT / "examples" / "ex1_RiselTX"
BINARY   = KI_ROOT / "reference" / "APEX0806.exe"


def validate_inputs(workspace: str | os.PathLike) -> None:
    if not EXAMPLE.is_dir():
        raise FileNotFoundError(
            f"APEX example template missing at {EXAMPLE}. "
            "Re-run `git status` on the KI directory or restore from backup."
        )
    if not BINARY.is_file():
        raise FileNotFoundError(f"APEX 0806 binary missing at {BINARY}")
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
    shutil.copy2(BINARY, ws / "APEX0806.exe")
    purged = purge_template_outputs(ws)
    if purged:
        print(f"  purged {len(purged)} stale template output file(s): "
              f"{', '.join(sorted(purged)[:8])}"
              f"{' ...' if len(purged) > 8 else ''}")
    validate_outputs(ws)
    return ws


# APEX writes these; the shipped ex1_RiselTX example carries a full set from
# the Texas run it was distributed with (OUTPUT.ACY/.OUT/.RCH/.AWS/... and
# fort.*).  Leaving them in a fresh workspace is a silent-wrong-answer trap:
# s7_parse_output happily parses the TEMPLATE's Texas results, so a run whose
# binary never executed (or crashed) still yields a full, plausible-looking
# yield time series.  Purge them at setup so any output present afterwards can
# only have come from this workspace's own run.  (Found 2026-08-09: a resume
# guard "*.ACY already contains CORN" matched the shipped example.)
OUTPUT_SUFFIXES = (
    ".OUT", ".ACY", ".SAD", ".SUS", ".MAN", ".MSW", ".MWS", ".DWS", ".AWS",
    ".DPS", ".AWP", ".HYC", ".RCH", ".SUM", ".ASA", ".ATG", ".DGN", ".DHY",
)
OUTPUT_PREFIXES = ("fort.",)
OUTPUT_NAMES = ("EPICERR.DAT",)


def purge_template_outputs(ws: Path) -> list[str]:
    """Delete APEX *output* artifacts copied in from the example template."""
    removed = []
    for p in list(ws.iterdir()):
        if not p.is_file():
            continue
        name = p.name
        if (name.upper().endswith(OUTPUT_SUFFIXES)
                or name.startswith(OUTPUT_PREFIXES)
                or name.upper() in OUTPUT_NAMES):
            try:
                p.unlink()
                removed.append(name)
            except OSError:
                pass
    return removed


def validate_outputs(ws: Path) -> None:
    # v0806 uses different file naming from v1501
    required = [
        "APEXFILE.DAT", "APEXRUN.DAT", "APEXCONT.DAT", "APEXDIM.DAT",
        "SITECOM.DAT", "SUBACOM.DAT", "SOILCOM.DAT", "OPSCCOM.DAT",
        "CROPCOM.DAT", "TILLCOM.DAT", "FERTCOM.DAT",
        "TR55COM.DAT", "APEX0806.exe",
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
