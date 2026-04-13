#!/usr/bin/env python3
"""
convert_bathymetry.py - Interpolate bathymetry/terrain data onto TELEMAC mesh nodes.

Reads a bathymetry source (XYZ point cloud, raster GeoTIFF, or CSV) and
interpolates bottom elevation values onto the nodes of an existing TELEMAC
SELAFIN mesh file. The result is written as a new SELAFIN geometry file
with updated bottom elevation.

Usage:
    python convert_bathymetry.py --mesh geo.slf --bathy bathy.xyz \
        --output geo_with_bathy.slf

    python convert_bathymetry.py --mesh geo.slf --bathy dem.tif \
        --output geo_with_bathy.slf --format geotiff

Unit conventions:
    - TELEMAC uses bottom ELEVATION (positive upward from datum)
    - Nautical charts use DEPTH (positive downward) -> negate
    - Coordinates must be in the same CRS as the mesh (metric)

Follows validate -> process -> validate pattern.
"""

import argparse
import json
import os
import struct
import sys

import numpy as np
from scipy.interpolate import griddata


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def validate_inputs(args):
    """Check input files exist and parameters are valid."""
    errors = []
    if not os.path.isfile(args.mesh):
        errors.append(f"Mesh file not found: {args.mesh}")
    if not os.path.isfile(args.bathy):
        errors.append(f"Bathymetry file not found: {args.bathy}")
    if args.format not in ("xyz", "csv", "geotiff"):
        errors.append(f"Unknown bathymetry format: {args.format}")
    if args.negate and args.scale != 1.0:
        print(json.dumps({"status": "warning",
                          "message": "Both --negate and --scale active; negate applied first"}))
    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)
    return True


def validate_outputs(output_path, npoin, zb_min, zb_max):
    """Verify output file and bottom elevation range."""
    errors = []
    if not os.path.isfile(output_path):
        errors.append(f"Output file not created: {output_path}")
    elif os.path.getsize(output_path) == 0:
        errors.append("Output file is empty")

    # Sanity checks on elevation range
    warnings = []
    if zb_max > 9000:
        warnings.append(f"Max bottom elevation {zb_max:.1f} m exceeds Mount Everest - check units")
    if zb_min < -12000:
        warnings.append(f"Min bottom elevation {zb_min:.1f} m below Mariana Trench - check units")
    if zb_max - zb_min < 0.001:
        warnings.append("Bathymetry range < 1 mm - effectively flat, check data")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)

    result = {
        "status": "success",
        "output": output_path,
        "npoin": npoin,
        "zb_min": round(zb_min, 4),
        "zb_max": round(zb_max, 4),
    }
    if warnings:
        result["warnings"] = warnings
    print(json.dumps(result))


# ---------------------------------------------------------------------------
# SELAFIN reader (minimal - reads mesh coordinates)
# ---------------------------------------------------------------------------
def read_selafin_mesh(filepath):
    """Read mesh geometry from a SELAFIN file (big-endian)."""
    with open(filepath, "rb") as f:
        def read_record():
            n = struct.unpack(">i", f.read(4))[0]
            data = f.read(n)
            struct.unpack(">i", f.read(4))  # trailing marker
            return data

        # Title
        title = read_record().decode("ascii", errors="replace").strip()

        # Number of variables
        rec = read_record()
        nvar = struct.unpack(">ii", rec)[0]

        # Variable names
        var_names = []
        for _ in range(nvar):
            vn = read_record().decode("ascii", errors="replace").strip()
            var_names.append(vn)

        # Integer parameters (10 values)
        rec = read_record()
        iparams = struct.unpack(">" + "i" * 10, rec)

        # Optional date block
        if iparams[9] != 0:
            read_record()  # 6-integer date

        # Mesh topology: NELEM, NPOIN, NDP, 1
        rec = read_record()
        nelem, npoin, ndp, _ = struct.unpack(">iiii", rec)

        # Connectivity (IKLE)
        rec = read_record()
        ikle_flat = struct.unpack(">" + "i" * (nelem * ndp), rec)
        ikle = np.array(ikle_flat).reshape(nelem, ndp)

        # IPOBO
        rec = read_record()
        ipobo = np.array(struct.unpack(">" + "i" * npoin, rec))

        # X coordinates
        rec = read_record()
        x = np.array(struct.unpack(">" + "f" * npoin, rec))

        # Y coordinates
        rec = read_record()
        y = np.array(struct.unpack(">" + "f" * npoin, rec))

    return {
        "title": title,
        "nvar": nvar,
        "var_names": var_names,
        "iparams": iparams,
        "nelem": nelem,
        "npoin": npoin,
        "ndp": ndp,
        "ikle": ikle,
        "ipobo": ipobo,
        "x": x,
        "y": y,
    }


# ---------------------------------------------------------------------------
# Bathymetry readers
# ---------------------------------------------------------------------------
def read_xyz(filepath):
    """Read XYZ point cloud (whitespace or comma delimited)."""
    try:
        data = np.loadtxt(filepath, comments="#")
    except ValueError:
        data = np.loadtxt(filepath, delimiter=",", comments="#")
    if data.ndim != 2 or data.shape[1] < 3:
        print(json.dumps({"status": "error",
                          "errors": ["XYZ file must have at least 3 columns (X, Y, Z)"]}))
        sys.exit(1)
    return data[:, 0], data[:, 1], data[:, 2]


def read_csv_bathy(filepath):
    """Read CSV bathymetry with header."""
    data = np.genfromtxt(filepath, delimiter=",", skip_header=1)
    if data.shape[1] < 3:
        print(json.dumps({"status": "error",
                          "errors": ["CSV must have >= 3 columns"]}))
        sys.exit(1)
    return data[:, 0], data[:, 1], data[:, 2]


