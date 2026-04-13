#!/usr/bin/env python3
"""
convert_bathymetry.py — Convert DEM / ASCII / NetCDF bathymetry to GeoClaw topo format.

GeoClaw expects topography files in one of four formats (Type 1–4).
This tool converts common DEM sources (GeoTIFF, ESRI ASCII, CSV, NetCDF)
into GeoClaw-compatible Type 2 or Type 3 ASCII grid files.

CRITICAL UNIT CONVENTIONS:
  - Elevation: meters relative to datum (negative = below sea level)
  - Coordinates: meters (coordinate_system=1) OR decimal degrees (coordinate_system=2)
  - GeoClaw sign convention: ocean depth is NEGATIVE, land is POSITIVE
  - Many DEM sources use positive-down for ocean depth — this tool detects and flips

Pattern: validate_inputs → process → validate_outputs
"""

import argparse
import json
import sys
import os
import numpy as np


def validate_inputs(args):
    """Phase 1: Validate all inputs before processing."""
    errors = []
    warnings = []

    # Check input file exists
    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")

    # Check output directory exists
    out_dir = os.path.dirname(args.output) or "."
    if not os.path.isdir(out_dir):
        errors.append(f"Output directory does not exist: {out_dir}")

    # Check topo type
    if args.topo_type not in [1, 2, 3]:
        errors.append(f"topo_type must be 1, 2, or 3, got {args.topo_type}")

    # Check coordinate system
    if args.coordinate_system not in [1, 2]:
        errors.append(f"coordinate_system must be 1 (Cartesian/m) or 2 (lat-lon/deg), got {args.coordinate_system}")

    # Check format
    supported = ["geotiff", "esri_asc", "csv", "netcdf", "xyz"]
    if args.format not in supported:
        errors.append(f"format must be one of {supported}, got {args.format}")

    # Warn about sign convention
    if args.flip_sign:
        warnings.append("flip_sign=True: will negate all elevation values (positive-down → negative-down)")

    if errors:
        print(json.dumps({"status": "error", "errors": errors, "warnings": warnings}))
        sys.exit(1)

    return warnings


def read_input(args):
    """Read input data based on format."""
    fmt = args.format

    if fmt == "csv" or fmt == "xyz":
        data = np.loadtxt(args.input, delimiter="," if fmt == "csv" else None,
                          comments="#", skiprows=args.skip_header)
        if data.shape[1] < 3:
            raise ValueError(f"Expected at least 3 columns (x, y, z), got {data.shape[1]}")
        x = data[:, 0]
        y = data[:, 1]
        z = data[:, 2]
        # Try to reshape into grid
        x_unique = np.unique(x)
        y_unique = np.unique(y)
        if len(x_unique) * len(y_unique) == len(z):
            ncols = len(x_unique)
            nrows = len(y_unique)
            Z = z.reshape(nrows, ncols)
            xll = x_unique.min()
            yll = y_unique.min()
            dx = (x_unique.max() - x_unique.min()) / max(ncols - 1, 1)
            dy = (y_unique.max() - y_unique.min()) / max(nrows - 1, 1)
        else:
            raise ValueError(
                f"Cannot reshape {len(z)} points into regular grid "
                f"({len(x_unique)} x {len(y_unique)} = {len(x_unique)*len(y_unique)})"
            )
        return ncols, nrows, xll, yll, dx, dy, Z

    elif fmt == "esri_asc":
        return _read_esri_asc(args.input)

    elif fmt == "geotiff":
        return _read_geotiff(args.input)

    elif fmt == "netcdf":
        return _read_netcdf(args.input, args.z_var)

    else:
        raise ValueError(f"Unsupported format: {fmt}")


def _read_esri_asc(filepath):
    """Read ESRI ASCII grid format."""
    header = {}
    header_lines = 0
    with open(filepath, "r") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) == 2 and parts[0].lower() in (
                "ncols", "nrows", "xllcorner", "yllcorner",
                "xllcenter", "yllcenter", "cellsize", "nodata_value"
            ):
                key = parts[0].lower()
                val = float(parts[1]) if "." in parts[1] or "e" in parts[1].lower() else int(parts[1])
                header[key] = val
                header_lines += 1
            else:
                break

    ncols = int(header.get("ncols", 0))
    nrows = int(header.get("nrows", 0))
    cellsize = header.get("cellsize", 1.0)

    # Handle xllcorner vs xllcenter
    if "xllcenter" in header:
        xll = header["xllcenter"] - cellsize / 2.0
    else:
        xll = header.get("xllcorner", 0.0)

    if "yllcenter" in header:
        yll = header["yllcenter"] - cellsize / 2.0
    else:
        yll = header.get("yllcorner", 0.0)

    nodata = header.get("nodata_value", -9999)

    Z = np.loadtxt(filepath, skiprows=header_lines)
    if Z.shape != (nrows, ncols):
        raise ValueError(f"Grid shape {Z.shape} doesn't match header ({nrows}, {ncols})")

    # Replace nodata with NaN
    Z[Z == nodata] = np.nan

    return ncols, nrows, xll, yll, cellsize, cellsize, Z


