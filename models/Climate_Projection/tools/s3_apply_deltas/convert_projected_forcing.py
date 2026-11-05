#!/usr/bin/env python3
"""
S3b: Convert projected forcing NetCDF -> VIC ASCII format.

After apply_deltas_forcing.py produces projected NC files (monthly, 3-hourly),
this tool converts them to per-grid-cell ASCII files that VIC can read directly.

Usage:
    python convert_projected_forcing.py \
        <input_dir> <output_dir> <soil_file> <forcing_prefix> <basin_tag> \
        <start_year> <end_year>

Example:
    python convert_projected_forcing.py \
        outputs/nuxia/climate_projection/forcing_ACCESS-CM2_126 \
        outputs/nuxia/climate_projection/forcing_final_ACCESS-CM2_126 \
        outputs/nuxia/vic_temp/soil/SOIL_PARAM_COMPLETE.txt \
        "nuxia_01dy_025deg_" "nuxia" 2041 2070

Input NetCDF units (forcing_1d / CMFD convention, checked on a real CMFD file):
    temp K, prec kg m-2 s-1, pres Pa, srad W m-2, lrad W m-2, shum kg kg-1, wind m s-1
Output VIC ASCII columns (no header):
    air_temp degC, prec mm per time step, pressure kPa, swdown W/m2, lwdown W/m2,
    vp kPa (from shum and pres), wind m/s

All 7 variables are REQUIRED. Missing variables, unknown units, missing/irregular time
steps and NaN values stop the tool with an error; nothing is filled with defaults
(owner rule: no fabricated data).

Exit codes: 0 = all cells converted, 1 = input error, 2 = conversion error / some cells failed.
"""

import sys
import glob
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

warnings.filterwarnings("ignore")

VAR_NAMES = ["prec", "temp", "pres", "srad", "lrad", "shum", "wind"]

# Accepted spellings of the NetCDF input unit attribute, per variable.
EXPECTED_UNITS = {
    "temp": {"K", "kelvin", "Kelvin"},
    "prec": {"kg m-2 s-1", "kg/m2/s", "kg m**-2 s**-1", "kg/(m2 s)", "mm s-1", "mm/s"},
    "pres": {"Pa", "pa"},
    "srad": {"W m-2", "W/m2", "W m**-2"},
    "lrad": {"W m-2", "W/m2", "W m**-2"},
    "shum": {"kg kg-1", "kg/kg", "1", "kg kg**-1"},
    "wind": {"m s-1", "m/s", "m s**-1"},
}

OUT_COLS = ["air_temp", "prec", "pressure", "swdown", "lwdown", "vp", "wind"]

# The projected forcing and the VIC global file (8 records/day) use a 3-hour step. The step is
# NOT inferred from the data: a series with every other record lost would otherwise look like a
# valid 6-hour series and precipitation would be integrated over the wrong interval.
STEP_SECONDS = 10800


class ConvertError(RuntimeError):
    """Clear, user-facing failure (exit code carried in .code)."""

    def __init__(self, msg, code=2):
        super().__init__(msg)
        self.code = code


def parse_args(argv):
    if len(argv) != 8:
        raise ConvertError(
            "usage: convert_projected_forcing.py <input_dir> <output_dir> <soil_file> "
            "<forcing_prefix> <basin_tag> <start_year> <end_year>", code=1)
    try:
        start, end = int(argv[6]), int(argv[7])
    except ValueError:
        raise ConvertError(f"start_year/end_year must be integers, got {argv[6]!r} {argv[7]!r}", code=1)
    if end < start:
        raise ConvertError(f"end_year {end} is before start_year {start}", code=1)
    return dict(input_dir=Path(argv[1]), output_dir=Path(argv[2]), soil_file=Path(argv[3]),
                prefix=argv[4], basin_tag=argv[5], start=start, end=end)


