#!/usr/bin/env python3
"""
Convert catchment physical properties to GR4J-compatible parameters.

Pipeline stage: s2 (Catchment parameter extraction)
Pattern: validate inputs -> process -> validate outputs

GR4J is a lumped model — it needs:
  - Catchment area [km2] (for Q unit conversion)
  - Hypsometric curve [m] (optional, for CemaNeige snow module)
  - Latitude [deg] (for PE_Oudin)

This tool extracts these from:
  - Shapefile or coordinates (catchment boundary)
  - DEM (for hypsometry)
  - HWSD (soil properties — informational only, GR4J has no soil parameters)
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_inputs(params: dict) -> list:
    """Validate input parameters."""
    errors = []

    if "area_km2" in params:
        area = params["area_km2"]
        if area <= 0:
            errors.append(f"Catchment area must be positive, got {area}")
        if area > 1e7:
            errors.append(f"Catchment area {area} km2 seems unrealistically large")

    if "latitude" in params:
        lat = params["latitude"]
        if lat < -90 or lat > 90:
            errors.append(f"Latitude must be in [-90, 90], got {lat}")

    if "longitude" in params:
        lon = params["longitude"]
        if lon < -180 or lon > 360:
            errors.append(f"Longitude must be in [-180, 360], got {lon}")

    return errors


def validate_outputs(result: dict) -> list:
    """Validate output catchment parameters."""
    warnings = []

    if result.get("area_km2", 0) < 1:
        warnings.append(
            f"Catchment area = {result['area_km2']:.2f} km2 — very small. "
            "Check if area is in m2 instead of km2 (UT-006)."
        )

    if result.get("area_km2", 0) > 100000:
        warnings.append(
            f"Catchment area = {result['area_km2']:.0f} km2 — very large. "
            "GR4J works best for catchments < 10,000 km2."
        )

    if "hypsometry" in result:
        hyp = result["hypsometry"]
        if len(hyp) != 101:
            warnings.append(
                f"Hypsometry has {len(hyp)} values, expected 101 (percentiles 0-100). "
                "CemaNeige requires exactly 101 values."
            )
        if hyp[0] > hyp[-1]:
            warnings.append(
                "Hypsometry is descending — should be ascending (min to max elevation)."
            )

    return warnings


# ---------------------------------------------------------------------------
# Hypsometric curve extraction
# ---------------------------------------------------------------------------

def compute_hypsometry_from_dem(dem_values: np.ndarray) -> np.ndarray:
    """
    Compute 101-point hypsometric curve from DEM grid cells within catchment.

    Parameters
    ----------
    dem_values : 1D array of elevation values [m] for cells within catchment

    Returns
    -------
    hypsometry : array of 101 float values (percentiles 0-100)
    """
    valid = dem_values[~np.isnan(dem_values)]
    if len(valid) == 0:
        return np.full(101, np.nan)

    percentiles = np.arange(0, 101)
    hypsometry = np.percentile(valid, percentiles)
    return hypsometry


def estimate_area_from_coordinates(lon_min: float, lon_max: float,
                                     lat_min: float, lat_max: float,
                                     fraction: float = 0.7) -> float:
    """
    Rough estimate of catchment area from bounding box.
    Uses approximate km/degree at given latitude.

    Parameters
    ----------
    lon_min, lon_max, lat_min, lat_max : bounding box [degrees]
    fraction : approximate fraction of bounding box covered by catchment

    Returns
    -------
    area_km2 : estimated area [km2]
    """
    import math
    lat_mid = (lat_min + lat_max) / 2.0
    km_per_deg_lat = 111.32
    km_per_deg_lon = 111.32 * math.cos(math.radians(lat_mid))

    width_km = (lon_max - lon_min) * km_per_deg_lon
    height_km = (lat_max - lat_min) * km_per_deg_lat
    area_km2 = width_km * height_km * fraction

    return area_km2


# ---------------------------------------------------------------------------
# Main: build catchment parameter file
# ---------------------------------------------------------------------------

def build_catchment_params(
    area_km2: float,
    latitude: float,
    longitude: float,
    elevation_mean: float = None,
    hypsometry: list = None,
    catchment_name: str = "unknown",
    output_json: str = None,
) -> dict:
    """
    Build GR4J catchment parameter dictionary.

    Parameters
    ----------
    area_km2       : catchment area [km2]
    latitude       : centroid latitude [degrees]
    longitude      : centroid longitude [degrees]
    elevation_mean : mean elevation [m]
    hypsometry     : 101-element list of elevation percentiles [m]
    catchment_name : human-readable name
    output_json    : output path for JSON

    Returns
    -------
    result : dict with catchment parameters
    """
    # --- Validate inputs ---
    params = {"area_km2": area_km2, "latitude": latitude, "longitude": longitude}
    errors = validate_inputs(params)
    if errors:
        raise ValueError("Input validation failed:\n" + "\n".join(errors))

    # --- Build result ---
    result = {
        "catchment_name": catchment_name,
        "area_km2": float(area_km2),
        "latitude_deg": float(latitude),
        "longitude_deg": float(longitude),
        "elevation_mean_m": float(elevation_mean) if elevation_mean else None,
        "model": "GR4J",
        "package": "airGR",
        "unit_system": {
            "precipitation": "mm/day",
            "potential_evapotranspiration": "mm/day",
            "discharge_input": "mm/day",
            "discharge_output": "mm/day",
            "area": "km2",
            "temperature": "degC",
        },
        "conversion_factors": {
            "Q_m3s_to_mmday": round(86.4 / area_km2, 8),
            "Q_ls_to_mmday": round(0.0864 / area_km2, 10),
            "mmday_to_m3s": round(area_km2 / 86.4, 6),
        },
    }

    if hypsometry is not None:
        result["hypsometry"] = [float(h) for h in hypsometry]
        result["hypsometry_length"] = len(hypsometry)
        result["elevation_min_m"] = float(min(hypsometry))
        result["elevation_max_m"] = float(max(hypsometry))
        if elevation_mean is None:
            result["elevation_mean_m"] = float(np.mean(hypsometry))

    # --- Validate outputs ---
    warnings = validate_outputs(result)
    for w in warnings:
        print(f"[catchment_params] WARNING: {w}")

    # --- Write output ---
    if output_json:
        with open(output_json, "w") as f:
            json.dump(result, f, indent=2)
        print(f"[catchment_params] Wrote parameters to {output_json}")

    return result


# ---------------------------------------------------------------------------
# HWSD soil properties (informational)
# ---------------------------------------------------------------------------

def extract_hwsd_properties(lat: float, lon: float,
                              hwsd_path: str = None) -> dict:
    """
    Extract HWSD soil properties for the catchment location.

    Note: GR4J does not use explicit soil parameters — these are informational
    only and may help interpret calibrated parameter values (e.g., X1 correlates
    with soil water holding capacity).

    Parameters
    ----------
    lat, lon : catchment centroid [degrees]
    hwsd_path : path to HWSD dataset

    Returns
    -------
    soil : dict with soil properties
    """
    # Placeholder: in production, read from HWSD NetCDF/shapefile
    soil = {
        "source": "HWSD v1.2",
        "latitude": lat,
        "longitude": lon,
        "properties": {
            "soil_class": "unknown",
            "clay_fraction": None,
            "sand_fraction": None,
            "organic_carbon": None,
            "bulk_density": None,
            "awc_mm": None,
        },
        "notes": (
            "GR4J does not use soil parameters directly. "
            "X1 (production store capacity) loosely correlates with available water capacity. "
            "X3 (routing store capacity) relates to aquifer storage."
        ),
    }
    return soil


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Build GR4J catchment parameter file"
    )
    parser.add_argument("--area-km2", type=float, required=True,
                        help="Catchment area [km2]")
    parser.add_argument("--lat", type=float, required=True,
                        help="Centroid latitude [degrees]")
    parser.add_argument("--lon", type=float, required=True,
                        help="Centroid longitude [degrees]")
    parser.add_argument("--elev", type=float, help="Mean elevation [m]")
    parser.add_argument("--name", default="unknown", help="Catchment name")
    parser.add_argument("--output", required=True, help="Output JSON path")

    args = parser.parse_args()
    build_catchment_params(
        area_km2=args.area_km2,
        latitude=args.lat,
        longitude=args.lon,
        elevation_mean=args.elev,
        catchment_name=args.name,
        output_json=args.output,
    )


if __name__ == "__main__":
    main()
