#!/usr/bin/env python3
"""
Convert real-world geomorphological parameters to pyDeltaRCM model units.

This tool converts common field measurements and literature values into
the specific units expected by pyDeltaRCM. It handles the most common
unit conversion traps.

Pattern: validate inputs → convert → validate outputs
"""

import argparse
import json
import sys


def validate_real_world_inputs(params: dict) -> list:
    """Validate real-world input parameters.

    Parameters
    ----------
    params : dict
        Real-world parameter dictionary with keys like:
        - channel_width_m: inlet channel width in meters
        - channel_depth_m: inlet channel depth in meters
        - flow_velocity_ms: flow velocity in m/s
        - slope: channel/topset slope (dimensionless)
        - sed_conc_mgL: sediment concentration in mg/L
        - slr_mmyr: sea level rise rate in mm/yr
        - subsidence_mmyr: subsidence rate in mm/yr
        - intermittency: flood intermittency factor

    Returns
    -------
    list
        List of validation warnings.
    """
    warnings = []

    if "channel_width_m" in params:
        w = params["channel_width_m"]
        if w <= 0:
            warnings.append(f"channel_width_m must be positive, got {w}")
        if w > 50000:
            warnings.append(f"channel_width_m={w} is very large (> 50 km)")

    if "channel_depth_m" in params:
        d = params["channel_depth_m"]
        if d <= 0:
            warnings.append(f"channel_depth_m must be positive, got {d}")
        if d > 50:
            warnings.append(f"channel_depth_m={d} is very deep (> 50 m)")

    if "flow_velocity_ms" in params:
        v = params["flow_velocity_ms"]
        if v <= 0:
            warnings.append(f"flow_velocity_ms must be positive, got {v}")
        if v > 5:
            warnings.append(f"flow_velocity_ms={v} — very fast (> 5 m/s)")

    if "sed_conc_mgL" in params:
        c = params["sed_conc_mgL"]
        if c < 0:
            warnings.append(f"sed_conc_mgL must be >= 0, got {c}")
        if c > 100000:
            warnings.append(f"sed_conc_mgL={c} — extremely high (> 100 g/L)")

    if "slope" in params:
        s = params["slope"]
        if s <= 0:
            warnings.append(f"slope must be positive, got {s}")
        if s > 0.1:
            warnings.append(f"slope={s} — very steep for a delta (> 0.1)")

    if "intermittency" in params:
        i = params["intermittency"]
        if i <= 0 or i > 1:
            warnings.append(f"intermittency must be in (0, 1], got {i}")

    return warnings


def sed_conc_mgL_to_C0_percent(conc_mgL: float, rho_sed: float = 2650.0) -> float:
    """Convert sediment concentration from mg/L to volume percent.

    Parameters
    ----------
    conc_mgL : float
        Mass concentration in mg/L.
    rho_sed : float
        Sediment grain density in kg/m³ (default 2650 for quartz).

    Returns
    -------
    float
        Volumetric concentration as percentage (C0_percent).

    Notes
    -----
    Conversion: C_vol = (conc_mg/L) / (rho_sed_kg/m3 * 1e6 mg/kg * 1e-3 L/m3)
    Simplifies to: C_vol = conc_mgL / (rho_sed * 1000)
    Then C0_percent = C_vol * 100

    Examples
    --------
    >>> sed_conc_mgL_to_C0_percent(2650)  # 2650 mg/L ~ 0.1% by volume
    0.1
    """
    C_vol_fraction = conc_mgL / (rho_sed * 1000.0)
    C0_percent = C_vol_fraction * 100.0
    return C0_percent


def slr_mmyr_to_model(slr_mmyr: float, If: float = 0.05) -> float:
    """Convert SLR from mm/yr real-world time to m/s model time.

    Parameters
    ----------
    slr_mmyr : float
        Sea level rise rate in mm/yr.
    If : float
        Intermittency factor.

    Returns
    -------
    float
        SLR in m/s of model time.

    Notes
    -----
    The model runs in "bankfull time" — only a fraction If of real time
    is at bankfull. So:
    SLR_model = SLR_real * If  (in same units)
    Then convert mm/yr -> m/s: / 1000 / (365.25*86400)
    """
    return slr_mmyr / 1000.0 / (365.25 * 86400) * If


