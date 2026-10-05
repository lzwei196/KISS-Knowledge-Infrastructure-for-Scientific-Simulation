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
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ESMF engine lookup. The engine is NOT in the HydroCraft python_env that SKILL.md uses to
# start this tool; on this server it is the conda env obs4mips (same defaults and env vars as
# preflight_check.py). An explicit value (CLI option or env var) is used as given: if it does
# not work, the run fails; it never falls back to another engine.
#   ESMF_RegridWeightGen: --regridweightgen -> $ESMF_REGRIDWEIGHTGEN -> server default
#                         -> first one on PATH -> none at all: ESMPy route (as before)
#   ESMPy python:         --esmf-python -> $ESMF_PYTHON -> server default
#                         -> this python (only if it imports esmpy / ESMF)
# The ESMPy route re-launches this tool with the ESMPy python when another python runs it.
# ---------------------------------------------------------------------------
ESMF_ENV_DEFAULT = "KISSPATH_HOME/miniconda3/envs/obs4mips"
REGRIDWEIGHTGEN_DEFAULT = os.path.join(ESMF_ENV_DEFAULT, "bin", "ESMF_RegridWeightGen")
ESMF_PYTHON_DEFAULT = os.path.join(ESMF_ENV_DEFAULT, "bin", "python")
_REEXEC_GUARD = "KI_ESMF_REEXEC"


class EngineError(RuntimeError):
    """The selected ESMF engine is missing or unusable."""


def _import_esmpy():
    """Import ESMPy under its current name, else the legacy name ESMF."""
    try:
        import esmpy
    except ImportError:
        import ESMF as esmpy
    return esmpy


def _is_executable(path):
    return bool(path) and os.path.isfile(path) and os.access(path, os.X_OK)


def resolve_regridweightgen(cli_value=None):
    """Return (path, source) of ESMF_RegridWeightGen, or (None, reason) if there is none."""
    if cli_value is not None:
        path, source = cli_value, "--regridweightgen"
    elif os.environ.get("ESMF_REGRIDWEIGHTGEN") is not None:
        path, source = os.environ["ESMF_REGRIDWEIGHTGEN"], "$ESMF_REGRIDWEIGHTGEN"
    elif os.path.isfile(REGRIDWEIGHTGEN_DEFAULT):
        path, source = REGRIDWEIGHTGEN_DEFAULT, "server default"
    else:
        path = shutil.which("ESMF_RegridWeightGen")
        if not path:
            return None, ("no --regridweightgen / $ESMF_REGRIDWEIGHTGEN, no server default "
                          f"{REGRIDWEIGHTGEN_DEFAULT}, none on PATH")
        source = "PATH"
    if not _is_executable(path):
        raise EngineError(f"ESMF_RegridWeightGen not found or not executable: {path!r} ({source})")
    # run exactly the file that was checked (a bare name would otherwise be searched on PATH)
    return os.path.abspath(path), source


def resolve_esmf_python(cli_value=None):
    """Return (python, source) of the interpreter that has ESMPy."""
    if cli_value is not None:
        return cli_value, "--esmf-python"
    if os.environ.get("ESMF_PYTHON") is not None:
        return os.environ["ESMF_PYTHON"], "$ESMF_PYTHON"
    if os.path.isfile(ESMF_PYTHON_DEFAULT):
        return ESMF_PYTHON_DEFAULT, "server default"
    try:
        _import_esmpy()
    except ImportError:
        raise EngineError(
            f"no python with ESMPy: --esmf-python and $ESMF_PYTHON not set, server default "
            f"{ESMF_PYTHON_DEFAULT} not found, and {sys.executable} cannot import esmpy/ESMF")
    return sys.executable, "running python (imports esmpy)"


def ensure_esmf_python(cli_value=None):
    """Make sure the ESMPy python runs this tool; re-launch with it (same arguments) if not."""
    python, source = resolve_esmf_python(cli_value)
    if os.path.abspath(python) == os.path.abspath(sys.executable):
        try:
            _import_esmpy()
        except ImportError as e:
            raise EngineError(f"{python} ({source}) cannot import esmpy/ESMF: {e}")
        return os.path.abspath(python), source
    if os.environ.get(_REEXEC_GUARD):
        raise EngineError(f"re-launch loop: running {sys.executable}, expected {python} ({source})")
    if not _is_executable(python):
        raise EngineError(f"ESMPy python not found or not executable: {python!r} ({source})")
    python = os.path.abspath(python)  # not realpath: a venv python must keep its own path
    logger.info("re-launching with ESMPy python %s (%s)", python, source)
    sys.stdout.flush()
    sys.stderr.flush()
    env = dict(os.environ, **{_REEXEC_GUARD: "1"})
    try:
        os.execve(python, [python, os.path.abspath(__file__)] + sys.argv[1:], env)
    except OSError as e:
        raise EngineError(f"could not start ESMPy python {python} ({source}): {e}")


