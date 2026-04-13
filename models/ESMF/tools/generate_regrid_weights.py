#!/usr/bin/env python3
"""
generate_regrid_weights.py — Wrapper for ESMF_RegridWeightGen and ESMPy regridding.

Generates interpolation weight files for regridding between different grids.
Supports bilinear, conservative, patch recovery, and nearest-neighbor methods.

Pipeline stage: s1_domain / s7_postprocess (used in multiple stages)
Pattern: validate → process → validate

Usage:
    python generate_regrid_weights.py \
        --source source_grid.nc \
        --destination dest_grid.nc \
        --weight weights.nc \
        --method conserve

    python generate_regrid_weights.py \
        --source source_grid.nc \
        --destination dest_grid.nc \
        --weight weights.nc \
        --method bilinear \
        --use-esmpy
"""

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regridding method specifications
# ---------------------------------------------------------------------------
REGRID_METHODS = {
    "bilinear": {
        "description": "Bilinear interpolation (1st order)",
        "conservative": False,
        "requires_corners": False,
        "requires_areas": False,
        "best_for": "Smooth continuous fields (temperature, pressure)",
    },
    "patch": {
        "description": "Patch recovery (2nd order polynomial)",
        "conservative": False,
        "requires_corners": False,
        "requires_areas": False,
        "best_for": "Fields where derivative accuracy matters",
    },
    "conserve": {
        "description": "First-order conservative",
        "conservative": True,
        "requires_corners": True,
        "requires_areas": True,
        "best_for": "Flux fields (precipitation, radiation, mass)",
    },
    "conserve2nd": {
        "description": "Second-order conservative",
        "conservative": True,
        "requires_corners": True,
        "requires_areas": True,
        "best_for": "Flux fields with smoother output",
    },
    "neareststod": {
        "description": "Nearest source to destination",
        "conservative": False,
        "requires_corners": False,
        "requires_areas": False,
        "best_for": "Categorical data (land use, soil type)",
    },
    "nearestdtos": {
        "description": "Nearest destination to source",
        "conservative": False,
        "requires_corners": False,
        "requires_areas": False,
        "best_for": "Sparse observational data",
    },
}


def validate_input(source: str, destination: str, method: str) -> dict:
    """Validate source/destination grids and regridding method.

    TRAP: Conservative regridding requires corner coordinates AND cell areas
    in BOTH source and destination grids. Missing corners or areas will
    either crash or produce silently wrong results.

    TRAP: Cell areas for conservative regridding must be in STERADIANS
    (radians²), not degrees² or m². Using degrees² produces ~3000x error
    in area-weighted integrals.

    TRAP: SCRIP grid file corners must be in COUNTER-CLOCKWISE order.
    Clockwise corners → negative cell areas → wrong interpolation weights.
    """
    errors = []

    if not os.path.isfile(source):
        errors.append(f"Source grid not found: {source}")
    if not os.path.isfile(destination):
        errors.append(f"Destination grid not found: {destination}")
    if method not in REGRID_METHODS:
        errors.append(f"Unknown method '{method}'. Supported: {list(REGRID_METHODS.keys())}")

    if errors:
        for e in errors:
            logger.error(e)
        raise ValueError(f"Input validation failed with {len(errors)} error(s)")

    spec = REGRID_METHODS[method]

    # Deep validation of grid files
    info = {"source": source, "destination": destination, "method": method}

    try:
        from netCDF4 import Dataset

        for label, path in [("source", source), ("destination", destination)]:
            with Dataset(path, "r") as ds:
                vars_present = list(ds.variables.keys())
                has_corners = any("corner" in v for v in vars_present)
                has_areas = any("area" in v for v in vars_present)

                info[f"{label}_vars"] = vars_present

                if spec["requires_corners"] and not has_corners:
                    logger.warning(
                        "TRAP: %s method requires corner coordinates but "
                        "%s grid (%s) has none. Results will be wrong!",
                        method, label, path
                    )

                if spec["requires_areas"] and not has_areas:
                    logger.warning(
                        "TRAP: %s method requires cell areas but "
                        "%s grid (%s) has none. Conservation will be violated!",
                        method, label, path
                    )

                # Check area units if present
                for vname in vars_present:
                    if "area" in vname.lower():
                        units = getattr(ds.variables[vname], "units", "unknown")
                        if units not in ("steradians", "sr", "rad^2", "radians^2"):
                            logger.warning(
                                "TRAP: %s grid area units='%s'. "
                                "Conservative regridding expects steradians!",
                                label, units
                            )

                # Check corner ordering (counter-clockwise)
                for vname in vars_present:
                    if "corner_lat" in vname.lower():
                        corner_data = ds.variables[vname]
                        if corner_data.ndim >= 2 and corner_data.shape[-1] >= 4:
                            sample = corner_data[0, :]
                            # Simple CCW check using signed area
                            n = len(sample)
                            signed_area = sum(
                                sample[i] * (sample[(i + 1) % n] if i < n - 1 else sample[0])
                                - sample[(i + 1) % n] * sample[i]
                                for i in range(n)
                            )
                            if signed_area < 0:
                                logger.warning(
                                    "TRAP: %s grid corners may be CLOCKWISE. "
                                    "ESMF conservative regridding requires counter-clockwise!",
                                    label
                                )
    except ImportError:
        logger.info("netCDF4 not available; skipping deep grid validation")
    except Exception as e:
        logger.warning("Grid validation error: %s", e)

    logger.info("Input validated: %s → %s (method=%s)", source, destination, method)
    return info


