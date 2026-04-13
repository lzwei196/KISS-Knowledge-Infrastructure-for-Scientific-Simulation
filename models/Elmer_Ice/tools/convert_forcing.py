#!/usr/bin/env python3
"""
convert_forcing.py — Convert climate/SMB data to Elmer/Ice boundary conditions.

Reads Surface Mass Balance (SMB), surface temperature, and basal melt data
from global reanalysis or RCM output and writes Elmer-compatible forcing files.

CRITICAL UNIT ISSUES:
  - SMB: Elmer expects m/a ice equivalent. RACMO gives kg/m2/s.
    Conversion: kg/m2/s * (86400*365.25) / 910 = m/a ice eq.
    Using mm w.e./day or kg/m2/a without conversion = SILENT ERROR.
  - Temperature: Elmer uses Celsius in SIF but Kelvin internally.
    RACMO gives Kelvin. Subtract 273.15 for SIF compatibility.
  - Basal melt: m/a ice equivalent, positive = melting.
    Ocean models often give m/a w.e. — divide by (rho_w/rho_i) = 1.126.
  - Geothermal heat flux: W/m2 (= mW/m2 / 1000). Many databases use mW/m2.

Expected input:
  NetCDF with SMB, T2m, or basal melt fields and time dimension.

Expected output:
  ASCII time series or spatial field files for SIF Body Force blocks:
    smb_forcing.dat       — Surface mass balance (m/a ice eq.)
    temperature_forcing.dat — Surface temperature (deg C)
    basal_melt_forcing.dat — Basal melt rate (m/a ice eq.)
    ghf_nodes.dat         — Geothermal heat flux (W/m2)

Usage:
    python convert_forcing.py --smb racmo_smb.nc --temperature racmo_t2m.nc \
        --mesh_dir ./rectangle --output_dir ./forcing \
        --smb_variable SMB_rec --temp_variable t2m \
        --smb_units kg/m2/s --temp_units K
"""

import argparse
import json
import os
import sys

import numpy as np

try:
    import netCDF4 as nc
    HAS_NETCDF = True
except ImportError:
    HAS_NETCDF = False


# Physical constants
RHO_ICE = 910.0       # kg/m3 — ice density
RHO_WATER = 1000.0    # kg/m3 — freshwater density
RHO_OCEAN = 1025.0    # kg/m3 — seawater density
SEC_PER_YEAR = 365.25 * 86400.0  # s/a


