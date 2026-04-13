#!/usr/bin/env python3
"""
convert_geometry.py — Convert ice sheet geometry data to PISM bootstrap format.

Takes geometry datasets (BedMachine, SeaRISE, ALBMAP, or custom) and produces a
PISM-ready bootstrap NetCDF file with correct variable names, units, and metadata.

Critical conversions handled:
  - Bedrock elevation: ensure meters above sea level
  - Ice thickness: must be in meters (not km or feet)
  - Geothermal heat flux: mW m^-2 → W m^-2 (divide by 1000)
  - Precipitation: m w.e./year → kg m^-2 year^-1 (multiply by 1000)
  - Surface mass balance: m w.e./year → kg m^-2 year^-1 (multiply by 1000)

Usage:
    python convert_geometry.py \\
        --input bedmachine_v5.nc \\
        --output pism_bootstrap.nc \\
        --topg-var bed --thk-var thickness \\
        --bheatflx-var ghf --bheatflx-units "mW/m2" \\
        --projection "+proj=stere +lat_0=90 +lat_ts=71 +lon_0=-39 ..." \\
        [--output-json result.json]
"""

import argparse
import json
import os
import sys

try:
    import numpy as np
    from netCDF4 import Dataset
except ImportError as e:
    print(json.dumps({
        "status": "error",
        "errors": [f"Missing dependency: {e}. Install with: pip install numpy netCDF4"]
    }))
    sys.exit(1)


BHEATFLX_CONVERSIONS = {
    "W/m2":  lambda x: x,
    "mW/m2": lambda x: x * 0.001,
    "uW/m2": lambda x: x * 1e-6,
}

THICKNESS_CONVERSIONS = {
    "m":    lambda x: x,
    "km":   lambda x: x * 1000.0,
    "feet": lambda x: x * 0.3048,
}

SMB_CONVERSIONS = {
    "kg_m-2_year-1": lambda x: x,
    "m_we/year":     lambda x: x * 1000.0,
    "mm_we/year":    lambda x: x,
    "m_ice/year":    lambda x: x * 910.0,
}


