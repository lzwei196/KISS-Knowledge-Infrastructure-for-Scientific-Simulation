#!/usr/bin/env python3
"""
validate_soil_profile.py - Validates a DSSAT .SOL soil profile.

Parses DSSAT soil files and validates a specific profile (by PEDON ID) against
DSSAT physical constraints and numerical stability requirements.

DSSAT Soil File Format Reference:
    Profile header: *PEDON_ID  SOURCE  TEXTURE  DEPTH  DESCRIPTION
    Site line:      @SITE  COUNTRY  LAT  LONG  SCS_FAMILY
    Surface line:   @ SCOM  SALB  SLU1  SLDR  SLRO  SLNF  SLPF  SMHB  SMPX  SMKE
    Layer header:   @  SLB  SLMH  SLLL  SDUL  SSAT  SRGF  SSKS  SBDM  SLOC ...
    Layer data:     depth values...

Hard limits from DSSAT Fortran source:
    NL = 20 (maximum soil layers)
    LL < DUL < SAT for every layer
    SAT - DUL >= 0.01 (minimum drainage gap)

Exit codes:
    0 = success (validation complete, may have warnings)
    1 = input error (file not found, profile not found)
    2 = processing error (unparseable format)
    3 = output error (validation failed with errors)
"""

import sys
import os
import logging
import json
import math
from collections import OrderedDict

# ---------------------------------------------------------------------------
# INPUT VARIABLES (agent sets these before invocation)
# ---------------------------------------------------------------------------
SOIL_FILE_PATH = ""         # Path to .SOL file (required)
PEDON_ID = ""               # Soil profile ID to validate (e.g., "IBMZ910014")
                            # If empty, validates ALL profiles in the file
STRICT_MODE = False         # If True, treat warnings as errors
OUTPUT_JSON = True          # If True, print JSON report to stdout

# ---------------------------------------------------------------------------
# DSSAT CONSTANTS
# ---------------------------------------------------------------------------
MAX_LAYERS = 20             # NL=20 hard limit in DSSAT Fortran source

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(message)s"
)
logger = logging.getLogger("validate_soil_profile")


def is_missing(val_str):
    """Check if a value string represents DSSAT missing data (-99)."""
    if val_str is None:
        return True
    s = val_str.strip()
    try:
        v = float(s)
        return v == -99.0
    except ValueError:
        return s == "-99" or s == "-99.0" or s == "-99."


def safe_float(val_str, default=None):
    """Safely convert a string to float, returning default on failure or -99."""
    if val_str is None:
        return default
    s = val_str.strip()
    try:
        v = float(s)
        if v == -99.0:
            return default
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except ValueError:
        return default


