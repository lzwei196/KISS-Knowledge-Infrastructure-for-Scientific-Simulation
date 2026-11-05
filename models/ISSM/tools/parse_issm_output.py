#!/usr/bin/env python3
"""
parse_issm_output.py — Parse ISSM simulation results to CSV and JSON summaries.

Reads ISSM model results (from saved .mat/.nc files or direct numpy arrays)
and produces:
1. CSV files with per-vertex results (velocity, thickness, temperature)
2. JSON summary with statistics (min, max, mean, std for each field)
3. Time series CSV for transient solutions

ISSM stores results in md.results.<SolutionType>:
  - StressbalanceSolution: Vx, Vy, Vz, Vel, Pressure
  - MasstransportSolution: Thickness, Surface
  - ThermalSolution: Temperature, Enthalpy
  - TransientSolution: Array of above per timestep

All velocities are in m/yr, temperatures in K, thicknesses in m.

Usage:
    python parse_issm_output.py \
        --results_dir ./issm_output/ \
        --mesh_x mesh_x.npy --mesh_y mesh_y.npy \
        --solution Stressbalance \
        --output_csv results.csv \
        --output_json summary.json

    python parse_issm_output.py \
        --netcdf_file output.nc \
        --solution Transient \
        --output_csv timeseries.csv \
        --output_json summary.json

    # ISSM's own result file (path is "outbin" in run_issm.py's results.json)
    python parse_issm_output.py \
        --outbin <execution_dir>/<runtimename>/<name>.outbin \
        --issm_dir /path/to/ISSM \
        --output_csv results.csv \
        --output_json summary.json
"""

import argparse
import csv
import json
import os
import sys

import numpy as np

try:
    from netCDF4 import Dataset as NCDataset
except ImportError:
    NCDataset = None


# =============================================================================
# Validation
# =============================================================================
def validate_inputs(args):
    """Validate command-line arguments."""
    errors = []

    if args.outbin:
        if not os.path.isfile(args.outbin):
            errors.append(f"ISSM .outbin file not found: {args.outbin}")
        if not (np.isfinite(args.yts) and args.yts > 0):
            errors.append(f"--yts must be a positive finite number, got {args.yts}")
    elif args.netcdf_file:
        if not os.path.exists(args.netcdf_file):
            errors.append(f"NetCDF file not found: {args.netcdf_file}")
        if NCDataset is None:
            errors.append("netCDF4 required for NetCDF parsing: pip install netCDF4")
    elif args.results_dir:
        if not os.path.isdir(args.results_dir):
            errors.append(f"Results directory not found: {args.results_dir}")
    else:
        errors.append("Must provide one of --outbin, --netcdf_file or --results_dir")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def validate_outputs(output_csv, output_json):
    """Validate generated outputs."""
    errors = []
    warnings = []

    if output_csv and os.path.exists(output_csv):
        size = os.path.getsize(output_csv)
        if size == 0:
            errors.append(f"Output CSV is empty: {output_csv}")
        elif size < 100:
            warnings.append(f"Output CSV very small ({size} bytes): {output_csv}")

    if output_json and os.path.exists(output_json):
        with open(output_json) as f:
            data = json.load(f)
        if "fields" not in data:
            errors.append("Output JSON missing 'fields' key")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)

    return warnings


# =============================================================================
# Data loading
# =============================================================================
def load_from_npy_dir(results_dir):
    """Load results from a directory of .npy files.

    Expected files:
      vx.npy, vy.npy, vel.npy — velocity components (m/yr)
      thickness.npy — ice thickness (m)
      surface.npy — surface elevation (m)
      temperature.npy — temperature (K)
      pressure.npy — pressure (Pa)
    """
    fields = {}
    field_units = {
        "vx": "m/yr", "vy": "m/yr", "vz": "m/yr", "vel": "m/yr",
        "thickness": "m", "surface": "m", "base": "m",
        "temperature": "K", "pressure": "Pa",
        "damage": "-", "smb": "m/yr"
    }

    for fname in os.listdir(results_dir):
        if fname.endswith(".npy"):
            name = fname[:-4]
            try:
                data = np.load(os.path.join(results_dir, fname))
                fields[name] = data
            except Exception as e:
                print(f"WARNING: Failed to load {fname}: {e}", file=sys.stderr)

    return fields, field_units


