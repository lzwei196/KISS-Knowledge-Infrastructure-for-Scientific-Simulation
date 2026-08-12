"""s4_update_site.py — Update *.SIT lat/lon/elevation in place.

The validated APEX example uses Marena, OK (35.54°N, -98.05°W). To retarget
to a new field, only the first three F8.2 fields on data line 1 of the SIT
header block need to change: LAT, LON, ELEV (m). Azimuth, slope, CO2 etc.
are kept at the validated defaults.

**APEX0806 vs APEX1501 filename note**: APEX1501 workspaces use ``SITE01.SIT``;
APEX0806 workspaces (ex1_RiselTX template) use ``SIT0002.SIT`` (or similar).
Pass ``--sit-name <filename>`` to target the correct file, or use
``--auto-detect`` to read the first ``*.SIT`` entry from ``SITECOM.DAT``.
Default is ``SITE01.SIT`` for backward compatibility with APEX1501 workspaces.
"""
from __future__ import annotations

from pathlib import Path

SIT_NAME = "SITE01.SIT"


def _detect_sit_name(ws: Path) -> str:
    """Read SITECOM.DAT (APEX0806) or SITELIST.DAT (APEX1501) and return
    the first *.SIT filename referenced, or fall back to SITE01.SIT."""
    for list_file in ("SITECOM.DAT", "SITELIST.DAT"):
        p = ws / list_file
        if p.is_file():
            for line in p.read_text(errors="replace").splitlines():
                parts = line.split()
                for tok in parts:
                    if tok.upper().endswith(".SIT"):
                        return tok
    # Last resort: find any .SIT in workspace
    sits = list(ws.glob("*.SIT")) + list(ws.glob("*.sit"))
    if sits:
        return sits[0].name
    return SIT_NAME


def validate_inputs(workspace: Path, lat: float, lon: float, elev_m: float,
                    sit_name: str = SIT_NAME) -> None:
    if not workspace.is_dir():
        raise FileNotFoundError(f"Workspace does not exist: {workspace}")
    if not (workspace / sit_name).is_file():
        raise FileNotFoundError(
            f"{sit_name} missing in workspace: {workspace}\n"
            f"  Tip: use --sit-name <file> or --auto-detect to find the correct *.SIT file.\n"
            f"  Available: {[p.name for p in workspace.glob('*.SIT')] + [p.name for p in workspace.glob('*.sit')]}"
        )
    if not -90.0 <= lat <= 90.0:
        raise ValueError(f"lat out of range: {lat}")
    if not -180.0 <= lon <= 180.0:
        raise ValueError(f"lon out of range: {lon}")
    if not -500.0 <= elev_m <= 9000.0:
        raise ValueError(f"elev_m out of range: {elev_m}")