def subsidence_mmyr_to_model(rate_mmyr: float, If: float = 0.05) -> float:
    """Convert subsidence rate from mm/yr to m/s of model time.

    Same conversion as SLR.
    """
    return rate_mmyr / 1000.0 / (365.25 * 86400) * If


def estimate_domain_size(
    channel_width_m: float,
    domain_width_ratio: float = 40.0,
    domain_length_ratio: float = 20.0,
) -> dict:
    """Estimate appropriate domain size from channel width.

    Parameters
    ----------
    channel_width_m : float
        Inlet channel width in meters.
    domain_width_ratio : float
        Domain width as multiple of channel width (default 40x).
    domain_length_ratio : float
        Domain length as multiple of channel width (default 20x).

    Returns
    -------
    dict
        Dictionary with 'Length', 'Width', and recommended 'dx'.
    """
    Width = channel_width_m * domain_width_ratio
    Length = channel_width_m * domain_length_ratio

    # dx should give at least 5 cells across channel
    dx = max(10, channel_width_m / 5.0)
    # Round dx to a nice number
    nice_values = [10, 15, 20, 25, 30, 40, 50, 75, 100, 150, 200, 250, 500]
    dx = min(nice_values, key=lambda x: abs(x - dx))

    return {"Length": Length, "Width": Width, "dx": dx}


def compute_gamma(S0: float, dx: float, u0: float, g: float = 9.81) -> float:
    """Compute gamma stability parameter.

    Parameters
    ----------
    S0 : float
        Characteristic slope.
    dx : float
        Cell size in meters.
    u0 : float
        Reference velocity in m/s.
    g : float
        Gravitational acceleration.

    Returns
    -------
    float
        Gamma value. Should be < 0.1 for stability.
    """
    return g * S0 * dx / (u0 ** 2)


def compute_timestep(u0, h0, N0_cells, dx, C0_percent):
    """Compute the model timestep dt.

    Parameters
    ----------
    u0 : float
        Reference velocity (m/s).
    h0 : float
        Reference depth (m).
    N0_cells : int
        Number of inlet cells.
    dx : float
        Cell size (m).
    C0_percent : float
        Sediment concentration in percent.

    Returns
    -------
    float
        Timestep in seconds.
    """
    V0 = h0 * dx ** 2
    Qw0 = u0 * h0 * N0_cells * dx
    C0 = C0_percent / 100.0
    Qs0 = Qw0 * C0
    dVs = 0.1 * N0_cells ** 2 * V0
    dt = dVs / Qs0
    return dt