def load_from_netcdf(nc_path, solution_type):
    """Load results from ISSM NetCDF output.

    ISSM's export_netCDF creates files with dimensions:
      - numberofvertices (or numberofnodes)
      - time (for transient)

    Variables follow naming: Vx, Vy, Vel, Thickness, Temperature, etc.
    """
    fields = {}
    field_units = {}

    with NCDataset(nc_path) as ds:
        for var_name in ds.variables:
            if var_name in ('x', 'y', 'z', 'elements', 'time'):
                continue
            var = ds.variables[var_name]
            data = np.array(var[:])
            fields[var_name] = data

            # Determine units
            if hasattr(var, 'units'):
                field_units[var_name] = var.units
            elif 'vel' in var_name.lower() or var_name in ('Vx', 'Vy', 'Vz', 'Vel'):
                field_units[var_name] = "m/yr"
            elif 'thick' in var_name.lower() or var_name == 'Thickness':
                field_units[var_name] = "m"
            elif 'temp' in var_name.lower() or var_name == 'Temperature':
                field_units[var_name] = "K"
            elif 'pressure' in var_name.lower() or var_name == 'Pressure':
                field_units[var_name] = "Pa"
            else:
                field_units[var_name] = "-"

    return fields, field_units


# Server default ISSM tree (same order as preflight_check.py ISSM_DIR_CANDIDATES)
ISSM_DIR_DEFAULTS = [
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/ISSM/source/repo",
    "KISSPATH_KI_ROOT/ISSM/source/repo",
]

# Known per-vertex result fields (used to pick the CSV row count when no mesh is given)
VERTEX_FIELD_HINTS = ("Vel", "Vx", "Vy", "Vz", "Thickness", "Surface", "Base", "Pressure",
                      "Temperature", "Enthalpy", "MaskOceanLevelset", "MaskIceLevelset")


# Units of fields AFTER ISSM's reader (it converts velocities/rates with yts and the
# mass totals to Gt/yr); only verified names, everything else "-" (unknown).
_ISSM_UNITS = {}
for _n in ("Vx", "Vy", "Vz", "Vel", "VxShear", "VyShear", "VxBase", "VyBase", "VxSurface",
           "VySurface", "VxAverage", "VyAverage", "VxDebris", "VyDebris", "HydrologyWaterVx",
           "HydrologyWaterVy", "BalancethicknessThickeningRate",
           "BasalforcingsGroundediceMeltingRate", "BasalforcingsFloatingiceMeltingRate",
           "BasalforcingsSpatialDeepwaterMeltingRate", "BasalforcingsSpatialUpperwaterMeltingRate",
           "CalvingCalvingrate", "Calvingratex", "Calvingratey", "CalvingMeltingrate"):
    _ISSM_UNITS[_n] = "m/yr"
for _n in ("TotalFloatingBmb", "TotalFloatingBmbScaled", "TotalGroundedBmb",
           "TotalGroundedBmbScaled", "TotalSmb", "TotalSmbScaled", "TotalSmbMelt",
           "TotalSmbRefreeze", "GroundinglineMassFlux", "IcefrontMassFlux",
           "IcefrontMassFluxLevelset"):
    _ISSM_UNITS[_n] = "Gt/yr"
for _n in ("Thickness", "Surface", "Base", "Bed"):
    _ISSM_UNITS[_n] = "m"
for _n in ("Pressure", "DeviatoricStressxx", "DeviatoricStressyy", "DeviatoricStresszz",
           "DeviatoricStressxy", "DeviatoricStressxz", "DeviatoricStressyz",
           "DeviatoricStresseffective"):
    _ISSM_UNITS[_n] = "Pa"
_ISSM_UNITS["Temperature"] = "K"


def _issm_units(name):
    return _ISSM_UNITS.get(name, "-")


def _json_safe(obj):
    """NaN/inf -> None so the JSON stays strict (NaN marks steps where a field is absent)."""
    if isinstance(obj, float):
        return obj if np.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


def resolve_issm_dir(arg):
    """--issm_dir -> $ISSM_DIR -> server default tree; must hold bin/parseresultsfromdisk.py."""
    if arg is not None:
        cands, source = [arg], "--issm_dir"
    elif os.environ.get("ISSM_DIR"):
        cands, source = [os.environ["ISSM_DIR"]], "$ISSM_DIR"
    else:
        cands, source = ISSM_DIR_DEFAULTS, "server default"
    for c in cands:
        if c and os.path.isfile(os.path.join(c, "bin", "parseresultsfromdisk.py")):
            return os.path.abspath(c)
    print(json.dumps({"status": "error", "errors": [
        f"ISSM result reader bin/parseresultsfromdisk.py not found in {cands} (from {source}); "
        f"give the ISSM tree with --issm_dir or $ISSM_DIR"]}))
    sys.exit(1)


