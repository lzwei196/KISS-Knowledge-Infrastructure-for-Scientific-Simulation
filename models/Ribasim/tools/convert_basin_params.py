#!/usr/bin/env python3
"""
convert_basin_params.py — Convert external forcing/parameter data to Ribasim format.

Converts meteorological forcing (precipitation, evaporation) from common units
(mm/day, mm/hr) to Ribasim's native units (m/s), and builds Basin parameter
tables (profile, state, static, time) from various data sources.

Also handles soil/land-use parameters such as Manning's n values from
land cover classifications.

Pattern: validate → process → validate

Usage:
    python convert_basin_params.py \
        --forcing_csv met_data.csv \
        --forcing_units mm/day \
        --profile_csv basin_profiles.csv \
        --profile_area_units km2 \
        --manning_csv manning_params.csv \
        --output_dir converted/
"""

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Unit conversion factors
# ---------------------------------------------------------------------------
# Precipitation / evaporation → m/s
PRECIP_CONVERSIONS = {
    "m/s": 1.0,
    "mm/s": 1.0e-3,
    "mm/hr": 1.0e-3 / 3600.0,
    "mm/day": 1.0e-3 / 86400.0,
    "mm/3hr": 1.0e-3 / 10800.0,
    "m/day": 1.0 / 86400.0,
    "m/hr": 1.0 / 3600.0,
    "inch/day": 0.0254 / 86400.0,
    "inch/hr": 0.0254 / 3600.0,
}

# Area → m²
AREA_CONVERSIONS = {
    "m2": 1.0,
    "km2": 1.0e6,
    "ha": 1.0e4,
    "acre": 4046.86,
    "sqft": 0.0929,
    "sqmi": 2.59e6,
}

# Flow → m³/s
FLOW_CONVERSIONS = {
    "m3/s": 1.0,
    "cms": 1.0,
    "l/s": 1.0e-3,
    "ml/day": 1.0e3 / 86400.0,
    "mcm/day": 1.0e6 / 86400.0,
    "cfs": 0.0283168,
    "m3/hr": 1.0 / 3600.0,
    "m3/day": 1.0 / 86400.0,
}

# Storage → m³
STORAGE_CONVERSIONS = {
    "m3": 1.0,
    "ml": 1.0e3,
    "mcm": 1.0e6,
    "gl": 1.0e6,
    "km3": 1.0e9,
    "acre-ft": 1233.48,
}

# Manning's n lookup by land cover type (approximate)
MANNING_N_LOOKUP = {
    "concrete": 0.013,
    "asphalt": 0.016,
    "gravel": 0.025,
    "earth_channel": 0.025,
    "natural_stream": 0.035,
    "floodplain_grass": 0.035,
    "floodplain_trees": 0.060,
    "dense_vegetation": 0.080,
    "wetland": 0.070,
    "urban": 0.015,
    "cropland": 0.035,
    "forest": 0.100,
    "default": 0.035,
}


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def validate_forcing_csv(df: pd.DataFrame) -> list[str]:
    """Validate meteorological forcing CSV."""
    errors = []

    if "time" not in df.columns:
        errors.append("Missing 'time' column in forcing CSV")

    # Check for at least one forcing variable.
    # Ribasim 2026.1.0-rc2 names the evaporation column `potential_evaporation`
    # (core/src/schema.jl); `evaporation` is accepted here as an input alias and
    # renamed on output.
    forcing_vars = {"precipitation", "evaporation", "potential_evaporation",
                    "drainage", "infiltration", "surface_runoff"}
    found = forcing_vars & set(df.columns)
    if not found:
        errors.append(f"No forcing variables found. Expected at least one of: {forcing_vars}")

    # Check for NaN
    for col in found:
        n_nan = df[col].isna().sum()
        if n_nan > 0:
            errors.append(f"Column '{col}' has {n_nan} NaN values")

    # Check for negative precipitation
    if "precipitation" in df.columns:
        n_neg = (df["precipitation"] < 0).sum()
        if n_neg > 0:
            errors.append(f"Precipitation has {n_neg} negative values")

    return errors


