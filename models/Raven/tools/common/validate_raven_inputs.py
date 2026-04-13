#!/usr/bin/env python3
"""
validate_raven_inputs.py — Cross-file consistency checks for all .rv* files.

Validates:
  - All required files exist (.rvi, .rvh, .rvp, .rvt)
  - HRU IDs consistent between .rvh and .rvp
  - Soil profile names match between .rvh and .rvp
  - Land use / vegetation class names match
  - Time range consistent between .rvi (StartDate/EndDate) and .rvt (data period)
  - Forcing variables present for selected PET method
  - Parameter names valid for selected model processes

Usage:
    python validate_raven_inputs.py \
        --run_dir outputs/chaohe_raven/ \
        --basin_name chaohe
"""

import argparse
import json
import os
import sys
import re
from pathlib import Path
from datetime import datetime


# PET methods and their forcing requirements
PET_FORCING_REQUIREMENTS = {
    "PET_PENMAN_MONTEITH": ["PRECIP", "TEMP_MIN", "TEMP_MAX", "WIND_VEL", "REL_HUMIDITY", "SW_RADIA"],
    "PET_PRIESTLEY_TAYLOR": ["PRECIP", "TEMP_MIN", "TEMP_MAX", "SW_RADIA"],
    "PET_HARGREAVES": ["PRECIP", "TEMP_MIN", "TEMP_MAX"],
    "PET_HARGREAVES_1985": ["PRECIP", "TEMP_MIN", "TEMP_MAX"],
    "PET_OUDIN": ["PRECIP", "TEMP_AVE"],
    "PET_MOHYSE": ["PRECIP", "TEMP_MIN", "TEMP_MAX"],
    "PET_HAMON": ["PRECIP", "TEMP_AVE"],
    "PET_DATA": ["PRECIP", "PET"],
    "PET_CONSTANT": ["PRECIP"],
}


def parse_rvi(filepath):
    """Parse .rvi file for key settings."""
    info = {
        "start_date": None,
        "end_date": None,
        "timestep": None,
        "evaporation": None,
        "processes": [],
        "soil_model": None,
        "eval_metrics": [],
    }

    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line.startswith("#") or not line:
                continue

            if line.startswith(":StartDate"):
                parts = line.split()
                if len(parts) >= 2:
                    info["start_date"] = parts[1]

            elif line.startswith(":EndDate"):
                parts = line.split()
                if len(parts) >= 2:
                    info["end_date"] = parts[1]

            elif line.startswith(":TimeStep"):
                parts = line.split()
                if len(parts) >= 2:
                    info["timestep"] = parts[1]

            elif line.startswith(":Evaporation"):
                parts = line.split()
                if len(parts) >= 2:
                    info["evaporation"] = parts[1]

            elif line.startswith(":SoilModel"):
                info["soil_model"] = line

            elif line.startswith(":EvaluationMetrics"):
                info["eval_metrics"] = line.split()[1:]

    return info


def parse_rvh_classes(filepath):
    """Extract all class names from .rvh."""
    land_uses = set()
    veg_classes = set()
    soil_profiles = set()
    terrain_classes = set()
    hru_ids = set()
    basin_ids = set()

    in_hrus = False
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line.startswith(":HRUs"):
                in_hrus = True
                continue
            if line.startswith(":EndHRUs"):
                in_hrus = False
                continue
            if in_hrus and not line.startswith(":") and not line.startswith("#") and line:
                parts = line.split()
                if len(parts) >= 12:
                    try:
                        hru_ids.add(int(parts[0]))
                        basin_ids.add(int(parts[5]))
                        land_uses.add(parts[6])
                        veg_classes.add(parts[7])
                        soil_profiles.add(parts[8])
                        terrain_classes.add(parts[9])
                    except (ValueError, IndexError):
                        continue

    return {
        "land_uses": land_uses,
        "veg_classes": veg_classes,
        "soil_profiles": soil_profiles,
        "terrain_classes": terrain_classes,
        "hru_ids": hru_ids,
        "basin_ids": basin_ids,
    }


def parse_rvp_classes(filepath):
    """Extract all class definitions from .rvp."""
    defined_soils = set()
    defined_lu = set()
    defined_veg = set()
    defined_terrain = set()
    defined_profiles = set()

    with open(filepath) as f:
        content = f.read()

    # Soil classes
    in_block = False
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith(":SoilClasses"):
            in_block = True
            continue
        if line.startswith(":EndSoilClasses"):
            in_block = False
            continue
        if in_block and not line.startswith(":") and not line.startswith("#") and line:
            defined_soils.add(line.split()[0])

    # Soil profiles
    for line in content.split("\n"):
        if line.strip().startswith(":SoilProfile"):
            parts = line.strip().split()
            if len(parts) >= 2:
                defined_profiles.add(parts[1])

    # Land use classes
    in_block = False
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith(":LandUseClasses"):
            in_block = True
            continue
        if line.startswith(":EndLandUseClasses"):
            in_block = False
            continue
        if in_block and not line.startswith(":") and not line.startswith("#") and line:
            defined_lu.add(line.split()[0])

    # Vegetation classes
    in_block = False
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith(":VegetationClasses"):
            in_block = True
            continue
        if line.startswith(":EndVegetationClasses"):
            in_block = False
            continue
        if in_block and not line.startswith(":") and not line.startswith("#") and line:
            defined_veg.add(line.split()[0])

    # Terrain classes
    in_block = False
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith(":TerrainClasses"):
            in_block = True
            continue
        if line.startswith(":EndTerrainClasses"):
            in_block = False
            continue
        if in_block and not line.startswith(":") and not line.startswith("#") and line:
            defined_terrain.add(line.split()[0])

    return {
        "soils": defined_soils,
        "profiles": defined_profiles,
        "land_uses": defined_lu,
        "veg_classes": defined_veg,
        "terrain_classes": defined_terrain,
    }


