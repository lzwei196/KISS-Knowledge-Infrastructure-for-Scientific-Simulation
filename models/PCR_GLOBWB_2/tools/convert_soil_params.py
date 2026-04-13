#!/usr/bin/env python3
"""
PCR-GLOBWB 2 Soil/Parameter Converter
=======================================
Converts soil data from HWSD (Harmonized World Soil Database), SoilGrids,
or other sources to PCR-GLOBWB 2 parameter format.

Pipeline stage: s3 (Soil/Parameter Setup)
Pattern: validate_inputs → process → validate_outputs

PCR-GLOBWB expects soil parameters in NetCDF format:
  - soilPropertiesNC: saturatedConductivity, porosity, matricSuction, etc.
  - topographyNC: tanslope, slopeLength, orographyBeta
  - groundwaterPropertiesNC: specificYield, kSatAquifer, recessionCoeff

Unit traps:
  dt_004: Soil storage must be in meters, not mm
  dt_007: Specific yield must be fraction (0-1), not percentage
  dt_008: kSat aquifer must be m/day, not cm/hr
"""

import os
import sys
import argparse
import logging
from datetime import datetime

import numpy as np

try:
    import netCDF4 as nc
except ImportError:
    nc = None

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inputs(input_nc, input_type):
    """Validate input soil data files."""
    errors = []

    if input_nc and not os.path.exists(input_nc):
        errors.append(f"Input file not found: {input_nc}")

    valid_types = ["hwsd", "soilgrids", "custom_soil", "custom_topo", "custom_gw"]
    if input_type not in valid_types:
        errors.append(f"Unknown input type '{input_type}'. Valid: {valid_types}")

    if errors:
        for e in errors:
            logger.error(e)
        raise ValueError(f"Input validation failed: {len(errors)} error(s)")

    logger.info("Input validation passed.")
    return True


def validate_outputs(output_nc, param_type):
    """Validate output parameter NetCDF files."""
    if nc is None:
        logger.warning("netCDF4 not available; skipping output validation.")
        return True

    if not os.path.exists(output_nc):
        raise FileNotFoundError(f"Output file not created: {output_nc}")

    warnings = []
    errors = []

    with nc.Dataset(output_nc, "r") as ds:
        variables = list(ds.variables.keys())
        logger.info(f"Output variables: {variables}")

        if param_type == "soil":
            # Check soil properties
            for required_var in ["Ksat", "porosity"]:
                found = False
                for v in variables:
                    if required_var.lower() in v.lower():
                        found = True
                        data = ds.variables[v][:]
                        valid = data[~np.isnan(data)]
                        if len(valid) > 0:
                            vmin, vmax = float(np.min(valid)), float(np.max(valid))
                            logger.info(f"  {v}: range [{vmin:.6f}, {vmax:.6f}]")

                            # dt_007: Specific yield check
                            if "yield" in v.lower() or "porosity" in v.lower():
                                if vmax > 1.0:
                                    warnings.append(
                                        f"dt_007: {v} max={vmax:.2f} > 1.0 — "
                                        f"likely in percentage, should be fraction"
                                    )
                        break

            # dt_008: kSat check
            for v in variables:
                if "ksat" in v.lower() or "conductivity" in v.lower():
                    data = ds.variables[v][:]
                    valid = data[~np.isnan(data)]
                    if len(valid) > 0:
                        vmax = float(np.max(valid))
                        if vmax > 1000:
                            warnings.append(
                                f"dt_008: {v} max={vmax:.1f} — "
                                f"suspiciously high for m/day. Check units."
                            )

        elif param_type == "groundwater":
            for v in variables:
                if "recession" in v.lower():
                    data = ds.variables[v][:]
                    valid = data[~np.isnan(data)]
                    if len(valid) > 0:
                        vmin = float(np.min(valid))
                        if vmin < 0:
                            errors.append(f"Recession coefficient negative: min={vmin}")

    for w in warnings:
        logger.warning(w)
    for e in errors:
        logger.error(e)

    if errors:
        raise ValueError(f"Output validation failed: {len(errors)} error(s)")

    logger.info("Output validation passed.")
    return True


# ---------------------------------------------------------------------------
# HWSD conversion
# ---------------------------------------------------------------------------

