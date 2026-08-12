#!/usr/bin/env python3
"""
generate_control_file.py — Generate PRMS control file.

The control file is the master configuration for a PRMS simulation. It specifies:
  - Simulation period (start/end time)
  - Input file paths (parameter file, data file, CBH files)
  - Module selection (temp, precip, ET, runoff, routing methods)
  - Output options (CSV, NetCDF, summary statistics)
  - Model flags (cascade, depression storage, etc.)

CRITICAL:
  - Type codes: 1=long, 2=float, 3=double, 4=string
  - start_time/end_time are arrays of 6 longs: year, month, day, hour, min, sec
  - File paths are type 4 (string)

Usage:
  python generate_control_file.py \\
    --output_file /path/to/control \\
    --param_file /path/to/prms.params \\
    --data_file /path/to/prms.data \\
    --start_date 1980-10-01 \\
    --end_date 2010-09-30 \\
    --temp_module climate_hru \\
    --precip_module climate_hru \\
    --et_module potet_jh
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Module choices and defaults
# ---------------------------------------------------------------------------
VALID_MODULES = {
    "temp_module": ["temp_1sta", "temp_laps", "temp_dist2", "climate_hru",
                    "ide_dist", "xyz_dist"],
    "precip_module": ["precip_1sta", "precip_laps", "precip_dist2", "climate_hru",
                      "ide_dist", "xyz_dist"],
    "et_module": ["potet_jh", "potet_hamon", "potet_hs", "potet_pt", "potet_pm",
                  "potet_pm_sta", "potet_pan", "climate_hru"],
    "solrad_module": ["ddsolrad", "ccsolrad", "climate_hru"],
    "srunoff_module": ["srunoff_smidx", "srunoff_carea"],
    "strmflow_module": ["strmflow", "strmflow_in_out", "muskingum", "muskingum_lake"],
    "transp_module": ["transp_tindex", "transp_frost", "climate_hru"],
    "soilzone_module": ["soilzone"],
}

DEFAULT_MODULES = {
    "temp_module": "climate_hru",
    "precip_module": "climate_hru",
    "et_module": "potet_jh",
    "solrad_module": "ddsolrad",
    "srunoff_module": "srunoff_smidx",
    "strmflow_module": "strmflow",
    "transp_module": "transp_tindex",
    "soilzone_module": "soilzone",
}


def validate_inputs(output_file: str, param_file: str, data_file: str,
                    start_date: str, end_date: str, modules: dict) -> dict:
    """Validate all inputs before generating control file.

    Returns dict with validated parameters.
    Raises ValueError on critical errors.
    """
    issues = []

    # Validate dates
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError as e:
        raise ValueError(f"Date format error (use YYYY-MM-DD): {e}")

    if end_dt <= start_dt:
        raise ValueError(f"end_date must be after start_date")

    # Check file paths exist
    if param_file and not Path(param_file).exists():
        issues.append(f"Parameter file not found: {param_file}")

    if data_file and not Path(data_file).exists():
        issues.append(f"Data file not found: {data_file}")

    # Validate module choices
    for mod_name, mod_value in modules.items():
        if mod_name in VALID_MODULES and mod_value not in VALID_MODULES[mod_name]:
            raise ValueError(
                f"Invalid {mod_name}: {mod_value}. "
                f"Valid: {VALID_MODULES[mod_name]}"
            )

    return {
        "start_dt": start_dt,
        "end_dt": end_dt,
        "issues": issues,
    }


def build_control_variables(start_dt: datetime, end_dt: datetime,
                            param_file: str, data_file: str,
                            modules: dict, cbh_dir: str = None,
                            output_dir: str = None,
                            csv_output: bool = True,
                            print_debug: int = -1) -> list:
    """Build ordered list of control variables.

    Returns list of (key, size, type_code, values) tuples.
    """
    variables = []

    # --- Time period ---
    variables.append(("start_time", 6, 1,
                      [start_dt.year, start_dt.month, start_dt.day, 0, 0, 0]))
    variables.append(("end_time", 6, 1,
                      [end_dt.year, end_dt.month, end_dt.day, 0, 0, 0]))

    # --- File paths ---
    variables.append(("param_file", 1, 4, [param_file]))
    variables.append(("data_file", 1, 4, [data_file or "./prms.data"]))

    # --- Model mode ---
    variables.append(("model_mode", 1, 4, ["PRMS"]))

    # --- Module selection ---
    for mod_name, default_val in DEFAULT_MODULES.items():
        mod_val = modules.get(mod_name, default_val)
        variables.append((mod_name, 1, 4, [mod_val]))

    # --- CBH files (for climate_hru module) ---
    if modules.get("temp_module") == "climate_hru" or \
       modules.get("precip_module") == "climate_hru":
        cbh = cbh_dir or "."
        if modules.get("temp_module") == "climate_hru":
            variables.append(("tmax_day", 1, 4, [os.path.join(cbh, "tmax.cbh")]))
            variables.append(("tmin_day", 1, 4, [os.path.join(cbh, "tmin.cbh")]))
        if modules.get("precip_module") == "climate_hru":
            variables.append(("precip_day", 1, 4, [os.path.join(cbh, "precip.cbh")]))

    # --- Output options ---
    out_dir = output_dir or "."
    model_output = os.path.join(out_dir, "prms.out")
    csv_file = os.path.join(out_dir, "prms_summary.csv")

    variables.append(("model_output_file", 1, 4, [model_output]))
    variables.append(("csv_output_file", 1, 4, [csv_file]))
    variables.append(("csvON_OFF", 1, 1, [1 if csv_output else 0]))

    # --- Basin summary output ---
    # PRMS basin_summary module ABORTS ("ERROR, basin_summary requested with
    # basinOutVars equal 0") and read_error's on basinOutBaseFileName unless ALL
    # of basinOutVars / basinOutVar_names / basinOut_freq / basinOutBaseFileName
    # are supplied whenever basinOutON_OFF=1. The previous version of this tool
    # emitted only the ON_OFF flag, so every generated control crashed the binary.
    # The four variables below restore the proven working configuration (matches
    # the shipped nuxia example control). basinOutVar_names MUST be scalar DOUBLE
    # PRMS variables; basin_cfs/basin_ppt/basin_actet/basin_potet all qualify.
    basin_out_vars = ["basin_cfs", "basin_ppt", "basin_actet", "basin_potet"]
    basin_summary_base = os.path.join(out_dir, "basin_summary")
    variables.append(("basinOutON_OFF", 1, 1, [1]))
    variables.append(("basinOutVars", 1, 1, [len(basin_out_vars)]))
    variables.append(("basinOutVar_names", len(basin_out_vars), 4, basin_out_vars))
    variables.append(("basinOut_freq", 1, 1, [1]))  # 1 = daily
    variables.append(("basinOutBaseFileName", 1, 4, [basin_summary_base]))

    variables.append(("nhruOutON_OFF", 1, 1, [0]))
    variables.append(("nsegmentOutON_OFF", 1, 1, [0]))
    variables.append(("NsubOutON_OFF", 1, 1, [0]))
    variables.append(("mapOutON_OFF", 1, 1, [0]))
    variables.append(("statsON_OFF", 1, 1, [0]))
    variables.append(("print_debug", 1, 1, [print_debug]))

    # --- Model flags ---
    variables.append(("cascade_flag", 1, 1, [0]))
    variables.append(("cascadegw_flag", 1, 1, [0]))
    variables.append(("subbasin_flag", 1, 1, [0]))
    variables.append(("dprst_flag", 1, 1, [0]))
    variables.append(("parameter_check_flag", 1, 1, [1]))
    variables.append(("cbh_check_flag", 1, 1, [1]))
    variables.append(("cbh_binary_flag", 1, 1, [0]))
    variables.append(("stream_temp_flag", 1, 1, [0]))

    # --- State save/restore ---
    variables.append(("init_vars_from_file", 1, 1, [0]))
    variables.append(("save_vars_to_file", 1, 1, [0]))

    # --- Initial delta t ---
    variables.append(("initial_deltat", 1, 2, [24.0]))

    # --- Warmup period ---
    variables.append(("prms_warmup", 1, 1, [1]))

    return variables


def write_control_file(output_file: str, variables: list) -> str:
    """Write PRMS control file.

    Format: header line, then #### delimited blocks with key, size, type, values.
    """
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, "w") as f:
        f.write("PRMS control file generated by generate_control_file.py\n")

        for key, size, type_code, values in variables:
            f.write("####\n")
            f.write(f"{key}\n")
            f.write(f"{size}\n")
            f.write(f"{type_code}\n")
            for v in values:
                f.write(f"{v}\n")

    print(f"[write] Control file: {output_file}")
    print(f"[write] {len(variables)} control variables")
    return output_file


def validate_outputs(output_file: str, variables: list) -> list:
    """Post-write validation."""
    warnings = []

    if not Path(output_file).exists():
        warnings.append("ERROR: Control file was not created")
        return warnings

    # Check for common issues
    var_dict = {v[0]: v[3] for v in variables}

    if "param_file" in var_dict:
        pf = var_dict["param_file"][0]
        if not Path(pf).exists():
            warnings.append(f"WARNING: param_file does not exist: {pf}")

    if "data_file" in var_dict:
        df = var_dict["data_file"][0]
        if not Path(df).exists():
            warnings.append(f"NOTE: data_file does not exist yet: {df}")

    # Check CBH files
    for cbh_key in ["tmax_day", "tmin_day", "precip_day"]:
        if cbh_key in var_dict:
            cbh_path = var_dict[cbh_key][0]
            if not Path(cbh_path).exists():
                warnings.append(f"NOTE: CBH file does not exist yet: {cbh_path}")

    for w in warnings:
        print(f"  {w}")

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Generate PRMS control file"
    )
    parser.add_argument("--output_file", required=True, help="Output control file path")
    parser.add_argument("--param_file", required=True, help="Path to parameter file")
    parser.add_argument("--data_file", default=None, help="Path to data file")
    parser.add_argument("--start_date", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end_date", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--cbh_dir", default=None, help="Directory with CBH files")
    parser.add_argument("--output_dir", default=None, help="Directory for model output")

    # Module options
    for mod_name, default_val in DEFAULT_MODULES.items():
        parser.add_argument(f"--{mod_name}", default=default_val,
                            help=f"{mod_name} (default: {default_val})")

    parser.add_argument("--csv_output", action="store_true", default=True,
                        help="Enable CSV output")
    parser.add_argument("--print_debug", type=int, default=-1,
                        help="Debug print level (-2=none, -1=minimal, 0-5=increasing)")
    args = parser.parse_args()

    print("=" * 60)
    print("PRMS Control File Generator")
    print("=" * 60)

    # Collect module choices
    modules = {}
    for mod_name in DEFAULT_MODULES:
        modules[mod_name] = getattr(args, mod_name)

    # Step 1: Validate
    validated = validate_inputs(
        args.output_file, args.param_file, args.data_file,
        args.start_date, args.end_date, modules
    )

    for issue in validated["issues"]:
        print(f"  {issue}")

    # Step 2: Build control variables
    print("\n--- Building control variables ---")
    variables = build_control_variables(
        validated["start_dt"], validated["end_dt"],
        args.param_file, args.data_file,
        modules, args.cbh_dir, args.output_dir,
        args.csv_output, args.print_debug
    )

    # Step 3: Write
    print("\n--- Writing control file ---")
    write_control_file(args.output_file, variables)

    # Step 4: Validate output
    print("\n--- Validating ---")
    warnings = validate_outputs(args.output_file, variables)

    if warnings:
        print(f"\n*** {len(warnings)} notes/warnings ***")
    else:
        print("\nControl file generated successfully.")


if __name__ == "__main__":
    main()
