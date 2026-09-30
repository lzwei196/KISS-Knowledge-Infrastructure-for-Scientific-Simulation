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
import re
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


def _columns(df: pd.DataFrame, name: str) -> list[str]:
    """``name`` for a single point, ``name_p1``, ``name_p2``, ... for several."""
    return [c for c in df.columns if c == name or re.fullmatch(rf"{name}_p\d+", str(c))]


def validate_output(df: pd.DataFrame) -> list[str]:
    """Run physical-range checks on parsed output (every point of a multi-point run)."""
    issues = []
    for c in _columns(df, "snd"):
        if (df[c] < 0).any():
            issues.append(f"Negative snow depth detected in {c}: min={df[c].min():.3f}")
        if (df[c] > 20).any():
            issues.append(f"Snow depth > 20 m in {c}: max={df[c].max():.1f}")
    for c in _columns(df, "snw"):
        if (df[c] < 0).any():
            issues.append(f"Negative SWE detected in {c}: min={df[c].min():.3f}")
    for c in _columns(df, "Tsrf"):
        if (df[c] < 180).any() or (df[c] > 340).any():
            issues.append(f"Tsrf out of range in {c}: min={df[c].min():.1f}, max={df[c].max():.1f}")
    for c in _columns(df, "H"):
        if (df[c].abs() > 1000).any():
            issues.append(f"Sensible heat flux |{c}| > 1000 W/m²")
    return issues


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _output_columns(variables: list[tuple[str, int, bool]], npnts: int) -> list[str]:
    """Column names in the order FSM2_OUTPUT.F90 writes them.

    Each ``write`` lists whole Fortran arrays: every variable for all points
    before the next variable (variable-major), and a layered array such as
    Tsoil(Nsoil, Npnts) in column-major order, i.e. all layers of point 1,
    then all layers of point 2.  Layered variables are always numbered
    (Tsoil1.., Tveg1..) and single-point names keep their old form.
    """
    cols = ["year", "month", "day", "hour"]
    for name, layers, numbered in variables:
        for p in range(1, npnts + 1):
            for layer in range(1, layers + 1):
                base = f"{name}{layer}" if numbered else name
                cols.append(base if npnts == 1 else f"{base}_p{p}")
    return cols


def _read_output(filepath: str, cols: list[str]) -> pd.DataFrame:
    data = pd.read_csv(filepath, sep=r"\s+", header=None)
    if len(data.columns) != len(cols):
        # A count mismatch means Npnts/Nsoil/Ncnpy do not match the run;
        # guessing would silently put one variable's values under another's name.
        raise ValueError(
            f"{Path(filepath).name} has {len(data.columns)} columns but the requested "
            f"layout expects {len(cols)}; check --npnts, --nsoil and --ncnpy against the namelist")
    data.columns = cols
    return data


def parse_flux_file(filepath: str, npnts: int = 1) -> pd.DataFrame:
    """
    Parse {runid}flux.txt.

    Variables: H, LE, LWout, Melt, Roff, subl, SWout, each written for all points.
    """
    flux_vars = ["H", "LE", "LWout", "Melt", "Roff", "subl", "SWout"]
    return _read_output(filepath, _output_columns([(v, 1, False) for v in flux_vars], npnts))


def parse_stat_file(filepath: str, npnts: int = 1, nsoil: int = 4, ncnpy: int = 1) -> pd.DataFrame:
    """
    Parse {runid}stat.txt.

    Variables: snd, snw, svg, Tsoil(1:Nsoil), Tsrf, Tveg(1:Ncnpy), each for all points.
    """
    stat_vars = [("snd", 1, False), ("snw", 1, False), ("svg", 1, False),
                 ("Tsoil", nsoil, True), ("Tsrf", 1, False), ("Tveg", ncnpy, True)]
    return _read_output(filepath, _output_columns(stat_vars, npnts))


