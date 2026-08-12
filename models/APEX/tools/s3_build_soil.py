"""s3_build_soil.py — Edit the *.SOL template with HWSD-derived properties.

Looks up the topsoil/subsoil sand/silt/clay/OC/pH/bulk-density at ``(lat, lon)``
from HWSD via ``ki_tools_common.soil_utils.lookup_hwsd`` and rewrites the rows
of the validated template that hold those quantities. Layer count, layer depths
and any unrelated rows are preserved verbatim — this is a copy-template-and-
modify pass, not a regeneration.

The example template uses 5 layers of constant thickness. We populate layers
1-2 with the HWSD topsoil values and layers 3-5 with the subsoil values.

**APEX0806 vs APEX1501 filename note**: APEX1501 workspaces use ``SOIL01.SOL``;
APEX0806 workspaces (ex1_RiselTX template) use ``Heiden.SOL`` (or ``HoustonB.SOL``
etc.).  Pass ``--sol-name <filename>`` to target the correct file, or use
``--auto-detect`` to read the first ``*.SOL`` entry from ``SOILCOM.DAT``.
Default is ``SOIL01.SOL`` for backward compatibility with APEX1501 workspaces.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make ki_tools_common importable
_KDT = Path("/home/server/knowledge-dissection-toolkit/auto_dissect_multi_agent")
if str(_KDT) not in sys.path:
    sys.path.insert(0, str(_KDT))

from ki_tools_common.soil_utils import lookup_hwsd  # noqa: E402

SOL_NAME = "SOIL01.SOL"


def _detect_sol_names(ws: Path) -> list[str]:
    """Return EVERY *.SOL filename referenced by SOILCOM.DAT (APEX0806) or
    SOILLIST.DAT (APEX1501), in list order.

    Why all of them (fixed 2026-08-09): the shipped ex1_RiselTX template lists
    three Texas soils and its four subareas reference soil ids 1 AND 2
    (``*.SUB`` line 2 field 1 = INPS).  Rewriting only the FIRST listed soil
    left 3 of the 4 subareas simulating Texas Houston-Black clay at a China
    site -- a silent, un-flagged wrong-soil run.  Callers that really want a
    single file can still pass ``sol_name=``.
    """
    names: list[str] = []
    for list_file in ("SOILCOM.DAT", "SOILLIST.DAT"):
        p = ws / list_file
        if p.is_file():
            for line in p.read_text(errors="replace").splitlines():
                for tok in line.split():
                    if tok.upper().endswith(".SOL") and tok not in names:
                        names.append(tok)
            if names:
                return names
    # Last resort: find any .SOL / .sol in workspace
    sols = list(ws.glob("*.SOL")) + list(ws.glob("*.sol"))
    if sols:
        return [sols[0].name]
    return [SOL_NAME]


def _detect_sol_name(ws: Path) -> str:
    """Back-compat single-file variant of :func:`_detect_sol_names`."""
    return _detect_sol_names(ws)[0]

# 1-indexed line numbers (matching the validated template structure)
ROW_BD = 5    # bulk density g/cm3
ROW_SAND = 8  # sand %
ROW_SILT = 9  # silt %
ROW_PH = 11   # pH
ROW_OC = 13   # organic C %


def validate_inputs(workspace: Path, lat: float, lon: float,
                    sol_name: str = SOL_NAME) -> None:
    if not workspace.is_dir():
        raise FileNotFoundError(f"Workspace does not exist: {workspace}")
    if not (workspace / sol_name).is_file():
        raise FileNotFoundError(
            f"{sol_name} missing in workspace: {workspace}\n"
            f"  Tip: use --sol-name <file> or --auto-detect to find the correct *.SOL file.\n"
            f"  Available: {[p.name for p in workspace.glob('*.SOL')] + [p.name for p in workspace.glob('*.sol')]}"
        )
    if not -90.0 <= lat <= 90.0:
        raise ValueError(f"lat out of range: {lat}")
    if not -180.0 <= lon <= 180.0:
        raise ValueError(f"lon out of range: {lon}")


def _format_layer_row(values: list[float]) -> str:
    return "".join(f"{v:8.2f}" for v in values)


def _layer_values(top: float, sub: float, n_layers: int) -> list[float]:
    out: list[float] = []
    for i in range(n_layers):
        out.append(top if i < 2 else sub)
    return out


def build_soil(workspace, *, lat: float, lon: float,
               sol_name: str | None = None,
               all_soils: bool = True) -> Path:
    """Build soil file(s) from HWSD lookup.

    Args:
        sol_name: Target SOL filename.  If None (default), auto-detects from
            SOILCOM.DAT (APEX0806) or SOILLIST.DAT (APEX1501).  Pass
            ``"SOIL01.SOL"`` explicitly for APEX1501 workspaces.
        all_soils: When ``sol_name`` is None, rewrite EVERY soil referenced by
            the soil list file (default).  The multi-subarea templates point
            different subareas at different soil ids, so rewriting only the
            first one leaves the rest on the template's original (Texas) soil.
            Set False to restore the pre-2026-08-09 first-file-only behaviour.

    Returns the path of the LAST soil file written (all of them share the same
    HWSD-derived properties).
    """
    ws = Path(workspace).expanduser().resolve()
    if sol_name is not None:
        targets = [sol_name]
    elif all_soils:
        targets = _detect_sol_names(ws)
    else:
        targets = [_detect_sol_name(ws)]

    hwsd = lookup_hwsd(lat, lon)
    written = None
    for tgt in targets:
        resolved = _resolve_case(ws, tgt)
        if resolved is None:
            # The shipped ex1_RiselTX SOILCOM.DAT references "Houston.sol"
            # while the file on disk is "HOUSTON.SOL" (and no subarea uses it).
            # A dangling list entry must not abort the whole soil build.
            print(f"  WARN: {tgt} listed in the soil list but not on disk — skipped")
            continue
        written = _apply_hwsd_to_sol(ws, lat, lon, resolved, hwsd)
    if written is None:
        raise FileNotFoundError(
            f"None of the listed soil files exist in {ws}: {targets}")
    return written


def _resolve_case(ws: Path, name: str) -> str | None:
    """Return the on-disk filename matching ``name`` case-insensitively."""
    if (ws / name).is_file():
        return name
    low = name.lower()
    for p in ws.iterdir():
        if p.is_file() and p.name.lower() == low:
            return p.name
    return None


def _apply_hwsd_to_sol(ws: Path, lat: float, lon: float,
                       sol_name: str, hwsd: dict) -> Path:
    validate_inputs(ws, lat, lon, sol_name)

    sol_path = ws / sol_name
    raw_lines = sol_path.read_text().splitlines()
    if len(raw_lines) < ROW_OC:
        raise RuntimeError(f"{sol_path} has only {len(raw_lines)} lines; expected ≥ {ROW_OC}")

    # The template uses 5 layers — counted from the bulk density row.
    bd_fields = raw_lines[ROW_BD - 1].split()
    n_layers = len([x for x in bd_fields if x not in ("0.00", "0.0", "0")])
    if n_layers == 0:
        n_layers = 5

    bd_layers = _layer_values(hwsd["bulk_density"], hwsd["bulk_density"], n_layers)
    sand_layers = _layer_values(hwsd["sand"], hwsd["sub_sand"], n_layers)
    silt_layers = _layer_values(hwsd["silt"], hwsd["sub_silt"], n_layers)
    ph_layers = _layer_values(hwsd["ph"], hwsd["ph"], n_layers)
    oc_layers = _layer_values(hwsd["oc"], hwsd["oc"] * 0.5, n_layers)

    raw_lines[ROW_BD - 1] = _format_layer_row(bd_layers)
    raw_lines[ROW_SAND - 1] = _format_layer_row(sand_layers)
    raw_lines[ROW_SILT - 1] = _format_layer_row(silt_layers)
    raw_lines[ROW_PH - 1] = _format_layer_row(ph_layers)
    raw_lines[ROW_OC - 1] = _format_layer_row(oc_layers)

    sol_path.write_text("\n".join(raw_lines) + "\n")
    validate_outputs(sol_path)
    return sol_path


def validate_outputs(sol_path: Path, sol_name: str = SOL_NAME) -> None:
    lines = sol_path.read_text().splitlines()
    if len(lines) < ROW_OC:
        raise RuntimeError(f"{sol_path} truncated to {len(lines)} lines after build_soil")
    sand = [float(x) for x in lines[ROW_SAND - 1].split() if x]
    silt = [float(x) for x in lines[ROW_SILT - 1].split() if x]
    if not sand or not silt:
        raise RuntimeError(f"{sol_path}: sand/silt rows are empty")
    if any(v < 0 or v > 100 for v in sand):
        raise RuntimeError(f"sand % out of [0,100]: {sand}")
    if any(v < 0 or v > 100 for v in silt):
        raise RuntimeError(f"silt % out of [0,100]: {silt}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--workspace", required=True)
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)
    p.add_argument("--sol-name", default=None,
                   help="Target SOL filename (default: auto-detect from SOILCOM.DAT / SOILLIST.DAT)")
    p.add_argument("--first-soil-only", action="store_true",
                   help="Rewrite only the first listed soil (pre-2026-08-09 behaviour); "
                        "by default EVERY soil in the list file is rewritten so all "
                        "subareas get the site soil")
    args = p.parse_args()
    out = build_soil(args.workspace, lat=args.lat, lon=args.lon,
                     sol_name=args.sol_name,
                     all_soils=not args.first_soil_only)
    print(f"[OK] soil written to {out}")