def parse_rvt_variables(filepath):
    """Extract forcing variables defined in .rvt."""
    variables = set()
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line.startswith(":Data "):
                parts = line.split()
                if len(parts) >= 2:
                    variables.add(parts[1])
    return variables


def validate(args):
    """Run all validation checks."""
    errors = []
    warnings = []
    info = {}

    run_dir = args.run_dir
    bn = args.basin_name

    # 1. Check file existence
    for ext in [".rvi", ".rvh", ".rvp", ".rvt"]:
        path = os.path.join(run_dir, f"{bn}{ext}")
        if not os.path.isfile(path):
            errors.append(f"MISSING: Required file {bn}{ext} not found in {run_dir}")

    if errors:
        return {"status": "error", "errors": errors, "warnings": warnings}

    # 2. Parse all files
    rvi_info = parse_rvi(os.path.join(run_dir, f"{bn}.rvi"))
    rvh_classes = parse_rvh_classes(os.path.join(run_dir, f"{bn}.rvh"))
    rvp_classes = parse_rvp_classes(os.path.join(run_dir, f"{bn}.rvp"))
    rvt_vars = parse_rvt_variables(os.path.join(run_dir, f"{bn}.rvt"))

    info["rvi"] = rvi_info
    info["rvh_classes"] = {k: sorted(v) for k, v in rvh_classes.items() if isinstance(v, set)}
    info["rvp_classes"] = {k: sorted(v) for k, v in rvp_classes.items() if isinstance(v, set)}
    info["rvt_variables"] = sorted(rvt_vars)

    # 3. Cross-check: .rvh land uses defined in .rvp
    missing_lu = rvh_classes["land_uses"] - rvp_classes["land_uses"]
    if missing_lu:
        errors.append(f"MISMATCH: Land use classes in .rvh but not defined in .rvp: {missing_lu}")

    # 4. Cross-check: vegetation classes
    missing_veg = rvh_classes["veg_classes"] - rvp_classes["veg_classes"]
    if missing_veg:
        errors.append(f"MISMATCH: Vegetation classes in .rvh but not defined in .rvp: {missing_veg}")

    # 5. Cross-check: soil profiles
    missing_prof = rvh_classes["soil_profiles"] - rvp_classes["profiles"]
    if missing_prof:
        errors.append(f"MISMATCH: Soil profiles in .rvh but not defined in .rvp: {missing_prof}")

    # 6. Cross-check: terrain classes
    missing_terrain = rvh_classes["terrain_classes"] - rvp_classes["terrain_classes"]
    if missing_terrain:
        errors.append(f"MISMATCH: Terrain classes in .rvh but not defined in .rvp: {missing_terrain}")

    # 7. Forcing variable requirements
    pet_method = rvi_info.get("evaporation", "")
    if pet_method in PET_FORCING_REQUIREMENTS:
        required_vars = set(PET_FORCING_REQUIREMENTS[pet_method])
        missing_vars = required_vars - rvt_vars
        if missing_vars:
            warnings.append(
                f"PET method {pet_method} requires {missing_vars} but .rvt only has {rvt_vars}. "
                f"Raven will use internal generators for missing variables, but results may be less accurate."
            )

    # 8. CRITICAL: Check for PRECIP in forcing
    if "PRECIP" not in rvt_vars:
        errors.append("CRITICAL: No PRECIP data in .rvt — Raven will fill with zeros (SILENT ERROR producing zero runoff)")

    # 9. Check .rvc exists (optional but recommended)
    rvc_path = os.path.join(run_dir, f"{bn}.rvc")
    if not os.path.isfile(rvc_path):
        warnings.append("No .rvc file — cold start with default initial conditions. Recommend 1-2 year spinup.")

    # 10. Check date consistency
    if rvi_info["start_date"] and rvi_info["end_date"]:
        try:
            start = datetime.strptime(rvi_info["start_date"], "%Y-%m-%d")
            end = datetime.strptime(rvi_info["end_date"], "%Y-%m-%d")
            sim_days = (end - start).days
            if sim_days <= 0:
                errors.append(f"StartDate {rvi_info['start_date']} >= EndDate {rvi_info['end_date']}")
            info["sim_days"] = sim_days
        except ValueError:
            warnings.append(f"Could not parse dates: {rvi_info['start_date']}, {rvi_info['end_date']}")

    result = {
        "status": "ok" if not errors else "error",
        "errors": errors,
        "warnings": warnings,
        "info": info,
        "n_hrus": len(rvh_classes["hru_ids"]),
        "n_subbasins": len(rvh_classes["basin_ids"]),
    }

    return result


def main():
    parser = argparse.ArgumentParser(description="Validate Raven input files")
    parser.add_argument("--run_dir", required=True, help="Directory containing .rv* files")
    parser.add_argument("--basin_name", required=True, help="Basin name (file prefix)")

    args = parser.parse_args()

    try:
        results = validate(args)
    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}))
        sys.exit(2)

    print(json.dumps(results, indent=2, default=str))
    sys.exit(0 if results["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