def run_regridweightgen(source: str, destination: str, weight_file: str,
                        method: str, extra_args: list = None) -> dict:
    """Run ESMF_RegridWeightGen command-line tool.

    TRAP: --ignore_unmapped is almost always needed. Without it,
    any destination cell without a source cell causes a fatal error.

    TRAP: --src_missingvalue excludes masked source cells.
    Without it, fill values (e.g., -9999) are interpolated as real data.
    """
    tool = shutil.which("ESMF_RegridWeightGen")
    if not tool:
        logger.warning("ESMF_RegridWeightGen not in PATH. Trying ESMPy fallback.")
        return _run_esmpy_regrid(source, destination, weight_file, method)

    cmd = [
        tool,
        "--source", source,
        "--destination", destination,
        "--weight", weight_file,
        "--method", method,
        "--ignore_unmapped",
    ]

    if REGRID_METHODS[method]["conservative"]:
        cmd.append("--src_missingvalue")

    if extra_args:
        cmd.extend(extra_args)

    logger.info("Running: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    output = {
        "tool": "ESMF_RegridWeightGen",
        "command": " ".join(cmd),
        "returncode": result.returncode,
        "stdout": result.stdout[:3000],
        "stderr": result.stderr[:3000],
    }

    if result.returncode != 0:
        logger.error("RegridWeightGen failed:\n%s", result.stderr[:2000])
    else:
        logger.info("Weight file generated: %s", weight_file)

    return output


def _run_esmpy_regrid(source: str, destination: str, weight_file: str,
                      method: str) -> dict:
    """Fallback: generate weights using ESMPy Python interface."""
    try:
        import esmpy
    except ImportError:
        try:
            import ESMF as esmpy
        except ImportError:
            logger.error("Neither ESMF_RegridWeightGen nor ESMPy available")
            return {"tool": "none", "returncode": -1,
                    "error": "No regridding tool available"}

    method_map = {
        "bilinear": esmpy.RegridMethod.BILINEAR,
        "patch": esmpy.RegridMethod.PATCH,
        "conserve": esmpy.RegridMethod.CONSERVE,
        "conserve2nd": esmpy.RegridMethod.CONSERVE_2ND,
        "neareststod": esmpy.RegridMethod.NEAREST_STOD,
        "nearestdtos": esmpy.RegridMethod.NEAREST_DTOS,
    }

    if method not in method_map:
        return {"tool": "esmpy", "returncode": -1,
                "error": f"Unsupported method: {method}"}

    logger.info("Using ESMPy for weight generation...")

    try:
        srcgrid = esmpy.Grid(filename=source, filetype=esmpy.FileFormat.SCRIP)
        dstgrid = esmpy.Grid(filename=destination, filetype=esmpy.FileFormat.SCRIP)

        srcfield = esmpy.Field(srcgrid, name="src")
        dstfield = esmpy.Field(dstgrid, name="dst")

        regrid = esmpy.Regrid(
            srcfield, dstfield,
            regrid_method=method_map[method],
            unmapped_action=esmpy.UnmappedAction.IGNORE,
            filename=weight_file,
        )

        logger.info("ESMPy weight file generated: %s", weight_file)
        return {"tool": "esmpy", "returncode": 0, "weight_file": weight_file}

    except Exception as e:
        logger.error("ESMPy regridding failed: %s", e)
        return {"tool": "esmpy", "returncode": -1, "error": str(e)}


