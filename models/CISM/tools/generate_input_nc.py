#!/usr/bin/env python3
"""
generate_input_nc.py -- Create NetCDF input files for CISM ice sheet model.

Generates the required NetCDF input file containing bed topography (topg),
initial ice thickness (thk), surface air temperature (artm), surface mass
balance (acab), and optionally basal traction (beta) fields.

Supports three modes:
  1. Dome: synthetic parabolic dome (benchmark test)
  2. Slab: inclined slab (HO dynamics test)
  3. Custom: user-provided fields from CSV or NumPy arrays

CRITICAL UNITS:
  - topg: meters (negative below sea level)
  - thk: meters
  - artm: degrees Celsius
  - acab: meters/year (NOT mm/year -- dt_001 trap)
  - beta: Pa yr/m (on staggered grid y0,x0 = nsn-1,ewn-1)
  - dew, dns: meters (NOT kilometers -- dt_006 trap)
  - bheatflx: W/m^2 (negative = upward -- dt_003 trap)

Usage:
    # Dome test case
    python generate_input_nc.py --mode dome --ewn 31 --nsn 31 --dew 2000 --output dome.nc

    # Custom input from CSV
    python generate_input_nc.py --mode custom --topg topg.csv --thk thk.csv \
        --artm artm.csv --acab acab.csv --ewn 100 --nsn 100 --dew 5000 --output input.nc

    # Slab test case
    python generate_input_nc.py --mode slab --ewn 5 --nsn 50 --dew 5000 --output slab.nc
"""

import argparse
import sys
import os
import numpy as np

try:
    import netCDF4
except ImportError:
    print("ERROR: netCDF4 required. Install with: pip install netCDF4")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inputs(args):
    """Validate input arguments before processing."""
    errors = []

    if args.ewn < 3:
        errors.append(f"ewn={args.ewn} too small, minimum 3 grid points")
    if args.nsn < 3:
        errors.append(f"nsn={args.nsn} too small, minimum 3 grid points")
    if args.upn < 3:
        errors.append(f"upn={args.upn} too small, minimum 3 sigma levels")
    if args.dew <= 0:
        errors.append(f"dew={args.dew} must be positive (meters)")
    if args.dns <= 0:
        errors.append(f"dns={args.dns} must be positive (meters)")

    # dt_006: grid spacing sanity check
    if args.dew < 10:
        errors.append(
            f"dew={args.dew} suspiciously small -- did you use km instead of m? "
            f"(dt_006: CISM expects meters)"
        )
    if args.dns < 10:
        errors.append(
            f"dns={args.dns} suspiciously small -- did you use km instead of m? "
            f"(dt_006: CISM expects meters)"
        )

    if args.mode == "custom":
        for field in ["topg", "thk"]:
            path = getattr(args, field, None)
            if path and not os.path.exists(path):
                errors.append(f"File not found: {path}")

    if errors:
        for e in errors:
            print(f"VALIDATION ERROR: {e}")
        sys.exit(1)

    print("Input validation passed.")


# ---------------------------------------------------------------------------
# Dome generator
# ---------------------------------------------------------------------------

