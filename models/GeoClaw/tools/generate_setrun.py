#!/usr/bin/env python3
"""
generate_setrun.py — Generate a GeoClaw setrun.py configuration from JSON parameters.

Creates a complete setrun.py file from a JSON parameter specification.
This avoids manual editing errors and ensures parameter consistency.

CRITICAL UNIT REQUIREMENTS:
  - All lengths in meters (coordinate_system=1) or degrees (coordinate_system=2)
  - All times in seconds
  - gravity in m/s² (default 9.81)
  - Manning coefficient: dimensionless (typical 0.01–0.06)
  - sea_level in meters relative to datum
  - Fault parameters: slip in m, depth in km, angles in degrees

Pattern: validate_inputs → process → validate_outputs
"""

import argparse
import json
import sys
import os


def validate_inputs(args):
    """Phase 1: Validate all inputs before generating setrun.py."""
    errors = []
    warnings = []

    # Load JSON config
    if not os.path.isfile(args.config):
        errors.append(f"Config file not found: {args.config}")
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)

    with open(args.config, "r") as f:
        try:
            config = json.load(f)
        except json.JSONDecodeError as e:
            errors.append(f"Invalid JSON: {e}")
            print(json.dumps({"status": "error", "errors": errors}))
            sys.exit(1)

    # Required fields
    required = ["domain", "time", "output"]
    for field in required:
        if field not in config:
            errors.append(f"Missing required section: '{field}'")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)

    # Validate domain
    domain = config.get("domain", {})
    if "xlower" not in domain or "xupper" not in domain:
        errors.append("domain must contain xlower and xupper")
    if "ylower" not in domain or "yupper" not in domain:
        errors.append("domain must contain ylower and yupper")
    if domain.get("xlower", 0) >= domain.get("xupper", 1):
        errors.append("xlower must be < xupper")
    if domain.get("ylower", 0) >= domain.get("yupper", 1):
        errors.append("ylower must be < yupper")

    # Validate coordinate system
    coord_sys = config.get("physics", {}).get("coordinate_system", 2)
    if coord_sys == 2:
        # lat-lon: check bounds are in degrees
        if abs(domain.get("xlower", 0)) > 360 or abs(domain.get("xupper", 0)) > 360:
            warnings.append("coordinate_system=2 (lat-lon) but domain bounds exceed 360°")
        if abs(domain.get("ylower", 0)) > 90 or abs(domain.get("yupper", 0)) > 90:
            warnings.append("coordinate_system=2 (lat-lon) but y-bounds exceed ±90°")
    elif coord_sys == 1:
        # Cartesian: check bounds are in meters (not degrees)
        if abs(domain.get("xupper", 0)) < 1.0 and abs(domain.get("yupper", 0)) < 1.0:
            warnings.append(
                "coordinate_system=1 (Cartesian/meters) but domain bounds are very small. "
                "Are these in degrees? Set coordinate_system=2 for lat-lon."
            )

    # Validate time
    time_cfg = config.get("time", {})
    t0 = time_cfg.get("t0", 0.0)
    tfinal = time_cfg.get("tfinal", 1.0)
    if tfinal <= t0:
        errors.append(f"tfinal ({tfinal}) must be > t0 ({t0})")
    if tfinal > 1e7:
        warnings.append(
            f"tfinal={tfinal}s = {tfinal/3600:.1f}h. Very long simulation. "
            "GeoClaw uses seconds — make sure this isn't in minutes or hours."
        )

    # Validate CFL
    cfl = config.get("numerics", {}).get("cfl_desired", 0.75)
    if cfl >= 1.0:
        errors.append(f"cfl_desired={cfl} ≥ 1.0 — will cause numerical instability")
    if cfl < 0.1:
        warnings.append(f"cfl_desired={cfl} is very small — simulation will be slow")

    # Validate AMR
    amr = config.get("amr", {})
    max_levels = amr.get("amr_levels_max", 1)
    ratios = amr.get("refinement_ratios_x", [])
    if len(ratios) != max(max_levels - 1, 0):
        if max_levels > 1:
            errors.append(
                f"refinement_ratios_x has {len(ratios)} entries "
                f"but amr_levels_max={max_levels} requires {max_levels-1}"
            )

    # Validate Manning coefficient
    manning = config.get("physics", {}).get("manning_coefficient", 0.025)
    if manning > 0.1:
        warnings.append(
            f"Manning coefficient {manning} is unusually high (typical: 0.01–0.06). "
            "This will cause extreme friction."
        )
    if manning < 0.001 and manning > 0:
        warnings.append(
            f"Manning coefficient {manning} is very low — nearly frictionless flow."
        )

    # Validate topography files
    topo_files = config.get("topography", {}).get("files", [])
    for tf in topo_files:
        fpath = tf.get("path", "")
        if fpath and not os.path.isfile(fpath):
            warnings.append(f"Topography file not found (may be created later): {fpath}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors, "warnings": warnings}))
        sys.exit(1)

    return config, warnings


def process(config, input_warnings):
    """Phase 2: Generate setrun.py content from config."""
    warnings = list(input_warnings)

    domain = config.get("domain", {})
    time_cfg = config.get("time", {})
    numerics = config.get("numerics", {})
    physics = config.get("physics", {})
    amr = config.get("amr", {})
    topo = config.get("topography", {})
    dtopo = config.get("dtopo", {})
    gauges = config.get("gauges", [])
    output = config.get("output", {})

    lines = []
    lines.append('"""')
    lines.append("setrun.py — GeoClaw configuration generated by generate_setrun.py")
    lines.append(f"Domain: [{domain.get('xlower')}, {domain.get('xupper')}] x "
                 f"[{domain.get('ylower')}, {domain.get('yupper')}]")
    lines.append(f"Time: {time_cfg.get('t0', 0)} to {time_cfg.get('tfinal')} seconds")
    lines.append('"""')
    lines.append("")
    lines.append("import os")
    lines.append("import numpy as np")
    lines.append("from clawpack.clawutil import data as clawdata_module")
    lines.append("")
    lines.append("")
    lines.append("def setrun(claw_pkg='geoclaw'):")
    lines.append("    from clawpack.clawutil import data as clawutil")
    lines.append("    assert claw_pkg.lower() == 'geoclaw', 'Expected geoclaw'")
    lines.append("")
    lines.append("    num_dim = 2")
    lines.append("    rundata = clawutil.ClawRunData(claw_pkg, num_dim)")
    lines.append("")

    # --- clawdata ---
    lines.append("    # ---- Standard Clawpack parameters ----")
    lines.append("    clawdata = rundata.clawdata")
    lines.append(f"    clawdata.num_dim = {2}")
    lines.append(f"    clawdata.lower[0] = {domain.get('xlower', -1.0)}")
    lines.append(f"    clawdata.upper[0] = {domain.get('xupper', 1.0)}")
    lines.append(f"    clawdata.lower[1] = {domain.get('ylower', -1.0)}")
    lines.append(f"    clawdata.upper[1] = {domain.get('yupper', 1.0)}")
    lines.append(f"    clawdata.num_cells[0] = {domain.get('mx', 100)}")
    lines.append(f"    clawdata.num_cells[1] = {domain.get('my', 100)}")
    lines.append("")
    lines.append(f"    clawdata.num_eqn = 3")
    lines.append(f"    clawdata.num_waves = 3")
    lines.append(f"    clawdata.num_aux = 1")
    lines.append("")

    # Time
    lines.append("    # ---- Time stepping ----")
    lines.append(f"    clawdata.t0 = {time_cfg.get('t0', 0.0)}")
    lines.append(f"    clawdata.tfinal = {time_cfg.get('tfinal', 1.0)}")
    lines.append(f"    clawdata.output_style = {output.get('output_style', 1)}")

    if output.get("output_style", 1) == 1:
        lines.append(f"    clawdata.num_output_times = {output.get('num_output_times', 10)}")
    elif output.get("output_style") == 2:
        times = output.get("output_times", [])
        lines.append(f"    clawdata.output_times = {times}")

    lines.append(f"    clawdata.output_format = '{output.get('output_format', 'ascii')}'")
    lines.append(f"    clawdata.output_t0 = True")
    lines.append("")

    # Numerics
    lines.append("    # ---- Numerical method ----")
    lines.append(f"    clawdata.order = {numerics.get('order', 2)}")
    lines.append(f"    clawdata.dimensional_split = 'unsplit'")
    lines.append(f"    clawdata.transverse_waves = {numerics.get('transverse_waves', 2)}")
    lines.append(f"    clawdata.num_ghost = 2")
    limiter = numerics.get("limiter", "mc")
    lines.append(f"    clawdata.limiter = ['{limiter}', '{limiter}', '{limiter}']")
    lines.append(f"    clawdata.use_fwaves = True")
    lines.append(f"    clawdata.source_split = 'godunov'")
    lines.append("")

    # CFL
    lines.append("    # ---- CFL ----")
    lines.append(f"    clawdata.dt_variable = True")
    lines.append(f"    clawdata.dt_initial = {numerics.get('dt_initial', 1.0)}")
    lines.append(f"    clawdata.dt_max = {numerics.get('dt_max', 1e9)}")
    lines.append(f"    clawdata.cfl_desired = {numerics.get('cfl_desired', 0.75)}")
    lines.append(f"    clawdata.cfl_max = {numerics.get('cfl_max', 1.0)}")
    lines.append(f"    clawdata.steps_max = {numerics.get('steps_max', 50000)}")
    lines.append("")

    # Boundary conditions
    bc_lower = domain.get("bc_lower", ["extrap", "extrap"])
    bc_upper = domain.get("bc_upper", ["extrap", "extrap"])
    lines.append("    # ---- Boundary conditions ----")
    lines.append(f"    clawdata.bc_lower[0] = '{bc_lower[0]}'")
    lines.append(f"    clawdata.bc_lower[1] = '{bc_lower[1]}'")
    lines.append(f"    clawdata.bc_upper[0] = '{bc_upper[0]}'")
    lines.append(f"    clawdata.bc_upper[1] = '{bc_upper[1]}'")
    lines.append("")

    # --- AMR ---
    lines.append("    # ---- AMR parameters ----")
    lines.append("    amrdata = rundata.amrdata")
    max_levels = amr.get("amr_levels_max", 1)
    lines.append(f"    amrdata.amr_levels_max = {max_levels}")
    if max_levels > 1:
        rx = amr.get("refinement_ratios_x", [4] * (max_levels - 1))
        ry = amr.get("refinement_ratios_y", rx)
        rt = amr.get("refinement_ratios_t", rx)
        lines.append(f"    amrdata.refinement_ratios_x = {rx}")
        lines.append(f"    amrdata.refinement_ratios_y = {ry}")
        lines.append(f"    amrdata.refinement_ratios_t = {rt}")
    lines.append(f"    amrdata.regrid_interval = {amr.get('regrid_interval', 3)}")
    lines.append(f"    amrdata.regrid_buffer_width = {amr.get('regrid_buffer_width', 2)}")
    lines.append("")

    # --- GeoClaw physics ---
    lines.append("    # ---- GeoClaw physics ----")
    lines.append("    geo_data = rundata.geo_data")
    lines.append(f"    geo_data.gravity = {physics.get('gravity', 9.81)}")
    lines.append(f"    geo_data.coordinate_system = {physics.get('coordinate_system', 2)}")
    lines.append(f"    geo_data.earth_radius = {physics.get('earth_radius', 6367500.0)}")
    lines.append(f"    geo_data.sea_level = {physics.get('sea_level', 0.0)}")
    lines.append(f"    geo_data.dry_tolerance = {physics.get('dry_tolerance', 1e-3)}")
    lines.append("")

    # Friction
    friction = physics.get("friction_forcing", True)
    lines.append(f"    geo_data.friction_forcing = {friction}")
    if friction:
        lines.append(f"    geo_data.manning_coefficient = {physics.get('manning_coefficient', 0.025)}")
        lines.append(f"    geo_data.friction_depth = {physics.get('friction_depth', 1e6)}")
    lines.append("")

    # Coriolis
    lines.append(f"    geo_data.coriolis_forcing = {physics.get('coriolis_forcing', False)}")
    lines.append("")

    # --- Refinement ---
    lines.append("    # ---- Refinement ----")
    lines.append("    refinement_data = rundata.refinement_data")
    lines.append(f"    refinement_data.wave_tolerance = {amr.get('wave_tolerance', 1e-2)}")
    lines.append("")

    # --- Topography ---
    lines.append("    # ---- Topography ----")
    lines.append("    topo_data = rundata.topo_data")
    topo_files = topo.get("files", [])
    for tf in topo_files:
        ttype = tf.get("type", 2)
        tpath = tf.get("path", "topo.tt2")
        lines.append(f"    topo_data.topofiles.append([{ttype}, '{tpath}'])")
    if not topo_files:
        lines.append("    # No topography files specified — add manually")
    lines.append("")

    # --- Dynamic topography ---
    dtopo_files = dtopo.get("files", [])
    if dtopo_files:
        lines.append("    # ---- Dynamic topography (earthquake) ----")
        lines.append("    dtopo_data = rundata.dtopo_data")
        for df in dtopo_files:
            dtype = df.get("type", 3)
            dpath = df.get("path", "dtopo.tt3")
            lines.append(f"    dtopo_data.dtopofiles.append([{dtype}, '{dpath}'])")
        lines.append("")

    # --- Gauges ---
    if gauges:
        lines.append("    # ---- Gauges ----")
        lines.append("    gaugedata = rundata.gaugedata")
        for g in gauges:
            gid = g.get("id", 1)
            gx = g.get("x", 0.0)
            gy = g.get("y", 0.0)
            gt1 = g.get("t1", time_cfg.get("t0", 0.0))
            gt2 = g.get("t2", time_cfg.get("tfinal", 1.0))
            lines.append(f"    gaugedata.gauges.append([{gid}, {gx}, {gy}, {gt1}, {gt2}])")
        lines.append("")

    # --- Return ---
    lines.append("    return rundata")
    lines.append("")
    lines.append("")
    lines.append("if __name__ == '__main__':")
    lines.append("    rundata = setrun()")
    lines.append("    rundata.write()")
    lines.append("")

    content = "\n".join(lines)

    result = {
        "status": "success",
        "content": content,
        "n_lines": len(lines),
        "sections": ["clawdata", "amr", "geo_data", "refinement", "topography"],
        "warnings": warnings,
    }

    return result


def validate_outputs(result, output_path):
    """Phase 3: Validate the generated setrun.py."""
    warnings = result.get("warnings", [])

    # Check file was written
    if not os.path.isfile(output_path):
        warnings.append(f"CRITICAL: Output file not created: {output_path}")
    else:
        size = os.path.getsize(output_path)
        if size < 500:
            warnings.append(f"WARNING: setrun.py is very small ({size} bytes)")
        result["file_size_bytes"] = size

    # Try to parse the generated file
    try:
        content = result["content"]
        compile(content, output_path, "exec")
        result["syntax_valid"] = True
    except SyntaxError as e:
        warnings.append(f"CRITICAL: Generated setrun.py has syntax error: {e}")
        result["syntax_valid"] = False

    result["warnings"] = warnings
    # Remove content from result to keep JSON clean
    del result["content"]
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Generate GeoClaw setrun.py from JSON configuration"
    )
    parser.add_argument("--config", required=True,
                        help="JSON configuration file")
    parser.add_argument("--output", required=True,
                        help="Output setrun.py file path")
    parser.add_argument("--json-output", default=None,
                        help="Write result JSON to this file")

    args = parser.parse_args()

    # Phase 1: Validate inputs
    config, input_warnings = validate_inputs(args)

    # Phase 2: Process
    result = process(config, input_warnings)

    # Write setrun.py
    with open(args.output, "w") as f:
        f.write(result["content"])

    # Phase 3: Validate outputs
    result = validate_outputs(result, args.output)
    result["output_file"] = args.output

    # Write JSON result
    if args.json_output:
        with open(args.json_output, "w") as f:
            json.dump(result, f, indent=2)
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