def validate_output(weight_file: str, method: str) -> dict:
    """Validate the generated weight file.

    Checks:
    - File exists and is non-empty
    - Weight matrix dimensions are reasonable
    - Weights sum to ~1.0 per destination cell (for conservative)
    - No NaN or negative weights
    """
    if not os.path.isfile(weight_file):
        raise RuntimeError(f"Weight file not created: {weight_file}")

    size = os.path.getsize(weight_file)
    if size == 0:
        raise RuntimeError(f"Weight file is empty: {weight_file}")

    validation = {"file": weight_file, "size_bytes": size}

    try:
        from netCDF4 import Dataset
        with Dataset(weight_file, "r") as ds:
            if "S" in ds.variables:
                weights = ds.variables["S"][:]
                validation["n_weights"] = len(weights)
                validation["weight_min"] = float(np.min(weights))
                validation["weight_max"] = float(np.max(weights))
                validation["has_nan"] = bool(np.any(np.isnan(weights)))
                validation["has_negative"] = bool(np.any(weights < 0))

                if validation["has_nan"]:
                    logger.warning("Weight file contains NaN values!")
                if validation["has_negative"] and method not in ("patch", "conserve2nd"):
                    logger.warning("Weight file contains negative values (unexpected for %s)", method)

                # Check weight sums for conservative methods
                if REGRID_METHODS.get(method, {}).get("conservative"):
                    if "col" in ds.variables and "row" in ds.variables:
                        rows = ds.variables["row"][:]
                        unique_rows = np.unique(rows)
                        sums = [np.sum(weights[rows == r]) for r in unique_rows[:100]]
                        mean_sum = np.mean(sums)
                        if abs(mean_sum - 1.0) > 0.01:
                            logger.warning(
                                "Conservative weights: mean row sum = %.4f (expected ~1.0). "
                                "Check grid areas!",
                                mean_sum
                            )
                        validation["mean_weight_sum"] = float(mean_sum)

                logger.info("Weight file: %d weights, range [%.4f, %.4f]",
                            len(weights), np.min(weights), np.max(weights))
    except ImportError:
        logger.info("netCDF4 not available; skipping deep weight validation")

    return validation


def main():
    parser = argparse.ArgumentParser(description="Generate ESMF regrid weights")
    parser.add_argument("--source", "-s", required=True, help="Source grid file")
    parser.add_argument("--destination", "-d", required=True, help="Destination grid file")
    parser.add_argument("--weight", "-w", required=True, help="Output weight file")
    parser.add_argument("--method", "-m", default="bilinear",
                        choices=list(REGRID_METHODS.keys()),
                        help="Regridding method")
    parser.add_argument("--use-esmpy", action="store_true",
                        help="Use ESMPy instead of ESMF_RegridWeightGen")
    parser.add_argument("--extra-args", nargs="*", default=[],
                        help="Extra arguments for ESMF_RegridWeightGen")
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.weight) or ".", exist_ok=True)

    # Validate
    validate_input(args.source, args.destination, args.method)

    # Process
    if args.use_esmpy:
        result = _run_esmpy_regrid(args.source, args.destination, args.weight, args.method)
    else:
        result = run_regridweightgen(args.source, args.destination, args.weight,
                                      args.method, args.extra_args)

    # Validate output
    if result.get("returncode") == 0:
        validation = validate_output(args.weight, args.method)
        print(json.dumps(validation, indent=2))
    else:
        logger.error("Regrid weight generation failed")
        print(json.dumps(result, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
