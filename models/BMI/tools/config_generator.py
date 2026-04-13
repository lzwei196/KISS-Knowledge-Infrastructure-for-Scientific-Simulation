#!/usr/bin/env python3
"""BMI Configuration File Generator.

Generates YAML configuration files for BMI-wrapped models.
Supports the standard heat-diffusion example and custom model templates.

Pipeline stage: S1 — Configuration Setup
Pattern: validate_inputs → generate_config → validate_outputs
"""

import os
import sys
import yaml
import logging
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default templates for known BMI example models
# ---------------------------------------------------------------------------

HEAT_MODEL_DEFAULTS = {
    "grid": {
        "shape": [10, 20],       # [ny, nx] — ij-order as BMI requires
        "spacing": [1.0, 1.0],   # [dy, dx] in model units
        "origin": [0.0, 0.0],    # [y0, x0] lower-left corner
    },
    "time": {
        "start": 0.0,
        "end": 100.0,
        "dt": 0.25,              # time step in seconds
    },
    "initial_conditions": {
        "temperature": 0.0,      # uniform initial temperature (K or degC)
    },
    "boundary_conditions": {
        "top": 0.0,
        "bottom": 0.0,
        "left": 0.0,
        "right": 0.0,
    },
    "alpha": 1.0,                # thermal diffusivity (m^2/s)
}

CUSTOM_MODEL_TEMPLATE = {
    "grid": {
        "shape": [50, 50],
        "spacing": [1.0, 1.0],
        "origin": [0.0, 0.0],
    },
    "time": {
        "start": 0.0,
        "end": 3600.0,
        "dt": 1.0,
    },
}


def validate_inputs(
    model_type: str,
    output_path: str,
    overrides: dict | None = None,
) -> dict:
    """Validate inputs before generating config.

    Parameters
    ----------
    model_type : str
        One of 'heat', 'custom', or any string for a generic template.
    output_path : str
        Path where the YAML config will be written.
    overrides : dict, optional
        Key-value pairs that override template defaults.

    Returns
    -------
    dict
        Validated configuration dictionary.

    Raises
    ------
    ValueError
        If model_type is unknown or parameters are out of range.
    """
    if model_type not in ("heat", "custom"):
        logger.warning(
            f"Unknown model type '{model_type}', using custom template."
        )
        model_type = "custom"

    template = (
        HEAT_MODEL_DEFAULTS.copy()
        if model_type == "heat"
        else CUSTOM_MODEL_TEMPLATE.copy()
    )

    if overrides:
        template = _deep_merge(template, overrides)

    # Validate grid shape — must be positive integers, ij-order
    shape = template.get("grid", {}).get("shape", [])
    if not shape or len(shape) < 2:
        raise ValueError(
            f"Grid shape must have at least 2 dimensions [ny, nx], got {shape}"
        )
    for dim in shape:
        if not isinstance(dim, int) or dim < 1:
            raise ValueError(f"Grid dimensions must be positive integers, got {dim}")

    # Validate time parameters
    time_cfg = template.get("time", {})
    dt = time_cfg.get("dt", 0)
    if dt <= 0:
        raise ValueError(f"Time step dt must be positive, got {dt}")
    if time_cfg.get("end", 0) <= time_cfg.get("start", 0):
        raise ValueError("End time must be greater than start time")

    # Validate spacing — must be positive
    spacing = template.get("grid", {}).get("spacing", [])
    for s in spacing:
        if s <= 0:
            raise ValueError(f"Grid spacing must be positive, got {s}")

    # UNIT TRAP: Check that spacing/origin are in ij-order [dy, dx]
    logger.info(
        "Grid convention: BMI uses ij-order. "
        f"shape=[ny={shape[0]}, nx={shape[1]}], "
        f"spacing=[dy={spacing[0]}, dx={spacing[1]}]"
    )

    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.isdir(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    return template


def generate_config(config: dict, output_path: str) -> str:
    """Generate a YAML configuration file.

    Parameters
    ----------
    config : dict
        Validated configuration dictionary.
    output_path : str
        File path for the output YAML.

    Returns
    -------
    str
        Absolute path to the generated config file.
    """
    with open(output_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    logger.info(f"Configuration written to {output_path}")
    return os.path.abspath(output_path)


def validate_outputs(output_path: str) -> bool:
    """Verify the generated config file is valid YAML and contains required keys.

    Parameters
    ----------
    output_path : str
        Path to the generated YAML config file.

    Returns
    -------
    bool
        True if validation passes.

    Raises
    ------
    FileNotFoundError
        If the config file does not exist.
    ValueError
        If required sections are missing.
    """
    if not os.path.isfile(output_path):
        raise FileNotFoundError(f"Config file not found: {output_path}")

    with open(output_path) as f:
        config = yaml.safe_load(f)

    if config is None:
        raise ValueError("Config file is empty")

    required_sections = ["grid", "time"]
    missing = [s for s in required_sections if s not in config]
    if missing:
        raise ValueError(f"Missing required config sections: {missing}")

    logger.info(f"Config validation passed: {output_path}")
    return True


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override dict into base dict."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def main():
    """CLI entry point for config generation."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate BMI configuration file"
    )
    parser.add_argument(
        "--model-type",
        choices=["heat", "custom"],
        default="heat",
        help="Model template to use (default: heat)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="bmi_config.yaml",
        help="Output YAML file path (default: bmi_config.yaml)",
    )
    parser.add_argument(
        "--nx", type=int, default=None, help="Number of columns"
    )
    parser.add_argument(
        "--ny", type=int, default=None, help="Number of rows"
    )
    parser.add_argument(
        "--dt", type=float, default=None, help="Time step"
    )
    parser.add_argument(
        "--end-time", type=float, default=None, help="End time"
    )

    args = parser.parse_args()

    overrides: dict[str, Any] = {}
    if args.nx or args.ny:
        grid_shape = HEAT_MODEL_DEFAULTS["grid"]["shape"].copy()
        if args.ny:
            grid_shape[0] = args.ny
        if args.nx:
            grid_shape[1] = args.nx
        overrides.setdefault("grid", {})["shape"] = grid_shape
    if args.dt:
        overrides.setdefault("time", {})["dt"] = args.dt
    if args.end_time:
        overrides.setdefault("time", {})["end"] = args.end_time

    # validate → process → validate
    config = validate_inputs(args.model_type, args.output, overrides)
    output_path = generate_config(config, args.output)
    validate_outputs(output_path)

    print(f"Config generated: {output_path}")


if __name__ == "__main__":
    main()