def _hwsd_texture_to_ksat(sand_pct, clay_pct):
    """Convert HWSD sand/clay percentages to saturated hydraulic conductivity.

    Uses Cosby et al. (1984) pedotransfer function:
        log10(Ksat) = -0.60 + 0.0126*sand - 0.0064*clay
        Ksat in inches/hour → convert to m/day

    Returns Ksat in m/day.
    """
    log_ksat_inhr = -0.60 + 0.0126 * sand_pct - 0.0064 * clay_pct
    ksat_inhr = 10.0 ** log_ksat_inhr
    # inches/hour to m/day: 1 inch = 0.0254 m, 24 hours/day
    ksat_mday = ksat_inhr * 0.0254 * 24.0
    return ksat_mday


def _hwsd_texture_to_porosity(sand_pct, clay_pct):
    """Convert HWSD texture to porosity.

    Uses Cosby et al. (1984):
        porosity = 0.489 - 0.00126*sand (fraction)
    """
    porosity = 0.489 - 0.00126 * sand_pct
    return np.clip(porosity, 0.1, 0.8)


def _hwsd_texture_to_matric_suction(sand_pct, clay_pct):
    """Convert HWSD texture to air entry matric suction.

    Uses Cosby et al. (1984):
        log10(psi_s) = 1.54 - 0.0095*sand + 0.0063*silt
        psi_s in cm of water → convert to m
    """
    silt_pct = 100.0 - sand_pct - clay_pct
    log_psi = 1.54 - 0.0095 * sand_pct + 0.0063 * silt_pct
    psi_cm = 10.0 ** log_psi
    return psi_cm / 100.0  # cm -> m


def convert_hwsd_to_pcrglobwb(input_nc, output_nc, layer="upper"):
    """Convert HWSD soil texture data to PCR-GLOBWB soil parameters.

    Args:
        input_nc: HWSD NetCDF with T_SAND, T_CLAY (topsoil) or S_SAND, S_CLAY (subsoil)
        output_nc: Output NetCDF with Ksat, porosity, matricSuction
        layer: 'upper' for topsoil, 'lower' for subsoil
    """
    if nc is None:
        raise ImportError("netCDF4 required for HWSD conversion")

    prefix = "T_" if layer == "upper" else "S_"

    with nc.Dataset(input_nc, "r") as src:
        sand_var = prefix + "SAND"
        clay_var = prefix + "CLAY"

        if sand_var not in src.variables or clay_var not in src.variables:
            available = list(src.variables.keys())
            raise KeyError(
                f"Variables {sand_var}/{clay_var} not found. Available: {available}"
            )

        sand = src.variables[sand_var][:].astype(np.float64)
        clay = src.variables[clay_var][:].astype(np.float64)

        lat = src.variables.get("lat", src.variables.get("latitude"))
        lon = src.variables.get("lon", src.variables.get("longitude"))

        # Compute derived parameters
        ksat = _hwsd_texture_to_ksat(sand, clay)
        porosity = _hwsd_texture_to_porosity(sand, clay)
        matric = _hwsd_texture_to_matric_suction(sand, clay)

        # Write output
        with nc.Dataset(output_nc, "w", format="NETCDF4") as dst:
            # Dimensions
            if lat is not None:
                lat_name = "lat" if "lat" in src.variables else "latitude"
                dst.createDimension(lat_name, len(lat))
                lat_out = dst.createVariable(lat_name, "f8", (lat_name,))
                lat_out[:] = lat[:]

            if lon is not None:
                lon_name = "lon" if "lon" in src.variables else "longitude"
                dst.createDimension(lon_name, len(lon))
                lon_out = dst.createVariable(lon_name, "f8", (lon_name,))
                lon_out[:] = lon[:]

            dims = tuple(d for d in [lat_name, lon_name] if d)

            # Ksat
            v = dst.createVariable("saturatedConductivity", "f4", dims, fill_value=1e20)
            v[:] = ksat
            v.units = "m.day-1"
            v.long_name = "saturated hydraulic conductivity"

            # Porosity
            v = dst.createVariable("porosity", "f4", dims, fill_value=1e20)
            v[:] = porosity
            v.units = "m3.m-3"
            v.long_name = "soil porosity"

            # Matric suction
            v = dst.createVariable("matricSuction", "f4", dims, fill_value=1e20)
            v[:] = matric
            v.units = "m"
            v.long_name = "air entry matric suction"

            dst.description = f"PCR-GLOBWB soil parameters ({layer} layer)"
            dst.source = f"Derived from HWSD: {input_nc}"
            dst.history = f"Created {datetime.now().isoformat()}"

    logger.info(f"HWSD -> PCR-GLOBWB soil params written to {output_nc}")
    logger.info(f"  Ksat range: {float(np.nanmin(ksat)):.4f} - {float(np.nanmax(ksat)):.4f} m/day")
    logger.info(f"  Porosity range: {float(np.nanmin(porosity)):.3f} - {float(np.nanmax(porosity)):.3f}")