def generate_dome(ewn, nsn, dew, dns, dome_center=None, dome_radius=None,
                  dome_thickness=1500.0, dome_artm=-10.0, dome_acab=0.25):
    """
    Generate a parabolic dome test case.

    Returns dict of numpy arrays: topg, thk, artm, acab.
    """
    if dome_center is None:
        dome_center = (ewn // 2, nsn // 2)
    if dome_radius is None:
        dome_radius = min(ewn, nsn) // 2 - 2

    x = np.arange(ewn)
    y = np.arange(nsn)
    xx, yy = np.meshgrid(x, y)

    r = np.sqrt((xx - dome_center[0])**2 + (yy - dome_center[1])**2)
    r_norm = r / dome_radius

    # Parabolic dome profile
    thk = np.where(r_norm <= 1.0,
                   dome_thickness * np.sqrt(1.0 - r_norm**2),
                   0.0)
    topg = np.zeros((nsn, ewn), dtype=np.float64)
    artm = np.full((nsn, ewn), dome_artm, dtype=np.float64)

    # SMB: positive in accumulation zone, negative at margins
    acab = np.where(r_norm <= 0.8,
                    dome_acab,
                    dome_acab * (1.0 - r_norm) / 0.2)
    acab = np.where(r_norm > 1.0, -dome_acab, acab)

    return {"topg": topg, "thk": thk, "artm": artm, "acab": acab}


# ---------------------------------------------------------------------------
# Slab generator
# ---------------------------------------------------------------------------

def generate_slab(ewn, nsn, dew, dns, slope=0.01, thickness=1000.0):
    """Generate an inclined slab test case for HO dynamics testing."""
    x = np.arange(ewn) * dew
    y = np.arange(nsn) * dns
    xx, yy = np.meshgrid(x, y)

    topg = -slope * yy
    thk = np.full((nsn, ewn), thickness, dtype=np.float64)
    artm = np.full((nsn, ewn), -15.0, dtype=np.float64)
    acab = np.zeros((nsn, ewn), dtype=np.float64)

    return {"topg": topg, "thk": thk, "artm": artm, "acab": acab}


# ---------------------------------------------------------------------------
# BedMachine ingestion (real ice-sheet domain)
# ---------------------------------------------------------------------------

def _block_mean(arr, f):
    """Block-mean coarsen a 2-D array by integer factor f (crops the remainder)."""
    ny, nx = arr.shape
    ny2, nx2 = (ny // f) * f, (nx // f) * f
    a = np.asarray(arr[:ny2, :nx2], dtype=np.float64)
    return a.reshape(ny2 // f, f, nx2 // f, f).mean(axis=(1, 3))


def generate_bedmachine(nc_path, dew, dns):
    """
    Ingest a BedMachine NetCDF (Greenland v6 / Antarctica v4.1) and coarsen the
    bed topography and ice thickness onto a regular CISM grid.

    BedMachine grids are polar-stereographic in METERS (native 150 m Greenland /
    500 m Antarctica) with `x` ascending and `y` DESCENDING. CISM expects the
    scalar grid with y1 ascending, so the coarsened fields are flipped in y.

    Returns (fields, grid) where:
      fields = {topg, thk, artm, acab, usurf, obs_usurf}
      grid   = {ewn, nsn, dew, dns}
    The coarsened observed `surface` is carried as `obs_usurf` for the
    spatial_snapshot validation against the model-computed `usurf`.
    """
    ds = netCDF4.Dataset(nc_path, "r")
    x = ds.variables["x"][:]
    y = ds.variables["y"][:]
    native_dx = abs(float(x[1] - x[0]))   # 150 m (Greenland v6)

    # Integer coarsening factor from requested spacing
    f = max(1, int(round(dew / native_dx)))
    dew_actual = f * native_dx
    dns_actual = f * abs(float(y[1] - y[0]))

    bed = ds.variables["bed"][:]
    thickness = ds.variables["thickness"][:]
    surface = ds.variables["surface"][:]
    ds.close()

    topg = _block_mean(bed, f)
    thk = np.clip(_block_mean(thickness, f), 0.0, None)
    obs_usurf = _block_mean(surface, f)

    # CISM wants y1 ascending; BedMachine y is descending -> flip in y (axis 0)
    topg = np.flipud(topg).copy()
    thk = np.flipud(thk).copy()
    obs_usurf = np.flipud(obs_usurf).copy()

    nsn, ewn = topg.shape

    # artm/acab: not the observable here (usurf snapshot), supply physically
    # plausible Greenland-wide constants so the run is well-posed.
    artm = np.full((nsn, ewn), -20.0, dtype=np.float64)
    acab = np.full((nsn, ewn), 0.3, dtype=np.float64)

    # Initial diagnostic surface (CISM recomputes usurf from topg+thk internally)
    usurf = np.where(thk > 0, np.maximum(topg, 0.0) + thk, np.maximum(topg, 0.0))

    print(f"BedMachine ingest: native {native_dx:.0f} m, factor {f} "
          f"-> {dew_actual:.0f} m grid")
    print(f"  Coarsened grid: {ewn} x {nsn} cells")
    print(f"  topg range: {topg.min():.1f} .. {topg.max():.1f} m")
    print(f"  thk  range: {thk.min():.1f} .. {thk.max():.1f} m "
          f"(ice-covered cells: {int((thk>1).sum())})")
    print(f"  obs surface range: {obs_usurf.min():.1f} .. {obs_usurf.max():.1f} m")

    fields = {"topg": topg, "thk": thk, "artm": artm, "acab": acab,
              "usurf": usurf, "obs_usurf": obs_usurf}
    grid = {"ewn": ewn, "nsn": nsn, "dew": dew_actual, "dns": dns_actual}
    return fields, grid


# ---------------------------------------------------------------------------
# Custom loader
# ---------------------------------------------------------------------------

def load_custom(args):
    """Load custom fields from CSV files."""
    fields = {}
    for field_name in ["topg", "thk", "artm", "acab"]:
        path = getattr(args, field_name, None)
        if path and os.path.exists(path):
            data = np.loadtxt(path, delimiter=",")
            if data.shape != (args.nsn, args.ewn):
                print(f"WARNING: {field_name} shape {data.shape} != expected "
                      f"({args.nsn}, {args.ewn}). Attempting reshape.")
                data = data.reshape(args.nsn, args.ewn)
            fields[field_name] = data
        else:
            fields[field_name] = np.zeros((args.nsn, args.ewn), dtype=np.float64)

    # dt_001 check: SMB magnitude
    acab_max = np.max(np.abs(fields["acab"]))
    if acab_max > 100:
        print(f"WARNING (dt_001): acab max={acab_max:.1f} -- "
              f"if in mm/yr, divide by 1000. CISM expects m/yr.")

    return fields


# ---------------------------------------------------------------------------
# NetCDF writer
# ---------------------------------------------------------------------------

def write_netcdf(output_path, fields, ewn, nsn, upn, dew, dns):
    """Write CISM-format NetCDF input file."""
    ds = netCDF4.Dataset(output_path, "w", format="NETCDF4")

    # Dimensions
    ds.createDimension("time", 1)
    ds.createDimension("x1", ewn)
    ds.createDimension("y1", nsn)
    ds.createDimension("x0", ewn - 1)
    ds.createDimension("y0", nsn - 1)
    ds.createDimension("level", upn)

    # Coordinate variables
    time_var = ds.createVariable("time", "f8", ("time",))
    time_var.units = "year since 0000-01-01"
    time_var[0] = 0.0

    x1 = ds.createVariable("x1", "f8", ("x1",))
    x1.units = "m"
    x1[:] = np.arange(ewn) * dew

    y1 = ds.createVariable("y1", "f8", ("y1",))
    y1.units = "m"
    y1[:] = np.arange(nsn) * dns

    x0 = ds.createVariable("x0", "f8", ("x0",))
    x0.units = "m"
    x0[:] = (np.arange(ewn - 1) + 0.5) * dew

    y0 = ds.createVariable("y0", "f8", ("y0",))
    y0.units = "m"
    y0[:] = (np.arange(nsn - 1) + 0.5) * dns

    level = ds.createVariable("level", "f8", ("level",))
    level.units = "1"
    level.long_name = "sigma coordinate"
    level[:] = np.linspace(0, 1, upn)

    # Data variables
    var_specs = {
        "topg":  ("f8", ("time", "y1", "x1"), "m", "bedrock topography"),
        "thk":   ("f8", ("time", "y1", "x1"), "m", "ice thickness"),
        "artm":  ("f8", ("time", "y1", "x1"), "degC", "surface air temperature"),
        "acab":  ("f8", ("time", "y1", "x1"), "m/year", "surface mass balance"),
        "usurf": ("f8", ("time", "y1", "x1"), "m", "upper ice surface elevation"),
        "obs_usurf": ("f8", ("time", "y1", "x1"), "m",
                      "observed upper surface (resampled, validation reference)"),
    }

    for vname, (dtype, dims, units, long_name) in var_specs.items():
        if vname in fields:
            v = ds.createVariable(vname, dtype, dims)
            v.units = units
            v.long_name = long_name
            v[0, :, :] = fields[vname]

    # Optional beta (staggered grid)
    if "beta" in fields:
        v = ds.createVariable("beta", "f8", ("time", "y0", "x0"))
        v.units = "Pa yr m-1"
        v.long_name = "basal traction coefficient"
        v[0, :, :] = fields["beta"]

    # Global attributes
    ds.title = "CISM input file"
    ds.source = "generate_input_nc.py (Knowledge Infrastructure)"
    ds.Conventions = "CF-1.6"

    ds.close()
    print(f"Written: {output_path}")
    print(f"  Grid: {ewn} x {nsn} x {upn}, spacing: {dew} x {dns} m")
    print(f"  Variables: {list(fields.keys())}")


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------

def validate_output(output_path, ewn, nsn):
    """Validate the generated NetCDF file."""
    ds = netCDF4.Dataset(output_path, "r")
    errors = []

    if ds.dimensions["x1"].size != ewn:
        errors.append(f"x1 dimension {ds.dimensions['x1'].size} != {ewn}")
    if ds.dimensions["y1"].size != nsn:
        errors.append(f"y1 dimension {ds.dimensions['y1'].size} != {nsn}")

    for vname in ["topg", "thk"]:
        if vname not in ds.variables:
            errors.append(f"Missing required variable: {vname}")
        else:
            data = ds.variables[vname][0, :, :]
            if np.any(np.isnan(data)):
                errors.append(f"{vname} contains NaN values")

    # Check thk is non-negative
    if "thk" in ds.variables:
        thk = ds.variables["thk"][0, :, :]
        if np.any(thk < 0):
            errors.append("thk contains negative values")

    ds.close()

    if errors:
        for e in errors:
            print(f"OUTPUT VALIDATION ERROR: {e}")
        return False

    print(f"Output validation passed: {output_path}")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate CISM NetCDF input files"
    )
    parser.add_argument("--mode", choices=["dome", "slab", "custom", "bedmachine"],
                        default="dome", help="Generation mode")
    parser.add_argument("--bedmachine",
                        help="Path to BedMachine NetCDF (mode=bedmachine)")
    parser.add_argument("--ewn", type=int, default=31, help="E-W grid points")
    parser.add_argument("--nsn", type=int, default=31, help="N-S grid points")
    parser.add_argument("--upn", type=int, default=11, help="Sigma levels")
    parser.add_argument("--dew", type=float, default=2000.0, help="E-W spacing (m)")
    parser.add_argument("--dns", type=float, default=2000.0, help="N-S spacing (m)")
    parser.add_argument("--output", default="input.nc", help="Output file path")

    # Dome options
    parser.add_argument("--dome_thickness", type=float, default=1500.0)
    parser.add_argument("--dome_artm", type=float, default=-10.0)
    parser.add_argument("--dome_acab", type=float, default=0.25)

    # Slab options
    parser.add_argument("--slope", type=float, default=0.01)
    parser.add_argument("--slab_thickness", type=float, default=1000.0)

    # Custom options
    parser.add_argument("--topg", help="CSV file for bed topography")
    parser.add_argument("--thk", help="CSV file for ice thickness")
    parser.add_argument("--artm", help="CSV file for air temperature")
    parser.add_argument("--acab", help="CSV file for surface mass balance")

    args = parser.parse_args()

    # BedMachine derives its grid from the file itself; handle before the
    # generic CLI-grid validation (which assumes ewn/nsn/dew/dns are given).
    if args.mode == "bedmachine":
        if not args.bedmachine or not os.path.exists(args.bedmachine):
            print(f"VALIDATION ERROR: --bedmachine path not found: {args.bedmachine}")
            sys.exit(1)
        fields, grid = generate_bedmachine(args.bedmachine, args.dew, args.dns)
        args.ewn, args.nsn = grid["ewn"], grid["nsn"]
        args.dew, args.dns = grid["dew"], grid["dns"]
        write_netcdf(args.output, fields, args.ewn, args.nsn, args.upn,
                     args.dew, args.dns)
        validate_output(args.output, args.ewn, args.nsn)
        return

    # Step 1: Validate inputs
    validate_inputs(args)

    # Step 2: Generate fields
    if args.mode == "dome":
        fields = generate_dome(args.ewn, args.nsn, args.dew, args.dns,
                               dome_thickness=args.dome_thickness,
                               dome_artm=args.dome_artm,
                               dome_acab=args.dome_acab)
    elif args.mode == "slab":
        fields = generate_slab(args.ewn, args.nsn, args.dew, args.dns,
                               slope=args.slope, thickness=args.slab_thickness)
    elif args.mode == "custom":
        fields = load_custom(args)

    # Step 3: Write NetCDF
    write_netcdf(args.output, fields, args.ewn, args.nsn, args.upn,
                 args.dew, args.dns)

    # Step 4: Validate output
    validate_output(args.output, args.ewn, args.nsn)


if __name__ == "__main__":
    main()