def _read_geotiff(filepath):
    """Read GeoTIFF using rasterio."""
    try:
        import rasterio
    except ImportError:
        raise ImportError("rasterio is required for GeoTIFF support: pip install rasterio")

    with rasterio.open(filepath) as src:
        Z = src.read(1).astype(float)
        nodata = src.nodata
        if nodata is not None:
            Z[Z == nodata] = np.nan
        transform = src.transform
        ncols = src.width
        nrows = src.height
        xll = transform.c
        yll = transform.f + transform.e * nrows
        dx = transform.a
        dy = abs(transform.e)

    # GeoTIFF rows are top-to-bottom; GeoClaw Type 2 also top-to-bottom
    return ncols, nrows, xll, yll, dx, dy, Z


def _read_netcdf(filepath, z_var=None):
    """Read NetCDF bathymetry file."""
    try:
        from netCDF4 import Dataset
    except ImportError:
        raise ImportError("netCDF4 is required for NetCDF support: pip install netCDF4")

    ds = Dataset(filepath, "r")

    # Find coordinate variables
    x_names = ["x", "lon", "longitude", "X"]
    y_names = ["y", "lat", "latitude", "Y"]
    z_names = ["z", "elevation", "topo", "Band1", "depth"]

    x_var = next((n for n in x_names if n in ds.variables), None)
    y_var = next((n for n in y_names if n in ds.variables), None)
    if z_var is None:
        z_var = next((n for n in z_names if n in ds.variables), None)

    if not all([x_var, y_var, z_var]):
        ds.close()
        raise ValueError(f"Cannot find x/y/z variables. Available: {list(ds.variables.keys())}")

    x = ds.variables[x_var][:]
    y = ds.variables[y_var][:]
    Z = ds.variables[z_var][:, :]
    ds.close()

    ncols = len(x)
    nrows = len(y)
    xll = float(x.min())
    yll = float(y.min())
    dx = float(x[1] - x[0]) if len(x) > 1 else 1.0
    dy = float(y[1] - y[0]) if len(y) > 1 else 1.0

    # Ensure y is ascending (south to north)
    if dy < 0:
        y = y[::-1]
        Z = Z[::-1, :]
        dy = abs(dy)

    return ncols, nrows, xll, yll, dx, dy, np.array(Z)


def process(args, input_warnings):
    """Phase 2: Convert bathymetry to GeoClaw topo format."""
    ncols, nrows, xll, yll, dx, dy, Z = read_input(args)

    warnings = list(input_warnings)

    # Apply sign flip if requested (positive-down → GeoClaw convention)
    if args.flip_sign:
        Z = -Z
        warnings.append("Elevation values negated (flip_sign=True)")

    # Apply vertical offset
    if args.z_offset != 0.0:
        Z = Z + args.z_offset
        warnings.append(f"Applied vertical offset: {args.z_offset} m")

    # Unit conversion for elevation
    if args.z_units == "feet":
        Z = Z * 0.3048
        warnings.append("Converted elevation from feet to meters (×0.3048)")
    elif args.z_units == "fathoms":
        Z = Z * 1.8288
        warnings.append("Converted elevation from fathoms to meters (×1.8288)")
    elif args.z_units == "cm":
        Z = Z * 0.01
        warnings.append("Converted elevation from cm to meters (×0.01)")

    # Replace NaN with nodata value
    nodata = -9999.0
    Z_out = np.where(np.isnan(Z), nodata, Z)

    # Write output
    _write_topo_file(args.output, args.topo_type, ncols, nrows,
                     xll, yll, dx, dy, Z_out, nodata)

    result = {
        "status": "success",
        "output_file": args.output,
        "topo_type": args.topo_type,
        "ncols": ncols,
        "nrows": nrows,
        "xll": xll,
        "yll": yll,
        "dx": dx,
        "dy": dy,
        "z_min": float(np.nanmin(Z)),
        "z_max": float(np.nanmax(Z)),
        "z_mean": float(np.nanmean(Z)),
        "n_nodata": int(np.sum(np.isnan(Z))),
        "warnings": warnings,
    }

    return result


