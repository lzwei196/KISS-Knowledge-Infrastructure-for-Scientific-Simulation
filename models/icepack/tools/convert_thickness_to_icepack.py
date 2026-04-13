#!/usr/bin/env python3
"""Convert ice thickness / bed elevation / surface data to icepack-compatible format.

Reads BedMachine or similar rasters (GeoTIFF/NetCDF), clips to a glacier domain,
validates physical consistency (surface = bed + thickness for grounded, flotation
for floating), and outputs fields ready for icepack.interpolate().

Pipeline stage: s1 (data acquisition / parameter preparation)
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

# Physical constants (SI)
RHO_ICE = 917.0    # kg/m³
RHO_WATER = 1024.0  # kg/m³


def validate_inputs(thickness_path: str, bed_path: str = None,
                    surface_path: str = None) -> dict:
    """Validate input raster files exist.

    Parameters
    ----------
    thickness_path : str
        Path to ice thickness raster (meters).
    bed_path : str, optional
        Path to bed elevation raster (meters).
    surface_path : str, optional
        Path to surface elevation raster (meters).

    Returns
    -------
    dict
        Validated paths.
    """
    errors = []
    if not os.path.isfile(thickness_path):
        errors.append(f"Thickness file not found: {thickness_path}")
    if bed_path and not os.path.isfile(bed_path):
        errors.append(f"Bed file not found: {bed_path}")
    if surface_path and not os.path.isfile(surface_path):
        errors.append(f"Surface file not found: {surface_path}")
    if errors:
        for e in errors:
            logger.error(e)
        raise FileNotFoundError("; ".join(errors))

    logger.info("Input validation passed.")
    return {
        "thickness_path": thickness_path,
        "bed_path": bed_path,
        "surface_path": surface_path,
    }


def compute_surface_from_thickness_bed(thickness: np.ndarray,
                                        bed: np.ndarray) -> np.ndarray:
    """Compute surface elevation consistent with hydrostatic balance.

    For grounded ice: s = b + h
    For floating ice: s = (1 - rho_ice/rho_water) * h

    This mirrors icepack.utilities.compute_surface().

    Parameters
    ----------
    thickness : np.ndarray
        Ice thickness in meters.
    bed : np.ndarray
        Bed elevation in meters (negative below sea level).

    Returns
    -------
    np.ndarray
        Surface elevation in meters.
    """
    grounded_surface = bed + thickness
    floating_surface = (1 - RHO_ICE / RHO_WATER) * thickness
    return np.maximum(grounded_surface, floating_surface)


def process(thickness_path: str, bed_path: str = None,
            surface_path: str = None, output_dir: str = "./geometry",
            min_thickness: float = 10.0) -> dict:
    """Read geometry rasters, validate consistency, write outputs.

    Parameters
    ----------
    thickness_path : str
        Path to thickness raster.
    bed_path : str, optional
        Path to bed elevation raster.
    surface_path : str, optional
        Path to surface elevation raster.
    output_dir : str
        Output directory.
    min_thickness : float
        Minimum ice thickness to enforce (meters). Thin ice causes solver divergence.

    Returns
    -------
    dict
        Paths to output files.
    """
    try:
        import rasterio
    except ImportError:
        logger.error("rasterio required. Install with: pip install rasterio")
        raise

    os.makedirs(output_dir, exist_ok=True)

    # Read thickness
    with rasterio.open(thickness_path) as src:
        h = src.read(1).astype(np.float64)
        profile = src.profile.copy()
        nodata_h = src.nodata

    mask = (h == nodata_h) if nodata_h is not None else np.isnan(h)
    h[mask] = np.nan

    # Enforce minimum thickness
    thin_count = np.sum((~mask) & (h < min_thickness) & (h > 0))
    if thin_count > 0:
        logger.warning(
            "Clamping %d cells with thickness < %.1f m to minimum. "
            "Zero-thickness ice causes solver divergence in icepack.",
            thin_count, min_thickness
        )
        h[(~mask) & (h < min_thickness) & (h > 0)] = min_thickness

    # Reject negative thickness
    neg_count = np.sum((~mask) & (h < 0))
    if neg_count > 0:
        logger.warning("Setting %d negative thickness cells to NaN", neg_count)
        h[(~mask) & (h < 0)] = np.nan

    logger.info("Thickness: min=%.1f, max=%.1f, mean=%.1f m",
                np.nanmin(h), np.nanmax(h), np.nanmean(h))

    results = {}

    # Write thickness
    out_h = os.path.join(output_dir, "thickness_m.tif")
    profile.update(dtype="float64", nodata=np.nan)
    with rasterio.open(out_h, "w", **profile) as dst:
        dst.write(h, 1)
    results["thickness"] = out_h

    # Read and write bed if available
    if bed_path:
        with rasterio.open(bed_path) as src:
            b = src.read(1).astype(np.float64)
            nodata_b = src.nodata
        b_mask = (b == nodata_b) if nodata_b is not None else np.isnan(b)
        b[b_mask] = np.nan

        logger.info("Bed: min=%.1f, max=%.1f m", np.nanmin(b), np.nanmax(b))

        out_b = os.path.join(output_dir, "bed_m.tif")
        with rasterio.open(out_b, "w", **profile) as dst:
            dst.write(b, 1)
        results["bed"] = out_b

        # Compute surface from thickness and bed
        s = compute_surface_from_thickness_bed(h, b)
        out_s = os.path.join(output_dir, "surface_m.tif")
        with rasterio.open(out_s, "w", **profile) as dst:
            dst.write(s, 1)
        results["surface"] = out_s

        # Determine floating fraction
        grounded = (~mask) & (~b_mask) & ((b + h) >= (1 - RHO_ICE / RHO_WATER) * h)
        floating = (~mask) & (~b_mask) & ~grounded
        total_valid = np.sum((~mask) & (~b_mask))
        if total_valid > 0:
            float_pct = 100.0 * np.sum(floating) / total_valid
            logger.info("Floating fraction: %.1f%%", float_pct)

    elif surface_path:
        with rasterio.open(surface_path) as src:
            s = src.read(1).astype(np.float64)
        out_s = os.path.join(output_dir, "surface_m.tif")
        with rasterio.open(out_s, "w", **profile) as dst:
            dst.write(s, 1)
        results["surface"] = out_s

    return results


def validate_outputs(results: dict) -> bool:
    """Validate output geometry fields for physical consistency.

    Parameters
    ----------
    results : dict
        Paths to output files.

    Returns
    -------
    bool
        True if outputs are valid.
    """
    import rasterio

    ok = True

    # Check thickness
    if "thickness" in results:
        with rasterio.open(results["thickness"]) as src:
            h = src.read(1)
        valid_h = h[~np.isnan(h)]
        if np.any(valid_h < 0):
            logger.error("Negative thickness values found — physically invalid")
            ok = False
        if np.nanmax(valid_h) > 5000:
            logger.warning(
                "Max thickness = %.0f m — unusually thick. "
                "Antarctic ice sheet max is ~4700 m.",
                np.nanmax(valid_h)
            )
        if np.nanmax(valid_h) < 1:
            logger.warning("Max thickness < 1 m — check units (should be meters)")
            ok = False

    # Check consistency: surface >= thickness × (1 - ρ_i/ρ_w)
    if "surface" in results and "thickness" in results:
        with rasterio.open(results["surface"]) as src:
            s = src.read(1)
        with rasterio.open(results["thickness"]) as src:
            h = src.read(1)
        float_level = (1 - RHO_ICE / RHO_WATER) * h
        both_valid = (~np.isnan(s)) & (~np.isnan(h))
        violations = both_valid & (s < float_level - 1.0)
        if np.any(violations):
            logger.warning(
                "%d cells where surface < flotation level — may indicate "
                "inconsistent thickness/surface data",
                np.sum(violations)
            )

    if ok:
        logger.info("Output validation passed.")
    return ok


def main():
    parser = argparse.ArgumentParser(description="Convert ice geometry to icepack format")
    parser.add_argument("--thickness", required=True, help="Path to thickness raster (m)")
    parser.add_argument("--bed", default=None, help="Path to bed elevation raster (m)")
    parser.add_argument("--surface", default=None, help="Path to surface elevation raster (m)")
    parser.add_argument("--output-dir", default="./geometry", help="Output directory")
    parser.add_argument("--min-thickness", type=float, default=10.0,
                        help="Minimum ice thickness (m)")
    args = parser.parse_args()

    params = validate_inputs(args.thickness, args.bed, args.surface)
    results = process(
        params["thickness_path"], params["bed_path"], params["surface_path"],
        args.output_dir, args.min_thickness
    )
    valid = validate_outputs(results)

    if not valid:
        logger.error("Output validation failed")
        sys.exit(1)

    logger.info("Done. Output files: %s", results)


if __name__ == "__main__":
    main()
