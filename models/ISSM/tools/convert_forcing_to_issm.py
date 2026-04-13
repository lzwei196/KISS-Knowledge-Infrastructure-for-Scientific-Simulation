#!/usr/bin/env python3
"""
convert_forcing_to_issm.py — Convert external forcing data to ISSM input format.

Handles conversion of climate/reanalysis data (RACMO2, MAR, ERA5, CMFD) into
ISSM-compatible surface mass balance (SMB) and basal forcing arrays, with all
necessary unit conversions.

CRITICAL UNIT CONVERSIONS (silent errors if wrong):
  - Temperature: Climate data in °C → ISSM needs K (add 273.15)
  - SMB: Often in mm w.e./yr or kg/m^2/yr → ISSM needs m/yr ice equivalent
    Conversion: kg/m^2/yr ÷ 917 = m/yr ice; mm w.e./yr ÷ 1000 = m w.e./yr ÷ 0.917 = m ice/yr
  - Geothermal flux: Often in mW/m^2 → ISSM needs W/m^2 (divide by 1000)
  - Velocity: Satellite data in m/s → ISSM needs m/yr (multiply by 3.1536e7)

ISSM internal time unit: YEARS (all rates are per year)
ISSM internal temperature unit: KELVIN

Usage:
    python convert_forcing_to_issm.py \
        --smb_file racmo2_smb.nc --smb_var SMB_rec \
        --temp_file racmo2_t2m.nc --temp_var T2m \
        --geothermal_file ghf_shapiro.nc --geothermal_var ghf \
        --mesh_x mesh_x.npy --mesh_y mesh_y.npy \
        --output_dir ./issm_forcing/

    python convert_forcing_to_issm.py \
        --smb_file era5_precip.nc --smb_var tp --smb_units "mm_we_per_yr" \
        --temp_file era5_t2m.nc --temp_var t2m --temp_units "celsius" \
        --output_dir ./issm_forcing/
"""

import argparse
import json
import os
import sys

import numpy as np

try:
    from scipy.interpolate import griddata
except ImportError:
    griddata = None

try:
    from netCDF4 import Dataset as NCDataset
except ImportError:
    NCDataset = None


# =============================================================================
# Constants
# =============================================================================
RHO_ICE = 917.0           # kg/m^3
RHO_WATER = 1000.0        # kg/m^3
SECONDS_PER_YEAR = 3.1536e7
KELVIN_OFFSET = 273.15