def parse_sol_file(filepath):
    """Parse a DSSAT .SOL file into a list of soil profiles.

    Each profile is a dict with:
        pedon_id, source, texture, max_depth, description,
        site_data (dict), surface_params (dict), layers (list of dicts),
        header_line_num (int).

    Args:
        filepath: Path to the .SOL file.

    Returns:
        List of profile dicts.
    """
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        raw_lines = f.readlines()

    profiles = []
    current_profile = None
    section = None  # 'site', 'surface', 'layers'
    layer_headers = []
    surface_headers = []

    for i, line in enumerate(raw_lines):
        stripped = line.strip()

        # Skip empty lines and comments
        if not stripped:
            continue
        if stripped.startswith("!"):
            continue

        # Profile header line: starts with * followed by profile ID
        if stripped.startswith("*") and not stripped.startswith("*SOILS"):
            # Save previous profile
            if current_profile is not None:
                profiles.append(current_profile)

            # Parse profile header: *ID  SOURCE  TEXTURE  DEPTH  DESCRIPTION
            parts = stripped[1:].split(None, 4)
            current_profile = {
                "pedon_id": parts[0] if len(parts) > 0 else "",
                "source": parts[1] if len(parts) > 1 else "",
                "texture": parts[2] if len(parts) > 2 else "",
                "max_depth": parts[3] if len(parts) > 3 else "",
                "description": parts[4] if len(parts) > 4 else "",
                "site_data": {},
                "surface_params": {},
                "layers": [],
                "header_line_num": i + 1,
                "raw_header": stripped,
            }
            section = "site_header"
            layer_headers = []
            surface_headers = []
            continue

        if current_profile is None:
            continue

        # Section detection via @ lines
        if stripped.startswith("@"):
            cols = stripped.lstrip("@ ").split()
            if "SITE" in cols or "COUNTRY" in cols:
                section = "site_data"
                continue
            elif "SCOM" in cols or "SALB" in cols:
                section = "surface_data"
                surface_headers = cols
                continue
            elif "SLB" in cols:
                section = "layer_data"
                layer_headers = cols
                continue
            else:
                # Unknown section header; keep current section
                continue

        # Parse data lines based on current section
        if section == "site_data":
            # Site data line: single line after @SITE header
            parts = stripped.split(None, 4)
            current_profile["site_data"] = {
                "site": parts[0] if len(parts) > 0 else "",
                "country": parts[1] if len(parts) > 1 else "",
                "lat": parts[2] if len(parts) > 2 else "",
                "long": parts[3] if len(parts) > 3 else "",
                "scs_family": parts[4] if len(parts) > 4 else "",
            }
            section = None
            continue

        if section == "surface_data":
            parts = stripped.split()
            surface = {}
            for j, col in enumerate(surface_headers):
                if j < len(parts):
                    surface[col] = parts[j]
                else:
                    surface[col] = None
            current_profile["surface_params"] = surface
            section = None
            continue

        if section == "layer_data":
            parts = stripped.split()
            # Verify this looks like a layer data line (first value should be numeric)
            try:
                float(parts[0])
            except (ValueError, IndexError):
                continue

            layer = OrderedDict()
            for j, col in enumerate(layer_headers):
                if j < len(parts):
                    layer[col] = parts[j]
                else:
                    layer[col] = None
            current_profile["layers"].append(layer)
            continue

    # Don't forget the last profile
    if current_profile is not None:
        profiles.append(current_profile)

    return profiles