def validate_inputs(args):
    """Check all input arguments for validity."""
    errors = []

    if not args.smb and not args.temperature and not args.basal_melt and not args.ghf:
        errors.append("Must provide at least one forcing file "
                      "(--smb, --temperature, --basal_melt, --ghf)")

    for fpath, name in [(args.smb, "SMB"), (args.temperature, "Temperature"),
                        (args.basal_melt, "Basal melt"), (args.ghf, "GHF")]:
        if fpath and not os.path.isfile(fpath):
            errors.append(f"{name} file not found: {fpath}")

    if args.mesh_dir and not os.path.isdir(args.mesh_dir):
        errors.append(f"Mesh directory not found: {args.mesh_dir}")

    valid_smb_units = ["kg/m2/s", "kg/m2/a", "mm_we/day", "m_ie/a"]
    if args.smb_units not in valid_smb_units:
        errors.append(f"SMB units must be one of {valid_smb_units}, got: {args.smb_units}")

    valid_temp_units = ["K", "C"]
    if args.temp_units not in valid_temp_units:
        errors.append(f"Temperature units must be K or C, got: {args.temp_units}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def convert_smb(values, from_units):
    """Convert SMB to m/a ice equivalent.

    CRITICAL: Getting this wrong is the #1 cause of wrong ice thickness evolution.

    Conversions:
      kg/m2/s   → m/a i.e.: multiply by SEC_PER_YEAR / RHO_ICE
      kg/m2/a   → m/a i.e.: divide by RHO_ICE
      mm_we/day → m/a i.e.: multiply by 365.25 / 1000 / (RHO_WATER/RHO_ICE)
      m_ie/a    → m/a i.e.: already correct
    """
    values = np.array(values, dtype=np.float64)
    if from_units == "kg/m2/s":
        return values * SEC_PER_YEAR / RHO_ICE
    elif from_units == "kg/m2/a":
        return values / RHO_ICE
    elif from_units == "mm_we/day":
        return values * 365.25 / 1000.0 * (RHO_WATER / RHO_ICE)
    elif from_units == "m_ie/a":
        return values
    else:
        raise ValueError(f"Unknown SMB units: {from_units}")


def convert_temperature(values, from_units):
    """Convert temperature to Celsius.

    CRITICAL: SIF accepts Celsius. If Kelvin values are used without conversion,
    the Arrhenius enhancement factor will be wildly wrong (silent error).
    """
    values = np.array(values, dtype=np.float64)
    if from_units == "K":
        return values - 273.15
    elif from_units == "C":
        return values
    else:
        raise ValueError(f"Unknown temperature units: {from_units}")


def convert_basal_melt(values, from_units):
    """Convert basal melt to m/a ice equivalent.

    Convention: positive = melting (ice loss).
    Ocean models may use positive = freezing — check sign carefully.
    """
    values = np.array(values, dtype=np.float64)
    if from_units == "m_we/a":
        return values * (RHO_WATER / RHO_ICE)
    elif from_units == "m_ie/a":
        return values
    elif from_units == "kg/m2/s":
        return values * SEC_PER_YEAR / RHO_ICE
    else:
        raise ValueError(f"Unknown basal melt units: {from_units}")


def convert_ghf(values, from_units):
    """Convert geothermal heat flux to W/m2.

    Many databases (Shapiro & Ritzwoller) report mW/m2.
    CRITICAL: Using mW/m2 as W/m2 gives 1000x too much basal heating.
    """
    values = np.array(values, dtype=np.float64)
    if from_units == "mW/m2":
        return values / 1000.0
    elif from_units == "W/m2":
        return values
    else:
        raise ValueError(f"Unknown GHF units: {from_units}")


def read_netcdf_timeseries(filepath, varname):
    """Read spatially-averaged time series from NetCDF."""
    if not HAS_NETCDF:
        print(json.dumps({"status": "error",
                          "errors": ["netCDF4 not installed"]}),
              file=sys.stderr)
        sys.exit(1)

    ds = nc.Dataset(filepath, "r")
    data = ds.variables[varname][:]

    # Find time variable
    time_vals = None
    for tname in ["time", "t", "TIME"]:
        if tname in ds.variables:
            time_vals = ds.variables[tname][:]
            break

    ds.close()

    # If 3D (time, y, x), take spatial mean
    if data.ndim == 3:
        data = np.nanmean(data, axis=(1, 2))
    elif data.ndim == 2:
        data = np.nanmean(data, axis=1)

    return time_vals, np.array(data)


def generate_synthetic_forcing(n_years=100, dt_years=1.0):
    """Generate synthetic forcing for testing.

    Returns dict with SMB, temperature, and time arrays.
    """
    n_steps = int(n_years / dt_years)
    time = np.arange(n_steps) * dt_years

    # Typical Greenland-like values
    smb = np.full(n_steps, 0.3)  # 0.3 m/a ice eq. (accumulation zone)
    # Add seasonal cycle
    smb += 0.1 * np.sin(2 * np.pi * time)

    temperature = -20.0 + 10.0 * np.sin(2 * np.pi * time)  # -30 to -10 C

    basal_melt = np.full(n_steps, 0.0)  # no basal melt
    ghf = np.full(n_steps, 0.06)  # 60 mW/m2

    return {
        "time": time,
        "smb": smb,
        "temperature": temperature,
        "basal_melt": basal_melt,
        "ghf": ghf,
    }


def process(args):
    """Core processing: read, convert, and package forcing data."""
    result = {}

    if args.synthetic:
        data = generate_synthetic_forcing(
            n_years=args.synthetic_years, dt_years=args.dt_years)
        result["time"] = data["time"]
        result["smb"] = data["smb"]
        result["temperature"] = data["temperature"]
        result["basal_melt"] = data["basal_melt"]
        result["ghf"] = data["ghf"]
    else:
        if args.smb:
            time_smb, smb_raw = read_netcdf_timeseries(args.smb, args.smb_variable)
            result["smb"] = convert_smb(smb_raw, args.smb_units)
            result["time"] = time_smb

        if args.temperature:
            time_t, temp_raw = read_netcdf_timeseries(
                args.temperature, args.temp_variable)
            result["temperature"] = convert_temperature(temp_raw, args.temp_units)
            if "time" not in result:
                result["time"] = time_t

        if args.basal_melt:
            time_bm, bm_raw = read_netcdf_timeseries(
                args.basal_melt, args.basal_melt_variable)
            result["basal_melt"] = convert_basal_melt(bm_raw, args.basal_melt_units)
            if "time" not in result:
                result["time"] = time_bm

        if args.ghf:
            _, ghf_raw = read_netcdf_timeseries(args.ghf, args.ghf_variable)
            result["ghf"] = convert_ghf(ghf_raw, args.ghf_units)

    return result


def validate_outputs(result):
    """Check converted forcing data for physical plausibility."""
    warnings = []

    if "smb" in result:
        smb = result["smb"]
        if np.any(np.abs(smb) > 20.0):
            warnings.append(f"SMB has values > 20 m/a ice eq. "
                            f"(max={np.nanmax(np.abs(smb)):.1f}) — likely unit error")
        if np.all(smb > 0):
            warnings.append("SMB is always positive — no ablation zone? Check sign.")
        nan_count = np.sum(np.isnan(smb))
        if nan_count > 0:
            warnings.append(f"SMB has {nan_count} NaN values")

    if "temperature" in result:
        temp = result["temperature"]
        if np.nanmax(temp) > 50.0:
            warnings.append(f"Temperature max = {np.nanmax(temp):.1f} C — "
                            "still in Kelvin?")
        if np.nanmin(temp) < -100.0:
            warnings.append(f"Temperature min = {np.nanmin(temp):.1f} C — "
                            "unrealistically cold")

    if "ghf" in result:
        ghf = result["ghf"]
        if np.nanmax(ghf) > 1.0:
            warnings.append(f"GHF max = {np.nanmax(ghf):.3f} W/m2 — "
                            "still in mW/m2? (typical: 0.04-0.12 W/m2)")

    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)
    return warnings


