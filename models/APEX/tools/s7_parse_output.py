"""s7_parse_output.py — Parse APEX 1501 ``*.OUT`` annual + ``*.ACY`` files into a DataFrame.

The annual ``*.OUT`` print contains a header line followed by per-year rows
holding precipitation, ET, water yield, sediment, and crop yield columns. We
locate the column-header row by scanning for the ``YEAR`` token, then read the
fixed-width columns with ``pandas.read_fwf``. ``*.ACY`` (annual crop yield)
holds the canonical t/ha dry-matter yield per crop per year.

Returns a DataFrame keyed by (year, subarea). The ``--out`` flag also writes
a CSV.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional


def validate_inputs(workspace: Path) -> None:
    if not workspace.is_dir():
        raise FileNotFoundError(f"Workspace does not exist: {workspace}")
    has_any = any(workspace.glob("*.OUT")) or any(workspace.glob("*.ACY"))
    if not has_any:
        raise FileNotFoundError(f"No *.OUT or *.ACY files in {workspace}")


def _read_table(path: Path):
    import pandas as pd
    text = path.read_text(errors="replace").splitlines()
    header_idx = None
    for i, line in enumerate(text):
        toks = line.split()
        if "YR" in toks or "YEAR" in toks:
            header_idx = i
            break
    if header_idx is None:
        return None
    rows = []
    headers = text[header_idx].split()
    for line in text[header_idx + 1:]:
        toks = line.split()
        if not toks:
            continue
        try:
            float(toks[0])
        except ValueError:
            continue
        if len(toks) >= len(headers):
            rows.append(toks[: len(headers)])
    if not rows:
        return None
    return pd.DataFrame(rows, columns=headers)


def parse_daily_water(workspace, *, out_csv: Optional[str] = None):
    """Parse the daily watershed file ``*.DWS`` into a daily DataFrame.

    The DWS print holds one row per simulated day with the watershed water
    balance. The column header line begins with ``Y  M  D`` and the first
    ``WYLD`` token is the daily water yield (surface runoff + lateral + return
    flow) in **mm** — the dag variable comparable to a gauged hydrograph. We
    also keep ``RFV`` (rainfall, mm), ``Q`` (outlet flow, mm) and ``PET`` (mm).

    Returns a DataFrame with columns: date, year, month, day, RFV, WYLD, Q, PET.
    Requires IPD set for daily output (the s5 default / example uses IPD=6).
    """
    import pandas as pd
    ws = Path(workspace).expanduser().resolve()
    dws = sorted(ws.glob("*.DWS"))
    if not dws:
        raise FileNotFoundError(
            f"No *.DWS daily watershed file in {ws}. Set a daily print code "
            f"(IPD) in APEXCONT.DAT via s5_update_control(ipd=6)."
        )
    text = dws[0].read_text(errors="replace").splitlines()
    hdr_idx = None
    for i, line in enumerate(text):
        toks = line.split()
        if len(toks) >= 5 and toks[:3] == ["Y", "M", "D"] and "WYLD" in toks:
            hdr_idx = i
            break
    if hdr_idx is None:
        raise RuntimeError(f"Could not locate 'Y M D ... WYLD' header in {dws[0].name}")
    headers = text[hdr_idx].split()
    iw = headers.index("WYLD")          # first WYLD = total water yield (mm)
    irfv = headers.index("RFV") if "RFV" in headers else 3
    iq = headers.index("Q") if "Q" in headers else None
    ipet = headers.index("PET") if "PET" in headers else None
    rows = []
    for line in text[hdr_idx + 1:]:
        toks = line.split()
        if len(toks) <= iw:
            continue
        if not (toks[0].isdigit() and len(toks[0]) == 4):
            continue
        try:
            yr, mo, da = int(toks[0]), int(toks[1]), int(toks[2])
            rec = {"year": yr, "month": mo, "day": da,
                   "RFV": float(toks[irfv]), "WYLD": float(toks[iw])}
            if iq is not None and len(toks) > iq:
                rec["Q"] = float(toks[iq])
            if ipet is not None and len(toks) > ipet:
                rec["PET"] = float(toks[ipet])
            rows.append(rec)
        except (ValueError, IndexError):
            continue
    if not rows:
        raise RuntimeError(f"No daily rows parsed from {dws[0].name}")
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df[["year", "month", "day"]])
    df = df.sort_values("date").reset_index(drop=True)
    if out_csv:
        out_path = Path(out_csv).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_path, index=False)
    return df


def parse(workspace, *, out_csv: Optional[str] = None):
    import pandas as pd
    ws = Path(workspace).expanduser().resolve()
    validate_inputs(ws)

    frames: list[pd.DataFrame] = []
    for ext in ("ACY", "OUT"):
        for path in sorted(ws.glob(f"*.{ext}")):
            df = _read_table(path)
            if df is None or df.empty:
                continue
            df["__source__"] = path.name
            frames.append(df)

    if not frames:
        raise RuntimeError(f"No parseable annual rows found in {ws}/*.OUT or *.ACY")

    result = pd.concat(frames, ignore_index=True, sort=False)

    for col in result.columns:
        if col == "__source__":
            continue
        try:
            result[col] = pd.to_numeric(result[col], errors="ignore")
        except Exception:
            pass

    if out_csv:
        out_path = Path(out_csv).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(out_path, index=False)

    validate_outputs(result)
    return result


def validate_outputs(df) -> None:
    if df is None or len(df) == 0:
        raise RuntimeError("parsed dataframe is empty")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--workspace", required=True)
    p.add_argument("--out", default=None)
    args = p.parse_args()
    df = parse(args.workspace, out_csv=args.out)
    print(f"[OK] parsed {len(df)} rows from {args.workspace}")
    if args.out:
        print(f"[OK] CSV written to {args.out}")
