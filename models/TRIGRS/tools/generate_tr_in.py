#!/usr/bin/env python3
"""
generate_tr_in.py
=================
Generate a TRIGRS initialization file (tr_in.txt) from individual
parameter components, with full validation.

This tool assembles the complex, line-ordered tr_in.txt file from
user-provided parameters, soil zone data, rainfall configuration,
and file paths. It validates all units and physical bounds before
writing.

CRITICAL: tr_in.txt is a fixed-format, line-ordered file.
Every line must appear in the correct position. This tool ensures
correct formatting that matches TRIGRS v2.1 expectations.

Usage:
    python generate_tr_in.py \\
        --config config.json \\
        --output tr_in.txt

    config.json structure:
    {
        "project_name": "My TRIGRS project",
        "tx": 1, "nmax": 30, "mmax": -100, "zones": 2,
        "nzs": 10, "zmin": 0.001, "uww": 9800, "nper": 2, "t": 216000,
        "zmax": -3.001, "depth": -2.4, "rizero": -1e-9,
        "slomin": 0.0, "slomax": 90.0,
        "zones_data": [...],
        "cri": [...],
        "capt": [...],
        "grid_files": {...},
        "output_options": {...}
    }
"""

import argparse
import json
import os
import sys
from typing import Any, Dict, List


def validate_inputs(config: dict) -> List[str]:
    """
    Validate all configuration parameters.

    Returns:
        list of error messages (empty = valid)
    """
    errors = []

    # Required fields
    required = ["project_name", "tx", "nmax", "mmax", "nzs", "uww",
                "nper", "t", "zmax", "depth"]
    for field in required:
        if field not in config:
            errors.append(f"Missing required field: {field}")

    if errors:
        return errors

    # Physical validation
    if config["uww"] < 9000 or config["uww"] > 11000:
        errors.append(
            f"uww = {config['uww']} N/m^3 is unusual. "
            f"Expected ~9800 N/m^3 for water. "
            f"CHECK: is this in N/m^3 (not kN/m^3)?"
        )

    if config["t"] < 0:
        errors.append(f"Total time t = {config['t']} must be positive")
    elif config["t"] < 3600:
        errors.append(
            f"Total time t = {config['t']} s is very short "
            f"({config['t']/3600:.2f} hours). "
            f"CHECK: is this in seconds (not hours)?"
        )

    if config.get("nper", 0) < 1:
        errors.append("nper must be >= 1")

    # Validate zone data
    zones_data = config.get("zones_data", [])
    n_zones = config.get("zones", len(zones_data))
    if len(zones_data) != n_zones:
        errors.append(
            f"zones = {n_zones} but {len(zones_data)} zone entries provided"
        )

    for i, zone in enumerate(zones_data):
        zid = zone.get("zone_id", i + 1)
        c = zone.get("cohesion", 0)
        if c > 0 and c < 100:
            errors.append(
                f"Zone {zid}: cohesion = {c} Pa is suspiciously low. "
                f"CHECK: should this be in kPa ({c*1000} Pa)?"
            )
        uws = zone.get("uws", 0)
        if 10 < uws < 30:
            errors.append(
                f"Zone {zid}: uws = {uws} looks like kN/m^3. "
                f"TRIGRS expects N/m^3 (e.g., {uws*1000})"
            )

    # Validate rainfall
    cri = config.get("cri", [])
    if len(cri) != config.get("nper", 0):
        errors.append(
            f"nper = {config['nper']} but {len(cri)} cri values provided"
        )

    for i, val in enumerate(cri):
        if abs(val) > 1e-3:
            errors.append(
                f"cri[{i}] = {val} m/s is extremely high "
                f"({val*3.6e6:.0f} mm/hr). "
                f"CHECK: is this in m/s?"
            )

    # Validate capt
    capt = config.get("capt", [])
    expected_capt = config.get("nper", 0) + 1
    if len(capt) != expected_capt:
        errors.append(
            f"Expected {expected_capt} capt values "
            f"(nper + 1), got {len(capt)}"
        )

    if capt and capt[-1] != config.get("t", 0):
        errors.append(
            f"Last capt value ({capt[-1]}) should equal t ({config['t']})"
        )

    return errors