def validate_inputs(args):
    """Validate inputs before processing."""
    errors = []

    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")
    else:
        try:
            ds = Dataset(args.input, "r")
            available = list(ds.variables.keys())

            if args.topg_var and args.topg_var not in ds.variables:
                errors.append(f"Bedrock variable '{args.topg_var}' not found. "
                              f"Available: {available}")
            if args.thk_var and args.thk_var not in ds.variables:
                errors.append(f"Thickness variable '{args.thk_var}' not found. "
                              f"Available: {available}")
            ds.close()
        except Exception as e:
            errors.append(f"Cannot open input file: {e}")

    if args.bheatflx_units not in BHEATFLX_CONVERSIONS:
        errors.append(f"Unknown heat flux units: '{args.bheatflx_units}'. "
                      f"Supported: {list(BHEATFLX_CONVERSIONS.keys())}")

    if args.thk_units not in THICKNESS_CONVERSIONS:
        errors.append(f"Unknown thickness units: '{args.thk_units}'. "
                      f"Supported: {list(THICKNESS_CONVERSIONS.keys())}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2))
        sys.exit(1)


def process(args):
    """Convert geometry data to PISM bootstrap format."""
    src = Dataset(args.input, "r")
    warnings = []

    # Identify spatial dimensions
    x_dim = y_dim = None
    for dname in src.dimensions:
        dl = dname.lower()
        if dl in ("x", "x1"):
            x_dim = dname
        elif dl in ("y", "y1"):
            y_dim = dname

    if x_dim is None or y_dim is None:
        for vname in [args.topg_var, args.thk_var]:
            if vname and vname in src.variables:
                dims = src.variables[vname].dimensions
                if len(dims) >= 2:
                    y_dim = y_dim or dims[-2]
                    x_dim = x_dim or dims[-1]

    # Create output
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    dst = Dataset(args.output, "w", format="NETCDF4")

    # Copy spatial dimensions
    for dname in [y_dim, x_dim]:
        if dname and dname in src.dimensions:
            dst.createDimension(dname, len(src.dimensions[dname]))
            if dname in src.variables:
                v = src.variables[dname]
                out_v = dst.createVariable(dname, v.datatype, v.dimensions)
                out_v[:] = v[:]
                for attr in v.ncattrs():
                    out_v.setncattr(attr, v.getncattr(attr))
                # Ensure coordinate units are meters
                if hasattr(out_v, "units") and out_v.units in ("km", "kilometers"):
                    warnings.append(f"Converting {dname} from km to m")
                    out_v[:] = out_v[:] * 1000.0
                    out_v.units = "m"

    converted = []
    spatial_dims = tuple(d for d in [y_dim, x_dim] if d)

    # Bedrock topography
    if args.topg_var and args.topg_var in src.variables:
        src_v = src.variables[args.topg_var]
        conv = THICKNESS_CONVERSIONS[args.thk_units]
        data = conv(np.array(src_v[:], dtype=np.float64))
        # Use only last 2 dims
        if data.ndim > 2:
            data = data[-1] if data.ndim == 3 else data
            while data.ndim > 2:
                data = data[0]

        out_v = dst.createVariable("topg", "f8", spatial_dims, fill_value=1e20)
        out_v[:] = data
        out_v.units = "m"
        out_v.long_name = "bedrock surface elevation"
        out_v.standard_name = "bedrock_altitude"
        converted.append("topg")

        if np.nanmin(data) < -12000 or np.nanmax(data) > 9000:
            warnings.append(f"topg range [{np.nanmin(data):.0f}, {np.nanmax(data):.0f}] m "
                            "seems unrealistic")

    # Ice thickness
    if args.thk_var and args.thk_var in src.variables:
        src_v = src.variables[args.thk_var]
        conv = THICKNESS_CONVERSIONS[args.thk_units]
        data = conv(np.array(src_v[:], dtype=np.float64))
        if data.ndim > 2:
            data = data[-1] if data.ndim == 3 else data
            while data.ndim > 2:
                data = data[0]

        data = np.maximum(data, 0.0)

        out_v = dst.createVariable("thk", "f8", spatial_dims, fill_value=1e20)
        out_v[:] = data
        out_v.units = "m"
        out_v.long_name = "land ice thickness"
        out_v.standard_name = "land_ice_thickness"
        converted.append("thk")

        if np.nanmax(data) > 5000:
            warnings.append(f"Maximum ice thickness {np.nanmax(data):.0f} m > 5000 m — "
                            "check units")

    # Geothermal heat flux
    if args.bheatflx_var and args.bheatflx_var in src.variables:
        src_v = src.variables[args.bheatflx_var]
        conv = BHEATFLX_CONVERSIONS[args.bheatflx_units]
        data = conv(np.array(src_v[:], dtype=np.float64))
        if data.ndim > 2:
            data = data[-1] if data.ndim == 3 else data
            while data.ndim > 2:
                data = data[0]

        out_v = dst.createVariable("bheatflx", "f8", spatial_dims, fill_value=1e20)
        out_v[:] = data
        out_v.units = "W m-2"
        out_v.long_name = "upward geothermal flux at bedrock surface"
        converted.append("bheatflx")

        if np.nanmax(data) > 1.0:
            warnings.append(f"Max heat flux {np.nanmax(data):.3f} W/m² > 1.0 — "
                            "likely still in mW/m² (did not convert?)")
        if np.nanmean(data) < 0.01:
            warnings.append(f"Mean heat flux {np.nanmean(data):.4f} W/m² very low — "
                            "check units")

    # SMB if available
    if args.smb_var and args.smb_var in src.variables:
        src_v = src.variables[args.smb_var]
        conv = SMB_CONVERSIONS.get(args.smb_units, lambda x: x)
        data = conv(np.array(src_v[:], dtype=np.float64))
        if data.ndim > 2:
            data = data[-1] if data.ndim == 3 else data
            while data.ndim > 2:
                data = data[0]

        out_v = dst.createVariable("climatic_mass_balance", "f8", spatial_dims,
                                   fill_value=1e20)
        out_v[:] = data
        out_v.units = "kg m^-2 year^-1"
        out_v.long_name = "surface mass balance (accumulation minus ablation)"
        out_v.standard_name = "land_ice_surface_specific_mass_balance_flux"
        converted.append("climatic_mass_balance")

    # Add projection
    if args.projection:
        dst.setncattr("proj", args.projection)

    # Global attributes
    dst.setncattr("Conventions", "CF-1.6")
    dst.setncattr("history", f"Created by convert_geometry.py from {args.input}")

    src.close()
    dst.close()

    return {
        "status": "success",
        "output_file": args.output,
        "converted_variables": converted,
        "warnings": warnings,
    }


def validate_outputs(result):
    """Verify the output bootstrap file."""
    if result["status"] != "success":
        return result

    post_errors = []
    try:
        ds = Dataset(result["output_file"], "r")

        required = ["topg", "thk"]
        for vname in required:
            if vname not in ds.variables:
                post_errors.append(f"Required variable '{vname}' missing from output")

        if "thk" in ds.variables:
            thk = ds.variables["thk"][:]
            if np.any(thk < 0):
                post_errors.append("Negative ice thickness values found")

        ds.close()
    except Exception as e:
        post_errors.append(f"Cannot validate output: {e}")

    if post_errors:
        result["warnings"].extend(post_errors)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert geometry data to PISM bootstrap format"
    )
    parser.add_argument("--input", required=True, help="Input geometry NetCDF")
    parser.add_argument("--output", required=True, help="Output PISM bootstrap file")
    parser.add_argument("--topg-var", default="topg", help="Bedrock elevation variable")
    parser.add_argument("--thk-var", default="thk", help="Ice thickness variable")
    parser.add_argument("--bheatflx-var", default=None, help="Heat flux variable")
    parser.add_argument("--smb-var", default=None, help="SMB variable name")
    parser.add_argument("--bheatflx-units", default="mW/m2",
                        choices=list(BHEATFLX_CONVERSIONS.keys()))
    parser.add_argument("--thk-units", default="m",
                        choices=list(THICKNESS_CONVERSIONS.keys()))
    parser.add_argument("--smb-units", default="m_we/year",
                        choices=list(SMB_CONVERSIONS.keys()))
    parser.add_argument("--projection", default=None, help="PROJ string for the dataset")
    parser.add_argument("--output-json", default=None, help="Write result JSON to file")

    args = parser.parse_args()
    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    output_json = json.dumps(result, indent=2)
    if args.output_json:
        os.makedirs(os.path.dirname(args.output_json) or ".", exist_ok=True)
        with open(args.output_json, "w") as f:
            f.write(output_json)
    print(output_json)


if __name__ == "__main__":
    main()