def validate_profile_csv(df: pd.DataFrame) -> list[str]:
    """Validate basin profile CSV."""
    errors = []

    required = {"node_id", "level", "area"}
    missing = required - set(df.columns)
    if missing:
        errors.append(f"Missing required columns in profile CSV: {missing}")
        return errors

    for nid, group in df.groupby("node_id"):
        levels = group["level"].values
        areas = group["area"].values

        if len(levels) < 2:
            errors.append(f"Basin {nid}: need >= 2 profile points, got {len(levels)}")

        if not np.all(np.diff(levels) > 0):
            errors.append(f"Basin {nid}: levels must be monotonically increasing")

        if np.any(areas < 0):
            errors.append(f"Basin {nid}: negative area values")

    return errors


def validate_converted_forcing(df: pd.DataFrame) -> list[str]:
    """Post-conversion validation for Ribasim forcing data."""
    errors = []

    if "precipitation" in df.columns:
        max_precip = df["precipitation"].max()
        # 500 mm/day = 5.787e-6 m/s (extreme rainfall)
        if max_precip > 1e-5:
            errors.append(
                f"Precipitation max = {max_precip:.2e} m/s — likely still in wrong units! "
                f"Expected < 1e-5 m/s (< 864 mm/day)"
            )
        if max_precip > 1.0:
            errors.append(
                f"CRITICAL: Precipitation = {max_precip:.2e} — almost certainly mm/day "
                f"passed as m/s (1e6x error)"
            )

    for evap_col in ("evaporation", "potential_evaporation"):
        if evap_col in df.columns:
            max_evap = df[evap_col].max()
            if max_evap > 1e-5:
                errors.append(
                    f"{evap_col} max = {max_evap:.2e} m/s — likely wrong units! "
                    f"Expected < 1e-6 m/s (< 86.4 mm/day)"
                )

    return errors


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------
def convert_forcing(
    df: pd.DataFrame, precip_units: str, evap_units: str | None = None
) -> pd.DataFrame:
    """Convert forcing data to Ribasim units (m/s for fluxes)."""
    out = df.copy()

    if evap_units is None:
        evap_units = precip_units

    if "precipitation" in out.columns:
        factor = PRECIP_CONVERSIONS.get(precip_units.lower())
        if factor is None:
            raise ValueError(
                f"Unknown precipitation unit: {precip_units}. "
                f"Valid: {list(PRECIP_CONVERSIONS.keys())}"
            )
        out["precipitation"] = out["precipitation"] * factor
        print(f"  Precipitation: {precip_units} → m/s (factor={factor:.2e})")

    # Ribasim 2026.1.0-rc2 schema column is `potential_evaporation`; accept the
    # legacy `evaporation` name on input and RENAME it on output so the written
    # CSV matches the schema (a column named `evaporation` would be rejected or
    # silently dropped by the model, leaving zero evaporation).
    if "evaporation" in out.columns and "potential_evaporation" not in out.columns:
        out = out.rename(columns={"evaporation": "potential_evaporation"})
        print("  Renamed column: evaporation → potential_evaporation (schema name)")

    if "potential_evaporation" in out.columns:
        factor = PRECIP_CONVERSIONS.get(evap_units.lower())
        if factor is None:
            raise ValueError(
                f"Unknown evaporation unit: {evap_units}. "
                f"Valid: {list(PRECIP_CONVERSIONS.keys())}"
            )
        out["potential_evaporation"] = out["potential_evaporation"] * factor
        print(f"  Evaporation: {evap_units} → m/s (factor={factor:.2e})")

    # Drainage and infiltration should be in m³/s already
    for col in ["drainage", "infiltration"]:
        if col in out.columns:
            print(f"  {col}: assumed m³/s (no conversion)")

    return out


def convert_profile_areas(df: pd.DataFrame, area_units: str) -> pd.DataFrame:
    """Convert profile areas to m²."""
    out = df.copy()
    factor = AREA_CONVERSIONS.get(area_units.lower())
    if factor is None:
        raise ValueError(
            f"Unknown area unit: {area_units}. Valid: {list(AREA_CONVERSIONS.keys())}"
        )
    out["area"] = out["area"] * factor
    print(f"  Area: {area_units} → m² (factor={factor:.2e})")

    # Compute storage by trapezoidal integration if not present
    if "storage" not in out.columns:
        print("  Computing storage from area-level profile (trapezoidal)...")
        storages = []
        for nid, group in out.groupby("node_id"):
            levels = group["level"].values
            areas = group["area"].values
            storage = np.zeros_like(levels)
            for i in range(1, len(levels)):
                dh = levels[i] - levels[i - 1]
                storage[i] = storage[i - 1] + 0.5 * (areas[i - 1] + areas[i]) * dh
            storages.extend(storage)
        out["storage"] = storages

    return out