def validate_profile(profile):
    """Validate a single soil profile against DSSAT constraints.

    Args:
        profile: Profile dict from parse_sol_file().

    Returns:
        dict with keys: passed, errors, warnings, info, missing_value_counts.
    """
    errors = []
    warnings = []
    info = OrderedDict()
    missing_counts = {}

    pedon = profile["pedon_id"]
    info["pedon_id"] = pedon
    info["description"] = profile.get("description", "")
    info["header_line"] = profile.get("header_line_num", 0)

    layers = profile["layers"]
    surface = profile["surface_params"]
    info["num_layers"] = len(layers)

    # -------------------------------------------------------------------
    # CHECK: Max 20 layers (NL=20 hard limit)
    # -------------------------------------------------------------------
    if len(layers) > MAX_LAYERS:
        errors.append(
            f"Profile {pedon}: {len(layers)} layers exceeds DSSAT maximum "
            f"of {MAX_LAYERS} (NL=20 in Fortran source)."
        )

    if len(layers) == 0:
        errors.append(f"Profile {pedon}: no soil layers found.")
        return {
            "passed": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "info": dict(info),
            "missing_value_counts": missing_counts,
        }

    # -------------------------------------------------------------------
    # PARSE LAYER DEPTHS AND CHECK MONOTONIC INCREASE
    # -------------------------------------------------------------------
    slb_values = []
    for idx, layer in enumerate(layers):
        slb_str = layer.get("SLB")
        if slb_str is None or is_missing(slb_str):
            errors.append(
                f"Profile {pedon}, layer {idx + 1}: SLB (depth) is missing."
            )
            slb_values.append(None)
        else:
            try:
                slb = float(slb_str)
                slb_values.append(slb)
            except ValueError:
                errors.append(
                    f"Profile {pedon}, layer {idx + 1}: SLB is not numeric: '{slb_str}'."
                )
                slb_values.append(None)

    # Check monotonically increasing
    prev_slb = None
    for idx, slb in enumerate(slb_values):
        if slb is not None:
            if prev_slb is not None and slb <= prev_slb:
                errors.append(
                    f"Profile {pedon}, layer {idx + 1}: SLB = {slb} cm is not greater "
                    f"than previous layer depth {prev_slb} cm. "
                    f"Layer depths must be monotonically increasing."
                )
            prev_slb = slb

    # Check top layer depth
    if slb_values and slb_values[0] is not None:
        if slb_values[0] > 5:
            warnings.append(
                f"Profile {pedon}: top layer depth = {slb_values[0]} cm > 5 cm. "
                f"This can cause numerical instability in the soil water balance. "
                f"DSSAT recommends top layer <= 5 cm."
            )

    # Check total depth
    valid_slb = [s for s in slb_values if s is not None]
    if valid_slb:
        total_depth = max(valid_slb)
        info["total_depth_cm"] = total_depth
        if total_depth < 20:
            warnings.append(
                f"Profile {pedon}: total depth = {total_depth} cm < 20 cm. "
                f"Shallow soils can cause division-by-zero in DSSAT "
                f"(see d3a65881 fix for soils < 20 cm)."
            )

    # -------------------------------------------------------------------
    # CHECK WATER LIMITS: LL < DUL < SAT for every layer
    # -------------------------------------------------------------------
    for idx, layer in enumerate(layers):
        ll_str = layer.get("SLLL")
        dul_str = layer.get("SDUL")
        sat_str = layer.get("SSAT")

        ll = safe_float(ll_str)
        dul = safe_float(dul_str)
        sat = safe_float(sat_str)

        layer_depth = slb_values[idx] if idx < len(slb_values) else "?"

        # Track missing values
        for col, val_str in layer.items():
            if is_missing(val_str):
                missing_counts[col] = missing_counts.get(col, 0) + 1

        # Skip water checks if values are missing
        if ll is None:
            missing_counts["SLLL"] = missing_counts.get("SLLL", 0)
            continue
        if dul is None:
            missing_counts["SDUL"] = missing_counts.get("SDUL", 0)
            continue
        if sat is None:
            missing_counts["SSAT"] = missing_counts.get("SSAT", 0)
            continue

        # LL < DUL
        if ll >= dul:
            errors.append(
                f"Profile {pedon}, layer {idx + 1} (SLB={layer_depth}): "
                f"SLLL ({ll:.3f}) >= SDUL ({dul:.3f}). "
                f"Must have LL < DUL."
            )

        # DUL < SAT
        if dul >= sat:
            errors.append(
                f"Profile {pedon}, layer {idx + 1} (SLB={layer_depth}): "
                f"SDUL ({dul:.3f}) >= SSAT ({sat:.3f}). "
                f"Must have DUL < SAT."
            )

        # SAT - DUL >= 0.01 (DSSAT minimum gap enforcement)
        if sat - dul < 0.01:
            errors.append(
                f"Profile {pedon}, layer {idx + 1} (SLB={layer_depth}): "
                f"SSAT - SDUL = {sat - dul:.4f} < 0.01. "
                f"DSSAT requires minimum gap of 0.01 cm3/cm3 for drainage."
            )

        # Physical plausibility: LL >= 0 and SAT <= 1.0
        if ll < 0:
            errors.append(
                f"Profile {pedon}, layer {idx + 1} (SLB={layer_depth}): "
                f"SLLL ({ll:.3f}) < 0. Physically impossible."
            )
        if sat > 1.0:
            errors.append(
                f"Profile {pedon}, layer {idx + 1} (SLB={layer_depth}): "
                f"SSAT ({sat:.3f}) > 1.0. Physically impossible (porosity > 100%)."
            )

    # -------------------------------------------------------------------
    # CHECK BULK DENSITY (BD > 0)
    # -------------------------------------------------------------------
    for idx, layer in enumerate(layers):
        bd_str = layer.get("SBDM")
        bd = safe_float(bd_str)
        layer_depth = slb_values[idx] if idx < len(slb_values) else "?"

        if bd is not None:
            if bd <= 0:
                errors.append(
                    f"Profile {pedon}, layer {idx + 1} (SLB={layer_depth}): "
                    f"SBDM (bulk density) = {bd} <= 0."
                )
            elif bd > 2.65:
                warnings.append(
                    f"Profile {pedon}, layer {idx + 1} (SLB={layer_depth}): "
                    f"SBDM = {bd} > 2.65 g/cm3 (exceeds mineral particle density)."
                )

    # -------------------------------------------------------------------
    # CHECK SURFACE PARAMETERS
    # -------------------------------------------------------------------
    # SALB (soil albedo) > 0
    salb = safe_float(surface.get("SALB"))
    if salb is not None:
        if salb <= 0:
            errors.append(
                f"Profile {pedon}: SALB (soil albedo) = {salb} <= 0."
            )
        elif salb > 1.0:
            errors.append(
                f"Profile {pedon}: SALB = {salb} > 1.0 (physically impossible)."
            )
        info["SALB"] = salb
    else:
        missing_counts["SALB"] = 1
        warnings.append(f"Profile {pedon}: SALB is missing.")

    # SLRO (runoff curve number) > 0
    slro = safe_float(surface.get("SLRO"))
    if slro is not None:
        if slro <= 0:
            errors.append(
                f"Profile {pedon}: SLRO (runoff curve number) = {slro} <= 0."
            )
        elif slro > 100:
            warnings.append(
                f"Profile {pedon}: SLRO = {slro} > 100 (SCS curve number range is 0-100)."
            )
        info["SLRO"] = slro
    else:
        missing_counts["SLRO"] = 1
        warnings.append(f"Profile {pedon}: SLRO is missing.")

    # SLNF (nitrogen fertility factor) in [0, 1]
    slnf = safe_float(surface.get("SLNF"))
    if slnf is not None:
        if slnf < 0 or slnf > 1:
            errors.append(
                f"Profile {pedon}: SLNF (N fertility factor) = {slnf} "
                f"out of range [0, 1]."
            )
        info["SLNF"] = slnf
    else:
        missing_counts["SLNF"] = 1

    # SLDR (drainage rate)
    sldr = safe_float(surface.get("SLDR"))
    if sldr is not None:
        if sldr < 0 or sldr > 1:
            warnings.append(
                f"Profile {pedon}: SLDR (drainage rate) = {sldr} "
                f"outside typical range [0, 1]."
            )
        info["SLDR"] = sldr

    # SLPF (photosynthesis factor)
    slpf = safe_float(surface.get("SLPF"))
    if slpf is not None:
        if slpf < 0 or slpf > 1:
            warnings.append(
                f"Profile {pedon}: SLPF (photosynthesis factor) = {slpf} "
                f"outside typical range [0, 1]."
            )
        info["SLPF"] = slpf

    # -------------------------------------------------------------------
    # CHECK for NaN values in all layer data
    # -------------------------------------------------------------------
    nan_count = 0
    for idx, layer in enumerate(layers):
        for col, val_str in layer.items():
            if val_str is not None:
                try:
                    v = float(val_str)
                    if math.isnan(v) or math.isinf(v):
                        nan_count += 1
                        if nan_count <= 5:
                            errors.append(
                                f"Profile {pedon}, layer {idx + 1}: "
                                f"NaN/Inf in column {col} = '{val_str}'."
                            )
                except ValueError:
                    pass  # Non-numeric columns (e.g., SLMH) are OK

    if nan_count > 5:
        errors.append(f"... and {nan_count - 5} more NaN/Inf values.")

    # -------------------------------------------------------------------
    # CHECK SRGF (root growth factor) monotonically decreasing
    # -------------------------------------------------------------------
    srgf_values = []
    for idx, layer in enumerate(layers):
        srgf = safe_float(layer.get("SRGF"))
        if srgf is not None:
            srgf_values.append((idx, srgf))

    if srgf_values:
        for k in range(1, len(srgf_values)):
            prev_idx, prev_val = srgf_values[k - 1]
            curr_idx, curr_val = srgf_values[k]
            if curr_val > prev_val:
                warnings.append(
                    f"Profile {pedon}: SRGF increases from layer {prev_idx + 1} "
                    f"({prev_val}) to layer {curr_idx + 1} ({curr_val}). "
                    f"SRGF typically decreases with depth."
                )
                break  # Only warn once

    # -------------------------------------------------------------------
    # SUMMARIZE MISSING VALUES
    # -------------------------------------------------------------------
    total_missing = sum(missing_counts.values())
    if total_missing > 0:
        info["total_missing_values"] = total_missing

    # -------------------------------------------------------------------
    # STRICT MODE
    # -------------------------------------------------------------------
    if STRICT_MODE:
        errors.extend(warnings)
        warnings = []

    passed = len(errors) == 0
    return {
        "passed": passed,
        "errors": errors,
        "warnings": warnings,
        "info": dict(info),
        "missing_value_counts": missing_counts,
    }


