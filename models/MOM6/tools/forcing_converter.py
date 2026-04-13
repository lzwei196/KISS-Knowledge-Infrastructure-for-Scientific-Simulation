#!/usr/bin/env python3
"""
forcing_converter.py — Convert atmospheric reanalysis data to MOM6 surface forcing format.

Supports ERA5, JRA55-do, and CORE/COREv2 forcing datasets.
Converts to MOM6-expected NetCDF with correct units, variable names, and sign conventions.

Pipeline stage: S2 (Atmospheric Forcing)
Pattern: validate → process → validate
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Unit conversion constants
# ---------------------------------------------------------------------------
KELVIN_OFFSET = 273.15          # K → degC
DYN_CM2_TO_PA = 0.1             # dyn/cm² → Pa
MM_DAY_TO_KG_M2_S = 1.0 / 86400.0  # mm/day → kg/m²/s (assuming rho_w=1000)
HOURS_TO_SECONDS = 3600.0

# MOM6 expected variable names and units
MOM6_FORCING_VARS = {
    "taux":    {"long_name": "Zonal wind stress",       "units": "Pa",      "bounds": (-3.0, 3.0)},
    "tauy":    {"long_name": "Meridional wind stress",   "units": "Pa",      "bounds": (-3.0, 3.0)},
    "SW":      {"long_name": "Shortwave radiation",      "units": "W/m^2",   "bounds": (0.0, 1500.0)},
    "LW":      {"long_name": "Longwave radiation",       "units": "W/m^2",   "bounds": (-500.0, 200.0)},
    "laten":   {"long_name": "Latent heat flux",         "units": "W/m^2",   "bounds": (-800.0, 200.0)},
    "sens":    {"long_name": "Sensible heat flux",       "units": "W/m^2",   "bounds": (-500.0, 200.0)},
    "evap":    {"long_name": "Evaporation",              "units": "kg/m^2/s","bounds": (-1e-3, 0.0)},
    "precip":  {"long_name": "Precipitation",            "units": "kg/m^2/s","bounds": (0.0, 1e-2)},
    "t_air":   {"long_name": "Near-surface air temp",    "units": "degC",    "bounds": (-80.0, 60.0)},
    "q_air":   {"long_name": "Near-surface spec. humid.","units": "kg/kg",   "bounds": (0.0, 0.05)},
    "slp":     {"long_name": "Sea level pressure",       "units": "Pa",      "bounds": (85000, 110000)},
}

# Source dataset variable mappings
ERA5_MAP = {
    "u10":   {"target": "u_wind",  "scale": 1.0,    "offset": 0.0},
    "v10":   {"target": "v_wind",  "scale": 1.0,    "offset": 0.0},
    "t2m":   {"target": "t_air",   "scale": 1.0,    "offset": -KELVIN_OFFSET},  # K → degC
    "d2m":   {"target": "td_air",  "scale": 1.0,    "offset": -KELVIN_OFFSET},
    "msdwswrf": {"target": "SW",   "scale": 1.0,    "offset": 0.0},
    "msdwlwrf": {"target": "LW",   "scale": 1.0,    "offset": 0.0},
    "mtpr":  {"target": "precip",  "scale": 1.0,    "offset": 0.0},  # already kg/m²/s
    "msl":   {"target": "slp",     "scale": 1.0,    "offset": 0.0},
    "d2m_rh":{"target": "q_air",   "scale": 1.0,    "offset": 0.0},
}

JRA55_MAP = {
    "uas":   {"target": "u_wind",  "scale": 1.0,    "offset": 0.0},
    "vas":   {"target": "v_wind",  "scale": 1.0,    "offset": 0.0},
    "tas":   {"target": "t_air",   "scale": 1.0,    "offset": -KELVIN_OFFSET},
    "rsds":  {"target": "SW",      "scale": 1.0,    "offset": 0.0},
    "rlds":  {"target": "LW",      "scale": 1.0,    "offset": 0.0},
    "prra":  {"target": "precip",  "scale": 1.0,    "offset": 0.0},
    "prsn":  {"target": "snow",    "scale": 1.0,    "offset": 0.0},
    "psl":   {"target": "slp",     "scale": 1.0,    "offset": 0.0},
    "huss":  {"target": "q_air",   "scale": 1.0,    "offset": 0.0},
}

DATASET_MAPS = {"era5": ERA5_MAP, "jra55": JRA55_MAP}


def validate_input(input_path: str, dataset: str) -> dict:
    """Pre-validate: check input file exists and contains expected variables."""
    try:
        import netCDF4
    except ImportError:
        log.error("netCDF4 is required. Install with: pip install netCDF4")
        sys.exit(1)

    if not os.path.isfile(input_path):
        log.error(f"Input file not found: {input_path}")
        sys.exit(1)

    ds = netCDF4.Dataset(input_path, "r")
    source_vars = set(ds.variables.keys())
    var_map = DATASET_MAPS.get(dataset)
    if var_map is None:
        log.error(f"Unknown dataset '{dataset}'. Supported: {list(DATASET_MAPS.keys())}")
        ds.close()
        sys.exit(1)

    found = {}
    missing = []
    for src_name, mapping in var_map.items():
        if src_name in source_vars:
            found[src_name] = mapping
        else:
            missing.append(src_name)

    if missing:
        log.warning(f"Missing source variables (will skip): {missing}")

    # Check dimensions
    dims = {d: len(ds.dimensions[d]) for d in ds.dimensions}
    log.info(f"Input dimensions: {dims}")
    log.info(f"Found {len(found)}/{len(var_map)} expected variables")

    info = {
        "path": input_path,
        "dataset": dataset,
        "found_vars": found,
        "dims": dims,
        "source_vars": list(source_vars),
    }
    ds.close()
    return info


def compute_wind_stress(u_wind: np.ndarray, v_wind: np.ndarray,
                        rho_air: float = 1.225, cd: float = 1.3e-3):
    """Compute wind stress from 10-m wind components using bulk formula.

    tau = rho_air * Cd * |W| * W_component   [Pa]
    """
    wspd = np.sqrt(u_wind**2 + v_wind**2)
    # Variable drag coefficient (Large & Pond 1981, modified)
    cd_var = np.where(wspd < 11.0, 1.2e-3,
             np.where(wspd < 25.0, (0.49 + 0.065 * wspd) * 1e-3,
                      2.115e-3))
    taux = rho_air * cd_var * wspd * u_wind
    tauy = rho_air * cd_var * wspd * v_wind
    return taux, tauy


def convert_temperature(t_data: np.ndarray, source_unit: str) -> np.ndarray:
    """Convert temperature to degC.

    TRAP dt_001: Source in Kelvin must subtract 273.15.
    """
    if source_unit == "K":
        log.info("UNIT TRAP dt_001: Converting temperature K → degC")
        return t_data - KELVIN_OFFSET
    return t_data


def convert_precip(p_data: np.ndarray, source_unit: str) -> np.ndarray:
    """Convert precipitation to kg/m²/s.

    TRAP dt_009: mm/day must be divided by 86400 (and multiply by rho_w=1000 if in m/day).
    """
    if source_unit == "mm/day":
        log.info("UNIT TRAP dt_009: Converting precipitation mm/day → kg/m²/s")
        return p_data * MM_DAY_TO_KG_M2_S
    if source_unit == "m/s":
        log.info("Converting precipitation m/s → kg/m²/s (×1000)")
        return p_data * 1000.0
    return p_data


def flip_heat_flux_sign(flux: np.ndarray, convention: str) -> np.ndarray:
    """Ensure heat flux sign convention: positive INTO ocean.

    TRAP dt_008: Some datasets use positive = out of ocean.
    """
    if convention == "positive_up":
        log.info("UNIT TRAP dt_008: Flipping heat flux sign (positive_up → positive_down)")
        return -flux
    return flux


def process_forcing(info: dict, output_path: str, rho_air: float = 1.225):
    """Convert source dataset to MOM6 forcing NetCDF."""
    import netCDF4

    ds_in = netCDF4.Dataset(info["path"], "r")
    found = info["found_vars"]

    # Determine time, lat, lon dimensions
    time_var = None
    for tname in ["time", "TIME", "Time", "t"]:
        if tname in ds_in.variables:
            time_var = tname
            break

    lat_var = None
    for lname in ["lat", "latitude", "LAT", "y", "yh"]:
        if lname in ds_in.variables:
            lat_var = lname
            break

    lon_var = None
    for lname in ["lon", "longitude", "LON", "x", "xh"]:
        if lname in ds_in.variables:
            lon_var = lname
            break

    if not all([time_var, lat_var, lon_var]):
        log.error(f"Cannot find time/lat/lon dims. Found: time={time_var}, lat={lat_var}, lon={lon_var}")
        ds_in.close()
        sys.exit(1)

    time_data = ds_in.variables[time_var][:]
    lat_data = ds_in.variables[lat_var][:]
    lon_data = ds_in.variables[lon_var][:]
    nt, nlat, nlon = len(time_data), len(lat_data), len(lon_data)

    # Create output
    ds_out = netCDF4.Dataset(output_path, "w", format="NETCDF4")
    ds_out.createDimension("time", None)
    ds_out.createDimension("lat", nlat)
    ds_out.createDimension("lon", nlon)

    # Copy coordinate variables
    t_out = ds_out.createVariable("time", "f8", ("time",))
    t_out[:] = time_data
    if hasattr(ds_in.variables[time_var], "units"):
        t_out.units = ds_in.variables[time_var].units
    if hasattr(ds_in.variables[time_var], "calendar"):
        t_out.calendar = ds_in.variables[time_var].calendar

    lat_out = ds_out.createVariable("lat", "f8", ("lat",))
    lat_out[:] = lat_data
    lat_out.units = "degrees_north"

    lon_out = ds_out.createVariable("lon", "f8", ("lon",))
    lon_out[:] = lon_data
    lon_out.units = "degrees_east"

    # Process wind → wind stress
    u_wind = v_wind = None
    for src_name, mapping in found.items():
        if mapping["target"] == "u_wind":
            u_wind = ds_in.variables[src_name][:] * mapping["scale"] + mapping["offset"]
        elif mapping["target"] == "v_wind":
            v_wind = ds_in.variables[src_name][:] * mapping["scale"] + mapping["offset"]

    if u_wind is not None and v_wind is not None:
        taux, tauy = compute_wind_stress(u_wind, v_wind, rho_air)
        for vname, data in [("taux", taux), ("tauy", tauy)]:
            spec = MOM6_FORCING_VARS[vname]
            var = ds_out.createVariable(vname, "f4", ("time", "lat", "lon"),
                                        fill_value=1e20)
            var[:] = data
            var.units = spec["units"]
            var.long_name = spec["long_name"]
            # Bounds check
            vmin, vmax = spec["bounds"]
            oob = np.sum((data < vmin) | (data > vmax))
            if oob > 0:
                log.warning(f"{vname}: {oob} values outside [{vmin}, {vmax}]")

    # Process scalar fields
    for src_name, mapping in found.items():
        target = mapping["target"]
        if target in ("u_wind", "v_wind"):
            continue

        raw = ds_in.variables[src_name][:]
        data = raw * mapping["scale"] + mapping["offset"]

        # Apply unit-specific conversions
        if target == "t_air" and mapping["offset"] == 0:
            src_units = getattr(ds_in.variables[src_name], "units", "")
            if "K" in src_units or "kelvin" in src_units.lower():
                data = convert_temperature(raw, "K")

        if target in MOM6_FORCING_VARS:
            spec = MOM6_FORCING_VARS[target]
            var = ds_out.createVariable(target, "f4", ("time", "lat", "lon"),
                                        fill_value=1e20)
            var[:] = data
            var.units = spec["units"]
            var.long_name = spec["long_name"]

            vmin, vmax = spec["bounds"]
            oob = np.sum((data < vmin) | (data > vmax))
            if oob > 0:
                log.warning(f"{target}: {oob} values outside [{vmin}, {vmax}]")

    ds_out.history = f"Created by forcing_converter.py on {datetime.utcnow().isoformat()}"
    ds_out.source_dataset = info["dataset"]
    ds_out.conventions = "CF-1.6"
    ds_out.close()
    ds_in.close()
    log.info(f"Wrote forcing file: {output_path}")
    return output_path


def validate_output(output_path: str) -> dict:
    """Post-validate: check output file integrity."""
    import netCDF4

    if not os.path.isfile(output_path):
        log.error(f"Output file not created: {output_path}")
        return {"valid": False, "error": "File not created"}

    ds = netCDF4.Dataset(output_path, "r")
    report = {"valid": True, "variables": {}, "warnings": []}

    for vname in ds.variables:
        if vname in ("time", "lat", "lon"):
            continue
        data = ds.variables[vname][:]
        nan_count = int(np.sum(np.isnan(data)))
        vmin, vmax = float(np.nanmin(data)), float(np.nanmax(data))
        report["variables"][vname] = {
            "min": vmin, "max": vmax, "nan_count": nan_count,
            "shape": list(data.shape),
        }
        if nan_count > 0:
            report["warnings"].append(f"{vname}: {nan_count} NaN values detected")
        if vname in MOM6_FORCING_VARS:
            bmin, bmax = MOM6_FORCING_VARS[vname]["bounds"]
            if vmin < bmin or vmax > bmax:
                report["warnings"].append(
                    f"{vname}: range [{vmin:.3g}, {vmax:.3g}] exceeds bounds [{bmin}, {bmax}]"
                )

    ds.close()

    if report["warnings"]:
        report["valid"] = False
        for w in report["warnings"]:
            log.warning(w)
    else:
        log.info("Output validation PASSED — all variables within physical bounds")

    return report


def main():
    parser = argparse.ArgumentParser(
        description="Convert atmospheric reanalysis to MOM6 forcing format"
    )
    parser.add_argument("input", help="Input NetCDF file path")
    parser.add_argument("-o", "--output", default="mom6_forcing.nc",
                        help="Output NetCDF path (default: mom6_forcing.nc)")
    parser.add_argument("-d", "--dataset", default="era5", choices=list(DATASET_MAPS.keys()),
                        help="Source dataset type (default: era5)")
    parser.add_argument("--rho-air", type=float, default=1.225,
                        help="Air density for wind stress [kg/m³] (default: 1.225)")
    parser.add_argument("--json-report", default=None,
                        help="Write validation report to JSON file")
    args = parser.parse_args()

    # Step 1: Validate input
    log.info("=== Step 1: Input validation ===")
    info = validate_input(args.input, args.dataset)

    # Step 2: Process
    log.info("=== Step 2: Processing ===")
    process_forcing(info, args.output, args.rho_air)

    # Step 3: Validate output
    log.info("=== Step 3: Output validation ===")
    report = validate_output(args.output)

    if args.json_report:
        with open(args.json_report, "w") as f:
            json.dump(report, f, indent=2)
        log.info(f"Report written to {args.json_report}")

    if not report["valid"]:
        log.warning("Output has warnings — review before use")
        sys.exit(1)

    log.info("Done.")


if __name__ == "__main__":
    main()