def generate_tr_in(config: dict) -> str:
    """
    Generate the tr_in.txt content from configuration.

    Returns:
        string content of tr_in.txt
    """
    lines = []

    # Line 1-2: Project name
    lines.append("Name of project (up to 255 characters)")
    lines.append(config["project_name"])

    # Line 3-4: tx, nmax, mmax, zones
    lines.append("tx, nmax, mmax, zones")
    n_zones = config.get("zones", len(config.get("zones_data", [])))
    lines.append(f"{config['tx']},   {config['nmax']},   "
                 f"{config['mmax']},   {n_zones}")

    # Line 5-6: nzs, zmin, uww, nper, t
    lines.append("nzs,  zmin,  uww,    nper    t")
    zmin = config.get("zmin", 0.001)
    lines.append(f"{config['nzs']},   {zmin},  {config['uww']},   "
                 f"{config['nper']},  {config['t']}")

    # Line 7-8: zmax, depth, rizero, slomin, slomax
    lines.append("zmax,   depth,   rizero,  Min_Slope_Angle (degrees), "
                 "Max_Slope_Angle (degrees)")
    rizero = config.get("rizero", -1e-9)
    slomin = config.get("slomin", 0.0)
    slomax = config.get("slomax", 90.0)
    lines.append(f"{config['zmax']},  {config['depth']},  {rizero},       "
                 f"{slomin},  {slomax}")

    # Zone blocks
    for zone in config.get("zones_data", []):
        zid = zone.get("zone_id", 1)
        lines.append(f"zone, {zid}")
        lines.append("cohesion,phi,  uws,   diffus,   K-sat, "
                      "Theta-sat,Theta-res,Alpha")
        lines.append(
            f"{zone.get('cohesion', 5000)}, "
            f"{zone.get('phi', 30.)}, "
            f"{zone.get('uws', 19000)}, "
            f"{zone.get('diffusivity', 1e-5)}, "
            f"{zone.get('ksat', 1e-6)}, "
            f"{zone.get('theta_sat', 0.45)}, "
            f"{zone.get('theta_res', 0.05)}, "
            f"{zone.get('alpha', -0.5)}"
        )

    # Rainfall intensities
    lines.append("cri(1), cri(2), ..., cri(nper)")
    cri = config.get("cri", [1e-7])
    lines.append(",  ".join([f"{v}" for v in cri]))

    # Time boundaries
    lines.append("capt(1), capt(2), ..., capt(n), capt(n+1)")
    capt = config.get("capt", [0, config["t"]])
    lines.append(", ".join([f"{v}" for v in capt]))

    # Grid file paths
    gf = config.get("grid_files", {})
    file_entries = [
        ("File name of slope angle grid (slofil)", "slope_file"),
        ("File name of digital elevation grid (elevfil)", "dem_file"),
        ("File name of property zone grid (zonfil)", "zone_file"),
        ("File name of depth grid (zfil)", "depth_file"),
        ("File name of initial depth of water table grid   (depfil)",
         "watertable_file"),
        ("File name of initial infiltration rate grid   (rizerofil)",
         "rizero_file"),
    ]

    for desc, key in file_entries:
        lines.append(desc)
        lines.append(gf.get(key, "none"))

    # Rainfall grid files
    lines.append("List of file name(s) of rainfall intensity for each "
                 "period, (rifil())")
    rain_files = gf.get("rainfall_files", ["none"])
    for rf in rain_files:
        lines.append(rf)

    # Runoff routing files
    routing_files = [
        ("File name of grid of D8 runoff receptor cell numbers (nxtfil)",
         "nxt_file"),
        ("File name of list of cells defining runoff computation order "
         "(ndxfil)", "ndx_file"),
        ("File name of list of all runoff receptor cells  (dscfil)",
         "dsc_file"),
        ("File name of list of runoff weighting factors  (wffil)",
         "wf_file"),
    ]
    for desc, key in routing_files:
        lines.append(desc)
        lines.append(gf.get(key, "none"))

    # Output configuration
    oo = config.get("output_options", {})
    lines.append("Folder where output grid files will be stored  (folder)")
    lines.append(oo.get("output_folder", "output/"))

    lines.append("Identification code to be added to names of output "
                 "files (suffix)")
    lines.append(oo.get("suffix", "run01"))

    # Boolean output options
    bool_options = [
        ("Save grid files of runoff? Enter T (.true.) or F (.false.)",
         "save_runoff", True),
        ("Save grid of minimum factor of safety? Enter T (.true.) or "
         "F (.false.)", "save_fs_min", True),
        ("Save grid of depth of minimum factor of safety? Enter T (.true.) "
         "or F (.false.)", "save_z_fs_min", True),
        ("Save grid of pressure head at depth of minimum factor of safety? "
         "Enter T (.true.) or F (.false.)", "save_p_fs_min", True),
    ]

    for desc, key, default in bool_options:
        lines.append(desc)
        val = oo.get(key, default)
        lines.append("T" if val else "F")

    # Water table output
    lines.append("Save grid of computed water table depth or elevation? "
                 "Enter T (.true.) or F (.false.) followed by 'depth,' "
                 "or 'eleva'")
    wt_save = oo.get("save_watertable", True)
    wt_type = oo.get("watertable_type", "depth")
    lines.append(f"{'T' if wt_save else 'F'}, {wt_type}")

    lines.append("Save grid files of actual infiltration rate? Enter T "
                 "(.true.) or F (.false.)")
    lines.append("T" if oo.get("save_infiltration", True) else "F")

    lines.append("Save grid files of unsaturated zone basal flux? Enter T "
                 "(.true.) or F (.false.)")
    lines.append("T" if oo.get("save_basal_flux", False) else "F")

    # List output
    lines.append('Save listing of pressure head and factor of safety '
                 '("flag")? (-9 sparse xmdv , -8 down-sampled xmdv, '
                 '-7 full xmdv, -6 sparse ijz, -5 down-sampled ijz, '
                 '-4 full ijz, -3 Z-P-Fs-saturation list -2 detailed '
                 'Z-P-Fs, -1 Z-P-Fs list, 0 none). Enter flag value '
                 'followed by down-sampling interval (integer).')
    flag = oo.get("list_flag", -2)
    spcg = oo.get("down_sample", 1)
    lines.append(f"{flag},{spcg}")

    # Output times
    out_times = oo.get("output_times", [config["t"]])
    lines.append("Number of times to save output grids and (or) "
                 "ijz / xmdv files")
    lines.append(str(len(out_times)))
    lines.append("Times of output grids and (or) ijz / xmdv files")
    lines.append(", ".join([f"{t}" for t in out_times]))

    # Additional options
    lines.append("Skip other timesteps? Enter T (.true.) or F (.false.)")
    lines.append("F")
    lines.append("Use analytic solution for fillable porosity?  Enter T "
                 "(.true.) or F (.false.)")
    lines.append("T" if oo.get("analytic_porosity", True) else "F")
    lines.append("Estimate positive pressure head in rising water table "
                 "zone (i.e. in lower part of unsat zone)?  Enter T "
                 "(.true.) or F (.false.)")
    lines.append("T" if oo.get("rising_wt", True) else "F")
    lines.append("Use psi0=-1/alpha? Enter T (.true.) or F (.false.) "
                 "(False selects the default value, psi0=0)")
    lines.append("T" if oo.get("psi0_alpha", False) else "F")
    lines.append("Log mass balance results?   Enter T (.true.) or F "
                 "(.false.)")
    lines.append("T" if oo.get("log_mass_balance", True) else "F")
    lines.append('Flow direction (Enter "gener", "slope", or "hydro")')
    lines.append(oo.get("flow_direction", "gener"))
    lines.append("Add steady background flux to transient infiltration "
                 "rate to prevent drying beyond the initial conditions "
                 "during periods of zero infiltration?")
    lines.append("T" if oo.get("background_flux", True) else "F")
    lines.append("Specify file extension for output grids. Enter T "
                 '(.true.) for ".asc" or F for ".txt"')
    lines.append("T" if oo.get("asc_extension", True) else "F")
    lines.append("Ignore negative pressure head in computing factor of "
                 "safety (saturated infiltration only)?   Enter T "
                 "(.true.) or F (.false.)")
    lines.append("T" if oo.get("ignore_neg_phead", True) else "F")
    lines.append("Ignore height of capillary fringe in computing pressure "
                 "head for unsaturated infiltration option?   Enter T "
                 "(.true.) or F (.false.)")
    lines.append("T" if oo.get("ignore_capillary", True) else "F")
    lines.append("Parameters for deep pressure-head estimate in SCOOPS "
                 "ijz output: Depth below ground surface (positive, use "
                 "negative value to cancel this option), pressure option "
                 "(enter 'zero' , 'flow' , 'hydr' , or 'relh')")
    deep_z = oo.get("deep_z", -50.0)
    deep_opt = oo.get("deep_pressure_option", "flow")
    lines.append(f"{deep_z},{deep_opt}")

    return "\n".join(lines) + "\n"