def check_units(var, da):
    units = da.attrs.get("units")
    if units is None:
        raise ConvertError(
            f"variable '{var}' has no 'units' attribute; expected one of "
            f"{sorted(EXPECTED_UNITS[var])}. Refusing to guess the unit.", code=1)
    if str(units).strip() not in EXPECTED_UNITS[var]:
        raise ConvertError(
            f"variable '{var}' has units {units!r}; this tool expects {sorted(EXPECTED_UNITS[var])} "
            f"(forcing_1d NetCDF units). Convert the input first.", code=1)


def load_variables(input_dir, basin_tag):
    """Load all 7 variables; stop if any is missing (no defaults)."""
    files = {v: sorted(glob.glob(str(input_dir / f"{v}_*_{basin_tag}*.nc"))) for v in VAR_NAMES}
    missing = [v for v, f in files.items() if not f]
    if missing:
        raise ConvertError(
            f"no NetCDF files for variable(s) {missing} in {input_dir} (pattern '<var>_*_{basin_tag}*.nc'). "
            f"All 7 VIC variables {VAR_NAMES} are required; nothing is filled with defaults. "
            f"Check that apply_deltas_forcing.py found every baseline variable.", code=1)
    all_ds = []
    for var in VAR_NAMES:
        print(f"  Loading {var}: {len(files[var])} files")
        ds_list = []
        for f in files[var]:
            ds = xr.open_dataset(f, engine="netcdf4")
            for drop_var in ["spatial_ref"]:
                if drop_var in ds.coords or drop_var in ds.data_vars:
                    ds = ds.drop_vars(drop_var)
            if var not in ds.data_vars:
                raise ConvertError(f"{f}: expected data variable '{var}', found {list(ds.data_vars)}", code=1)
            check_units(var, ds[var])
            ds_list.append(ds[[var]])
        all_ds.append(xr.concat(ds_list, dim="time"))
    return all_ds


def check_time_axis(times, start, end):
    """Time steps must be unique, regular and cover start..end. Returns step in seconds."""
    t = pd.DatetimeIndex(times)
    if len(t) < 2:
        raise ConvertError(f"only {len(t)} time step(s) in {start}-{end}; cannot convert", code=2)
    if t.has_duplicates:
        dup = t[t.duplicated()][:3]
        raise ConvertError(f"duplicate time stamps in projected forcing, e.g. {list(dup)}", code=2)
    steps = np.diff(t.values).astype("timedelta64[s]").astype(np.int64)
    dt = STEP_SECONDS
    if not np.all(steps == dt):
        bad = np.where(steps != dt)[0][:3]
        raise ConvertError(
            f"time steps are not all {dt} s (3-hourly): gap, overlap or other cadence near "
            f"{[str(t[i]) for i in bad]}; VIC needs 8 records per day", code=2)
    first_needed = pd.Timestamp(f"{start}-01-01 00:00")
    last_needed = pd.Timestamp(f"{end}-12-31 00:00") + pd.Timedelta(days=1) - pd.Timedelta(seconds=dt)
    if t[0] > first_needed or t[-1] < last_needed:
        raise ConvertError(
            f"projected forcing covers {t[0]} .. {t[-1]} but {first_needed} .. {last_needed} is needed", code=2)
    return dt


def check_values(cell_df):
    """Per active cell: catch unit mix-ups the label did not reveal (e.g. degC data labelled K).
    Run on active cells only, so inactive cells (ignored by VIC) cannot fail the run."""
    tmin, tmax = float(cell_df["temp"].min()), float(cell_df["temp"].max())
    if not (150.0 <= tmin and tmax <= 350.0):
        raise ValueError(f"temp range {tmin:.2f}..{tmax:.2f} is not plausible for Kelvin "
                         f"(expected within 150..350 K); check the input unit")
    pmin = float(cell_df["prec"].min())
    if pmin < 0:
        raise ValueError(f"negative precipitation ({pmin})")
    smax = float(cell_df["shum"].max())
    if smax > 0.1:
        raise ValueError(f"shum max {smax} > 0.1 kg/kg; not specific humidity (check unit)")