def convert_all(params: dict) -> dict:
    """Convert a dictionary of real-world parameters to model parameters.

    Parameters
    ----------
    params : dict
        Real-world parameters. Supported keys:
        - channel_width_m, channel_depth_m, flow_velocity_ms
        - slope, sed_conc_mgL, bedload_fraction
        - slr_mmyr, subsidence_mmyr, intermittency
        - domain_length_m, domain_width_m, grid_spacing_m

    Returns
    -------
    dict
        Model parameters ready for YAML config.
    """
    If = params.get("intermittency", 0.05)
    model = {}

    # Domain geometry
    if "domain_length_m" in params:
        model["Length"] = params["domain_length_m"]
    if "domain_width_m" in params:
        model["Width"] = params["domain_width_m"]
    if "grid_spacing_m" in params:
        model["dx"] = params["grid_spacing_m"]

    # If no domain specified, estimate from channel width
    if "channel_width_m" in params and "domain_length_m" not in params:
        domain = estimate_domain_size(params["channel_width_m"])
        model.setdefault("Length", domain["Length"])
        model.setdefault("Width", domain["Width"])
        model.setdefault("dx", domain["dx"])

    # Inlet conditions
    if "channel_width_m" in params:
        model["N0_meters"] = params["channel_width_m"]
    if "channel_depth_m" in params:
        model["h0"] = params["channel_depth_m"]
    if "flow_velocity_ms" in params:
        model["u0"] = params["flow_velocity_ms"]
    if "slope" in params:
        model["S0"] = params["slope"]
    if "sed_conc_mgL" in params:
        model["C0_percent"] = sed_conc_mgL_to_C0_percent(params["sed_conc_mgL"])
    if "bedload_fraction" in params:
        model["f_bedload"] = params["bedload_fraction"]

    # Sea level rise
    if "slr_mmyr" in params and params["slr_mmyr"] != 0:
        model["SLR"] = slr_mmyr_to_model(params["slr_mmyr"], If)

    # Subsidence
    if "subsidence_mmyr" in params and params["subsidence_mmyr"] != 0:
        model["toggle_subsidence"] = True
        model["subsidence_rate"] = subsidence_mmyr_to_model(
            params["subsidence_mmyr"], If
        )

    return model


def validate_model_params(model: dict) -> list:
    """Validate converted model parameters for consistency.

    Returns
    -------
    list
        List of error/warning strings.
    """
    errors = []

    if "S0" in model and "dx" in model and "u0" in model:
        gamma = compute_gamma(model["S0"], model["dx"], model["u0"])
        if gamma > 0.1:
            errors.append(
                f"gamma = {gamma:.4f} > 0.1 — UNSTABLE. "
                f"Reduce dx from {model['dx']} or increase u0 from {model['u0']}"
            )
        elif gamma > 0.05:
            errors.append(
                f"gamma = {gamma:.4f} — near stability limit. Monitor carefully."
            )

    if "dx" in model and "N0_meters" in model:
        N0_cells = round(model["N0_meters"] / model["dx"])
        if N0_cells < 3:
            errors.append(
                f"Inlet is only {N0_cells} cells wide. Need >= 3. "
                f"Reduce dx or increase N0_meters."
            )

    return errors


def main():
    parser = argparse.ArgumentParser(
        description="Convert real-world parameters to pyDeltaRCM model units"
    )
    parser.add_argument("--json", type=str, help="Input JSON file with parameters")
    parser.add_argument("--channel-width", type=float, help="Channel width (m)")
    parser.add_argument("--channel-depth", type=float, help="Channel depth (m)")
    parser.add_argument("--velocity", type=float, help="Flow velocity (m/s)")
    parser.add_argument("--slope", type=float, help="Topset slope")
    parser.add_argument("--sed-conc", type=float, help="Sediment conc (mg/L)")
    parser.add_argument("--slr", type=float, default=0, help="SLR (mm/yr)")
    parser.add_argument("--If", type=float, default=0.05, help="Intermittency")

    args = parser.parse_args()

    if args.json:
        with open(args.json) as f:
            params = json.load(f)
    else:
        params = {"intermittency": args.If}
        if args.channel_width:
            params["channel_width_m"] = args.channel_width
        if args.channel_depth:
            params["channel_depth_m"] = args.channel_depth
        if args.velocity:
            params["flow_velocity_ms"] = args.velocity
        if args.slope:
            params["slope"] = args.slope
        if args.sed_conc:
            params["sed_conc_mgL"] = args.sed_conc
        if args.slr:
            params["slr_mmyr"] = args.slr

    # Validate inputs
    input_warnings = validate_real_world_inputs(params)
    for w in input_warnings:
        print(f"INPUT WARNING: {w}", file=sys.stderr)

    # Convert
    model = convert_all(params)

    # Validate outputs
    output_errors = validate_model_params(model)
    for e in output_errors:
        print(f"MODEL WARNING: {e}", file=sys.stderr)

    # Print results
    print(json.dumps(model, indent=2))


if __name__ == "__main__":
    main()
