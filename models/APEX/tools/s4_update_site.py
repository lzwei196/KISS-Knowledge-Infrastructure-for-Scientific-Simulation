"""s4_update_site.py — Update SITE01.SIT lat/lon/elevation in place.

The validated APEX example uses Marena, OK (35.54°N, -98.05°W). To retarget
to a new field, only the first three F8.2 fields on data line 1 of the SIT
header block need to change: LAT, LON, ELEV (m). Azimuth, slope, CO2 etc.
are kept at the validated defaults.
"""
from __future__ import annotations

from pathlib import Path

SIT_NAME = "SITE01.SIT"


def validate_inputs(workspace: Path, lat: float, lon: float, elev_m: float) -> None:
    if not workspace.is_dir():
        raise FileNotFoundError(f"Workspace does not exist: {workspace}")
    if not (workspace / SIT_NAME).is_file():
        raise FileNotFoundError(f"{SIT_NAME} missing in workspace")
    if not -90.0 <= lat <= 90.0:
        raise ValueError(f"lat out of range: {lat}")
    if not -180.0 <= lon <= 180.0:
        raise ValueError(f"lon out of range: {lon}")
    if not -500.0 <= elev_m <= 9000.0:
        raise ValueError(f"elev_m out of range: {elev_m}")


def update_site(workspace, *, lat: float, lon: float, elev_m: float) -> Path:
    ws = Path(workspace).expanduser().resolve()
    validate_inputs(ws, lat, lon, elev_m)

    sit_path = ws / SIT_NAME
    lines = sit_path.read_text().splitlines()
    if len(lines) < 4:
        raise RuntimeError(f"{sit_path} has only {len(lines)} lines; expected ≥ 4")

    # Header line 1: site name; line 2: subarea name; line 3: blank; line 4: data row
    data_idx = 3
    fields = lines[data_idx].split()
    if len(fields) < 5:
        raise RuntimeError(f"{sit_path} line {data_idx+1} has too few fields: {fields!r}")

    # Replace the three leading floats; preserve trailing fields verbatim.
    tail = fields[3:]
    new_fields = [f"{lat:8.2f}", f"{lon:8.2f}", f"{elev_m:8.2f}"]
    for f in tail:
        new_fields.append(f"{float(f):8.2f}")
    lines[data_idx] = "   " + "".join(new_fields)

    sit_path.write_text("\n".join(lines) + "\n")
    validate_outputs(sit_path, lat, lon, elev_m)
    return sit_path


def validate_outputs(sit_path: Path, lat: float, lon: float, elev_m: float) -> None:
    lines = sit_path.read_text().splitlines()
    fields = lines[3].split()
    actual_lat, actual_lon, actual_elev = float(fields[0]), float(fields[1]), float(fields[2])
    if abs(actual_lat - lat) > 0.01:
        raise RuntimeError(f"{sit_path}: lat write-back mismatch {actual_lat} vs {lat}")
    if abs(actual_lon - lon) > 0.01:
        raise RuntimeError(f"{sit_path}: lon write-back mismatch {actual_lon} vs {lon}")
    if abs(actual_elev - elev_m) > 0.5:
        raise RuntimeError(f"{sit_path}: elev write-back mismatch {actual_elev} vs {elev_m}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--workspace", required=True)
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)
    p.add_argument("--elev", type=float, required=True)
    args = p.parse_args()
    out = update_site(args.workspace, lat=args.lat, lon=args.lon, elev_m=args.elev)
    print(f"[OK] site updated at {out}")