def convert_groundwater_params(input_nc, output_nc):
    """Convert groundwater properties to PCR-GLOBWB format.

    Expected inputs: specificYield (fraction), kSatAquifer (m/day), recessionCoeff (day-1)
    """
    if nc is None:
        raise ImportError("netCDF4 required")

    with nc.Dataset(input_nc, "r") as src:
        with nc.Dataset(output_nc, "w", format="NETCDF4") as dst:
            # Copy dimensions
            for dim_name, dim in src.dimensions.items():
                dst.createDimension(dim_name, len(dim))

            # Copy all variables with unit checks
            for var_name in src.variables:
                src_var = src.variables[var_name]
                data = src_var[:]

                # Unit corrections
                if "yield" in var_name.lower():
                    if float(np.nanmax(data)) > 1.0:
                        logger.warning(
                            f"dt_007: {var_name} appears to be in percentage. "
                            f"Converting to fraction."
                        )
                        data = data / 100.0

                if "ksat" in var_name.lower() and "aquifer" in var_name.lower():
                    # Check if in cm/hr and convert to m/day
                    if float(np.nanmax(data)) > 500:
                        logger.warning(
                            f"dt_008: {var_name} suspiciously high. "
                            f"Assuming cm/hr, converting to m/day."
                        )
                        data = data * 0.24  # cm/hr -> m/day

                out_var = dst.createVariable(
                    var_name, src_var.dtype, src_var.dimensions,
                    fill_value=1e20
                )
                out_var[:] = data
                for attr in src_var.ncattrs():
                    if attr != "_FillValue":
                        out_var.setncattr(attr, src_var.getncattr(attr))

            dst.description = "PCR-GLOBWB groundwater parameters"
            dst.history = f"Converted {datetime.now().isoformat()}"

    logger.info(f"Groundwater params written to {output_nc}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def process(input_nc, output_nc, input_type, layer="upper"):
    """Main conversion dispatcher."""
    os.makedirs(os.path.dirname(output_nc) or ".", exist_ok=True)

    if input_type == "hwsd":
        convert_hwsd_to_pcrglobwb(input_nc, output_nc, layer)
    elif input_type == "custom_gw":
        convert_groundwater_params(input_nc, output_nc)
    else:
        logger.info(f"Conversion type '{input_type}' — copying with unit validation")
        # For SoilGrids and custom: copy with validation
        if nc is not None and os.path.exists(input_nc):
            import shutil
            shutil.copy2(input_nc, output_nc)
            logger.info(f"Copied {input_nc} -> {output_nc}")


def main():
    parser = argparse.ArgumentParser(
        description="Convert soil/parameter data to PCR-GLOBWB 2 format"
    )
    parser.add_argument("--input", required=True, help="Input NetCDF file")
    parser.add_argument("--output", required=True, help="Output NetCDF file")
    parser.add_argument(
        "--type", required=True,
        choices=["hwsd", "soilgrids", "custom_soil", "custom_topo", "custom_gw"],
        help="Input data type"
    )
    parser.add_argument(
        "--layer", default="upper", choices=["upper", "lower"],
        help="Soil layer (for HWSD)"
    )

    args = parser.parse_args()

    # Validate → Process → Validate
    validate_inputs(args.input, args.type)
    process(args.input, args.output, args.type, args.layer)

    param_type = "groundwater" if args.type == "custom_gw" else "soil"
    validate_outputs(args.output, param_type)


if __name__ == "__main__":
    main()
