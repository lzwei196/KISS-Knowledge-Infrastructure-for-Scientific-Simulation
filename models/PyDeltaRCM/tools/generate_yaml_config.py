#!/usr/bin/env python3
"""
Generate YAML configuration file for pyDeltaRCM.

Converts real-world parameters (e.g., channel width in meters, SLR in mm/yr)
into the model-expected units and writes a valid YAML configuration.

Pattern: validate inputs → convert units → generate YAML → validate output
"""

import argparse
import os
import sys
import yaml


# Default parameter ranges for validation
PARAM_RANGES = {
    "Length": (100, 100000, "m"),
    "Width": (100, 200000, "m"),
    "dx": (1, 1000, "m"),
    "L0_meters": (0, 10000, "m"),
    "N0_meters": (10, 50000, "m"),
    "S0": (1e-6, 0.1, "dimensionless"),
    "u0": (0.01, 10.0, "m/s"),
    "h0": (0.1, 50.0, "m"),
    "hb": (0.1, 100.0, "m"),
    "H_SL": (-100, 100, "m"),
    "C0_percent": (0.001, 10.0, "%"),
    "f_bedload": (0.0, 1.0, "fraction"),
    "Np_water": (100, 50000, "count"),
    "Np_sed": (100, 50000, "count"),
    "itermax": (1, 20, "count"),
    "save_dt": (1, 1e9, "seconds"),
}


def validate_inputs(params: dict) -> list:
    """Validate input parameters against expected ranges.

    Parameters
    ----------
    params : dict
        Dictionary of parameter name -> value pairs.

    Returns
    -------
    list
        List of warning strings for out-of-range values.
    """
    warnings = []
    for key, value in params.items():
        if key in PARAM_RANGES and value is not None:
            lo, hi, unit = PARAM_RANGES[key]
            if isinstance(value, (int, float)):
                if value < lo or value > hi:
                    warnings.append(
                        f"WARNING: {key}={value} {unit} is outside "
                        f"expected range [{lo}, {hi}]"
                    )
    return warnings


def convert_slr_mmyr_to_ms(slr_mmyr: float, If: float = 0.05) -> float:
    """Convert sea level rise from mm/yr (real time) to m/s (model time).

    Parameters
    ----------
    slr_mmyr : float
        Sea level rise rate in mm/yr of real-world time.
    If : float
        Intermittency factor (default 0.05).

    Returns
    -------
    float
        SLR in m/s of model time.

    Examples
    --------
    >>> convert_slr_mmyr_to_ms(3.0, If=0.05)  # ~3 mm/yr real
    4.756...e-09
    """
    # mm/yr -> m/s: divide by 1000 (mm->m), by 365.25*86400 (yr->s), multiply by If
    slr_ms = slr_mmyr / 1000.0 / (365.25 * 86400) * If
    return slr_ms


def convert_subsidence_mmyr_to_ms(rate_mmyr: float, If: float = 0.05) -> float:
    """Convert subsidence rate from mm/yr to m/s of model time.

    Parameters
    ----------
    rate_mmyr : float
        Subsidence rate in mm/yr.
    If : float
        Intermittency factor.

    Returns
    -------
    float
        Subsidence rate in m/s of model time.
    """
    return rate_mmyr / 1000.0 / (365.25 * 86400) * If


def generate_config(
    out_dir: str = "deltaRCM_Output",
    Length: float = 5000.0,
    Width: float = 10000.0,
    dx: float = 50.0,
    u0: float = 1.0,
    h0: float = 5.0,
    N0_meters: float = 250.0,
    L0_meters: float = 150.0,
    S0: float = 0.00015,
    C0_percent: float = 0.1,
    f_bedload: float = 0.5,
    Np_water: int = 2000,
    Np_sed: int = 2000,
    itermax: int = 3,
    H_SL: float = 0.0,
    SLR_mmyr: float = 0.0,
    If: float = 0.05,
    toggle_subsidence: bool = False,
    subsidence_rate_mmyr: float = 0.0,
    start_subsidence_years: float = 0.0,
    save_eta_grids: bool = True,
    save_depth_grids: bool = False,
    save_velocity_grids: bool = False,
    save_sandfrac_grids: bool = False,
    save_discharge_grids: bool = False,
    save_dt_days: float = 1.0,
    seed: int = None,
    verbose: int = 0,
    hb: float = None,
) -> dict:
    """Generate a pyDeltaRCM configuration dictionary.

    Accepts parameters in user-friendly units and converts to model units.

    Parameters
    ----------
    SLR_mmyr : float
        Sea level rise in mm/yr of real-world time.
    save_dt_days : float
        Output save interval in days of model time.
    subsidence_rate_mmyr : float
        Subsidence rate in mm/yr.
    start_subsidence_years : float
        When to start subsidence, in years of model time.

    Returns
    -------
    dict
        Configuration dictionary ready for YAML serialization.
    """
    # --- Convert units ---
    SLR = convert_slr_mmyr_to_ms(SLR_mmyr, If) if SLR_mmyr != 0 else 0.0
    subsidence_rate = (
        convert_subsidence_mmyr_to_ms(subsidence_rate_mmyr, If)
        if subsidence_rate_mmyr != 0
        else 2e-9
    )
    start_subsidence = start_subsidence_years * 365.25 * 86400  # years -> seconds
    save_dt = int(save_dt_days * 86400)  # days -> seconds

    config = {
        "out_dir": out_dir,
        "verbose": verbose,
        "Length": Length,
        "Width": Width,
        "dx": dx,
        "L0_meters": L0_meters,
        "N0_meters": N0_meters,
        "S0": S0,
        "u0": u0,
        "h0": h0,
        "H_SL": H_SL,
        "SLR": SLR,
        "C0_percent": C0_percent,
        "f_bedload": f_bedload,
        "Np_water": Np_water,
        "Np_sed": Np_sed,
        "itermax": itermax,
        "toggle_subsidence": toggle_subsidence,
        "subsidence_rate": subsidence_rate,
        "start_subsidence": start_subsidence,
        "save_eta_grids": save_eta_grids,
        "save_depth_grids": save_depth_grids,
        "save_velocity_grids": save_velocity_grids,
        "save_sandfrac_grids": save_sandfrac_grids,
        "save_discharge_grids": save_discharge_grids,
        "save_dt": save_dt,
    }

    if seed is not None:
        config["seed"] = seed
    if hb is not None:
        config["hb"] = hb

    return config


