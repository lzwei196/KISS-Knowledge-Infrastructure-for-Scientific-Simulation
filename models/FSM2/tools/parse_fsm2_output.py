#!/usr/bin/env python3
"""
Parse FSM2 ASCII output files into CSV with headers.

FSM2 produces three ASCII output files (when PROFNC=0):
  - {runid}flux.txt: year month day hour H LE LWout Melt Roff subl SWout
  - {runid}stat.txt: year month day hour snd snw svg Tsoil(1..Nsoil) Tsrf Tveg(1..Ncnpy)
  - {runid}subc.txt: year month day hour LWsub SWsub Tsub Usub

Format: 3(i4),f8.3,*(e14.6)

This tool parses all three files and merges them into a single CSV.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_input(flux_file: str, stat_file: str, subc_file: str) -> list[str]:
    """Check input files exist and are non-empty."""
    issues = []
    for fpath, name in [(flux_file, "flux"), (stat_file, "stat"), (subc_file, "subc")]:
        p = Path(fpath)
        if not p.is_file():
            issues.append(f"{name} file not found: {fpath}")
        elif p.stat().st_size == 0:
            issues.append(f"{name} file is empty: {fpath}")
    return issues


def validate_output(df: pd.DataFrame) -> list[str]:
    """Run physical-range checks on parsed output."""
    issues = []
    if "snd" in df.columns:
        if (df["snd"] < 0).any():
            issues.append(f"Negative snow depth detected: min={df['snd'].min():.3f}")
        if (df["snd"] > 20).any():
            issues.append(f"Snow depth > 20 m: max={df['snd'].max():.1f}")
    if "snw" in df.columns:
        if (df["snw"] < 0).any():
            issues.append(f"Negative SWE detected: min={df['snw'].min():.3f}")
    if "Tsrf" in df.columns:
        if (df["Tsrf"] < 180).any() or (df["Tsrf"] > 340).any():
            issues.append(f"Tsrf out of range: min={df['Tsrf'].min():.1f}, max={df['Tsrf'].max():.1f}")
    if "H" in df.columns:
        if (df["H"].abs() > 1000).any():
            issues.append(f"Sensible heat flux |H| > 1000 W/m²")
    return issues


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def parse_flux_file(filepath: str, npnts: int = 1) -> pd.DataFrame:
    """
    Parse {runid}flux.txt.

    Columns per point: H, LE, LWout, Melt, Roff, subl, SWout (7 vars)
    """
    data = pd.read_csv(filepath, sep=r"\s+", header=None)

    date_cols = ["year", "month", "day", "hour"]
    flux_vars = ["H", "LE", "LWout", "Melt", "Roff", "subl", "SWout"]

    if npnts == 1:
        cols = date_cols + flux_vars
    else:
        cols = date_cols.copy()
        for i in range(npnts):
            cols.extend([f"{v}_p{i+1}" for v in flux_vars])

    if len(data.columns) == len(cols):
        data.columns = cols
    else:
        # Assign what we can
        for i, c in enumerate(cols):
            if i < len(data.columns):
                data = data.rename(columns={data.columns[i]: c})

    return data


def parse_stat_file(filepath: str, npnts: int = 1, nsoil: int = 4, ncnpy: int = 1) -> pd.DataFrame:
    """
    Parse {runid}stat.txt.

    Columns per point: snd, snw, svg, Tsoil(1:Nsoil), Tsrf, Tveg(1:Ncnpy)
    """
    data = pd.read_csv(filepath, sep=r"\s+", header=None)

    date_cols = ["year", "month", "day", "hour"]
    stat_vars = ["snd", "snw", "svg"]
    stat_vars += [f"Tsoil{i+1}" for i in range(nsoil)]
    stat_vars += ["Tsrf"]
    stat_vars += [f"Tveg{i+1}" for i in range(ncnpy)]

    if npnts == 1:
        cols = date_cols + stat_vars
    else:
        cols = date_cols.copy()
        for i in range(npnts):
            cols.extend([f"{v}_p{i+1}" for v in stat_vars])

    if len(data.columns) == len(cols):
        data.columns = cols
    else:
        for i, c in enumerate(cols):
            if i < len(data.columns):
                data = data.rename(columns={data.columns[i]: c})

    return data


def parse_subc_file(filepath: str, npnts: int = 1) -> pd.DataFrame:
    """
    Parse {runid}subc.txt.

    Columns per point: LWsub, SWsub, Tsub, Usub
    """
    data = pd.read_csv(filepath, sep=r"\s+", header=None)

    date_cols = ["year", "month", "day", "hour"]
    subc_vars = ["LWsub", "SWsub", "Tsub", "Usub"]

    if npnts == 1:
        cols = date_cols + subc_vars
    else:
        cols = date_cols.copy()
        for i in range(npnts):
            cols.extend([f"{v}_p{i+1}" for v in subc_vars])

    if len(data.columns) == len(cols):
        data.columns = cols
    else:
        for i, c in enumerate(cols):
            if i < len(data.columns):
                data = data.rename(columns={data.columns[i]: c})

    return data


# ---------------------------------------------------------------------------
# Merge and export
# ---------------------------------------------------------------------------

def parse_fsm2_output(
    run_dir: str,
    runid: str = "",
    output_csv: str | None = None,
    npnts: int = 1,
    nsoil: int = 4,
    ncnpy: int = 1,
    point: int | None = None,
) -> pd.DataFrame:
    """
    Parse all FSM2 output files and merge into a single DataFrame.

    Parameters
    ----------
    run_dir : str
        Directory containing output files.
    runid : str
        Run ID prefix for file names.
    output_csv : str, optional
        Path to write merged CSV.
    npnts : int
        Number of simulation points.
    nsoil : int
        Number of soil layers.
    ncnpy : int
        Number of canopy layers.
    point : int, optional
        If multi-point, extract only this point (1-based).

    Returns
    -------
    pd.DataFrame : merged output
    """
    rd = Path(run_dir)
    flux_file = str(rd / f"{runid}flux.txt")
    stat_file = str(rd / f"{runid}stat.txt")
    subc_file = str(rd / f"{runid}subc.txt")

    # Validate input
    issues = validate_input(flux_file, stat_file, subc_file)
    if issues:
        print("Input validation issues:")
        for iss in issues:
            print(f"  - {iss}")

    # Parse each file
    dfs = {}
    if Path(flux_file).is_file() and Path(flux_file).stat().st_size > 0:
        dfs["flux"] = parse_flux_file(flux_file, npnts)
        print(f"Parsed flux: {len(dfs['flux'])} rows, {len(dfs['flux'].columns)} cols")

    if Path(stat_file).is_file() and Path(stat_file).stat().st_size > 0:
        dfs["stat"] = parse_stat_file(stat_file, npnts, nsoil, ncnpy)
        print(f"Parsed stat: {len(dfs['stat'])} rows, {len(dfs['stat'].columns)} cols")

    if Path(subc_file).is_file() and Path(subc_file).stat().st_size > 0:
        dfs["subc"] = parse_subc_file(subc_file, npnts)
        print(f"Parsed subc: {len(dfs['subc'])} rows, {len(dfs['subc'].columns)} cols")

    if not dfs:
        raise RuntimeError("No output files could be parsed")

    # Merge on date columns
    date_cols = ["year", "month", "day", "hour"]
    merged = None
    for name, df in dfs.items():
        if merged is None:
            merged = df
        else:
            # Drop duplicate date columns before merge
            non_date = [c for c in df.columns if c not in date_cols]
            merged = pd.concat([merged, df[non_date]], axis=1)

    # Add datetime column
    merged["datetime"] = pd.to_datetime(
        merged[["year", "month", "day"]].astype(int).assign(
            hour=merged["hour"].astype(int)
        )
    )

    # Extract single point if requested
    if point is not None and npnts > 1:
        suffix = f"_p{point}"
        point_cols = ["datetime"] + [c for c in merged.columns if c.endswith(suffix)]
        merged = merged[point_cols]
        merged.columns = [c.replace(suffix, "") for c in merged.columns]

    # Validate output
    out_issues = validate_output(merged)
    if out_issues:
        print("Output validation issues:")
        for iss in out_issues:
            print(f"  - {iss}")

    # Summary statistics
    print(f"\nOutput summary ({len(merged)} timesteps):")
    for var in ["snd", "snw", "Tsrf", "H", "LE", "Melt", "Roff"]:
        if var in merged.columns:
            print(f"  {var:8s}: min={merged[var].min():10.3f}  max={merged[var].max():10.3f}  mean={merged[var].mean():10.3f}")

    # Write CSV
    if output_csv:
        merged.to_csv(output_csv, index=False)
        print(f"\nWrote {len(merged)} rows to {output_csv}")

    return merged


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Parse FSM2 ASCII output to CSV")
    parser.add_argument("run_dir", help="Directory containing FSM2 output files")
    parser.add_argument("-o", "--output", help="Output CSV file")
    parser.add_argument("--runid", default="", help="Run ID prefix")
    parser.add_argument("--npnts", type=int, default=1, help="Number of points")
    parser.add_argument("--nsoil", type=int, default=4, help="Number of soil layers")
    parser.add_argument("--ncnpy", type=int, default=1, help="Number of canopy layers")
    parser.add_argument("--point", type=int, help="Extract single point (1-based)")
    args = parser.parse_args()

    parse_fsm2_output(
        args.run_dir, args.runid, args.output,
        args.npnts, args.nsoil, args.ncnpy, args.point,
    )


if __name__ == "__main__":
    main()