def read_geotiff(filepath):
    """Read GeoTIFF raster and return scattered XYZ points."""
    try:
        import rasterio
    except ImportError:
        print(json.dumps({"status": "error",
                          "errors": ["rasterio required for GeoTIFF: pip install rasterio"]}))
        sys.exit(1)

    with rasterio.open(filepath) as src:
        band = src.read(1)
        nodata = src.nodata
        rows, cols = np.where(band != nodata) if nodata is not None else (
            np.arange(band.shape[0]).repeat(band.shape[1]),
            np.tile(np.arange(band.shape[1]), band.shape[0]),
        )
        xs, ys = rasterio.transform.xy(src.transform, rows, cols)
        zs = band[rows, cols]
    return np.array(xs), np.array(ys), np.array(zs)


# ---------------------------------------------------------------------------
# Interpolation
# ---------------------------------------------------------------------------
def interpolate_bathymetry(bathy_x, bathy_y, bathy_z, mesh_x, mesh_y, method="linear"):
    """Interpolate bathymetry onto mesh nodes using scipy griddata."""
    points = np.column_stack((bathy_x, bathy_y))
    zb = griddata(points, bathy_z, (mesh_x, mesh_y), method=method)

    # Fill NaNs with nearest-neighbor
    nan_mask = np.isnan(zb)
    if nan_mask.any():
        zb_nn = griddata(points, bathy_z, (mesh_x, mesh_y), method="nearest")
        zb[nan_mask] = zb_nn[nan_mask]

    return zb


# ---------------------------------------------------------------------------
# SELAFIN writer (copy mesh + overwrite bottom)
# ---------------------------------------------------------------------------
def write_selafin_with_bottom(output_path, mesh_info, zb):
    """Write a SELAFIN geometry file with bottom elevation as the only variable."""
    npoin = mesh_info["npoin"]
    nelem = mesh_info["nelem"]
    ndp = mesh_info["ndp"]

    with open(output_path, "wb") as f:
        def write_record(raw_bytes):
            n = len(raw_bytes)
            f.write(struct.pack(">i", n))
            f.write(raw_bytes)
            f.write(struct.pack(">i", n))

        # Title
        title = "BOTTOM FROM CONVERT_BATHYMETRY".ljust(72)[:72] + "SERAFIN "
        write_record(title.encode("ascii"))

        # 1 variable: BOTTOM
        write_record(struct.pack(">ii", 1, 0))
        write_record("BOTTOM          M               ".encode("ascii"))

        # Integer params
        iparams = list(mesh_info["iparams"])
        write_record(struct.pack(">" + "i" * 10, *iparams))

        # Mesh topology
        write_record(struct.pack(">iiii", nelem, npoin, ndp, 1))

        # IKLE
        ikle_flat = mesh_info["ikle"].flatten().tolist()
        write_record(struct.pack(">" + "i" * len(ikle_flat), *ikle_flat))

        # IPOBO
        write_record(struct.pack(">" + "i" * npoin, *mesh_info["ipobo"].tolist()))

        # Coordinates
        write_record(struct.pack(">" + "f" * npoin, *mesh_info["x"].tolist()))
        write_record(struct.pack(">" + "f" * npoin, *mesh_info["y"].tolist()))

        # One timestep with bottom elevation
        write_record(struct.pack(">f", 0.0))
        write_record(struct.pack(">" + "f" * npoin, *zb.astype(np.float32).tolist()))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Interpolate bathymetry onto TELEMAC mesh")
    parser.add_argument("--mesh", required=True, help="Input SELAFIN mesh (.slf)")
    parser.add_argument("--bathy", required=True, help="Bathymetry data file")
    parser.add_argument("--output", required=True, help="Output SELAFIN file")
    parser.add_argument("--format", default="xyz", choices=["xyz", "csv", "geotiff"],
                        help="Bathymetry file format")
    parser.add_argument("--method", default="linear", choices=["linear", "nearest", "cubic"],
                        help="Interpolation method")
    parser.add_argument("--negate", action="store_true",
                        help="Negate Z values (depth -> elevation)")
    parser.add_argument("--scale", type=float, default=1.0,
                        help="Scale factor for Z values")
    parser.add_argument("--offset", type=float, default=0.0,
                        help="Vertical offset (added after scaling)")
    args = parser.parse_args()

    # Step 1: Validate inputs
    validate_inputs(args)

    # Step 2: Read mesh
    mesh = read_selafin_mesh(args.mesh)
    print(f"Mesh: {mesh['npoin']} nodes, {mesh['nelem']} elements", file=sys.stderr)

    # Step 3: Read bathymetry
    if args.format == "xyz":
        bx, by, bz = read_xyz(args.bathy)
    elif args.format == "csv":
        bx, by, bz = read_csv_bathy(args.bathy)
    elif args.format == "geotiff":
        bx, by, bz = read_geotiff(args.bathy)
    print(f"Bathymetry: {len(bz)} points, Z range [{bz.min():.2f}, {bz.max():.2f}]",
          file=sys.stderr)

    # Step 4: Apply transformations
    if args.negate:
        bz = -bz
    bz = bz * args.scale + args.offset

    # Step 5: Interpolate
    zb = interpolate_bathymetry(bx, by, bz, mesh["x"], mesh["y"], method=args.method)
    print(f"Interpolated ZB range: [{zb.min():.4f}, {zb.max():.4f}]", file=sys.stderr)

    # Step 6: Write output
    write_selafin_with_bottom(args.output, mesh, zb)

    # Step 7: Validate output
    validate_outputs(args.output, mesh["npoin"], zb.min(), zb.max())


if __name__ == "__main__":
    main()