def convert_cell(cell_df, dt_seconds):
    """Unit conversion for one cell. No defaults; NaN -> error."""
    bad_cols = [c for c in VAR_NAMES if not np.isfinite(cell_df[c].to_numpy(dtype=float)).all()]
    if bad_cols:
        n = int((~np.isfinite(cell_df[bad_cols].to_numpy(dtype=float))).any(axis=1).sum())
        raise ValueError(f"NaN or inf in {bad_cols} ({n} time steps)")
    check_values(cell_df)
    q, P = cell_df["shum"], cell_df["pres"]
    out = pd.DataFrame(index=cell_df.index)
    out["air_temp"] = cell_df["temp"] - 273.15                  # K -> degC
    out["prec"] = cell_df["prec"] * dt_seconds                  # kg m-2 s-1 -> mm per step
    out["pressure"] = P / 1000.0                                # Pa -> kPa
    out["swdown"] = cell_df["srad"]                             # W m-2
    out["lwdown"] = cell_df["lrad"]                             # W m-2
    out["vp"] = (q * P / (0.622 + 0.378 * q)) / 1000.0          # specific humidity -> kPa
    out["wind"] = cell_df["wind"]                               # m s-1
    out = out[OUT_COLS]
    if not np.isfinite(out.to_numpy(dtype=float)).all():
        raise ValueError("non-finite value after unit conversion")
    return out


def main(argv):
    a = parse_args(argv)
    if not a["input_dir"].is_dir():
        raise ConvertError(f"Input directory not found: {a['input_dir']}", code=1)
    if not a["soil_file"].is_file():
        raise ConvertError(f"Soil file not found: {a['soil_file']}", code=1)

    df_soil = pd.read_csv(a["soil_file"], sep=r"\s+", header=None, usecols=[0, 1, 2, 3],
                          names=["run_cell", "grid_id", "lat", "lon"])
    # VIC skips soil rows whose run_cell flag is 0, so only active cells need forcing.
    n_all = len(df_soil)
    df_soil = df_soil[df_soil["run_cell"] != 0]
    n_cells = len(df_soil)
    if n_cells == 0:
        raise ConvertError(f"no active grid cells (run_cell != 0) in soil file {a['soil_file']}", code=1)
    print(f"Grid cells: {n_cells} active of {n_all}")
    print(f"Period: {a['start']}-{a['end']}")

    all_ds = load_variables(a["input_dir"], a["basin_tag"])
    ds_m = xr.merge(all_ds).sortby("time").sel(
        time=slice(f"{a['start']}-01-01", f"{a['end']}-12-31T23:59:59"))
    dt_seconds = check_time_axis(ds_m.time.values, a["start"], a["end"])

    lat_dim = "y" if "y" in ds_m.coords else "lat"
    lon_dim = "x" if "x" in ds_m.coords else "lon"
    print(f"  Time steps: {len(ds_m.time)} (step {dt_seconds} s)")
    print("  Converting to VIC ASCII...")

    a["output_dir"].mkdir(parents=True, exist_ok=True)
    success, failures = 0, []
    for _, row in df_soil.iterrows():
        lat, lon = row["lat"], row["lon"]
        try:
            cell = ds_m.sel({lat_dim: lat, lon_dim: lon}, method="nearest", tolerance=0.13).compute()
            vic_df = convert_cell(cell.to_dataframe(), dt_seconds)
            out_path = a["output_dir"] / f"{a['prefix']}{lat:.4f}_{lon:.4f}"
            vic_df.to_csv(out_path, sep="\t", header=False, index=False, float_format="%.4f")
            success += 1
        except Exception as e:  # recorded and reported, never silently passed
            failures.append((lat, lon, f"{type(e).__name__}: {e}"))

    print(f"Converted: {success}/{n_cells} cells")
    if failures:
        for lat, lon, msg in failures[:10]:
            print(f"  FAILED cell {lat:.4f},{lon:.4f}: {msg}")
        if len(failures) > 10:
            print(f"  ... and {len(failures) - 10} more")
        raise ConvertError(f"{len(failures)} of {n_cells} cells were NOT converted (see above); "
                           f"the VIC ASCII set is incomplete", code=2)


if __name__ == "__main__":
    try:
        main(sys.argv)
    except ConvertError as e:
        print(f"ERROR: {e}")
        sys.exit(e.code)