def write_forcing_file(filepath, time, values, header="# time value"):
    """Write time series forcing file."""
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    with open(filepath, "w") as f:
        f.write(header + "\n")
        for t, v in zip(time, values):
            if np.isnan(v):
                v = 0.0
            f.write(f"{t:.6f} {v:.8e}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Convert climate forcing to Elmer/Ice boundary conditions")
    parser.add_argument("--smb", type=str, default=None,
                        help="NetCDF file with SMB data")
    parser.add_argument("--temperature", type=str, default=None,
                        help="NetCDF file with surface temperature")
    parser.add_argument("--basal_melt", type=str, default=None,
                        help="NetCDF file with basal melt rates")
    parser.add_argument("--ghf", type=str, default=None,
                        help="NetCDF file with geothermal heat flux")
    parser.add_argument("--smb_variable", type=str, default="SMB_rec",
                        help="NetCDF variable name for SMB")
    parser.add_argument("--temp_variable", type=str, default="t2m",
                        help="NetCDF variable name for temperature")
    parser.add_argument("--basal_melt_variable", type=str, default="melt",
                        help="NetCDF variable name for basal melt")
    parser.add_argument("--ghf_variable", type=str, default="ghf",
                        help="NetCDF variable name for GHF")
    parser.add_argument("--smb_units", type=str, default="kg/m2/s",
                        choices=["kg/m2/s", "kg/m2/a", "mm_we/day", "m_ie/a"],
                        help="Input SMB units")
    parser.add_argument("--temp_units", type=str, default="K",
                        choices=["K", "C"],
                        help="Input temperature units")
    parser.add_argument("--basal_melt_units", type=str, default="m_ie/a",
                        choices=["m_we/a", "m_ie/a", "kg/m2/s"],
                        help="Input basal melt units")
    parser.add_argument("--ghf_units", type=str, default="mW/m2",
                        choices=["mW/m2", "W/m2"],
                        help="Input GHF units")
    parser.add_argument("--mesh_dir", type=str, default=None,
                        help="Path to Elmer mesh directory (for spatial fields)")
    parser.add_argument("--output_dir", type=str, required=True,
                        help="Output directory for forcing files")
    parser.add_argument("--synthetic", action="store_true",
                        help="Generate synthetic forcing for testing")
    parser.add_argument("--synthetic_years", type=float, default=100.0,
                        help="Number of years for synthetic forcing")
    parser.add_argument("--dt_years", type=float, default=1.0,
                        help="Timestep in years for synthetic forcing")

    args = parser.parse_args()
    validate_inputs(args)
    result = process(args)
    warnings = validate_outputs(result)

    # Write output files
    os.makedirs(args.output_dir, exist_ok=True)
    files_written = []

    if "smb" in result and "time" in result:
        fp = os.path.join(args.output_dir, "smb_forcing.dat")
        write_forcing_file(fp, result["time"], result["smb"],
                           header="# time(a)  SMB(m/a_ice_eq)")
        files_written.append(fp)

    if "temperature" in result and "time" in result:
        fp = os.path.join(args.output_dir, "temperature_forcing.dat")
        write_forcing_file(fp, result["time"], result["temperature"],
                           header="# time(a)  Temperature(degC)")
        files_written.append(fp)

    if "basal_melt" in result and "time" in result:
        fp = os.path.join(args.output_dir, "basal_melt_forcing.dat")
        write_forcing_file(fp, result["time"], result["basal_melt"],
                           header="# time(a)  BasalMelt(m/a_ice_eq)")
        files_written.append(fp)

    if "ghf" in result:
        fp = os.path.join(args.output_dir, "ghf_nodes.dat")
        ghf_vals = result["ghf"]
        with open(fp, "w") as f:
            f.write("# GHF(W/m2)\n")
            for v in ghf_vals:
                f.write(f"{v:.8e}\n")
        files_written.append(fp)

    status = {
        "status": "success",
        "files_written": files_written,
        "warnings": warnings,
    }

    if "smb" in result:
        status["smb_range"] = [float(np.nanmin(result["smb"])),
                               float(np.nanmax(result["smb"]))]
    if "temperature" in result:
        status["temp_range"] = [float(np.nanmin(result["temperature"])),
                                float(np.nanmax(result["temperature"]))]

    print(json.dumps(status, indent=2), file=sys.stderr)


if __name__ == "__main__":
    main()
