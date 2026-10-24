#!/usr/bin/env python3
"""
preflight_forcing.py -- Universal forcing data preflight validator.
===================================================================
Run BEFORE any model simulation to catch unit errors in forcing data.

Detects the data source (CMFD, MSWX, ERA5, FLUXNET), reads one sample
file, checks ALL variables against physical plausibility ranges, and
produces PASS/WARN/FAIL per variable with specific unit-trap hints.

Usage (CLI):
    python preflight_forcing.py /path/to/forcing/
    python preflight_forcing.py /path/to/forcing/ --source cmfd --year 1980
    python preflight_forcing.py /path/to/forcing/ --source auto --shapefile bengbu.shp

Usage (library):
    from validators.preflight_forcing import quick_check_forcing
    result = quick_check_forcing('/path/to/forcing/', source='cmfd')
    if not result['all_pass']:
        print("WARNING:", result['warnings'])

Background:
    Unit mismatches can produce plausible-looking but scientifically invalid
    output. All supported physical ranges and conversion hints are encoded in
    RANGE_TABLE below so this module remains self-contained.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------
PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"


# ---------------------------------------------------------------------------
# Physical plausibility ranges
# ---------------------------------------------------------------------------

@dataclass
class RangeSpec:
    """A physical plausibility range for one variable."""
    var_canonical: str          # canonical name (e.g. "temperature")
    unit_label: str             # expected unit label (e.g. "K")
    lo: float                   # lower bound (inclusive)
    hi: float                   # upper bound (inclusive)
    below_hint: str = ""        # diagnosis if values fall below lo
    above_hint: str = ""        # diagnosis if values exceed hi
    # secondary range (alternate unit system) -- optional
    alt_unit_label: str = ""
    alt_lo: float = 0.0
    alt_hi: float = 0.0
    alt_below_hint: str = ""
    alt_above_hint: str = ""


# The master table of checks.  Order matters for reporting.
RANGE_TABLE: List[RangeSpec] = [
    # -- Temperature --
    RangeSpec(
        var_canonical="temperature",
        unit_label="K",
        lo=200.0, hi=330.0,
        below_hint="Values look like Celsius (add 273.15 to convert to K)",
        above_hint="Values implausibly high -- possible double-conversion (K+273.15 twice?)",
        alt_unit_label="degC",
        alt_lo=-80.0, alt_hi=60.0,
        alt_below_hint="Already in Kelvin? (subtract 273.15)",
        alt_above_hint="",
    ),
    # -- Precipitation (daily accumulation) --
    RangeSpec(
        var_canonical="precipitation_daily",
        unit_label="mm/day",
        lo=0.0, hi=300.0,
        below_hint="May be in kg/m2/s (multiply by 86400) or m/day (multiply by 1000)",
        above_hint="May be in mm/s (divide by 86400) or mm/3hr not aggregated",
    ),
    # -- Precipitation (rate) --
    RangeSpec(
        var_canonical="precipitation_rate",
        unit_label="kg/m2/s",
        lo=0.0, hi=0.01,
        below_hint="Already in mm/day? (divide by 86400 to get kg/m2/s)",
        above_hint="May be in mm/day (divide by 86400) or mm/hr (divide by 3600)",
    ),
    # -- Shortwave radiation --
    RangeSpec(
        var_canonical="shortwave_radiation",
        unit_label="W/m2",
        lo=0.0, hi=1400.0,
        below_hint="",
        above_hint="May be in J/m2 (divide by timestep_seconds) or MJ/m2/day (multiply by 11.574)",
    ),
    # -- Longwave radiation --
    RangeSpec(
        var_canonical="longwave_radiation",
        unit_label="W/m2",
        lo=50.0, hi=600.0,
        below_hint="Net LW may have been used instead of downward LW",
        above_hint="",
    ),
    # -- Pressure (Pa) --
    RangeSpec(
        var_canonical="pressure",
        unit_label="Pa",
        lo=30000.0, hi=110000.0,
        below_hint="May be in hPa (multiply by 100)",
        above_hint="",
        alt_unit_label="hPa",
        alt_lo=300.0, alt_hi=1100.0,
        alt_below_hint="Already in Pa? (divide by 100 to get hPa)",
        alt_above_hint="",
    ),
    # -- Specific humidity --
    RangeSpec(
        var_canonical="specific_humidity",
        unit_label="kg/kg",
        lo=0.0, hi=0.05,
        below_hint="",
        above_hint="May be in g/kg (divide by 1000), or relative humidity % used as q",
    ),
    # -- Wind speed --
    RangeSpec(
        var_canonical="wind_speed",
        unit_label="m/s",
        lo=0.0, hi=50.0,
        below_hint="",
        above_hint="May be in km/h (divide by 3.6)",
    ),
]


# ---------------------------------------------------------------------------
# Source-specific variable-name mappings
# ---------------------------------------------------------------------------
# Each source maps its own variable names to canonical names used above.
# The dict value is a tuple (canonical_name, primary_unit_expected).

_CMFD_VARS = {
    "temp":  ("temperature", "K"),
    "prec":  ("precipitation_rate", "kg/m2/s"),
    "srad":  ("shortwave_radiation", "W/m2"),
    "lrad":  ("longwave_radiation", "W/m2"),
    "pres":  ("pressure", "Pa"),
    "shum":  ("specific_humidity", "kg/kg"),
    "wind":  ("wind_speed", "m/s"),
    # alternate spellings seen in some CMFD files
    "tmp":   ("temperature", "K"),
    "pre":   ("precipitation_rate", "kg/m2/s"),
}

_MSWX_VARS = {
    "Tair":      ("temperature", "K"),
    "P":         ("precipitation_daily", "mm/day"),  # mm/3hr accumulated
    "SWd":       ("shortwave_radiation", "W/m2"),
    "LWd":       ("longwave_radiation", "W/m2"),
    "Wind":      ("wind_speed", "m/s"),
    "Pres":      ("pressure", "Pa"),
    "SpecHum":   ("specific_humidity", "kg/kg"),
    # lower-case variants
    "tair":      ("temperature", "K"),
    "p":         ("precipitation_daily", "mm/day"),
    "swd":       ("shortwave_radiation", "W/m2"),
    "lwd":       ("longwave_radiation", "W/m2"),
    "wind":      ("wind_speed", "m/s"),
    "pres":      ("pressure", "Pa"),
    "spechum":   ("specific_humidity", "kg/kg"),
}

_ERA5_VARS = {
    "t2m":   ("temperature", "K"),
    "tp":    ("precipitation_daily", "mm/day"),  # ERA5 hourly is m, daily is m
    "ssrd":  ("shortwave_radiation", "W/m2"),    # J/m2 in raw ERA5 -- must convert
    "strd":  ("longwave_radiation", "W/m2"),
    "sp":    ("pressure", "Pa"),
    "q":     ("specific_humidity", "kg/kg"),
    "u10":   ("wind_speed", "m/s"),
    "v10":   ("wind_speed", "m/s"),
    "d2m":   ("temperature", "K"),  # dewpoint -- same K check
    # single-level pressure-level
    "msl":   ("pressure", "Pa"),
}

_FLUXNET_VARS = {
    "TA_F":       ("temperature", "degC"),
    "TA_F_MDS":   ("temperature", "degC"),
    "P_F":        ("precipitation_daily", "mm/day"),
    "SW_IN_F":    ("shortwave_radiation", "W/m2"),
    "SW_IN_F_MDS":("shortwave_radiation", "W/m2"),
    "LW_IN_F":    ("longwave_radiation", "W/m2"),
    "LW_IN_F_MDS":("longwave_radiation", "W/m2"),
    "PA_F":       ("pressure", "hPa"),  # FLUXNET uses hPa / kPa
    "WS_F":       ("wind_speed", "m/s"),
    # humidity comes as VPD in FLUXNET, but some sites have specific humidity
    "VPD_F":      ("specific_humidity", "kg/kg"),  # will likely FAIL range -- that is intentional
}

SOURCE_VAR_MAPS = {
    "cmfd":    _CMFD_VARS,
    "mswx":    _MSWX_VARS,
    "era5":    _ERA5_VARS,
    "fluxnet": _FLUXNET_VARS,
}


# ---------------------------------------------------------------------------
# Source auto-detection
# ---------------------------------------------------------------------------

def detect_source(forcing_dir: str) -> str:
    """Detect the forcing data source from directory structure / filenames.

    Returns one of: 'cmfd', 'mswx', 'era5', 'fluxnet', 'unknown'.
    """
    p = Path(forcing_dir)
    dir_lower = str(p).lower()

    # Quick path-based heuristics
    if "cmfd" in dir_lower or "data_forcing_01dy" in dir_lower:
        return "cmfd"
    if "mswx" in dir_lower or "msxw" in dir_lower:
        return "mswx"
    if "era5" in dir_lower or "era-5" in dir_lower:
        return "era5"
    if "fluxnet" in dir_lower:
        return "fluxnet"

    # Scan filenames for patterns
    nc_files = _find_nc_files(p, limit=50)
    names_lower = " ".join(f.name.lower() for f in nc_files)

    if "cmfd" in names_lower:
        return "cmfd"
    if "mswx" in names_lower:
        return "mswx"
    if "era5" in names_lower:
        return "era5"
    if "flx" in names_lower or "fluxnet" in names_lower:
        return "fluxnet"

    # Check for FLUXNET CSV (site-level data)
    csv_files = list(p.glob("*.csv")) + list(p.glob("**/*.csv"))
    for cf in csv_files[:10]:
        if "FULLSET" in cf.name or "SUBSET" in cf.name or "FLX" in cf.name:
            return "fluxnet"

    return "unknown"


def _find_nc_files(dirpath: Path, limit: int = 50) -> List[Path]:
    """Return up to *limit* NetCDF files, searching one level deep."""
    files: List[Path] = []
    for ext in ("*.nc", "*.nc4", "*.NC", "*.netcdf"):
        files.extend(dirpath.glob(ext))
        if len(files) < limit:
            files.extend(dirpath.glob(f"*/{ext}"))
        if len(files) >= limit:
            break
    return sorted(files)[:limit]


# ---------------------------------------------------------------------------
# Sample file selection
# ---------------------------------------------------------------------------

def _pick_sample_file(forcing_dir: str, source: str,
                      year: Optional[int] = None) -> Optional[Path]:
    """Pick a single representative NetCDF (or CSV) file to inspect."""
    files = _pick_sample_files(forcing_dir, source, year)
    return files[0] if files else None


def _pick_sample_files(forcing_dir: str, source: str,
                       year: Optional[int] = None) -> List[Path]:
    """Pick one sample file per variable for multi-file datasets.

    CMFD and MSWX store one variable per file (e.g. temp_CMFD_...nc,
    prec_CMFD_...nc).  This function returns one file per unique variable
    prefix so that all variables get checked.

    For datasets with all variables in a single file, returns a list
    with one entry.
    """
    p = Path(forcing_dir)

    # For FLUXNET, look for CSV first
    if source == "fluxnet":
        csvs = sorted(p.glob("**/*FULLSET*.csv"))
        if not csvs:
            csvs = sorted(p.glob("**/*.csv"))
        return csvs[:1]

    nc_files = _find_nc_files(p, limit=500)
    if not nc_files:
        return []

    # Filter by year if requested
    year_files = nc_files
    if year is not None:
        yr_str = str(year)
        matched = [f for f in nc_files if yr_str in f.name]
        if matched:
            year_files = matched

    # Group files by their variable prefix.
    # Common patterns:  "temp_CMFD_..._1980.nc"  ->  prefix "temp"
    #                   "Tair/Tair_1980.nc"      ->  prefix "Tair"
    var_map = SOURCE_VAR_MAPS.get(source, {})
    selected: Dict[str, Path] = {}

    for f in year_files:
        stem = f.stem.lower()
        # Check if the filename starts with a known variable name
        matched_var = None
        for known_var in var_map:
            kv_lower = known_var.lower()
            if stem.startswith(kv_lower + "_") or stem.startswith(kv_lower + "."):
                matched_var = known_var
                break
            # Also check parent directory name (MSWX pattern: Tair/Tair_1980.nc)
            if f.parent.name.lower() == kv_lower:
                matched_var = known_var
                break
        if matched_var and matched_var not in selected:
            selected[matched_var] = f

    # If we found per-variable files, return one per variable
    if selected:
        return list(selected.values())

    # Otherwise just return the first file (all-in-one dataset)
    return [year_files[0]]


# ---------------------------------------------------------------------------
# Variable statistics extraction
# ---------------------------------------------------------------------------

def _read_nc_stats(filepath: Path, source: str,
                   shapefile: Optional[str] = None,
                   ) -> Dict[str, Dict[str, Any]]:
    """Read a NetCDF and return per-variable statistics.

    Returns dict like:
        { "temp": {"min": 250.1, "max": 310.2, "mean": 280.3,
                   "units_attr": "K", "shape": (365, 10, 20)} }
    """
    try:
        import xarray as xr
    except ImportError:
        raise RuntimeError(
            "xarray is required for NetCDF inspection.  "
            "Install with: pip install xarray netCDF4"
        )

    ds = xr.open_dataset(filepath)

    # Optional spatial clip with shapefile
    if shapefile is not None:
        ds = _clip_to_shapefile(ds, shapefile)

    var_map = SOURCE_VAR_MAPS.get(source, {})
    stats: Dict[str, Dict[str, Any]] = {}

    for vname in ds.data_vars:
        vname_str = str(vname)
        da = ds[vname_str]

        # Skip coordinate-like variables (1-D, string, etc.)
        if da.ndim < 1:
            continue

        # Compute stats on a subsample to keep it fast (first time-slice
        # or first 10 time steps if large)
        sample = da
        time_dims = [d for d in da.dims if d.lower() in ("time", "t")]
        if time_dims and da.sizes[time_dims[0]] > 10:
            sample = da.isel({time_dims[0]: slice(0, 10)})

        try:
            vals = sample.values
            import numpy as np
            finite = vals[np.isfinite(vals)]
            if finite.size == 0:
                continue
            stats[vname_str] = {
                "min": float(np.nanmin(finite)),
                "max": float(np.nanmax(finite)),
                "mean": float(np.nanmean(finite)),
                "std": float(np.nanstd(finite)),
                "units_attr": da.attrs.get("units", da.attrs.get("unit", "")),
                "long_name": da.attrs.get("long_name", ""),
                "shape": list(da.shape),
                "n_finite": int(finite.size),
                "pct_nan": float(1.0 - finite.size / vals.size) if vals.size > 0 else 0.0,
            }
        except Exception:
            # Silently skip variables that cannot be cast to float
            continue

    ds.close()
    return stats


def _read_csv_stats(filepath: Path,
                    source: str) -> Dict[str, Dict[str, Any]]:
    """Read a FLUXNET-style CSV and return per-variable statistics."""
    try:
        import pandas as pd
        import numpy as np
    except ImportError:
        raise RuntimeError(
            "pandas is required for CSV inspection.  "
            "Install with: pip install pandas"
        )

    df = pd.read_csv(filepath, nrows=5000)
    var_map = SOURCE_VAR_MAPS.get(source, {})
    stats: Dict[str, Dict[str, Any]] = {}

    for col in df.columns:
        if col not in var_map:
            continue
        series = pd.to_numeric(df[col], errors="coerce")
        finite = series.dropna()
        if finite.empty:
            continue
        # FLUXNET uses -9999 as fill value
        finite = finite[finite > -9990]
        if finite.empty:
            continue
        stats[col] = {
            "min": float(finite.min()),
            "max": float(finite.max()),
            "mean": float(finite.mean()),
            "std": float(finite.std()),
            "units_attr": "",
            "long_name": col,
            "shape": [len(finite)],
            "n_finite": int(len(finite)),
            "pct_nan": float(1.0 - len(finite) / len(df)),
        }
    return stats


def _clip_to_shapefile(ds: "xarray.Dataset",
                       shapefile: str) -> "xarray.Dataset":
    """Clip dataset to bounding box of a shapefile.

    Falls back to the full dataset if geopandas/rioxarray are unavailable.
    """
    try:
        import geopandas as gpd
    except ImportError:
        return ds

    gdf = gpd.read_file(shapefile)
    bounds = gdf.total_bounds  # minx, miny, maxx, maxy

    # Identify lat/lon dimension names
    lat_names = [d for d in ds.dims if d.lower() in ("lat", "latitude", "y")]
    lon_names = [d for d in ds.dims if d.lower() in ("lon", "longitude", "x")]
    if not lat_names or not lon_names:
        return ds

    lat_dim = lat_names[0]
    lon_dim = lon_names[0]

    ds = ds.sel({
        lat_dim: slice(
            min(bounds[1], bounds[3]),
            max(bounds[1], bounds[3]),
        ),
        lon_dim: slice(
            min(bounds[0], bounds[2]),
            max(bounds[0], bounds[2]),
        ),
    })
    return ds


# ---------------------------------------------------------------------------
# Range-check engine
# ---------------------------------------------------------------------------

@dataclass
class VarCheckResult:
    """Result of checking one variable."""
    variable: str               # original variable name in file
    canonical: str              # canonical name (e.g. "temperature")
    expected_unit: str          # what unit we expect for this source
    file_unit_attr: str         # what the file's 'units' attribute says
    status: str                 # PASS, WARN, or FAIL
    detail: str = ""            # human-readable explanation
    min_val: float = 0.0
    max_val: float = 0.0
    mean_val: float = 0.0
    pct_nan: float = 0.0
    hints: List[str] = field(default_factory=list)


def _find_range_spec(canonical: str, unit: str) -> Optional[RangeSpec]:
    """Find the matching RangeSpec for a canonical variable and unit."""
    for spec in RANGE_TABLE:
        if spec.var_canonical == canonical:
            if spec.unit_label == unit:
                return spec
            if spec.alt_unit_label == unit:
                # Build a "flipped" spec so the alt range becomes primary
                return RangeSpec(
                    var_canonical=spec.var_canonical,
                    unit_label=spec.alt_unit_label,
                    lo=spec.alt_lo,
                    hi=spec.alt_hi,
                    below_hint=spec.alt_below_hint,
                    above_hint=spec.alt_above_hint,
                )
    # Fallback: match canonical only (use first match)
    for spec in RANGE_TABLE:
        if spec.var_canonical == canonical:
            return spec
    return None


def check_variable(var_name: str, canonical: str, expected_unit: str,
                   var_stats: Dict[str, Any]) -> VarCheckResult:
    """Check one variable against physical plausibility ranges.

    Returns a VarCheckResult with status PASS / WARN / FAIL.
    """
    result = VarCheckResult(
        variable=var_name,
        canonical=canonical,
        expected_unit=expected_unit,
        file_unit_attr=var_stats.get("units_attr", ""),
        status=PASS,
        min_val=var_stats.get("min", 0.0),
        max_val=var_stats.get("max", 0.0),
        mean_val=var_stats.get("mean", 0.0),
        pct_nan=var_stats.get("pct_nan", 0.0),
    )

    spec = _find_range_spec(canonical, expected_unit)
    if spec is None:
        result.status = WARN
        result.detail = f"No plausibility range defined for {canonical} ({expected_unit})"
        return result

    lo, hi = spec.lo, spec.hi
    vmin = var_stats["min"]
    vmax = var_stats["max"]
    vmean = var_stats["mean"]

    hints: List[str] = []

    # -- NaN check --
    # Note: gridded datasets (CMFD, MSWX, ERA5) commonly have 30-60% NaN
    # from ocean/border masking in rectangular subsets.  Only flag truly
    # extreme NaN fractions as FAIL; moderate fractions as WARN.
    pct_nan = var_stats.get("pct_nan", 0.0)
    if pct_nan > 0.95:
        result.status = FAIL
        hints.append(
            f"{pct_nan*100:.1f}% of values are NaN/missing -- "
            "file may be empty or corrupt"
        )
    elif pct_nan > 0.8:
        if result.status != FAIL:
            result.status = WARN
        hints.append(
            f"{pct_nan*100:.1f}% of values are NaN/missing -- "
            "verify spatial domain covers your study area"
        )
    elif pct_nan > 0.3:
        # Common for gridded subsets; note but do not elevate status
        hints.append(
            f"{pct_nan*100:.1f}% of values are NaN (likely spatial masking, "
            "e.g. ocean cells -- normal for gridded subsets)"
        )

    # -- Unit-attr mismatch warning --
    file_unit = var_stats.get("units_attr", "")
    if file_unit and not _units_compatible(file_unit, expected_unit):
        if result.status != FAIL:
            result.status = WARN
        hints.append(
            f"File 'units' attribute is '{file_unit}' but source expects "
            f"'{expected_unit}' -- verify conversion"
        )

    # -- Range check on min --
    if vmin < lo:
        # How far below?
        if canonical == "temperature" and vmin < lo and vmin > -90:
            # Likely Celsius when K expected (or vice versa)
            result.status = FAIL
            if spec.below_hint:
                hints.append(spec.below_hint)
            else:
                hints.append(f"Min value {vmin:.2f} is below plausible {lo} {spec.unit_label}")
        elif canonical in ("precipitation_daily", "precipitation_rate") and vmin < 0:
            result.status = FAIL
            hints.append(f"Negative precipitation ({vmin:.4g}) -- check fill values or sign convention")
        elif canonical == "longwave_radiation" and vmin < lo:
            result.status = FAIL
            if spec.below_hint:
                hints.append(spec.below_hint)
            else:
                hints.append(f"Min LW {vmin:.1f} W/m2 is below plausible {lo} W/m2")
        elif canonical == "pressure" and vmin < lo:
            result.status = FAIL
            if spec.below_hint:
                hints.append(spec.below_hint)
            else:
                hints.append(f"Min pressure {vmin:.0f} below plausible {lo} {spec.unit_label}")
        else:
            if vmin < lo:
                if result.status != FAIL:
                    result.status = WARN
                hint = spec.below_hint or f"Min value {vmin:.4g} < {lo} {spec.unit_label}"
                hints.append(hint)

    # -- Range check on max --
    if vmax > hi:
        if canonical == "temperature" and vmax > hi:
            result.status = FAIL
            if spec.above_hint:
                hints.append(spec.above_hint)
            else:
                hints.append(f"Max value {vmax:.2f} exceeds plausible {hi} {spec.unit_label}")
        elif canonical in ("precipitation_daily",) and vmax > hi:
            result.status = FAIL
            if spec.above_hint:
                hints.append(spec.above_hint)
            else:
                hints.append(f"Max precip {vmax:.2f} > {hi} mm/day")
        elif canonical == "precipitation_rate" and vmax > hi:
            result.status = FAIL
            if spec.above_hint:
                hints.append(spec.above_hint)
            else:
                hints.append(f"Max precip rate {vmax:.6g} > {hi} kg/m2/s")
        elif canonical == "shortwave_radiation" and vmax > hi:
            result.status = FAIL
            if spec.above_hint:
                hints.append(spec.above_hint)
            else:
                hints.append(f"Max SW {vmax:.1f} > {hi} W/m2")
        elif canonical == "specific_humidity" and vmax > hi:
            result.status = FAIL
            if spec.above_hint:
                hints.append(spec.above_hint)
            else:
                hints.append(f"Max q {vmax:.4g} > {hi} kg/kg")
        elif canonical == "wind_speed" and vmax > hi:
            if result.status != FAIL:
                result.status = WARN
            if spec.above_hint:
                hints.append(spec.above_hint)
            else:
                hints.append(f"Max wind {vmax:.1f} > {hi} m/s")
        else:
            if result.status != FAIL:
                result.status = WARN
            hint = spec.above_hint or f"Max value {vmax:.4g} > {hi} {spec.unit_label}"
            hints.append(hint)

    # -- Special: detect if temperature is in wrong system entirely --
    if canonical == "temperature" and expected_unit == "K":
        if -80 < vmean < 60:
            result.status = FAIL
            hints.append(
                f"Mean temperature {vmean:.2f} looks like Celsius, "
                "but source expects Kelvin (add 273.15)"
            )
        elif vmean > 400:
            result.status = FAIL
            hints.append(
                f"Mean temperature {vmean:.2f} K is implausibly high -- "
                "possible double-conversion"
            )

    # -- Special: detect CMFD precip read as mm/day when it is kg/m2/s --
    if canonical == "precipitation_rate" and expected_unit == "kg/m2/s":
        if vmean > 0.1:
            result.status = FAIL
            hints.append(
                f"Mean precip rate {vmean:.4g} is far too high for kg/m2/s "
                "(typical mean ~0.00002). Data may be in mm/day -- "
                "divide by 86400"
            )
        if vmax > 0.05 and vmax < 500:
            result.status = FAIL
            hints.append(
                f"Max precip {vmax:.4g} looks like mm/day values, not kg/m2/s. "
                "CMFD prec is kg/m2/s (multiply by 86400 to get mm/day)"
            )

    # -- Special: detect pressure in wrong system --
    if canonical == "pressure" and expected_unit == "Pa":
        if 300 <= vmean <= 1100:
            result.status = FAIL
            hints.append(
                f"Mean pressure {vmean:.0f} looks like hPa, not Pa "
                "(multiply by 100)"
            )

    if canonical == "pressure" and expected_unit == "hPa":
        if vmean > 30000:
            result.status = FAIL
            hints.append(
                f"Mean pressure {vmean:.0f} looks like Pa, not hPa "
                "(divide by 100)"
            )

    # -- Special: detect specific humidity in g/kg or RH% --
    if canonical == "specific_humidity" and expected_unit == "kg/kg":
        if 0.05 < vmean < 50:
            result.status = FAIL
            hints.append(
                f"Mean q = {vmean:.3g} -- too high for kg/kg. "
                "Probably in g/kg (divide by 1000)"
            )
        if vmean > 50:
            result.status = FAIL
            hints.append(
                f"Mean q = {vmean:.1f} -- looks like relative humidity %, "
                "not specific humidity kg/kg"
            )

    # -- Compose final detail --
    if not hints:
        result.detail = (
            f"Values [{vmin:.4g}, {vmax:.4g}] within plausible range "
            f"[{lo}, {hi}] {spec.unit_label}"
        )
    else:
        result.detail = "; ".join(hints)

    result.hints = hints
    return result


def _units_compatible(file_unit: str, expected_unit: str) -> bool:
    """Fuzzy check whether file unit string matches expected unit.

    Not meant to be exhaustive -- just catches obvious mismatches.
    """
    fu = file_unit.lower().replace(" ", "").replace("_", "")
    eu = expected_unit.lower().replace(" ", "").replace("_", "")

    # Exact match
    if fu == eu:
        return True

    # Common equivalences
    equivalences = [
        ({"k", "kelvin"}, {"k", "kelvin"}),
        ({"degc", "c", "celsius", "degreec", "degrees_celsius", "degreescelsius"},
         {"degc", "c", "celsius", "degreec", "degrees_celsius", "degreescelsius"}),
        ({"pa", "pascal"}, {"pa", "pascal"}),
        ({"hpa", "hectopascal", "mbar", "mb"}, {"hpa", "hectopascal", "mbar", "mb"}),
        ({"w/m2", "wm-2", "w/m^2", "wm**-2", "watt/m2", "wattspermetersquared"},
         {"w/m2", "wm-2", "w/m^2", "wm**-2", "watt/m2", "wattspermetersquared"}),
        ({"kg/m2/s", "kgm-2s-1", "kg/m^2/s", "kgm**-2s**-1"},
         {"kg/m2/s", "kgm-2s-1", "kg/m^2/s", "kgm**-2s**-1"}),
        ({"mm/day", "mm/d", "mmday-1", "mmd-1"},
         {"mm/day", "mm/d", "mmday-1", "mmd-1"}),
        ({"m/s", "ms-1", "ms**-1"}, {"m/s", "ms-1", "ms**-1"}),
        ({"kg/kg", "kgkg-1", "kg/kg-1"}, {"kg/kg", "kgkg-1", "kg/kg-1"}),
    ]
    for group_a, group_b in equivalences:
        if fu in group_a and eu in group_b:
            return True
        if fu in group_b and eu in group_a:
            return True
    return False


# ---------------------------------------------------------------------------
# Main validation orchestrator
# ---------------------------------------------------------------------------

@dataclass
class PreflightReport:
    """Full preflight validation report."""
    forcing_dir: str
    source: str
    sample_file: str
    timestamp: str
    all_pass: bool
    n_pass: int = 0
    n_warn: int = 0
    n_fail: int = 0
    checks: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    summary: str = ""


def validate_forcing(forcing_dir: str,
                     source: str = "auto",
                     year: Optional[int] = None,
                     shapefile: Optional[str] = None,
                     ) -> PreflightReport:
    """Run full preflight validation on a forcing directory.

    Parameters
    ----------
    forcing_dir : str
        Path to directory containing forcing data files.
    source : str
        Data source identifier: 'cmfd', 'mswx', 'era5', 'fluxnet', or
        'auto' (default) to auto-detect.
    year : int, optional
        Prefer a sample file from this year.
    shapefile : str, optional
        Path to a shapefile to clip the spatial domain before checking.

    Returns
    -------
    PreflightReport
        Dataclass with per-variable results and summary.
    """
    forcing_dir = str(Path(forcing_dir).resolve())

    # Detect source
    if source == "auto" or not source:
        source = detect_source(forcing_dir)

    report = PreflightReport(
        forcing_dir=forcing_dir,
        source=source,
        sample_file="",
        timestamp=datetime.now().isoformat(),
        all_pass=True,
    )

    if source == "unknown":
        report.all_pass = False
        report.errors.append(
            "Could not auto-detect forcing source. "
            "Use --source cmfd|mswx|era5|fluxnet to specify."
        )
        report.summary = "FAIL: Unable to detect data source."
        return report

    # Pick sample files (one per variable for multi-file datasets)
    samples = _pick_sample_files(forcing_dir, source, year)
    if not samples:
        report.all_pass = False
        report.errors.append(
            f"No data files found in {forcing_dir} for source '{source}'"
        )
        report.summary = f"FAIL: No data files found."
        return report

    report.sample_file = "; ".join(s.name for s in samples)

    # Read statistics from all sample files, merging into one dict
    var_stats: Dict[str, Dict[str, Any]] = {}
    for sample in samples:
        try:
            if sample.suffix.lower() == ".csv":
                file_stats = _read_csv_stats(sample, source)
            else:
                file_stats = _read_nc_stats(sample, source, shapefile)
            var_stats.update(file_stats)
        except Exception as exc:
            report.errors.append(f"Failed to read {sample.name}: {exc}")

    if not var_stats:
        report.all_pass = False
        if not report.errors:
            report.errors.append(
                f"No recognized variables found in sample files. "
                f"Expected variables for '{source}': "
                f"{list(SOURCE_VAR_MAPS.get(source, {}).keys())}"
            )
        report.summary = "FAIL: No recognized variables in sample files."
        return report

    # Run checks
    var_map = SOURCE_VAR_MAPS.get(source, {})
    n_pass = n_warn = n_fail = 0
    all_warnings: List[str] = []
    all_errors: List[str] = []

    for var_name, stats in var_stats.items():
        if var_name in var_map:
            canonical, expected_unit = var_map[var_name]
        else:
            # Try to match by canonical name patterns
            canonical, expected_unit = _guess_canonical(var_name, stats)
            if canonical is None:
                continue  # skip unknown variables

        result = check_variable(var_name, canonical, expected_unit, stats)
        report.checks.append(asdict(result))

        if result.status == PASS:
            n_pass += 1
        elif result.status == WARN:
            n_warn += 1
            all_warnings.append(f"[WARN] {var_name}: {result.detail}")
        elif result.status == FAIL:
            n_fail += 1
            all_errors.append(f"[FAIL] {var_name}: {result.detail}")

    report.n_pass = n_pass
    report.n_warn = n_warn
    report.n_fail = n_fail
    report.warnings = all_warnings
    report.errors = all_errors
    report.all_pass = (n_fail == 0)

    # Build human-readable summary
    total = n_pass + n_warn + n_fail
    sample_names = ", ".join(s.name for s in samples)
    lines = [
        f"Preflight check: {source.upper()} forcing in {forcing_dir}",
        f"Sample files ({len(samples)}): {sample_names}",
        f"Variables checked: {total}  "
        f"(PASS: {n_pass}, WARN: {n_warn}, FAIL: {n_fail})",
    ]
    if n_fail > 0:
        lines.append("")
        lines.append("=== FAILURES (likely unit errors) ===")
        for e in all_errors:
            lines.append(f"  {e}")
    if n_warn > 0:
        lines.append("")
        lines.append("=== WARNINGS ===")
        for w in all_warnings:
            lines.append(f"  {w}")
    if n_fail == 0 and n_warn == 0:
        lines.append("")
        lines.append("All variables within plausible physical ranges.")

    report.summary = "\n".join(lines)
    return report


def _guess_canonical(var_name: str,
                     stats: Dict[str, Any],
                     ) -> Tuple[Optional[str], str]:
    """Best-effort guess of canonical variable name from arbitrary var names.

    Returns (canonical_name, assumed_unit) or (None, "").
    """
    vn = var_name.lower()

    # Temperature
    if any(k in vn for k in ("temp", "t2m", "tair", "tas", "tmp")):
        # Guess unit from value range
        vmean = stats.get("mean", 0)
        if vmean > 100:
            return ("temperature", "K")
        else:
            return ("temperature", "degC")

    # Precipitation
    if any(k in vn for k in ("prec", "rain", "tp", "ppt", "pr")):
        vmax = stats.get("max", 0)
        if vmax < 1.0:
            return ("precipitation_rate", "kg/m2/s")
        else:
            return ("precipitation_daily", "mm/day")

    # Shortwave radiation
    if any(k in vn for k in ("srad", "ssrd", "sw_in", "swd", "rsds",
                              "swdown", "solar", "dswrf")):
        return ("shortwave_radiation", "W/m2")

    # Longwave radiation
    if any(k in vn for k in ("lrad", "strd", "lw_in", "lwd", "rlds",
                              "lwdown", "dlwrf")):
        return ("longwave_radiation", "W/m2")

    # Pressure
    if any(k in vn for k in ("pres", "sp", "msl", "ps", "press",
                              "pa_f", "slp")):
        vmean = stats.get("mean", 0)
        if vmean > 10000:
            return ("pressure", "Pa")
        else:
            return ("pressure", "hPa")

    # Specific humidity
    if any(k in vn for k in ("shum", "spechum", "huss", "q2",
                              "specific_humidity")):
        return ("specific_humidity", "kg/kg")

    # Wind
    if any(k in vn for k in ("wind", "ws", "u10", "v10", "sfcwind",
                              "ws_f")):
        return ("wind_speed", "m/s")

    return (None, "")


# ---------------------------------------------------------------------------
# Quick-check convenience function (for use from ki/tools/ scripts)
# ---------------------------------------------------------------------------

def quick_check_forcing(forcing_dir: str,
                        source: str = "auto",
                        year: Optional[int] = None,
                        shapefile: Optional[str] = None,
                        ) -> Dict[str, Any]:
    """Quick-check a forcing directory and return a simple dict.

    Intended to be called from any ki/tools/ script::

        from validators.preflight_forcing import quick_check_forcing
        result = quick_check_forcing('/path/to/forcing/', source='cmfd')
        if not result['all_pass']:
            print("WARNING:", result['warnings'])

    Returns
    -------
    dict with keys:
        all_pass : bool
            True if no FAIL-level issues found.
        n_pass : int
        n_warn : int
        n_fail : int
        warnings : list[str]
            Human-readable warning messages.
        errors : list[str]
            Human-readable error messages (FAIL-level).
        summary : str
            Full human-readable summary.
        checks : list[dict]
            Per-variable detail dicts.
        source : str
            Detected or specified source.
        sample_file : str
            Which file was inspected.
    """
    report = validate_forcing(
        forcing_dir=forcing_dir,
        source=source,
        year=year,
        shapefile=shapefile,
    )
    return asdict(report)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="preflight_forcing",
        description=(
            "Pre-simulation validator for forcing data.  "
            "Detects the data source, reads a sample file, and checks "
            "all variables against physical plausibility ranges."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python preflight_forcing.py /path/to/forcing/\n"
            "  python preflight_forcing.py /path/to/forcing/ --source cmfd --year 1980\n"
            "  python preflight_forcing.py /path/to/forcing/ --source auto --shapefile bengbu.shp\n"
            "  python preflight_forcing.py /path/to/forcing/ --json\n"
        ),
    )
    parser.add_argument(
        "forcing_dir",
        help="Path to directory containing forcing data files.",
    )
    parser.add_argument(
        "--source",
        choices=["cmfd", "mswx", "era5", "fluxnet", "auto"],
        default="auto",
        help="Data source (default: auto-detect).",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=None,
        help="Prefer a sample file from this year.",
    )
    parser.add_argument(
        "--shapefile",
        default=None,
        help="Optional shapefile to clip spatial domain before checking.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output full report as JSON (default: human-readable summary).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 1 on any WARN or FAIL (default: only FAIL).",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point.  Returns exit code (0 = ok, 1 = fail)."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    report = validate_forcing(
        forcing_dir=args.forcing_dir,
        source=args.source,
        year=args.year,
        shapefile=args.shapefile,
    )

    if args.json_output:
        print(json.dumps(asdict(report), indent=2, default=str))
    else:
        print(report.summary)

    if report.n_fail > 0:
        return 1
    if args.strict and report.n_warn > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
