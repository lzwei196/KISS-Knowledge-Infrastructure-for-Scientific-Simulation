"""s3_build_soil.py — Edit the SOIL01.SOL template with HWSD-derived properties.

Looks up the topsoil/subsoil sand/silt/clay/OC/pH/bulk-density at ``(lat, lon)``
from HWSD via ``ki_tools_common.soil_utils.lookup_hwsd`` and rewrites the rows
of the validated template that hold those quantities. Layer count, layer depths
and any unrelated rows are preserved verbatim — this is a copy-template-and-
modify pass, not a regeneration.

The example template uses 5 layers of constant thickness. We populate layers
1-2 with the HWSD topsoil values and layers 3-5 with the subsoil values.
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

# 1-indexed line numbers (matching the validated template structure)
ROW_BD = 5    # bulk density g/cm3
ROW_SAND = 8  # sand %
ROW_SILT = 9  # silt %
ROW_PH = 11   # pH
ROW_OC = 13   # organic C %


def validate_inputs(workspace: Path, lat: float, lon: float) -> None:
    if not workspace.is_dir():
        raise FileNotFoundError(f"Workspace does not exist: {workspace}")
    if not (workspace / SOL_NAME).is_file():
        raise FileNotFoundError(f"{SOL_NAME} missing in workspace")
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


def build_soil(workspace, *, lat: float, lon: float) -> Path:
    ws = Path(workspace).expanduser().resolve()
    validate_inputs(ws, lat, lon)

    hwsd = lookup_hwsd(lat, lon)

    sol_path = ws / SOL_NAME
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


def validate_outputs(sol_path: Path) -> None:
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
    args = p.parse_args()
    out = build_soil(args.workspace, lat=args.lat, lon=args.lon)
    print(f"[OK] soil written to {out}")