def validate_output(content: str) -> List[str]:
    """Validate generated tr_in.txt content."""
    warnings = []
    lines = content.strip().split("\n")

    if len(lines) < 40:
        warnings.append(
            f"Generated file has only {len(lines)} lines "
            f"(expected ~80+)"
        )

    # Check for common formatting issues
    for i, line in enumerate(lines):
        if "\t" in line:
            warnings.append(f"Line {i+1} contains tabs (use spaces)")

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Generate TRIGRS initialization file"
    )
    parser.add_argument("--config", required=True,
                        help="JSON configuration file")
    parser.add_argument("--output", default="tr_in.txt",
                        help="Output tr_in.txt file")

    args = parser.parse_args()

    # Step 1: Load and validate config
    print("[1/3] Loading configuration...")
    with open(args.config, "r") as f:
        config = json.load(f)

    errors = validate_inputs(config)
    if errors:
        print("  Configuration errors:")
        for e in errors:
            print(f"    - {e}")
        return 1

    # Step 2: Generate tr_in.txt
    print("[2/3] Generating tr_in.txt...")
    content = generate_tr_in(config)

    # Step 3: Validate and write
    print("[3/3] Validating output...")
    warnings = validate_output(content)
    if warnings:
        print("  Warnings:")
        for w in warnings:
            print(f"    - {w}")

    with open(args.output, "w") as f:
        f.write(content)

    line_count = len(content.strip().split("\n"))
    print(f"\nDone. Generated {args.output} ({line_count} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