def _write_topo_file(filepath, topo_type, ncols, nrows, xll, yll, dx, dy, Z, nodata):
    """Write GeoClaw topo file."""
    with open(filepath, "w") as f:
        if topo_type == 2:
            # Type 2: header with mx, my, xlow, ylow, dx, dy
            f.write(f"{ncols:10d}  mx\n")
            f.write(f"{nrows:10d}  my\n")
            f.write(f"{xll:20.10e}  xlow\n")
            f.write(f"{yll:20.10e}  ylow\n")
            f.write(f"{dx:20.10e}  dx\n")
            f.write(f"{dy:20.10e}  dy\n")
            # Write Z values (top row first = northernmost)
            for j in range(nrows):
                row = Z[j, :]
                line = "  ".join(f"{v:.6f}" for v in row)
                f.write(line + "\n")

        elif topo_type == 3:
            # Type 3: ESRI ASCII grid format
            f.write(f"ncols         {ncols}\n")
            f.write(f"nrows         {nrows}\n")
            f.write(f"xllcorner     {xll}\n")
            f.write(f"yllcorner     {yll}\n")
            f.write(f"cellsize      {dx}\n")
            f.write(f"NODATA_value  {nodata}\n")
            for j in range(nrows):
                row = Z[j, :]
                line = " ".join(f"{v:.6f}" for v in row)
                f.write(line + "\n")

        elif topo_type == 1:
            # Type 1: x, y, z columns
            for j in range(nrows):
                for i in range(ncols):
                    x = xll + i * dx
                    y = yll + (nrows - 1 - j) * dy
                    f.write(f"{x:.10e}  {y:.10e}  {Z[j, i]:.6f}\n")


def validate_outputs(result):
    """Phase 3: Validate output file and computed statistics."""
    warnings = result.get("warnings", [])

    # Check elevation range is physically reasonable
    z_min = result["z_min"]
    z_max = result["z_max"]

    if z_min < -12000:
        warnings.append(
            f"CRITICAL: z_min={z_min:.1f} m is deeper than Mariana Trench (-11034 m). "
            "Check units — may be in cm or mm instead of meters."
        )
    if z_max > 9000:
        warnings.append(
            f"CRITICAL: z_max={z_max:.1f} m exceeds Mt. Everest (8849 m). "
            "Check units — may be in cm or feet instead of meters."
        )

    # Check if all values are positive (possible sign convention error)
    if z_min > 0:
        warnings.append(
            "WARNING: All elevations are positive. If this includes ocean areas, "
            "the sign convention may be wrong. Use --flip-sign to negate."
        )

    # Check if all values are negative (possible land area missing)
    if z_max < 0:
        warnings.append(
            "WARNING: All elevations are negative. If this includes land areas, "
            "the sign convention may be wrong."
        )

    # Check nodata fraction
    total = result["ncols"] * result["nrows"]
    nodata_frac = result["n_nodata"] / max(total, 1)
    if nodata_frac > 0.5:
        warnings.append(
            f"WARNING: {nodata_frac*100:.1f}% of cells are NODATA. "
            "Check if the correct region was extracted."
        )

    # Check output file exists and has content
    outfile = result["output_file"]
    if not os.path.isfile(outfile):
        warnings.append(f"CRITICAL: Output file was not created: {outfile}")
    else:
        size_mb = os.path.getsize(outfile) / 1e6
        if size_mb < 0.001:
            warnings.append(f"WARNING: Output file is very small ({size_mb:.4f} MB)")
        result["file_size_mb"] = round(size_mb, 3)

    result["warnings"] = warnings
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert DEM/ASCII/NetCDF bathymetry to GeoClaw topo format"
    )
    parser.add_argument("--input", required=True, help="Input bathymetry file")
    parser.add_argument("--output", required=True, help="Output GeoClaw topo file")
    parser.add_argument("--format", required=True,
                        choices=["geotiff", "esri_asc", "csv", "netcdf", "xyz"],
                        help="Input file format")
    parser.add_argument("--topo-type", type=int, default=2,
                        choices=[1, 2, 3],
                        help="GeoClaw topo type (default: 2)")
    parser.add_argument("--coordinate-system", type=int, default=2,
                        choices=[1, 2],
                        help="1=Cartesian (m), 2=lat-lon (deg)")
    parser.add_argument("--flip-sign", action="store_true",
                        help="Negate elevation values (positive-down → GeoClaw convention)")
    parser.add_argument("--z-offset", type=float, default=0.0,
                        help="Vertical offset to add to all elevations (meters)")
    parser.add_argument("--z-units", default="meters",
                        choices=["meters", "feet", "fathoms", "cm"],
                        help="Input elevation units (converted to meters)")
    parser.add_argument("--z-var", default=None,
                        help="NetCDF variable name for elevation")
    parser.add_argument("--skip-header", type=int, default=0,
                        help="Lines to skip in CSV/XYZ input")
    parser.add_argument("--json-output", default=None,
                        help="Write result JSON to this file")

    args = parser.parse_args()

    # Phase 1: Validate inputs
    input_warnings = validate_inputs(args)

    # Phase 2: Process
    result = process(args, input_warnings)

    # Phase 3: Validate outputs
    result = validate_outputs(result)

    # Write JSON result
    if args.json_output:
        with open(args.json_output, "w") as f:
            json.dump(result, f, indent=2)
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
