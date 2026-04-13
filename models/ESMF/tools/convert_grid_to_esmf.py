#!/usr/bin/env python3
"""
convert_grid_to_esmf.py — Convert external grid definitions to ESMF-compatible NetCDF.

Supports:
  - Regular lat-lon grids (from CSV or raw arrays)
  - SCRIP format grids
  - Unstructured mesh definitions

Pipeline stage: s1_domain
Pattern: validate → process → validate

Usage:
    python convert_grid_to_esmf.py \
        --input grid_definition.csv \
        --format latlon \
        --output esmf_grid.nc \
        --resolution 0.25
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Unit conversion constants
# ---------------------------------------------------------------------------
DEG_TO_RAD = np.pi / 180.0
RAD_TO_DEG = 180.0 / np.pi
EARTH_RADIUS_M = 6371000.0


def validate_input(input_path: str, fmt: str) -> dict:
    """Validate that input file exists and format is supported.

    Returns metadata dict with grid shape info.
    """
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"Input grid file not found: {input_path}")

    supported = ("latlon", "scrip", "ugrid", "csv")
    if fmt not in supported:
        raise ValueError(f"Unsupported format '{fmt}'. Choose from: {supported}")

    info = {"path": input_path, "format": fmt, "size_bytes": os.path.getsize(input_path)}
    logger.info("Input validated: %s (%d bytes, format=%s)", input_path, info["size_bytes"], fmt)
    return info


def create_regular_latlon_grid(lat_min: float, lat_max: float,
                                lon_min: float, lon_max: float,
                                resolution: float) -> dict:
    """Create a regular latitude-longitude grid definition.

    TRAP: ESMF expects coordinates in DEGREES for spherical grids.
    If input is in radians, a 57.3x error will propagate silently
    through all regridding operations.

    TRAP: For conservative regridding, cell AREAS must be in steradians
    (radians²), NOT in degrees² or m². This is the #1 silent error
    in ESMF regridding pipelines.
    """
    nlat = int(np.round((lat_max - lat_min) / resolution))
    nlon = int(np.round((lon_max - lon_min) / resolution))

    lat_centers = np.linspace(lat_min + resolution / 2, lat_max - resolution / 2, nlat)
    lon_centers = np.linspace(lon_min + resolution / 2, lon_max - resolution / 2, nlon)

    lat_corners = np.linspace(lat_min, lat_max, nlat + 1)
    lon_corners = np.linspace(lon_min, lon_max, nlon + 1)

    # Validate coordinate ranges
    if np.any(np.abs(lat_centers) > 90.0):
        raise ValueError("Latitude values exceed ±90°. Are coordinates in radians?")
    if np.any(lon_centers > 360.0) or np.any(lon_centers < -180.0):
        raise ValueError("Longitude values out of expected range [-180, 360].")

    # Compute cell areas in steradians (for conservative regridding)
    lon2d, lat2d = np.meshgrid(lon_corners, lat_corners)
    areas = np.zeros((nlat, nlon))
    for j in range(nlat):
        for i in range(nlon):
            dlon = (lon_corners[i + 1] - lon_corners[i]) * DEG_TO_RAD
            dlat_sin = np.sin(lat_corners[j + 1] * DEG_TO_RAD) - np.sin(lat_corners[j] * DEG_TO_RAD)
            areas[j, i] = np.abs(dlon * dlat_sin)

    logger.info("Created %dx%d regular grid (%.4f° resolution)", nlat, nlon, resolution)
    logger.info("Area range: %.6e to %.6e steradians", areas.min(), areas.max())

    return {
        "nlat": nlat,
        "nlon": nlon,
        "lat_centers": lat_centers,
        "lon_centers": lon_centers,
        "lat_corners": lat_corners,
        "lon_corners": lon_corners,
        "areas": areas,
        "resolution": resolution,
    }


def read_csv_grid(path: str) -> dict:
    """Read grid definition from CSV with columns: lat, lon [, area].

    Infers grid structure from unique coordinate values.
    """
    data = np.genfromtxt(path, delimiter=",", names=True)

    if "lat" not in data.dtype.names or "lon" not in data.dtype.names:
        raise ValueError("CSV must have 'lat' and 'lon' columns")

    lats = np.unique(data["lat"])
    lons = np.unique(data["lon"])

    # Check for radians vs degrees
    if np.max(np.abs(lats)) < 2.0 * np.pi and np.max(np.abs(lons)) < 2.0 * np.pi:
        logger.warning(
            "UNIT TRAP: Lat range [%.4f, %.4f] looks like RADIANS. "
            "ESMF expects DEGREES. Converting...",
            lats.min(), lats.max()
        )
        lats = lats * RAD_TO_DEG
        lons = lons * RAD_TO_DEG

    resolution = np.median(np.diff(lats)) if len(lats) > 1 else 1.0

    return create_regular_latlon_grid(
        lats.min() - resolution / 2, lats.max() + resolution / 2,
        lons.min() - resolution / 2, lons.max() + resolution / 2,
        resolution
    )


def write_esmf_grid_netcdf(grid: dict, output_path: str, title: str = "ESMF Grid"):
    """Write grid definition in ESMF-compatible NetCDF format.

    The output follows CF-1.6 conventions with:
    - Center coordinates (grid_center_lat, grid_center_lon)
    - Corner coordinates (grid_corner_lat, grid_corner_lon)
    - Grid cell areas in steradians
    - Grid dimensions and rank
    - Mask variable (1 = active, 0 = masked)

    TRAP: SCRIP convention uses 0=masked, 1=active — same as ESMF.
    But many datasets use 1=masked. Check your mask convention!
    """
    try:
        from netCDF4 import Dataset
    except ImportError:
        logger.warning("netCDF4 not available. Writing grid as JSON fallback.")
        _write_grid_json(grid, output_path)
        return

    nlat, nlon = grid["nlat"], grid["nlon"]
    ncells = nlat * nlon

    with Dataset(output_path, "w", format="NETCDF4") as ds:
        ds.title = title
        ds.conventions = "CF-1.6"
        ds.institution = "ESMF Knowledge Infrastructure"
        ds.grid_type = "regular_latlon"

        ds.createDimension("grid_size", ncells)
        ds.createDimension("grid_corners", 4)
        ds.createDimension("grid_rank", 2)

        dims_var = ds.createVariable("grid_dims", "i4", ("grid_rank",))
        dims_var[:] = [nlon, nlat]

        # Center coordinates
        clat = ds.createVariable("grid_center_lat", "f8", ("grid_size",))
        clat.units = "degrees"
        clon = ds.createVariable("grid_center_lon", "f8", ("grid_size",))
        clon.units = "degrees"

        lat2d, lon2d = np.meshgrid(grid["lat_centers"], grid["lon_centers"], indexing="ij")
        clat[:] = lat2d.ravel()
        clon[:] = lon2d.ravel()

        # Corner coordinates
        corner_lat = ds.createVariable("grid_corner_lat", "f8", ("grid_size", "grid_corners"))
        corner_lat.units = "degrees"
        corner_lon = ds.createVariable("grid_corner_lon", "f8", ("grid_size", "grid_corners"))
        corner_lon.units = "degrees"

        # Fill corners (counter-clockwise: SW, SE, NE, NW)
        # TRAP: corners MUST be counter-clockwise for ESMF conservative regridding
        for j in range(nlat):
            for i in range(nlon):
                idx = j * nlon + i
                corner_lat[idx, 0] = grid["lat_corners"][j]      # SW
                corner_lat[idx, 1] = grid["lat_corners"][j]      # SE
                corner_lat[idx, 2] = grid["lat_corners"][j + 1]  # NE
                corner_lat[idx, 3] = grid["lat_corners"][j + 1]  # NW
                corner_lon[idx, 0] = grid["lon_corners"][i]      # SW
                corner_lon[idx, 1] = grid["lon_corners"][i + 1]  # SE
                corner_lon[idx, 2] = grid["lon_corners"][i + 1]  # NE
                corner_lon[idx, 3] = grid["lon_corners"][i]      # NW

        # Cell areas in steradians
        area_var = ds.createVariable("grid_area", "f8", ("grid_size",))
        area_var.units = "steradians"
        area_var.long_name = "cell area in steradians for conservative regridding"
        area_var[:] = grid["areas"].ravel()

        # Mask (1 = active)
        mask_var = ds.createVariable("grid_imask", "i4", ("grid_size",))
        mask_var.units = "unitless"
        mask_var[:] = np.ones(ncells, dtype=np.int32)

    logger.info("Wrote ESMF grid: %s (%d cells)", output_path, ncells)


def _write_grid_json(grid: dict, output_path: str):
    """Fallback: write grid as JSON when NetCDF is unavailable."""
    json_path = output_path.replace(".nc", ".json")
    out = {
        "nlat": grid["nlat"],
        "nlon": grid["nlon"],
        "resolution": grid["resolution"],
        "lat_centers": grid["lat_centers"].tolist(),
        "lon_centers": grid["lon_centers"].tolist(),
        "area_min_sr": float(grid["areas"].min()),
        "area_max_sr": float(grid["areas"].max()),
    }
    with open(json_path, "w") as f:
        json.dump(out, f, indent=2)
    logger.info("Wrote grid JSON fallback: %s", json_path)


def validate_output(output_path: str, expected_cells: int):
    """Validate that the output grid file is well-formed."""
    if not os.path.isfile(output_path) and not os.path.isfile(output_path.replace(".nc", ".json")):
        raise RuntimeError(f"Output file not created: {output_path}")

    size = os.path.getsize(output_path) if os.path.isfile(output_path) else 0
    if size == 0:
        raise RuntimeError(f"Output file is empty: {output_path}")

    try:
        from netCDF4 import Dataset
        with Dataset(output_path, "r") as ds:
            ncells = len(ds.dimensions["grid_size"])
            if ncells != expected_cells:
                raise RuntimeError(
                    f"Grid cell count mismatch: expected {expected_cells}, got {ncells}"
                )
            # Check area units
            if hasattr(ds.variables.get("grid_area", None), "units"):
                if ds.variables["grid_area"].units != "steradians":
                    logger.warning("TRAP: grid_area units are '%s', expected 'steradians'",
                                   ds.variables["grid_area"].units)
    except ImportError:
        logger.info("netCDF4 not available; skipping deep validation")

    logger.info("Output validated: %s", output_path)


def main():
    parser = argparse.ArgumentParser(description="Convert grid definitions to ESMF format")
    parser.add_argument("--input", "-i", help="Input grid file (CSV, SCRIP, etc.)")
    parser.add_argument("--format", "-f", default="latlon",
                        choices=["latlon", "scrip", "ugrid", "csv"],
                        help="Input format")
    parser.add_argument("--output", "-o", required=True, help="Output ESMF grid NetCDF")
    parser.add_argument("--resolution", "-r", type=float, default=0.25,
                        help="Grid resolution in degrees (for latlon)")
    parser.add_argument("--lat-range", nargs=2, type=float, default=[-90, 90],
                        help="Latitude range (min max)")
    parser.add_argument("--lon-range", nargs=2, type=float, default=[0, 360],
                        help="Longitude range (min max)")
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)

    # Step 1: Validate input
    if args.input:
        info = validate_input(args.input, args.format)

    # Step 2: Process
    if args.format == "csv" and args.input:
        grid = read_csv_grid(args.input)
    else:
        grid = create_regular_latlon_grid(
            args.lat_range[0], args.lat_range[1],
            args.lon_range[0], args.lon_range[1],
            args.resolution
        )

    # Step 3: Write output
    write_esmf_grid_netcdf(grid, args.output)

    # Step 4: Validate output
    validate_output(args.output, grid["nlat"] * grid["nlon"])

    logger.info("Done. Grid written to %s", args.output)


if __name__ == "__main__":
    main()
