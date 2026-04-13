#!/usr/bin/env python3
"""Convert satellite-derived velocity data to icepack-compatible format.

Reads MEaSUREs or other velocity rasters (GeoTIFF/NetCDF) in m/s or m/yr,
performs unit conversion, coordinate reprojection, and outputs an xarray
DataArray or rasterio-compatible file ready for icepack.interpolate().

Pipeline stage: s1 (data acquisition / forcing conversion)
Pattern: validate → process → validate
"""

import sys
import os
import argparse
import logging
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# icepack internal unit: meters per year
SECONDS_PER_YEAR = 365.25 * 24 * 3600  # 3.15576e7


def validate_inputs(vx_path: str, vy_path: str, unit: str) -> dict:
    """Validate input velocity files exist and unit is recognized.

    Parameters
    ----------
    vx_path : str
        Path to x-component velocity raster.
    vy_path : str
        Path to y-component velocity raster.
    unit : str
        Source unit: 'm/s', 'm/yr', 'm/day'.

    Returns
    -------
    dict
        Validated parameters.

    Raises
    ------
    FileNotFoundError
        If input files do not exist.
    ValueError
        If unit is not recognized.
    """
    errors = []
    if not os.path.isfile(vx_path):
        errors.append(f"vx file not found: {vx_path}")
    if not os.path.isfile(vy_path):
        errors.append(f"vy file not found: {vy_path}")
    valid_units = ("m/s", "m/yr", "m/day")
    if unit not in valid_units:
        errors.append(f"Unrecognized unit '{unit}'; must be one of {valid_units}")
    if errors:
        for e in errors:
            logger.error(e)
        raise ValueError("; ".join(errors))

    logger.info("Input validation passed: vx=%s, vy=%s, unit=%s", vx_path, vy_path, unit)
    return {"vx_path": vx_path, "vy_path": vy_path, "unit": unit}


def compute_conversion_factor(unit: str) -> float:
    """Return the multiplicative factor to convert from source unit to m/yr.

    Parameters
    ----------
    unit : str
        Source unit.

    Returns
    -------
    float
        Conversion factor.
    """
    factors = {
        "m/s": SECONDS_PER_YEAR,
        "m/yr": 1.0,
        "m/day": 365.25,
    }
    return factors[unit]


def process(vx_path: str, vy_path: str, unit: str, output_dir: str) -> dict:
    """Read velocity rasters, convert units, write output.

    Parameters
    ----------
    vx_path : str
        Path to x-component velocity raster.
    vy_path : str
        Path to y-component velocity raster.
    unit : str
        Source unit.
    output_dir : str
        Output directory.

    Returns
    -------
    dict
        Paths to output files and conversion metadata.
    """
    try:
        import rasterio
    except ImportError:
        logger.error("rasterio is required. Install with: pip install rasterio")
        raise

    factor = compute_conversion_factor(unit)
    logger.info("Conversion factor from %s to m/yr: %.6e", unit, factor)

    os.makedirs(output_dir, exist_ok=True)

    results = {}
    for component, path in [("vx", vx_path), ("vy", vy_path)]:
        with rasterio.open(path) as src:
            data = src.read(1).astype(np.float64)
            profile = src.profile.copy()
            nodata = src.nodata

        # Apply unit conversion
        if nodata is not None:
            mask = data == nodata
        else:
            mask = np.isnan(data)

        data_converted = data * factor
        data_converted[mask] = np.nan

        # Check for unrealistic values
        speed = np.abs(data_converted[~mask])
        logger.info(
            "%s: min=%.2f, max=%.2f, mean=%.2f m/yr",
            component, speed.min(), speed.max(), speed.mean()
        )

        out_path = os.path.join(output_dir, f"{component}_myr.tif")
        profile.update(dtype="float64", nodata=np.nan)
        with rasterio.open(out_path, "w", **profile) as dst:
            dst.write(data_converted, 1)

        results[component] = out_path

    results["unit"] = "m/yr"
    results["conversion_factor"] = factor
    return results


def validate_outputs(results: dict) -> bool:
    """Validate output files and check for unrealistic velocity values.

    Parameters
    ----------
    results : dict
        Output from process().

    Returns
    -------
    bool
        True if outputs are valid.
    """
    import rasterio

    ok = True
    for component in ("vx", "vy"):
        path = results[component]
        if not os.path.isfile(path):
            logger.error("Output file missing: %s", path)
            ok = False
            continue

        with rasterio.open(path) as src:
            data = src.read(1)

        valid = data[~np.isnan(data)]
        speed = np.abs(valid)

        # Antarctic ice streams rarely exceed 4000 m/yr (Pine Island max ~4 km/yr)
        if speed.max() > 15000:
            logger.warning(
                "UNIT TRAP: %s max velocity = %.1f m/yr — suspiciously high. "
                "Check if source data was already in m/yr and got double-converted.",
                component, speed.max()
            )
            ok = False

        # If max velocity < 0.01 m/yr for a glacier, likely still in m/s
        if speed.max() < 0.01 and speed.max() > 0:
            logger.warning(
                "UNIT TRAP: %s max velocity = %.6f m/yr — suspiciously low. "
                "Check if source data is in m/s and conversion was not applied.",
                component, speed.max()
            )
            ok = False

    if ok:
        logger.info("Output validation passed.")
    return ok


def main():
    parser = argparse.ArgumentParser(description="Convert velocity data to icepack format (m/yr)")
    parser.add_argument("--vx", required=True, help="Path to vx raster")
    parser.add_argument("--vy", required=True, help="Path to vy raster")
    parser.add_argument("--unit", default="m/yr", choices=["m/s", "m/yr", "m/day"],
                        help="Source velocity unit")
    parser.add_argument("--output-dir", default="./velocity_converted",
                        help="Output directory")
    args = parser.parse_args()

    params = validate_inputs(args.vx, args.vy, args.unit)
    results = process(params["vx_path"], params["vy_path"], params["unit"], args.output_dir)
    valid = validate_outputs(results)

    if not valid:
        logger.error("Output validation failed — check warnings above")
        sys.exit(1)

    logger.info("Done. Output files: %s", results)


if __name__ == "__main__":
    main()