def parse_subc_file(filepath: str, npnts: int = 1) -> pd.DataFrame:
    """
    Parse {runid}subc.txt.

    Variables: LWsub, SWsub, Tsub, Usub, each written for all points.
    """
    subc_vars = ["LWsub", "SWsub", "Tsub", "Usub"]
    return _read_output(filepath, _output_columns([(v, 1, False) for v in subc_vars], npnts))


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
# Snow metrics and plot
# ---------------------------------------------------------------------------

def snow_metrics(merged: pd.DataFrame) -> pd.DataFrame:
    """Peak SWE, peak depth and melt-out for every point of a parsed run.

    Melt-out is the first timestep after the SWE peak with snow depth exactly
    0 (FSM2 writes 0 once the pack is gone).  If the pack is still there at the
    last record, the status says so and no date is invented: the record end
    and the remaining depth/SWE are reported instead.
    """
    rows = []
    for snw_col in _columns(merged, "snw"):
        suffix = snw_col[len("snw"):]
        snd_col = "snd" + suffix
        if snd_col not in merged.columns:
            continue
        snw, snd, when = merged[snw_col], merged[snd_col], merged["datetime"]
        peak = int(snw.idxmax())
        after = merged.index[(merged.index > peak) & (snd == 0)]
        melted = len(after) > 0 and float(snw.max()) > 0
        last = merged.index[-1]
        rows.append({
            "point": suffix.lstrip("_") or "p1",
            "peak_swe_kg_m2": round(float(snw.max()), 3),
            "peak_swe_time": when[peak].isoformat(),
            "peak_depth_m": round(float(snd.max()), 4),
            "peak_depth_time": when[int(snd.idxmax())].isoformat(),
            "melt_out_time": when[after[0]].isoformat() if melted else "",
            "melt_out_status": ("melted out (first snow depth == 0 after the SWE peak)" if melted
                                else "snow remains at record end: melt-out not reached within the record"),
            "record_end": when[last].isoformat(),
            "swe_at_record_end_kg_m2": round(float(snw[last]), 3),
            "depth_at_record_end_m": round(float(snd[last]), 4),
        })
    if not rows:
        raise ValueError("no snd/snw columns to compute snow metrics from")
    return pd.DataFrame(rows)


def plot_snow(merged: pd.DataFrame, path: str, labels: list[str] | None = None) -> None:
    """Snow depth and SWE of every point; the format follows the file suffix (.svg, .png)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    snw_cols = _columns(merged, "snw")
    fig, (ax_d, ax_w) = plt.subplots(2, 1, figsize=(10, 6.5), sharex=True)
    for i, snw_col in enumerate(snw_cols):
        suffix = snw_col[len("snw"):]
        name = labels[i] if labels and i < len(labels) else (suffix.lstrip("_") or "point")
        ax_d.plot(merged["datetime"], merged["snd" + suffix], label=name, linewidth=1)
        ax_w.plot(merged["datetime"], merged[snw_col], label=name, linewidth=1)
    ax_d.set_ylabel("Snow depth (m)")
    ax_w.set_ylabel("SWE (kg m$^{-2}$)")
    ax_w.set_xlabel("Date")
    ax_d.legend(loc="upper right")
    ax_d.set_title("FSM2 snow depth and snow water equivalent")
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    print(f"Wrote plot to {path}")


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
    parser.add_argument("--metrics", help="Write per-point peak SWE, peak depth and melt-out "
                        "(first depth == 0 after the SWE peak, else 'snow remains at record end') to this CSV")
    parser.add_argument("--plot", help="Write a snow depth / SWE figure to this file (.svg or .png)")
    parser.add_argument("--labels", help="Comma-separated point names for the figure, e.g. open,forest")
    args = parser.parse_args()

    merged = parse_fsm2_output(
        args.run_dir, args.runid, args.output,
        args.npnts, args.nsoil, args.ncnpy, args.point,
    )
    if args.metrics:
        metrics = snow_metrics(merged)
        metrics.to_csv(args.metrics, index=False)
        print(f"\nSnow metrics ({args.metrics}):")
        print(metrics.to_string(index=False))
    if args.plot:
        plot_snow(merged, args.plot, args.labels.split(",") if args.labels else None)


if __name__ == "__main__":
    main()