def update_site(workspace, *, lat: float, lon: float, elev_m: float,
                sit_name: str | None = None) -> Path:
    """Update SIT file lat/lon/elevation.

    Args:
        sit_name: Target SIT filename.  If None (default), auto-detects from
            SITECOM.DAT (APEX0806) or SITELIST.DAT (APEX1501).  Pass
            ``"SITE01.SIT"`` explicitly for APEX1501 workspaces.
    """
    ws = Path(workspace).expanduser().resolve()
    if sit_name is None:
        sit_name = _detect_sit_name(ws)
    validate_inputs(ws, lat, lon, elev_m, sit_name)

    sit_path = ws / sit_name
    lines = sit_path.read_text().splitlines()
    if len(lines) < 4:
        raise RuntimeError(f"{sit_path} has only {len(lines)} lines; expected ≥ 4")

    # Header line 1: site name; line 2: subarea name; line 3: blank; line 4: data row
    data_idx = 3
    fields = lines[data_idx].split()
    if len(fields) < 5:
        raise RuntimeError(f"{sit_path} line {data_idx+1} has too few fields: {fields!r}")

    # Replace the three leading floats; preserve trailing fields verbatim.
    #
    # *.SIT line 4 is Fortran F8.2 -- TEN 8-character columns, NO leading pad
    # (the shipped template reads "   31.47  -96.88  166.06    0.25  330.00").
    # Emitting a 3-space prefix (the pre-2026-08-09 behaviour) pushed every
    # field 3 columns right, so APEX re-read the row as
    #   YLAT=32, XLOG=0.25, ELEV=0.25, APM=0.0, CO2X=0.25 ppm ...
    # A CO2X of 0.25 ppm starves photosynthesis: maize collapsed from ~15 to
    # 0.6 t/ha with NO stress flag raised (WS/NS/PS all ~0), i.e. a completely
    # silent wrong answer.  split()-based validation could not see it, so
    # validate_outputs now re-reads the row by COLUMN.
    tail = fields[3:]
    new_fields = [f"{lat:8.2f}", f"{lon:8.2f}", f"{elev_m:8.2f}"]
    for f in tail:
        new_fields.append(f"{float(f):8.2f}")
    lines[data_idx] = "".join(new_fields)

    sit_path.write_text("\n".join(lines) + "\n")
    validate_outputs(sit_path, lat, lon, elev_m)
    return sit_path


def _fixed_fields(line: str, width: int = 8, n: int = 10) -> list[float]:
    """Read ``line`` the way Fortran F8.2 does: fixed 8-column chunks."""
    out = []
    for i in range(n):
        chunk = line[i * width:(i + 1) * width]
        if not chunk.strip():
            break
        try:
            out.append(float(chunk.replace(" ", "")))
        except ValueError:
            out.append(float("nan"))
    return out


def validate_outputs(sit_path: Path, lat: float, lon: float, elev_m: float,
                     sit_name: str = SIT_NAME) -> None:
    lines = sit_path.read_text().splitlines()
    fields = lines[3].split()
    actual_lat, actual_lon, actual_elev = float(fields[0]), float(fields[1]), float(fields[2])
    if abs(actual_lat - lat) > 0.01:
        raise RuntimeError(f"{sit_path}: lat write-back mismatch {actual_lat} vs {lat}")
    if abs(actual_lon - lon) > 0.01:
        raise RuntimeError(f"{sit_path}: lon write-back mismatch {actual_lon} vs {lon}")
    if abs(actual_elev - elev_m) > 0.5:
        raise RuntimeError(f"{sit_path}: elev write-back mismatch {actual_elev} vs {elev_m}")

    # ALSO validate the way APEX actually parses the row (fixed 8-col fields).
    cols = _fixed_fields(lines[3])
    if len(cols) < 3:
        raise RuntimeError(f"{sit_path}: line 4 has < 3 fixed-width columns")
    if (abs(cols[0] - lat) > 0.01 or abs(cols[1] - lon) > 0.01
            or abs(cols[2] - elev_m) > 0.5):
        raise RuntimeError(
            f"{sit_path}: line 4 is not column-aligned for APEX's F8.2 read — "
            f"fixed-width parse gives lat/lon/elev {cols[:3]} but "
            f"{[lat, lon, elev_m]} was requested. Line: {lines[3]!r}")
    if len(cols) >= 5 and not (100.0 <= cols[4] <= 1200.0):
        raise RuntimeError(
            f"{sit_path}: CO2X (line 4 field 5) = {cols[4]} ppm is outside "
            f"[100,1200] — the row is almost certainly mis-aligned. "
            f"Line: {lines[3]!r}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--workspace", required=True)
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)
    p.add_argument("--elev", type=float, required=True)
    p.add_argument("--sit-name", default=None,
                   help="Target SIT filename (default: auto-detect from SITECOM.DAT / SITELIST.DAT)")
    args = p.parse_args()
    out = update_site(args.workspace, lat=args.lat, lon=args.lon, elev_m=args.elev,
                      sit_name=args.sit_name)
    print(f"[OK] site updated at {out}")