def load_from_outbin(outbin, issm_dir, yts):
    """Read an ISSM .outbin with ISSM's OWN reader (parseresultsfromdisk.ReadData).

    ReadData applies ISSM's unit conversions (e.g. velocities m/s -> m/yr with md.constants.yts),
    so values equal md.results. Returns (fields, field_units, info):
      - one solution step: per-node/element arrays (M,1) -> 1-D (M,); scalars -> 1-D length 1
      - several steps: every numeric field -> 2-D (n_steps, M), rows aligned by the real step
        numbers (NaN where a field was not written at that step)
      - string records (e.g. SolutionType) go to info["metadata"], not to the numeric fields;
      - matrix records with more than one column (e.g. MeshElements) go to info["matrix_fields"]
        (per step: step, shape, min, max, mean), not to the per-vertex/time-series fields.
    """
    sys.path.insert(0, os.path.join(issm_dir, "bin"))
    try:
        from parseresultsfromdisk import ReadData
    except Exception as e:
        print(json.dumps({"status": "error", "errors": [
            f"Cannot import ISSM's reader from {issm_dir}/bin: {e}"]}))
        sys.exit(1)

    class _Constants:
        pass

    class _MdStub:
        pass

    md = _MdStub()
    md.constants = _Constants()
    md.constants.yts = float(yts)

    size = os.path.getsize(outbin)
    records = []
    with open(outbin, "rb") as fid:
        while True:
            start = fid.tell()
            rec = ReadData(fid, md)
            if rec is None:
                # ReadData treats any struct.error as end of file: make sure it really was
                if start != size:
                    raise ValueError(f"truncated or corrupt .outbin: record at byte {start} of "
                                     f"{size} could not be read completely")
                break
            records.append(rec)
    if not records:
        raise ValueError(f"no results found in {outbin}")

    steps = sorted({int(r["step"]) for r in records if r["step"] != -9999})
    n_steps = max(len(steps), 1)
    step_index = {st: i for i, st in enumerate(steps)}
    metadata, warnings, per_step, matrix_fields = {}, [], {}, {}
    times = [None] * n_steps
    for r in records:
        name = r["fieldname"]
        if isinstance(name, bytes):
            name = name.decode(errors="replace")
        idx = step_index.get(int(r["step"]), 0)
        if r["time"] != -9999:
            times[idx] = float(r["time"])
        val = r["field"]
        if isinstance(val, (str, bytes)):
            metadata[name] = val.decode(errors="replace") if isinstance(val, bytes) else val
            continue
        arr = np.asarray(val, dtype=float)
        if arr.ndim == 2 and arr.shape[1] == 1:
            arr = arr[:, 0]
        arr = np.atleast_1d(arr)
        if arr.ndim != 1:
            matrix_fields.setdefault(name, []).append({
                "step": int(r["step"]), "shape": list(arr.shape),
                "min": float(np.nanmin(arr)), "max": float(np.nanmax(arr)),
                "mean": float(np.nanmean(arr))})
            continue
        slot = per_step.setdefault(name, {})
        if idx in slot:
            warnings.append(f"field {name} written more than once for step index {idx}; "
                            f"last record kept (as ISSM's own reader does)")
        slot[idx] = arr

    fields = {}
    for name, slot in per_step.items():
        if n_steps == 1:
            fields[name] = slot[0]
            continue
        width = max(a.size for a in slot.values())
        stack = np.full((n_steps, width), np.nan)
        for i, a in slot.items():
            stack[i, :a.size] = a
        fields[name] = stack
    field_units = {name: _issm_units(name) for name in fields}
    info = {"metadata": metadata, "matrix_fields": matrix_fields, "n_steps": n_steps,
            "steps": steps, "times_yr": times, "yts": float(yts), "issm_dir": issm_dir,
            "reader_warnings": warnings}
    return fields, field_units, info


def pick_vertex_count(fields, mesh_x):
    """Row count for the per-vertex CSV: mesh size if given, else a known per-vertex field."""
    if mesh_x is not None:
        return len(mesh_x)
    for hint in VERTEX_FIELD_HINTS:
        data = fields.get(hint)
        if data is not None and data.ndim == 1 and data.size > 1:
            return int(data.size)
    sizes = [d.size for d in fields.values() if d.ndim == 1 and d.size > 1]
    return max(set(sizes), key=sizes.count) if sizes else None