def check_engine(use_esmpy, regridweightgen=None, esmf_python=None):
    """--check-engine: resolve and probe the engine exactly as a real run would."""
    if not use_esmpy:
        tool, source = resolve_regridweightgen(regridweightgen)
        if tool:
            try:
                with tempfile.TemporaryDirectory() as tmp:  # --version writes PET*.Log to cwd
                    proc = subprocess.run([tool, "--version"], capture_output=True, text=True,
                                          timeout=180, cwd=tmp)
            except (OSError, subprocess.TimeoutExpired) as e:
                raise EngineError(f"{tool} --version did not run ({source}): {e}")
            out = proc.stdout + proc.stderr
            version = next((l.split(":", 1)[1].strip() for l in out.splitlines()
                            if l.strip().startswith("ESMF_VERSION_STRING:")), "")
            if proc.returncode != 0 or not version:
                raise EngineError(f"{tool} --version failed (rc={proc.returncode}, {source}): "
                                  f"{out.strip()[-300:]}")
            return {"ok": True, "route": "ESMF_RegridWeightGen", "path": tool,
                    "source": source, "version": version}
        logger.warning("ESMF_RegridWeightGen: %s; checking the ESMPy route", source)
    python, source = ensure_esmf_python(esmf_python)
    try:
        esmpy = _import_esmpy()
    except ImportError as e:
        raise EngineError(f"{python} ({source}) cannot import esmpy/ESMF: {e}")
    return {"ok": True, "route": "esmpy", "python": python, "source": source,
            "version": getattr(esmpy, "__version__", "?")}

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
                        method: str, extra_args: list = None,
                        regridweightgen: str = None, esmf_python: str = None) -> dict:
    """Run ESMF_RegridWeightGen command-line tool.

    TRAP: --ignore_unmapped is almost always needed. Without it,
    any destination cell without a source cell causes a fatal error.

    TRAP: --src_missingvalue <var> excludes masked source cells, but ESMF accepts it only
    for UGRID/GRIDSPEC source files and only with a variable name, so it is NOT added
    automatically (it made every SCRIP conservative run fail). Pass it when needed:
    --extra-args "--src_missingvalue <var>".
    """
    tool, tool_source = resolve_regridweightgen(regridweightgen)
    if not tool:
        logger.warning("ESMF_RegridWeightGen: %s. Trying ESMPy fallback.", tool_source)
        ensure_esmf_python(esmf_python)
        return _run_esmpy_regrid(source, destination, weight_file, method)
    logger.info("ESMF_RegridWeightGen: %s (%s)", tool, tool_source)

    cmd = [
        tool,
        "--source", source,
        "--destination", destination,
        "--weight", weight_file,
        "--method", method,
        "--ignore_unmapped",
    ]

    if extra_args:
        # each value may hold several ESMF tokens ("--src_missingvalue var"): split like a shell
        for arg in extra_args:
            cmd.extend(shlex.split(arg))

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
        esmpy = _import_esmpy()
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
        # conservative methods need the cell corners (ESMPy default: no corner stagger)
        corners = REGRID_METHODS[method]["requires_corners"]
        srcgrid = esmpy.Grid(filename=source, filetype=esmpy.FileFormat.SCRIP,
                             add_corner_stagger=corners)
        dstgrid = esmpy.Grid(filename=destination, filetype=esmpy.FileFormat.SCRIP,
                             add_corner_stagger=corners)

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
    parser.add_argument("--source", "-s", help="Source grid file (required)")
    parser.add_argument("--destination", "-d", help="Destination grid file (required)")
    parser.add_argument("--weight", "-w", help="Output weight file (required)")
    parser.add_argument("--method", "-m", default="bilinear",
                        choices=list(REGRID_METHODS.keys()),
                        help="Regridding method")
    parser.add_argument("--use-esmpy", action="store_true",
                        help="Use ESMPy instead of ESMF_RegridWeightGen")
    parser.add_argument("--extra-args", nargs="*", default=[],
                        help="Extra arguments for ESMF_RegridWeightGen; give options as one quoted "
                             "value, e.g. --extra-args \"--src_missingvalue var\" (split like a "
                             "shell), or --extra-args=--netcdf4")
    parser.add_argument("--regridweightgen", default=None,
                        help="ESMF_RegridWeightGen to use (default: $ESMF_REGRIDWEIGHTGEN, else "
                             f"the server default {REGRIDWEIGHTGEN_DEFAULT}, else the first on "
                             "PATH, else the ESMPy route)")
    parser.add_argument("--esmf-python", default=None,
                        help="Python with ESMPy for the ESMPy route (default: $ESMF_PYTHON, else "
                             f"the server default {ESMF_PYTHON_DEFAULT}, else this python if it "
                             "imports esmpy); the tool re-launches itself with it")
    parser.add_argument("--check-engine", action="store_true",
                        help="Only resolve and test the engine this run would use "
                             "(with --use-esmpy: the ESMPy route); print one JSON line")
    args = parser.parse_args()

    if args.check_engine:
        try:
            info = check_engine(args.use_esmpy, args.regridweightgen, args.esmf_python)
        except EngineError as e:
            print(json.dumps({"ok": False, "error": str(e)}))
            sys.exit(1)
        print(json.dumps(info))
        return

    missing = [f"--{n}" for n in ("source", "destination", "weight") if not getattr(args, n)]
    if missing:
        parser.error("the following arguments are required: " + ", ".join(missing))

    os.makedirs(os.path.dirname(args.weight) or ".", exist_ok=True)

    try:
        if args.use_esmpy:
            ensure_esmf_python(args.esmf_python)

        # Validate
        validate_input(args.source, args.destination, args.method)

        # Process
        if args.use_esmpy:
            result = _run_esmpy_regrid(args.source, args.destination, args.weight, args.method)
        else:
            result = run_regridweightgen(args.source, args.destination, args.weight,
                                          args.method, args.extra_args,
                                          args.regridweightgen, args.esmf_python)
    except EngineError as e:
        logger.error("%s", e)
        print(json.dumps({"tool": "none", "returncode": -1, "error": str(e)}, indent=2))
        sys.exit(1)

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