def main():
    """Entry point: parse and validate soil profile(s).

    The target may be supplied on the command line
    (``validate_soil_profile.py /path/to/SOIL.SOL [PEDON_ID]``) so a batch
    driver can validate many .SOL files without rewriting the module. The
    module globals SOIL_FILE_PATH / PEDON_ID stay the defaults when no
    argument is given, so existing set-the-global callers are unaffected.
    """
    global SOIL_FILE_PATH, PEDON_ID
    _pos = [a for a in sys.argv[1:] if not a.startswith("-")]
    if _pos:
        SOIL_FILE_PATH = _pos[0]
    if len(_pos) > 1:
        PEDON_ID = _pos[1]

    # -----------------------------------------------------------------------
    # PRECONDITIONS
    # -----------------------------------------------------------------------
    if not SOIL_FILE_PATH:
        logger.error("SOIL_FILE_PATH must be set before running.")
        sys.exit(1)

    if not os.path.isfile(SOIL_FILE_PATH):
        logger.error("Soil file not found: %s", SOIL_FILE_PATH)
        sys.exit(1)

    # -----------------------------------------------------------------------
    # CORE PROCESSING
    # -----------------------------------------------------------------------
    try:
        profiles = parse_sol_file(SOIL_FILE_PATH)
    except Exception as e:
        logger.error("Failed to parse soil file: %s", e, exc_info=True)
        sys.exit(2)

    if not profiles:
        logger.error("No soil profiles found in %s", SOIL_FILE_PATH)
        sys.exit(2)

    logger.info(
        "Parsed %d soil profile(s) from %s", len(profiles), SOIL_FILE_PATH
    )

    # Filter to requested profile
    if PEDON_ID:
        target_profiles = [
            p for p in profiles if p["pedon_id"] == PEDON_ID
        ]
        if not target_profiles:
            # Try partial match
            target_profiles = [
                p for p in profiles if PEDON_ID in p["pedon_id"]
            ]
        if not target_profiles:
            available = [p["pedon_id"] for p in profiles[:20]]
            logger.error(
                "Profile '%s' not found. Available profiles (first 20): %s",
                PEDON_ID, ", ".join(available)
            )
            sys.exit(1)
    else:
        target_profiles = profiles

    # Validate each target profile
    reports = []
    any_failed = False

    for profile in target_profiles:
        try:
            report = validate_profile(profile)
            reports.append(report)
            if not report["passed"]:
                any_failed = True
                logger.warning(
                    "VALIDATION FAILED for %s (%d errors, %d warnings)",
                    profile["pedon_id"],
                    len(report["errors"]),
                    len(report["warnings"]),
                )
            else:
                logger.info(
                    "VALIDATION PASSED for %s (%d warnings)",
                    profile["pedon_id"],
                    len(report["warnings"]),
                )
        except Exception as e:
            logger.error(
                "Error validating profile %s: %s",
                profile.get("pedon_id", "UNKNOWN"), e
            )
            reports.append({
                "passed": False,
                "errors": [f"Validation error: {e}"],
                "warnings": [],
                "info": {"pedon_id": profile.get("pedon_id", "UNKNOWN")},
                "missing_value_counts": {},
            })
            any_failed = True

    # -----------------------------------------------------------------------
    # POSTCONDITIONS
    # -----------------------------------------------------------------------
    for report in reports:
        required_keys = {"passed", "errors", "warnings", "info", "missing_value_counts"}
        if not required_keys.issubset(report.keys()):
            logger.error(
                "Report missing required keys: %s",
                required_keys - report.keys()
            )
            sys.exit(3)

    # -----------------------------------------------------------------------
    # OUTPUT
    # -----------------------------------------------------------------------
    if len(reports) == 1:
        output = reports[0]
    else:
        output = {
            "all_passed": not any_failed,
            "profiles_validated": len(reports),
            "profiles_passed": sum(1 for r in reports if r["passed"]),
            "profiles_failed": sum(1 for r in reports if not r["passed"]),
            "reports": reports,
        }

    if OUTPUT_JSON:
        print(json.dumps(output, indent=2, default=str))

    if any_failed:
        sys.exit(3)
    sys.exit(0)


if __name__ == "__main__":
    main()
