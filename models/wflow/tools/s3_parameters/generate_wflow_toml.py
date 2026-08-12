#!/usr/bin/env python3
"""
generate_wflow_toml.py — Generate wflow TOML configuration file.

CRITICAL: wflow v1.0+ uses CSDMS standard names in the TOML configuration.
This is a BREAKING CHANGE from pre-v1.0 where shorter names were used.
Most online examples and tutorials use the OLD format — they will NOT work
with wflow v1.0+.

This tool generates a valid v1.0+ TOML file. If you need pre-v1.0 format,
use --legacy flag.

Usage:
    python generate_wflow_toml.py \
      --config /path/to/wflow_config.yaml \
      --output /path/to/wflow_sbm.toml

    python generate_wflow_toml.py \
      --staticmaps staticmaps.nc \
      --forcing forcing.nc \
      --start_date 2000-01-01 --end_date 2010-12-31 \
      --routing kinematic \
      --output wflow_sbm.toml
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path


def validate_inputs(args):
    """Validate inputs."""
    errors = []

    if args.config and not os.path.exists(args.config):
        errors.append(f"Config not found: {args.config}")

    if not args.config:
        if not args.staticmaps:
            errors.append("--staticmaps required when --config not provided")
        if not args.forcing:
            errors.append("--forcing required when --config not provided")
        if not args.start_date or not args.end_date:
            errors.append("--start_date and --end_date required when --config not provided")

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


def _resolve_staticmaps_path(staticmaps, output_path):
    """Locate staticmaps.nc on disk.

    The TOML records a path relative to dir_input, so the value passed in may
    not resolve from the current working directory.
    """
    if os.path.exists(staticmaps):
        return staticmaps
    cand = os.path.join(os.path.dirname(os.path.abspath(output_path)), staticmaps)
    return cand if os.path.exists(cand) else None


def resolve_outlet(staticmaps, output_path, outlet_lat=None, outlet_lon=None):
    """Determine the coordinates of the outlet/gauge cell to sample.

    Q_outlet must read the discharge OF THE GAUGE CELL. There is no acceptable
    fallback: `reducer = "maximum"` reports the largest river_water__volume_flow_rate
    anywhere in the domain, which coincides with the outlet only by accident, so
    a silent fallback produces a plausible-looking hydrograph from the wrong cell.
    Every source below is resolved from the build tool's own delineation; if none
    is available we fail rather than emit a domain-wide reducer.

    Order: explicit CLI args -> outlet.json sidecar -> staticmaps global attrs ->
    the single LDD pit cell inside the active subcatchment.
    """
    if outlet_lat is not None and outlet_lon is not None:
        return float(outlet_lat), float(outlet_lon), "explicit --outlet_lat/--outlet_lon"

    sm_path = _resolve_staticmaps_path(staticmaps, output_path)
    if sm_path is None:
        raise ValueError(
            f"cannot resolve outlet: staticmaps not found at '{staticmaps}'. "
            "Pass --outlet_lat/--outlet_lon explicitly."
        )

    sidecar = os.path.join(os.path.dirname(os.path.abspath(sm_path)), "outlet.json")
    if os.path.exists(sidecar):
        try:
            with open(sidecar) as f:
                meta = json.load(f)
            if meta.get("outlet_lat") is not None and meta.get("outlet_lon") is not None:
                return (float(meta["outlet_lat"]), float(meta["outlet_lon"]),
                        f"outlet.json sidecar ({sidecar})")
        except (ValueError, KeyError, OSError):
            pass

    try:
        import numpy as np
        import xarray as xr
    except ImportError as e:
        raise ValueError(
            f"cannot resolve outlet from staticmaps ({e}); "
            "pass --outlet_lat/--outlet_lon explicitly."
        )

    with xr.open_dataset(sm_path) as ds:
        if ds.attrs.get("outlet_lat") is not None and ds.attrs.get("outlet_lon") is not None:
            return (float(ds.attrs["outlet_lat"]), float(ds.attrs["outlet_lon"]),
                    f"staticmaps global attributes ({sm_path})")

        if "wflow_ldd" not in ds:
            raise ValueError(
                f"{sm_path} has no outlet attributes and no wflow_ldd to derive one "
                "from. Pass --outlet_lat/--outlet_lon explicitly."
            )

        ldd = ds["wflow_ldd"].values
        active = np.isfinite(ldd)
        if "wflow_subcatch" in ds:
            sub = ds["wflow_subcatch"].values
            active &= np.isfinite(sub) & (np.nan_to_num(sub) > 0)
        # LDD 5 = pit. A correctly delineated domain has exactly one.
        pits = np.argwhere(active & (np.nan_to_num(ldd) == 5))
        if len(pits) != 1:
            raise ValueError(
                f"{sm_path} has {len(pits)} LDD pit cell(s) (expected exactly 1), so "
                "the outlet cell is ambiguous. Rebuild the domain or pass "
                "--outlet_lat/--outlet_lon explicitly."
            )
        oj, oi = int(pits[0][0]), int(pits[0][1])
        ycoord = "y" if "y" in ds.coords else "lat"
        xcoord = "x" if "x" in ds.coords else "lon"
        return (float(ds[ycoord].values[oj]), float(ds[xcoord].values[oi]),
                f"wflow_ldd pit cell ({oj},{oi}) in {sm_path}")


def generate_toml_content(
    staticmaps_path,
    forcing_path,
    start_date,
    end_date,
    output_dir,
    routing="kinematic",
    timestep=86400,
    sediment=False,
    glacier=False,
    output_grid_nc="output_grid.nc",
    output_scalar_nc="output_scalar.nc",
    outstates_nc="outstates.nc",
    instates_nc="",
    legacy=False,
    outlet_lat=None,
    outlet_lon=None,
):
    """Generate the TOML configuration string.

    This generates a valid wflow v1.1.0+ TOML configuration using CSDMS standard
    names. IMPORTANT: wflow v1.1.0 has completely different TOML format from pre-v1.0.
    Key differences:
      - [time] not [calendar]
      - [model] uses double-underscore field names (snow__flag, glacier__flag, etc.)
      - [input] requires basin__local_drain_direction, river_location__mask,
        subbasin_location__count as mandatory fields
      - [input.forcing] uses CSDMS names (atmosphere_water__precipitation_volume_flux, etc.)
      - [input.static] uses CSDMS names for all parameters
      - [state.variables] must list ALL 11 required state variables even for cold start
      - [output.csv.column] uses 'parameter' not 'map'
      - soil_layer__thickness creates maxlayers = n + 1 internally
    """
    lines = []
    lines.append("# wflow_sbm configuration file")
    lines.append(f"# Generated by HydroCraft generate_wflow_toml.py")
    lines.append(f"# Date: {datetime.now().isoformat()}")
    lines.append(f"# IMPORTANT: wflow v1.1.0+ CSDMS standard names format")
    lines.append("")

    lines.append('dir_input = "."')
    lines.append('dir_output = "."')
    lines.append("")

    # --- Time section ---
    lines.append("[time]")
    lines.append(f'starttime = {start_date}T00:00:00')
    lines.append(f'endtime = {end_date}T00:00:00')
    lines.append(f"timestepsecs = {timestep}")
    lines.append("")

    lines.append("[logging]")
    lines.append('loglevel = "info"')
    lines.append("")

    # --- Model section ---
    lines.append("[model]")
    lines.append('type = "sbm"')
    lines.append(f"snow__flag = true")
    lines.append(f"glacier__flag = {'true' if glacier else 'false'}")
    lines.append(f"cold_start__flag = {'false' if instates_nc else 'true'}")
    lines.append("soil_layer__thickness = [100, 300, 1500]")
    lines.append("")

    # --- Input section ---
    lines.append("[input]")
    lines.append(f'path_forcing = "{forcing_path}"')
    lines.append(f'path_static = "{staticmaps_path}"')
    lines.append("")
    lines.append("# Domain definition (mandatory)")
    lines.append('basin__local_drain_direction = "wflow_ldd"')
    lines.append('river_location__mask = "wflow_river"')
    lines.append('subbasin_location__count = "wflow_subcatch"')
    lines.append("")

    # Forcing variables (CSDMS standard names)
    lines.append("[input.forcing]")
    lines.append('atmosphere_water__precipitation_volume_flux = "precip"')
    lines.append('land_surface_water__potential_evaporation_volume_flux = "pet"')
    lines.append('atmosphere_air__temperature = "temp"')
    lines.append("")

    # Static input (CSDMS standard names)
    lines.append("[input.static]")
    lines.append("# Snow parameters")
    lines.append('atmosphere_air__snowfall_temperature_threshold = "tt"')
    lines.append('atmosphere_air__snowfall_temperature_interval = "tti"')
    lines.append('snowpack__melting_temperature_threshold = "ttm"')
    lines.append('snowpack__degree_day_coefficient = "cfmax"')
    lines.append("")
    lines.append("# Soil parameters")
    # Read the Brooks-Corey exponent from the staticmaps map (layer, y, x) so the
    # HWSD-derived, spatially varying value is actually used. A hard-coded
    # .value list silently overrides whatever the build tool wrote.
    lines.append('soil_layer_water__brooks_corey_exponent = "c"')
    lines.append('soil_surface_water__vertical_saturated_hydraulic_conductivity = "KsatVer"')
    lines.append('soil_water__vertical_saturated_hydraulic_conductivity_scale_parameter = "f"')
    lines.append('compacted_soil_surface_water__infiltration_capacity = "InfiltCapPath"')
    lines.append('soil_water__residual_volume_fraction = "theta_r"')
    lines.append('soil_water__saturated_volume_fraction = "theta_s"')
    lines.append('soil_water_saturated_zone_bottom__max_leakage_volume_flux = "MaxLeakage"')
    lines.append('compacted_soil__area_fraction = "PathFrac"')
    lines.append('soil__thickness = "SoilThickness"')
    lines.append('subsurface_water__horizontal_to_vertical_saturated_hydraulic_conductivity_ratio = "KsatHorFrac"')
    lines.append("")
    lines.append("# Vegetation parameters")
    lines.append('vegetation_canopy__gap_fraction = "CanopyGapFraction"')
    lines.append('vegetation_water__storage_capacity = "Cmax"')
    lines.append('vegetation_root__depth = "RootingDepth"')
    lines.append('land_water_covered__area_fraction = "WaterFrac"')
    lines.append("")
    lines.append("# River parameters")
    lines.append('river__length = "RiverLength"')
    lines.append('river_water_flow__manning_n_parameter = "N_River"')
    lines.append('river__slope = "RiverSlope"')
    lines.append('river__width = "RiverWidth"')
    lines.append("")
    lines.append("# Land surface parameters")
    lines.append('land_surface_water_flow__manning_n_parameter = "N"')
    lines.append('land_surface__slope = "Slope"')
    lines.append("")

    # --- State section ---
    lines.append("[state]")
    lines.append(f'path_output = "{outstates_nc}"')
    if instates_nc:
        lines.append(f'path_input = "{instates_nc}"')
    lines.append("")

    # State variable mappings (ALL 11 required even for cold start)
    lines.append("[state.variables]")
    lines.append('snowpack_dry_snow__leq_depth = "snow"')
    lines.append('snowpack_liquid_water__depth = "snowwater"')
    lines.append('vegetation_canopy_water__depth = "canopystorage"')
    lines.append('soil_water_saturated_zone__depth = "satwaterdepth"')
    lines.append('soil_surface__temperature = "tsoil"')
    lines.append('soil_layer_water_unsaturated_zone__depth = "ustorelayerdepth"')
    lines.append('subsurface_water__volume_flow_rate = "ssf"')
    lines.append('land_surface_water__instantaneous_volume_flow_rate = "q_land"')
    lines.append('land_surface_water__depth = "h_land"')
    lines.append('river_water__instantaneous_volume_flow_rate = "q_river"')
    lines.append('river_water__depth = "h_river"')
    lines.append("")

    # --- Output section ---
    lines.append("[output.netcdf_grid]")
    lines.append(f'path = "{output_grid_nc}"')
    lines.append("")

    lines.append("[output.netcdf_grid.variables]")
    lines.append('river_water__volume_flow_rate = "q_river"')
    # Actual ET is needed to close the water balance (P - ET - Q - dS).
    # Without it the closure check can only be computed with ET as the
    # residual, which makes it vacuous.
    lines.append('land_surface__evapotranspiration_volume_flux = "actevap"')
    # Storage terms, so delta-S in the closure check is measured rather than
    # assumed zero.
    lines.append('soil_water_saturated_zone__depth = "satwaterdepth"')
    lines.append('soil_layer_water_unsaturated_zone__depth = "ustorelayerdepth"')
    lines.append('snowpack_dry_snow__leq_depth = "snow"')
    lines.append("")

    # CSV output
    lines.append("[output.csv]")
    lines.append('path = "output.csv"')
    lines.append("")

    # Q_outlet ALWAYS samples the gauge/outlet cell by coordinate. A reducer
    # such as "maximum" takes the largest q anywhere in the domain, which is the
    # outlet only by accident — on any basin with a larger neighbouring channel,
    # or during a tributary flood peak, it silently reports the wrong cell. The
    # caller must resolve the outlet (see resolve_outlet) before getting here.
    if outlet_lat is None or outlet_lon is None:
        raise ValueError(
            "outlet_lat/outlet_lon are required: Q_outlet must sample the gauge "
            "cell explicitly and there is no valid domain-wide fallback."
        )
    lines.append("[[output.csv.column]]")
    lines.append('header = "Q_outlet"')
    lines.append('parameter = "river_water__volume_flow_rate"')
    lines.append(f"coordinate.x = {outlet_lon}")
    lines.append(f"coordinate.y = {outlet_lat}")
    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Generate wflow TOML configuration file"
    )
    parser.add_argument("--config", type=str, default="",
                        help="HydroCraft wflow_config.yaml")
    parser.add_argument("--staticmaps", type=str, default="staticmaps.nc")
    parser.add_argument("--forcing", type=str, default="forcing.nc")
    parser.add_argument("--start_date", type=str, default="")
    parser.add_argument("--end_date", type=str, default="")
    parser.add_argument("--routing", type=str, default="kinematic",
                        choices=["kinematic", "local_inertial"])
    parser.add_argument("--timestep", type=int, default=86400,
                        help="Timestep in seconds (default: 86400 = daily)")
    parser.add_argument("--sediment", action="store_true")
    parser.add_argument("--glacier", action="store_true")
    parser.add_argument("--instates", type=str, default="",
                        help="Path to initial states NetCDF for warm start")
    parser.add_argument("--output_dir", type=str, default="output")
    parser.add_argument("--legacy", action="store_true",
                        help="Generate pre-v1.0 TOML format")
    parser.add_argument("--outlet_lat", type=float, default=None,
                        help="Gauge latitude for the Q_outlet CSV column. Optional: "
                             "when omitted it is resolved from outlet.json, the "
                             "staticmaps attributes, or the single LDD pit cell. "
                             "If none of those resolve, the tool fails — Q_outlet "
                             "is never a domain-wide reducer.")
    parser.add_argument("--outlet_lon", type=float, default=None)
    parser.add_argument("--output", type=str, required=True)
    args = parser.parse_args()

    validate_inputs(args)

    # Load config if provided
    if args.config:
        import yaml
        with open(args.config) as f:
            config = yaml.safe_load(f)
        staticmaps = config["paths"]["staticmaps"]
        forcing = config["paths"]["forcing_nc"]
        start_date = f"{config['simulation']['start_year']}-01-01"
        end_date = f"{config['simulation']['end_year']}-12-31"
        routing = config["model"]["routing"]
        sediment = config["model"]["sediment"]
        glacier = config["model"]["glacier"]
        output_dir = config["paths"]["output_dir"]
        timestep = config["simulation"]["timestep_seconds"]
    else:
        staticmaps = args.staticmaps
        forcing = args.forcing
        start_date = args.start_date
        end_date = args.end_date
        routing = args.routing
        sediment = args.sediment
        glacier = args.glacier
        output_dir = args.output_dir
        timestep = args.timestep

    # Q_outlet must sample the gauge cell; resolve it before writing the TOML so
    # a missing outlet is a hard, visible failure rather than a silent
    # domain-wide maximum.
    outlet_lat, outlet_lon = args.outlet_lat, args.outlet_lon
    if (outlet_lat is None or outlet_lon is None) and args.config:
        basin = config.get("basin", {}) if isinstance(config, dict) else {}
        if basin.get("outlet_lat") is not None and basin.get("outlet_lon") is not None:
            outlet_lat = float(basin["outlet_lat"])
            outlet_lon = float(basin["outlet_lon"])
    try:
        outlet_lat, outlet_lon, outlet_source = resolve_outlet(
            staticmaps, args.output, outlet_lat, outlet_lon)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(1)  # see os._exit note below: xarray/libgmt teardown SIGSEGV
    print(f"Q_outlet sampled at ({outlet_lat}, {outlet_lon}) "
          f"from {outlet_source}", file=sys.stderr)

    content = generate_toml_content(
        staticmaps_path=staticmaps,
        forcing_path=forcing,
        start_date=start_date,
        end_date=end_date,
        output_dir=output_dir,
        routing=routing,
        timestep=timestep,
        sediment=sediment,
        glacier=glacier,
        instates_nc=args.instates,
        outlet_lat=outlet_lat,
        outlet_lon=outlet_lon,
    )

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        f.write(content)

    result = {
        "status": "success",
        "toml_path": args.output,
        "model_type": "wflow_sbm",
        "routing": routing,
        "period": f"{start_date} to {end_date}",
        "timestep_seconds": timestep,
        "sediment": sediment,
        "glacier": glacier,
        "outlet_lat": outlet_lat,
        "outlet_lon": outlet_lon,
        "outlet_source": outlet_source,
    }

    print(json.dumps(result, indent=2))
    # Resolving the outlet imports xarray, which can pull in a broken libgmt
    # backend that SIGSEGVs at interpreter teardown AFTER the TOML is written —
    # turning a successful run into exit 139. Flush and hard-exit instead.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