def lookup_manning_n(land_cover: str) -> float:
    """Get Manning's n value from land cover type."""
    return MANNING_N_LOOKUP.get(land_cover.lower(), MANNING_N_LOOKUP["default"])


def convert_manning_params(df: pd.DataFrame) -> pd.DataFrame:
    """Convert Manning parameters with land cover lookup."""
    out = df.copy()

    if "land_cover" in out.columns and "manning_n" not in out.columns:
        out["manning_n"] = out["land_cover"].apply(lookup_manning_n)
        print("  Manning n: derived from land_cover classification")

    # Validate ranges
    if "manning_n" in out.columns:
        invalid = out[(out["manning_n"] < 0.001) | (out["manning_n"] > 0.5)]
        if len(invalid) > 0:
            print(f"  WARNING: {len(invalid)} Manning n values outside typical range [0.001, 0.5]")

    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Convert parameters to Ribasim format")
    parser.add_argument("--forcing_csv", help="Meteorological forcing CSV")
    parser.add_argument("--forcing_units", default="mm/day",
                        help=f"Precip/evap units: {list(PRECIP_CONVERSIONS.keys())}")
    parser.add_argument("--evap_units", help="Evaporation units (if different from precip)")
    parser.add_argument("--profile_csv", help="Basin profile CSV (node_id, level, area)")
    parser.add_argument("--profile_area_units", default="m2",
                        help=f"Profile area units: {list(AREA_CONVERSIONS.keys())}")
    parser.add_argument("--manning_csv", help="Manning resistance parameters CSV")
    parser.add_argument("--output_dir", required=True, help="Output directory")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = {"status": "success", "conversions": []}

    # --- Forcing conversion ---
    if args.forcing_csv:
        print("[1] Converting meteorological forcing...")
        df = pd.read_csv(args.forcing_csv, parse_dates=["time"])

        errors = validate_forcing_csv(df)
        if errors:
            print("ERROR: Forcing validation failed:")
            for e in errors:
                print(f"  - {e}")
            sys.exit(1)

        converted = convert_forcing(df, args.forcing_units, args.evap_units)

        # Post-conversion validation
        errors = validate_converted_forcing(converted)
        if errors:
            print("WARNING: Post-conversion validation issues:")
            for e in errors:
                print(f"  - {e}")

        out_path = output_dir / "basin_forcing.csv"
        converted.to_csv(out_path, index=False)
        print(f"  Written: {out_path}")
        summary["conversions"].append({
            "type": "forcing",
            "input_units": args.forcing_units,
            "output_units": "m/s",
            "records": len(converted),
        })

    # --- Profile conversion ---
    if args.profile_csv:
        print("[2] Converting basin profiles...")
        df = pd.read_csv(args.profile_csv)

        errors = validate_profile_csv(df)
        if errors:
            print("ERROR: Profile validation failed:")
            for e in errors:
                print(f"  - {e}")
            sys.exit(1)

        converted = convert_profile_areas(df, args.profile_area_units)

        out_path = output_dir / "basin_profile.csv"
        converted.to_csv(out_path, index=False)
        print(f"  Written: {out_path}")
        summary["conversions"].append({
            "type": "profile",
            "input_area_units": args.profile_area_units,
            "output_area_units": "m2",
            "n_basins": df["node_id"].nunique(),
        })

    # --- Manning parameter conversion ---
    if args.manning_csv:
        print("[3] Converting Manning parameters...")
        df = pd.read_csv(args.manning_csv)
        converted = convert_manning_params(df)

        out_path = output_dir / "manning_params.csv"
        converted.to_csv(out_path, index=False)
        print(f"  Written: {out_path}")
        summary["conversions"].append({
            "type": "manning",
            "records": len(converted),
        })

    # Write summary
    summary_path = output_dir / "conversion_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    print(f"\nSummary: {summary_path}")


if __name__ == "__main__":
    main()