# =============================================================================
# Output generation
# =============================================================================
def compute_statistics(fields, field_units):
    """Compute summary statistics for each field."""
    stats = []
    for name, data in fields.items():
        if data.ndim == 1:
            stat = {
                "name": name,
                "units": field_units.get(name, "-"),
                "shape": list(data.shape),
                "min": float(np.nanmin(data)),
                "max": float(np.nanmax(data)),
                "mean": float(np.nanmean(data)),
                "std": float(np.nanstd(data)),
                "n_nan": int(np.sum(np.isnan(data))),
                "n_total": int(data.size)
            }
        elif data.ndim == 2:
            # Time-varying field: compute per-timestep stats
            stat = {
                "name": name,
                "units": field_units.get(name, "-"),
                "shape": list(data.shape),
                "n_timesteps": data.shape[0],
                "min": float(np.nanmin(data)),
                "max": float(np.nanmax(data)),
                "mean": float(np.nanmean(data)),
                "std": float(np.nanstd(data)),
                "final_mean": float(np.nanmean(data[-1])),
                "final_max": float(np.nanmax(data[-1]))
            }
        else:
            stat = {
                "name": name,
                "units": field_units.get(name, "-"),
                "shape": list(data.shape)
            }
        stats.append(stat)
    return stats


def write_csv(fields, mesh_x, mesh_y, output_csv):
    """Write per-vertex results to CSV.

    Format: x, y, field1, field2, ...
    Only includes 1D (per-vertex) fields.
    """
    # Filter to 1D fields matching vertex count
    nv = len(mesh_x) if mesh_x is not None else None
    csv_fields = {}
    for name, data in fields.items():
        if data.ndim == 1:
            if nv is None or data.shape[0] == nv:
                csv_fields[name] = data

    if not csv_fields:
        print("WARNING: No 1D fields found for CSV output", file=sys.stderr)
        return

    header = []
    if mesh_x is not None:
        header.extend(["x", "y"])
    header.extend(sorted(csv_fields.keys()))

    with open(output_csv, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(header)

        n_rows = len(list(csv_fields.values())[0])
        for i in range(n_rows):
            row = []
            if mesh_x is not None:
                row.extend([f"{mesh_x[i]:.2f}", f"{mesh_y[i]:.2f}"])
            for name in sorted(csv_fields.keys()):
                row.append(f"{csv_fields[name][i]:.6g}")
            writer.writerow(row)

    print(f"CSV written: {output_csv} ({n_rows} rows, {len(header)} columns)", file=sys.stderr)


def write_timeseries_csv(fields, output_csv):
    """Write time series summary CSV for transient solutions.

    Format: timestep, field1_mean, field1_max, field2_mean, field2_max, ...
    """
    # Filter to 2D (time-varying) fields
    ts_fields = {name: data for name, data in fields.items() if data.ndim == 2}

    if not ts_fields:
        print("WARNING: No time-varying fields found for timeseries CSV", file=sys.stderr)
        return

    n_timesteps = max(data.shape[0] for data in ts_fields.values())

    header = ["timestep"]
    for name in sorted(ts_fields.keys()):
        header.extend([f"{name}_mean", f"{name}_max", f"{name}_min"])

    with open(output_csv, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(header)

        for t in range(n_timesteps):
            row = [t]
            for name in sorted(ts_fields.keys()):
                data = ts_fields[name]
                if t < data.shape[0]:
                    row.extend([
                        f"{np.nanmean(data[t]):.6g}",
                        f"{np.nanmax(data[t]):.6g}",
                        f"{np.nanmin(data[t]):.6g}"
                    ])
                else:
                    row.extend(["", "", ""])
            writer.writerow(row)

    print(f"Timeseries CSV written: {output_csv} ({n_timesteps} timesteps)", file=sys.stderr)


# =============================================================================
# Processing
# =============================================================================
def process_results(args):
    """Main processing: load, compute stats, write outputs."""
    # Load results
    outbin_info = None
    if args.outbin:
        issm_dir = resolve_issm_dir(args.issm_dir)
        try:
            fields, field_units, outbin_info = load_from_outbin(args.outbin, issm_dir, args.yts)
        except Exception as e:
            print(json.dumps({"status": "error",
                              "errors": [f"Failed to read {args.outbin}: {e}"]}))
            sys.exit(1)
        for w in outbin_info["reader_warnings"]:
            print(f"WARNING: {w}", file=sys.stderr)
        sol_type = outbin_info["metadata"].get("SolutionType")
        if sol_type and sol_type != args.solution + "Solution":
            print(f"WARNING: file holds {sol_type}, --solution is {args.solution}", file=sys.stderr)
    elif args.netcdf_file:
        fields, field_units = load_from_netcdf(args.netcdf_file, args.solution)
    else:
        fields, field_units = load_from_npy_dir(args.results_dir)

    if not fields:
        print(json.dumps({"status": "error", "errors": ["No result fields found"]}))
        sys.exit(1)

    print(f"Loaded {len(fields)} fields: {', '.join(fields.keys())}", file=sys.stderr)

    # Load mesh coordinates if available
    mesh_x = np.load(args.mesh_x) if args.mesh_x and os.path.exists(args.mesh_x) else None
    mesh_y = np.load(args.mesh_y) if args.mesh_y and os.path.exists(args.mesh_y) else None

    # Compute statistics
    stats = compute_statistics(fields, field_units)

    # Write JSON summary
    if args.output_json:
        summary = {
            "status": "success",
            "solution_type": args.solution,
            "n_fields": len(fields),
            "fields": stats
        }
        if outbin_info is not None:
            summary["outbin"] = outbin_info
            summary = _json_safe(summary)
        os.makedirs(os.path.dirname(os.path.abspath(args.output_json)), exist_ok=True)
        with open(args.output_json, 'w') as f:
            json.dump(summary, f, indent=2)
        print(f"JSON summary written: {args.output_json}", file=sys.stderr)

    # Write CSV
    if args.output_csv:
        os.makedirs(os.path.dirname(os.path.abspath(args.output_csv)), exist_ok=True)

        # Check if transient (time-varying fields)
        has_timeseries = any(data.ndim == 2 for data in fields.values())

        multi_step_outbin = outbin_info is not None and outbin_info["n_steps"] > 1
        if has_timeseries and (args.solution == "Transient" or multi_step_outbin):
            write_timeseries_csv(fields, args.output_csv)
        elif outbin_info is not None:
            # only per-vertex fields go to the CSV (an .outbin also holds per-element fields
            # and scalar diagnostics, which stay in the JSON statistics)
            nv = pick_vertex_count(fields, mesh_x)
            vfields = {k: v for k, v in fields.items() if v.ndim == 1 and nv and v.size == nv}
            if not vfields:
                print(json.dumps({"status": "error",
                                  "errors": ["No per-vertex fields found for the CSV"]}))
                sys.exit(1)
            write_csv(vfields, mesh_x, mesh_y, args.output_csv)
        else:
            write_csv(fields, mesh_x, mesh_y, args.output_csv)

    # Validate outputs
    warnings = validate_outputs(args.output_csv, args.output_json)

    # Print summary
    result = {
        "status": "success",
        "solution_type": args.solution,
        "n_fields": len(fields),
        "fields": stats,
        "csv": args.output_csv,
        "json": args.output_json,
        "warnings": warnings
    }
    if outbin_info is not None:
        result["outbin"] = outbin_info
        result = _json_safe(result)
    print(json.dumps(result, indent=2))


# =============================================================================
# CLI
# =============================================================================
def main():
    parser = argparse.ArgumentParser(description="Parse ISSM simulation results")

    parser.add_argument("--results_dir", help="Directory with .npy result files")
    parser.add_argument("--netcdf_file", help="ISSM NetCDF output file")
    parser.add_argument("--outbin", help="ISSM binary result file (<name>.outbin, written by "
                                         "issm.exe in the execution folder)")
    parser.add_argument("--issm_dir", default=None,
                        help="ISSM tree whose bin/parseresultsfromdisk.py reads --outbin "
                             "(default $ISSM_DIR, else the server ISSM tree)")
    parser.add_argument("--yts", type=float, default=365.0 * 24.0 * 3600.0,
                        help="md.constants.yts used by the run (s per year; ISSM default "
                             "31536000; run_issm.py records it in results.json)")
    parser.add_argument("--mesh_x", help="Mesh x-coordinates (.npy)")
    parser.add_argument("--mesh_y", help="Mesh y-coordinates (.npy)")
    parser.add_argument("--solution", default="Stressbalance",
                        choices=["Stressbalance", "Masstransport", "Thermal",
                                 "Transient", "Balancethickness", "Hydrology",
                                 "DamageEvolution", "Steadystate"])
    parser.add_argument("--output_csv", help="Output CSV file path")
    parser.add_argument("--output_json", help="Output JSON summary path")

    args = parser.parse_args()
    validate_inputs(args)
    process_results(args)


if __name__ == "__main__":
    main()