def validate_config(config: dict) -> list:
    """Validate the generated configuration for internal consistency.

    Parameters
    ----------
    config : dict
        Configuration dictionary.

    Returns
    -------
    list
        List of error strings. Empty list means valid.
    """
    errors = []

    # dx must be smaller than Length and Width
    if config["dx"] > config["Length"]:
        errors.append(f"dx ({config['dx']}) > Length ({config['Length']})")
    if config["dx"] > config["Width"]:
        errors.append(f"dx ({config['dx']}) > Width ({config['Width']})")

    # N0_meters should produce at least 3 cells
    N0_cells = round(config["N0_meters"] / config["dx"])
    if N0_cells < 3:
        errors.append(
            f"N0_meters/dx = {N0_cells} cells — need at least 3 for inlet"
        )

    # gamma check
    g = 9.81
    gamma = g * config["S0"] * config["dx"] / (config["u0"] ** 2)
    if gamma > 0.1:
        errors.append(
            f"gamma = {gamma:.4f} > 0.1 — model may be numerically unstable. "
            f"Reduce dx, reduce S0, or increase u0."
        )

    # f_bedload range
    if config["f_bedload"] < 0 or config["f_bedload"] > 1:
        errors.append(f"f_bedload must be in [0, 1], got {config['f_bedload']}")

    # C0_percent range
    if config["C0_percent"] < 0:
        errors.append(f"C0_percent must be >= 0, got {config['C0_percent']}")

    return errors


def write_yaml(config: dict, filepath: str) -> str:
    """Write configuration dictionary to YAML file.

    Parameters
    ----------
    config : dict
        Configuration dictionary.
    filepath : str
        Output YAML file path.

    Returns
    -------
    str
        Absolute path to the written file.
    """
    filepath = os.path.abspath(filepath)
    with open(filepath, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    return filepath


def main():
    parser = argparse.ArgumentParser(
        description="Generate pyDeltaRCM YAML configuration"
    )
    parser.add_argument("-o", "--output", default="pydeltarcm_config.yml",
                        help="Output YAML file path")
    parser.add_argument("--out-dir", default="deltaRCM_Output",
                        help="Model output directory")
    parser.add_argument("--length", type=float, default=5000,
                        help="Domain length in meters")
    parser.add_argument("--width", type=float, default=10000,
                        help="Domain width in meters")
    parser.add_argument("--dx", type=float, default=50,
                        help="Grid cell size in meters")
    parser.add_argument("--u0", type=float, default=1.0,
                        help="Inlet velocity in m/s")
    parser.add_argument("--h0", type=float, default=5.0,
                        help="Inlet depth in meters")
    parser.add_argument("--slr-mmyr", type=float, default=0.0,
                        help="Sea level rise in mm/yr (real time)")
    parser.add_argument("--If", type=float, default=0.05,
                        help="Intermittency factor")
    parser.add_argument("--seed", type=int, default=None,
                        help="Random seed for reproducibility")
    parser.add_argument("--save-dt-days", type=float, default=1.0,
                        help="Output interval in days of model time")

    args = parser.parse_args()

    # Generate config
    config = generate_config(
        out_dir=args.out_dir,
        Length=args.length,
        Width=args.width,
        dx=args.dx,
        u0=args.u0,
        h0=args.h0,
        SLR_mmyr=args.slr_mmyr,
        If=args.If,
        seed=args.seed,
        save_dt_days=args.save_dt_days,
    )

    # Validate
    input_warnings = validate_inputs(config)
    for w in input_warnings:
        print(w, file=sys.stderr)

    config_errors = validate_config(config)
    if config_errors:
        for e in config_errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    # Write
    outpath = write_yaml(config, args.output)
    print(f"Configuration written to: {outpath}")

    # Print derived parameters for reference
    g = 9.81
    gamma = g * config["S0"] * config["dx"] / (config["u0"] ** 2)
    N0 = max(3, round(config.get("N0_meters", 250) / config["dx"]))
    Qw0 = config["u0"] * config["h0"] * N0 * config["dx"]
    dt = 0.1 * N0**2 * config["h0"] * config["dx"]**2 / (Qw0 * config["C0_percent"] / 100)
    print(f"  gamma = {gamma:.5f} {'(OK)' if gamma <= 0.1 else '(WARNING: > 0.1)'}")
    print(f"  Qw0 = {Qw0:.1f} m3/s")
    print(f"  dt = {dt:.1f} s ({dt/86400:.2f} days)")
    print(f"  Grid: {int(config['Length']/config['dx'])} x {int(config['Width']/config['dx'])} cells")


if __name__ == "__main__":
    main()
