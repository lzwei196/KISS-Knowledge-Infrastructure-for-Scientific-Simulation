#!/usr/bin/env python3
"""
Parse EPIC0810 output files into pandas DataFrames.

EPIC outputs share a 10-line header (EPIC0810 timestamp, run name, weather files,
soil/op files, then a single column-name line at row 11). After the header, rows
are whitespace-delimited.
"""

import os
import re
import pandas as pd

HEADER_LINES = 10  # rows 1-10 are metadata, row 11 is column names


def _read_skip_header(path: str) -> pd.DataFrame:
    """
    Read a fixed-header EPIC output file. Returns an empty DataFrame
    (with column names) if the file has only the header.
    """
    with open(path, "r") as f:
        lines = f.readlines()
    if len(lines) <= HEADER_LINES:
        return pd.DataFrame()
    header = lines[HEADER_LINES].split()
    rows = []
    for line in lines[HEADER_LINES + 1:]:
        toks = line.split()
        if not toks:
            continue
        rows.append(toks)
    if not rows:
        return pd.DataFrame(columns=header)
    # Pad short rows so DataFrame can build cleanly
    width = len(header)
    padded = [r + [None] * (width - len(r)) if len(r) < width else r[:width] for r in rows]
    df = pd.DataFrame(padded, columns=header)
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="ignore")
    return df


def parse_acy(path: str) -> pd.DataFrame:
    """Annual crop yield: YR RT# CPNM YLDG YLDF BIOM RW HI WUEF WS NS PS ..."""
    return _read_skip_header(path)


def parse_dgn(path: str) -> pd.DataFrame:
    """Daily general: Y M D PDSW TMX TMN RAD PRCP PET ET LAI BIOM ..."""
    df = _read_skip_header(path)
    if not df.empty and {"Y", "M", "D"}.issubset(df.columns):
        df["date"] = pd.to_datetime(
            df[["Y", "M", "D"]].rename(columns={"Y": "year", "M": "month", "D": "day"}),
            errors="coerce",
        )
    return df


def parse_ann(path: str) -> pd.DataFrame:
    """Annual summary: RUN YR PRCP IRGA PET ET Q DN LIME DN2O FULU ..."""
    return _read_skip_header(path)


def parse_acn(path: str) -> pd.DataFrame:
    """Annual carbon/nitrogen mass."""
    return _read_skip_header(path)


def parse_dwt(path: str) -> pd.DataFrame:
    """Daily water table / drainage."""
    return _read_skip_header(path)


def parse_out_annual_table(path: str) -> dict:
    """
    Scrape the annual-summary block from the .OUT file. EPIC writes a
    table with row labels like 'PRCP(mm)', 'ET(mm)', 'Q(mm)', 'WBMC(kg/ha)'
    where each column is one annual cycle (or rotation).

    Returns dict {label: list_of_values}.
    """
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        text = f.read()
    out = {}
    pattern = re.compile(r"^\s*([A-Z][A-Z0-9_]+\(.+?\))((?:\s+-?\d+(?:\.\d+)?)+)\s*$",
                         re.MULTILINE)
    for m in pattern.finditer(text):
        label = m.group(1).strip()
        values = [float(x) for x in m.group(2).split()]
        out[label] = values
    return out


def water_balance_summary(workspace_dir: str, site_id: str = "umstead_0") -> dict:
    """
    Build a quick water-balance summary by scraping the OUT annual table.
    Expected keys: PRCP, ET, Q, PET (mm/yr).
    """
    out_path = os.path.join(workspace_dir, f"{site_id}.OUT")
    table = parse_out_annual_table(out_path)
    summary = {}
    for k in list(table):
        for needle in ("PRCP", "PET", "ET", "Q(mm)"):
            if k.startswith(needle):
                summary[k] = table[k]
    return summary


def main():
    import argparse, json
    p = argparse.ArgumentParser()
    p.add_argument("--workspace", required=True)
    p.add_argument("--site-id", default="umstead_0")
    args = p.parse_args()

    ws = args.workspace
    sid = args.site_id
    summary = {
        "ACY_rows": len(parse_acy(os.path.join(ws, f"{sid}.ACY"))),
        "DGN_rows": len(parse_dgn(os.path.join(ws, f"{sid}.DGN"))),
        "ANN_rows": len(parse_ann(os.path.join(ws, f"{sid}.ANN"))),
        "OUT_water_balance": water_balance_summary(ws, sid),
    }
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