# =============================================================================
# Validation
# =============================================================================
def validate_inputs(args):
    """Validate command-line arguments before processing."""
    errors = []
    warnings = []

    # Check input files exist
    if args.smb_file and not os.path.exists(args.smb_file):
        errors.append(f"SMB file not found: {args.smb_file}")
    if args.temp_file and not os.path.exists(args.temp_file):
        errors.append(f"Temperature file not found: {args.temp_file}")
    if args.geothermal_file and not os.path.exists(args.geothermal_file):
        errors.append(f"Geothermal file not found: {args.geothermal_file}")
    if args.velocity_file and not os.path.exists(args.velocity_file):
        errors.append(f"Velocity file not found: {args.velocity_file}")

    # Check mesh files
    if not os.path.exists(args.mesh_x):
        errors.append(f"Mesh x-coordinates not found: {args.mesh_x}")
    if not os.path.exists(args.mesh_y):
        errors.append(f"Mesh y-coordinates not found: {args.mesh_y}")

    # Check dependencies
    if NCDataset is None:
        errors.append("netCDF4 not installed: pip install netCDF4")
    if griddata is None:
        warnings.append("scipy not installed; griddata interpolation unavailable")

    # Validate units
    valid_smb_units = ["m_ice_per_yr", "mm_we_per_yr", "kg_per_m2_per_yr", "m_we_per_yr"]
    if args.smb_units not in valid_smb_units:
        errors.append(f"Invalid --smb_units '{args.smb_units}'. Must be one of: {valid_smb_units}")

    valid_temp_units = ["kelvin", "celsius"]
    if args.temp_units not in valid_temp_units:
        errors.append(f"Invalid --temp_units '{args.temp_units}'. Must be one of: {valid_temp_units}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors, "warnings": warnings}))
        sys.exit(1)
    if warnings:
        for w in warnings:
            print(f"WARNING: {w}", file=sys.stderr)

    return True


def validate_outputs(output_dir, mesh_nv):
    """Validate generated output files."""
    errors = []
    warnings = []

    # Check SMB output
    smb_path = os.path.join(output_dir, "smb.npy")
    if os.path.exists(smb_path):
        smb = np.load(smb_path)
        if smb.shape[0] != mesh_nv:
            errors.append(f"SMB array size {smb.shape[0]} != mesh vertices {mesh_nv}")
        if np.any(np.isnan(smb)):
            warnings.append(f"SMB contains {np.sum(np.isnan(smb))} NaN values")
        if np.max(np.abs(smb)) > 50.0:
            warnings.append(f"SMB max |{np.max(np.abs(smb)):.1f}| m/yr seems unrealistic (>50)")

    # Check temperature output
    temp_path = os.path.join(output_dir, "temperature.npy")
    if os.path.exists(temp_path):
        temp = np.load(temp_path)
        if temp.shape[0] != mesh_nv:
            errors.append(f"Temperature array size {temp.shape[0]} != mesh vertices {mesh_nv}")
        if np.any(temp < 0):
            errors.append(f"Temperature contains negative Kelvin values — likely in Celsius (dt_002)")
        if np.any(temp > 350):
            warnings.append(f"Temperature max {np.max(temp):.1f} K seems unrealistic (>350 K)")
        if np.max(temp) < 100:
            errors.append(f"Temperature max {np.max(temp):.1f} K — likely in Celsius, not Kelvin (dt_002)")

    # Check velocity output
    vx_path = os.path.join(output_dir, "vx.npy")
    if os.path.exists(vx_path):
        vx = np.load(vx_path)
        if np.max(np.abs(vx)) < 1e-3:
            warnings.append("Velocity vx all near zero — may be in m/s instead of m/yr (dt_001)")
        if np.max(np.abs(vx)) > 50000:
            warnings.append("Velocity vx > 50 km/yr — unrealistically fast")

    if errors:
        print(json.dumps({"status": "error", "errors": errors, "warnings": warnings}))
        sys.exit(1)

    return warnings


# =============================================================================
# Unit conversion functions
# =============================================================================
def convert_smb(data, from_units):
    """Convert SMB to ISSM units (m/yr ice equivalent).

    Args:
        data: numpy array of SMB values
        from_units: source unit string

    Returns:
        numpy array in m/yr ice equivalent
    """
    if from_units == "m_ice_per_yr":
        return data
    elif from_units == "mm_we_per_yr":
        # mm w.e./yr → m w.e./yr → m ice/yr
        return (data / 1000.0) * (RHO_WATER / RHO_ICE)
    elif from_units == "kg_per_m2_per_yr":
        # kg/m^2/yr ÷ ρ_ice = m/yr ice
        return data / RHO_ICE
    elif from_units == "m_we_per_yr":
        # m w.e./yr → m ice/yr
        return data * (RHO_WATER / RHO_ICE)
    else:
        raise ValueError(f"Unknown SMB units: {from_units}")


def convert_temperature(data, from_units):
    """Convert temperature to Kelvin.

    Args:
        data: numpy array of temperature values
        from_units: 'celsius' or 'kelvin'

    Returns:
        numpy array in Kelvin
    """
    if from_units == "kelvin":
        return data
    elif from_units == "celsius":
        return data + KELVIN_OFFSET
    else:
        raise ValueError(f"Unknown temperature units: {from_units}")


def convert_geothermal(data, from_units="mW_per_m2"):
    """Convert geothermal heat flux to W/m^2.

    Args:
        data: numpy array of geothermal flux values
        from_units: 'mW_per_m2' or 'W_per_m2'

    Returns:
        numpy array in W/m^2
    """
    if from_units == "W_per_m2":
        return data
    elif from_units == "mW_per_m2":
        return data / 1000.0
    else:
        raise ValueError(f"Unknown geothermal units: {from_units}")


def convert_velocity(data, from_units="m_per_s"):
    """Convert velocity to m/yr.

    Args:
        data: numpy array of velocity values
        from_units: 'm_per_s', 'm_per_day', or 'm_per_yr'

    Returns:
        numpy array in m/yr
    """
    if from_units == "m_per_yr":
        return data
    elif from_units == "m_per_s":
        return data * SECONDS_PER_YEAR
    elif from_units == "m_per_day":
        return data * 365.25
    else:
        raise ValueError(f"Unknown velocity units: {from_units}")


# =============================================================================
# Interpolation
# =============================================================================
def interp_grid_to_mesh(grid_x, grid_y, grid_data, mesh_x, mesh_y, method='linear'):
    """Interpolate from regular grid to unstructured mesh.

    Args:
        grid_x: 1D array of grid x-coordinates
        grid_y: 1D array of grid y-coordinates
        grid_data: 2D array [ny, nx] of field values
        mesh_x: 1D array of mesh vertex x-coordinates
        mesh_y: 1D array of mesh vertex y-coordinates
        method: interpolation method ('linear', 'nearest', 'cubic')

    Returns:
        1D array of interpolated values at mesh vertices
    """
    if griddata is None:
        raise ImportError("scipy.interpolate.griddata required for interpolation")

    gx, gy = np.meshgrid(grid_x, grid_y)
    points = np.column_stack([gx.ravel(), gy.ravel()])
    values = grid_data.ravel()

    # Remove NaN points
    valid = ~np.isnan(values)
    if np.sum(valid) == 0:
        raise ValueError("All grid values are NaN")

    result = griddata(points[valid], values[valid],
                      (mesh_x, mesh_y), method=method)

    # Fill remaining NaNs with nearest neighbor
    nan_mask = np.isnan(result)
    if np.any(nan_mask):
        result_nn = griddata(points[valid], values[valid],
                             (mesh_x[nan_mask], mesh_y[nan_mask]), method='nearest')
        result[nan_mask] = result_nn

    return result


# =============================================================================
# Processing
# =============================================================================
def process_forcing(args):
    """Main processing: load data, convert units, interpolate, save."""
    os.makedirs(args.output_dir, exist_ok=True)

    # Load mesh coordinates
    mesh_x = np.load(args.mesh_x)
    mesh_y = np.load(args.mesh_y)
    mesh_nv = len(mesh_x)
    print(f"Mesh: {mesh_nv} vertices", file=sys.stderr)

    results = {"status": "success", "output_dir": args.output_dir, "fields": []}

    # --- SMB ---
    if args.smb_file:
        print(f"Processing SMB from {args.smb_file}...", file=sys.stderr)
        with NCDataset(args.smb_file) as ds:
            smb_raw = np.array(ds.variables[args.smb_var][:])
            # Average over time if 3D
            if smb_raw.ndim == 3:
                smb_raw = np.nanmean(smb_raw, axis=0)
            grid_x = np.array(ds.variables[args.x_var][:])
            grid_y = np.array(ds.variables[args.y_var][:])

        smb_converted = convert_smb(smb_raw, args.smb_units)
        smb_mesh = interp_grid_to_mesh(grid_x, grid_y, smb_converted, mesh_x, mesh_y)

        np.save(os.path.join(args.output_dir, "smb.npy"), smb_mesh)
        results["fields"].append({
            "name": "smb", "units": "m/yr ice equivalent",
            "min": float(np.nanmin(smb_mesh)), "max": float(np.nanmax(smb_mesh)),
            "mean": float(np.nanmean(smb_mesh))
        })

    # --- Temperature ---
    if args.temp_file:
        print(f"Processing temperature from {args.temp_file}...", file=sys.stderr)
        with NCDataset(args.temp_file) as ds:
            temp_raw = np.array(ds.variables[args.temp_var][:])
            if temp_raw.ndim == 3:
                temp_raw = np.nanmean(temp_raw, axis=0)
            grid_x = np.array(ds.variables[args.x_var][:])
            grid_y = np.array(ds.variables[args.y_var][:])

        temp_converted = convert_temperature(temp_raw, args.temp_units)
        temp_mesh = interp_grid_to_mesh(grid_x, grid_y, temp_converted, mesh_x, mesh_y)

        np.save(os.path.join(args.output_dir, "temperature.npy"), temp_mesh)
        results["fields"].append({
            "name": "temperature", "units": "K",
            "min": float(np.nanmin(temp_mesh)), "max": float(np.nanmax(temp_mesh)),
            "mean": float(np.nanmean(temp_mesh))
        })

    # --- Geothermal flux ---
    if args.geothermal_file:
        print(f"Processing geothermal flux from {args.geothermal_file}...", file=sys.stderr)
        with NCDataset(args.geothermal_file) as ds:
            ghf_raw = np.array(ds.variables[args.geothermal_var][:])
            if ghf_raw.ndim == 3:
                ghf_raw = np.nanmean(ghf_raw, axis=0)
            grid_x = np.array(ds.variables[args.x_var][:])
            grid_y = np.array(ds.variables[args.y_var][:])

        ghf_converted = convert_geothermal(ghf_raw, args.geothermal_units)
        ghf_mesh = interp_grid_to_mesh(grid_x, grid_y, ghf_converted, mesh_x, mesh_y)

        np.save(os.path.join(args.output_dir, "geothermal_flux.npy"), ghf_mesh)
        results["fields"].append({
            "name": "geothermal_flux", "units": "W/m^2",
            "min": float(np.nanmin(ghf_mesh)), "max": float(np.nanmax(ghf_mesh)),
            "mean": float(np.nanmean(ghf_mesh))
        })

    # --- Velocity ---
    if args.velocity_file:
        print(f"Processing velocity from {args.velocity_file}...", file=sys.stderr)
        with NCDataset(args.velocity_file) as ds:
            vx_raw = np.array(ds.variables[args.vx_var][:])
            vy_raw = np.array(ds.variables[args.vy_var][:])
            if vx_raw.ndim == 3:
                vx_raw = np.nanmean(vx_raw, axis=0)
                vy_raw = np.nanmean(vy_raw, axis=0)
            grid_x = np.array(ds.variables[args.x_var][:])
            grid_y = np.array(ds.variables[args.y_var][:])

        vx_converted = convert_velocity(vx_raw, args.velocity_units)
        vy_converted = convert_velocity(vy_raw, args.velocity_units)
        vx_mesh = interp_grid_to_mesh(grid_x, grid_y, vx_converted, mesh_x, mesh_y)
        vy_mesh = interp_grid_to_mesh(grid_x, grid_y, vy_converted, mesh_x, mesh_y)

        np.save(os.path.join(args.output_dir, "vx.npy"), vx_mesh)
        np.save(os.path.join(args.output_dir, "vy.npy"), vy_mesh)
        vel_mesh = np.sqrt(vx_mesh**2 + vy_mesh**2)
        results["fields"].append({
            "name": "velocity", "units": "m/yr",
            "min": float(np.nanmin(vel_mesh)), "max": float(np.nanmax(vel_mesh)),
            "mean": float(np.nanmean(vel_mesh))
        })

    # Validate outputs
    output_warnings = validate_outputs(args.output_dir, mesh_nv)
    results["warnings"] = output_warnings
    print(json.dumps(results, indent=2))


# =============================================================================
# CLI
# =============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Convert external forcing data to ISSM input format")

    # SMB
    parser.add_argument("--smb_file", help="NetCDF file with SMB data")
    parser.add_argument("--smb_var", default="SMB_rec", help="SMB variable name")
    parser.add_argument("--smb_units", default="kg_per_m2_per_yr",
                        choices=["m_ice_per_yr", "mm_we_per_yr", "kg_per_m2_per_yr", "m_we_per_yr"])

    # Temperature
    parser.add_argument("--temp_file", help="NetCDF file with temperature data")
    parser.add_argument("--temp_var", default="T2m", help="Temperature variable name")
    parser.add_argument("--temp_units", default="celsius", choices=["kelvin", "celsius"])

    # Geothermal
    parser.add_argument("--geothermal_file", help="NetCDF file with geothermal flux")
    parser.add_argument("--geothermal_var", default="ghf", help="Geothermal variable name")
    parser.add_argument("--geothermal_units", default="mW_per_m2",
                        choices=["mW_per_m2", "W_per_m2"])

    # Velocity
    parser.add_argument("--velocity_file", help="NetCDF file with velocity data")
    parser.add_argument("--vx_var", default="VX", help="Vx variable name")
    parser.add_argument("--vy_var", default="VY", help="Vy variable name")
    parser.add_argument("--velocity_units", default="m_per_yr",
                        choices=["m_per_yr", "m_per_s", "m_per_day"])

    # Grid coordinate variables
    parser.add_argument("--x_var", default="x", help="Grid x-coordinate variable name")
    parser.add_argument("--y_var", default="y", help="Grid y-coordinate variable name")

    # Mesh
    parser.add_argument("--mesh_x", required=True, help="Path to mesh x-coordinates (.npy)")
    parser.add_argument("--mesh_y", required=True, help="Path to mesh y-coordinates (.npy)")

    # Output
    parser.add_argument("--output_dir", required=True, help="Output directory")

    args = parser.parse_args()
    validate_inputs(args)
    process_forcing(args)


if __name__ == "__main__":
    main()
