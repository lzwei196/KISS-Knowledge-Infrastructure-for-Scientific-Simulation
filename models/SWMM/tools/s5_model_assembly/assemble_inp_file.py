#!/usr/bin/env python3
"""
Assemble a complete SWMM .inp file from component CSVs and JSONs.

Combines subcatchment definitions, drainage network, rainfall timeseries,
simulation options, and optional LID controls into a single SWMM input file.

This is the central assembly step that brings together outputs from all
upstream tools (s1-s4) into a runnable model.

Component inputs:
  - Subcatchments CSV (id, rain_gage, outlet, area_ha, imperv_pct, width, slope)
  - Subareas CSV (id, n_imperv, n_perv, ds_imperv, ds_perv, pct_zero, route_to)
  - Infiltration CSV (id, params depending on method)
  - Junctions CSV (id, invert_elev, max_depth, init_depth, surcharge_depth, ponded_area)
  - Conduits CSV (id, from_node, to_node, length, roughness, in_offset, out_offset)
  - Outfalls CSV (id, invert_elev, type, stage_data, gated)
  - Cross-sections CSV (conduit_id, shape, geom1, geom2, geom3, geom4, barrels)
  - Rain gages JSON
  - Timeseries file(s)
  - Options JSON
  - LID controls JSON (optional)
  - LID usage JSON (optional)

Output:
  - Complete SWMM .inp file
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path


def read_csv_rows(csv_path):
    """Read all rows from CSV as list of dicts."""
    if not csv_path or not os.path.isfile(csv_path):
        return []
    with open(csv_path, "r") as f:
        return list(csv.DictReader(f))


def read_json(json_path):
    """Read JSON file."""
    if not json_path or not os.path.isfile(json_path):
        return {}
    with open(json_path, "r") as f:
        return json.load(f)


def write_section(f, section_name, header_comment, rows, col_widths=None):
    """Write a SWMM .inp section."""
    f.write(f"\n[{section_name}]\n")
    if header_comment:
        f.write(f";;{header_comment}\n")
    for row in rows:
        if isinstance(row, str):
            f.write(row + "\n")
        elif isinstance(row, (list, tuple)):
            f.write("  ".join(str(v) for v in row) + "\n")
    return


def fmt(value, width=16):
    """Format a value to fixed width."""
    s = str(value)
    return s.ljust(width)


def main():
    parser = argparse.ArgumentParser(
        description="Assemble a complete SWMM .inp file from components"
    )
    parser.add_argument("--subcatchments", required=True,
                        help="Subcatchments CSV")
    parser.add_argument("--subareas", default=None,
                        help="Subareas CSV (N-Imperv, N-Perv, etc.)")
    parser.add_argument("--infiltration", default=None,
                        help="Infiltration CSV (method-specific params)")
    parser.add_argument("--junctions", required=True,
                        help="Junctions CSV")
    parser.add_argument("--conduits", required=True,
                        help="Conduits CSV")
    parser.add_argument("--outfalls", required=True,
                        help="Outfalls CSV")
    parser.add_argument("--xsections", default=None,
                        help="Cross-sections CSV")
    parser.add_argument("--raingages", default=None,
                        help="Rain gages JSON")
    parser.add_argument("--timeseries", default=None,
                        help="Timeseries file (.dat)")
    parser.add_argument("--options", default=None,
                        help="Simulation options JSON")
    parser.add_argument("--lid_controls", default=None,
                        help="LID controls JSON")
    parser.add_argument("--lid_usage", default=None,
                        help="LID usage JSON")
    parser.add_argument("--output", required=True,
                        help="Output .inp file path")
    parser.add_argument("--title", default="SWMM Model (HydroCraft)",
                        help="Model title")
    args = parser.parse_args()

    # Validate required files
    for name, path in [("subcatchments", args.subcatchments),
                       ("junctions", args.junctions),
                       ("conduits", args.conduits),
                       ("outfalls", args.outfalls)]:
        if not os.path.isfile(path):
            print(f"ERROR: {name} file not found: {path}", file=sys.stderr)
            sys.exit(1)

    # Read all components
    subcatchments = read_csv_rows(args.subcatchments)
    subareas = read_csv_rows(args.subareas)
    infiltration = read_csv_rows(args.infiltration)
    junctions = read_csv_rows(args.junctions)
    conduits = read_csv_rows(args.conduits)
    outfalls = read_csv_rows(args.outfalls)
    xsections = read_csv_rows(args.xsections)
    options = read_json(args.options) if args.options else {}
    raingages = read_json(args.raingages) if args.raingages else {}
    lid_controls = read_json(args.lid_controls) if args.lid_controls else {}
    lid_usage = read_json(args.lid_usage) if args.lid_usage else {}

    # Set defaults for options
    opts = {
        "FLOW_UNITS": options.get("flow_units", "CMS"),
        "INFILTRATION": options.get("infiltration", "GREEN_AMPT"),
        "ROUTING_MODEL": options.get("routing", "DYNWAVE"),
        "LINK_OFFSETS": options.get("link_offsets", "DEPTH"),
        "FORCE_MAIN_EQUATION": options.get("force_main", "H-W"),
        "IGNORE_RAINFALL": options.get("ignore_rainfall", "NO"),
        "IGNORE_SNOWMELT": options.get("ignore_snowmelt", "YES"),
        "IGNORE_GROUNDWATER": options.get("ignore_groundwater", "YES"),
        "IGNORE_ROUTING": options.get("ignore_routing", "NO"),
        "ALLOW_PONDING": options.get("allow_ponding", "YES"),
        "SKIP_STEADY_STATE": options.get("skip_steady_state", "NO"),
        "START_DATE": options.get("start_date", options.get("start", "01/01/2000")),
        "START_TIME": options.get("start_time", "00:00:00"),
        "REPORT_START_DATE": options.get("report_start_date",
                                         options.get("start", "01/01/2000")),
        "REPORT_START_TIME": options.get("report_start_time", "00:00:00"),
        "END_DATE": options.get("end_date", options.get("end", "12/31/2000")),
        "END_TIME": options.get("end_time", "23:59:59"),
        "SWEEP_START": options.get("sweep_start", "01/01"),
        "SWEEP_END": options.get("sweep_end", "12/31"),
        "DRY_DAYS": options.get("dry_days", "0"),
        "REPORT_STEP": options.get("report_step", "00:05:00"),
        "WET_STEP": options.get("wet_step", "00:05:00"),
        "DRY_STEP": options.get("dry_step", "01:00:00"),
        "ROUTING_STEP": options.get("routing_step", "10"),
        "VARIABLE_STEP": options.get("variable_step", "0.75"),
        "LENGTHENING_STEP": options.get("lengthening_step", "0"),
        "MIN_SURFAREA": options.get("min_surfarea", "12.557"),
        "NORMAL_FLOW_LIMITED": options.get("normal_flow", "BOTH"),
        "INERTIAL_DAMPING": options.get("inertial_damping", "PARTIAL"),
        "MIN_SLOPE": options.get("min_slope", "0"),
    }

    # Write .inp file
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        # TITLE
        f.write("[TITLE]\n")
        f.write(f";;{args.title}\n")
        f.write(f";;Generated by HydroCraft SWMM assembler\n")
        f.write(f";;Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

        # OPTIONS
        f.write("\n[OPTIONS]\n")
        for key, value in opts.items():
            f.write(f"{key:<24}{value}\n")

        # RAINGAGES
        f.write("\n[RAINGAGES]\n")
        f.write(";;Name           Format    Interval  SCF       Source\n")
        if raingages:
            gages = raingages.get("raingages", [raingages]) if isinstance(raingages, dict) else raingages
            for g in (gages if isinstance(gages, list) else [gages]):
                name = g.get("name", "RG1")
                fmt_type = g.get("format", "INTENSITY")
                interval = g.get("interval", "0:05")
                scf = g.get("scf", "1.0")
                source = g.get("source", f"TIMESERIES {g.get('timeseries', 'TS1')}")
                f.write(f"{name:<17}{fmt_type:<10}{interval:<10}{scf:<10}{source}\n")
        else:
            f.write("RG1              INTENSITY 0:05      1.0       TIMESERIES TS1\n")

        # SUBCATCHMENTS
        f.write("\n[SUBCATCHMENTS]\n")
        f.write(";;Name           Rain Gage        Outlet           Area     %Imperv  Width    %Slope   CurbLen  SnowPack\n")
        for sc in subcatchments:
            sid = sc.get("id", "S1")
            rg = sc.get("rain_gage", "RG1")
            outlet = sc.get("outlet", "")
            area = sc.get("area_ha", "1.0")
            imperv = sc.get("imperv_pct", "25")
            width = sc.get("width_m", sc.get("width", "500"))
            slope = sc.get("slope_pct", sc.get("slope", "0.5"))
            f.write(f"{sid:<17}{rg:<17}{outlet:<17}{area:<9}{imperv:<9}{width:<9}{slope:<9}0\n")

        # SUBAREAS
        f.write("\n[SUBAREAS]\n")
        f.write(";;Subcatchment   N-Imperv   N-Perv     S-Imperv   S-Perv     PctZero    RouteTo    PctRouted\n")
        if subareas:
            for sa in subareas:
                sid = sa.get("id", "")
                f.write(f"{sid:<17}{sa.get('n_imperv', '0.015'):<11}"
                        f"{sa.get('n_perv', '0.20'):<11}"
                        f"{sa.get('ds_imperv', sa.get('ds_imperv_mm', '2.0')):<11}"
                        f"{sa.get('ds_perv', sa.get('ds_perv_mm', '5.0')):<11}"
                        f"{sa.get('pct_zero', '25'):<11}"
                        f"{sa.get('route_to', 'OUTLET'):<11}"
                        f"{sa.get('pct_routed', '100')}\n")
        else:
            for sc in subcatchments:
                sid = sc.get("id", "S1")
                f.write(f"{sid:<17}0.015      0.20       2.0        5.0        25         OUTLET     100\n")

        # INFILTRATION
        f.write("\n[INFILTRATION]\n")
        infil_method = opts.get("INFILTRATION", "GREEN_AMPT")
        if infil_method == "GREEN_AMPT":
            f.write(";;Subcatchment   Suction    Ksat       IMD\n")
            if infiltration:
                for inf in infiltration:
                    sid = inf.get("id", "")
                    f.write(f"{sid:<17}{inf.get('suction_mm', '88.9'):<11}"
                            f"{inf.get('ksat_mm_hr', '3.4'):<11}"
                            f"{inf.get('imd', '0.434')}\n")
            else:
                for sc in subcatchments:
                    sid = sc.get("id", "S1")
                    f.write(f"{sid:<17}88.9       3.4        0.434\n")
        elif infil_method == "HORTON":
            f.write(";;Subcatchment   MaxRate    MinRate    Decay      DryTime    MaxInfil\n")
            if infiltration:
                for inf in infiltration:
                    sid = inf.get("id", "")
                    f.write(f"{sid:<17}{inf.get('f0_mm_hr', '75'):<11}"
                            f"{inf.get('fmin_mm_hr', '3'):<11}"
                            f"{inf.get('decay_1_hr', '4'):<11}"
                            f"{inf.get('dry_time_hr', '7'):<11}0\n")
        elif infil_method == "CURVE_NUMBER":
            f.write(";;Subcatchment   CurveNum   Ksat       DryTime\n")
            if infiltration:
                for inf in infiltration:
                    sid = inf.get("id", "")
                    f.write(f"{sid:<17}{inf.get('curve_number', '75'):<11}"
                            f"{inf.get('ksat_mm_hr', '0.5'):<11}"
                            f"{inf.get('dry_time_hr', '7')}\n")

        # JUNCTIONS
        f.write("\n[JUNCTIONS]\n")
        f.write(";;Name           Elevation  MaxDepth   InitDepth  SurDepth   Aponded\n")
        for j in junctions:
            jid = j.get("id", "J1")
            f.write(f"{jid:<17}{j.get('invert_elev', '0'):<11}"
                    f"{j.get('max_depth', '2'):<11}"
                    f"{j.get('init_depth', '0'):<11}"
                    f"{j.get('surcharge_depth', '0'):<11}"
                    f"{j.get('ponded_area', '0')}\n")

        # OUTFALLS
        f.write("\n[OUTFALLS]\n")
        f.write(";;Name           Elevation  Type       Stage Data       Gated    Route To\n")
        for o in outfalls:
            oid = o.get("id", "OUT1")
            f.write(f"{oid:<17}{o.get('invert_elev', '0'):<11}"
                    f"{o.get('type', 'FREE'):<11}"
                    f"{o.get('stage_data', ''):<17}"
                    f"{o.get('gated', 'NO')}\n")

        # CONDUITS
        f.write("\n[CONDUITS]\n")
        f.write(";;Name           From Node        To Node          Length     Roughness  InOffset   OutOffset\n")
        for c in conduits:
            cid = c.get("id", "C1")
            f.write(f"{cid:<17}{c.get('from_node', ''):<17}"
                    f"{c.get('to_node', ''):<17}"
                    f"{c.get('length', '100'):<11}"
                    f"{c.get('roughness', '0.013'):<11}"
                    f"{c.get('in_offset', '0'):<11}"
                    f"{c.get('out_offset', '0')}\n")

        # XSECTIONS
        f.write("\n[XSECTIONS]\n")
        f.write(";;Link           Shape        Geom1      Geom2      Geom3      Geom4      Barrels\n")
        if xsections:
            for xs in xsections:
                xid = xs.get("conduit_id", xs.get("id", ""))
                f.write(f"{xid:<17}{xs.get('shape', 'CIRCULAR'):<13}"
                        f"{xs.get('geom1', '0.6'):<11}"
                        f"{xs.get('geom2', '0'):<11}"
                        f"{xs.get('geom3', '0'):<11}"
                        f"{xs.get('geom4', '0'):<11}"
                        f"{xs.get('barrels', '1')}\n")
        else:
            for c in conduits:
                cid = c.get("id", "C1")
                f.write(f"{cid:<17}{'CIRCULAR':<13}{'0.6':<11}{'0':<11}{'0':<11}{'0':<11}1\n")

        # TIMESERIES
        if args.timeseries and os.path.isfile(args.timeseries):
            f.write("\n[TIMESERIES]\n")
            f.write(";;Name           Date       Time       Value\n")
            with open(args.timeseries, "r") as ts:
                for line in ts:
                    if not line.startswith(";"):
                        f.write(line)

        # LID_CONTROLS
        if lid_controls:
            controls = lid_controls.get("lid_controls", [lid_controls]) \
                if isinstance(lid_controls, dict) else lid_controls
            if not isinstance(controls, list):
                controls = [controls]

            f.write("\n[LID_CONTROLS]\n")
            for ctrl in controls:
                if not isinstance(ctrl, dict) or "name" not in ctrl:
                    continue
                name = ctrl["name"]
                lid_type = ctrl.get("type", "BC")
                f.write(f"{name:<17}{lid_type}\n")
                layers = ctrl.get("layers", {})
                layer_order = ["surface", "pavement", "soil", "storage", "drain", "drainmat"]
                for layer in layer_order:
                    if layer not in layers:
                        continue
                    p = layers[layer]
                    layer_key = layer.upper()
                    if layer == "surface":
                        f.write(f"{name:<17}SURFACE    "
                                f"{p.get('berm_height', 0):<9}"
                                f"{p.get('vegetation_fraction', 0):<9}"
                                f"{p.get('roughness', 0.1):<9}"
                                f"{p.get('slope', 1):<9}5\n")
                    elif layer == "soil":
                        f.write(f"{name:<17}SOIL       "
                                f"{p.get('thickness', 600):<9}"
                                f"{p.get('porosity', 0.45):<9}"
                                f"{p.get('field_capacity', 0.2):<9}"
                                f"{p.get('wilting_point', 0.1):<9}"
                                f"{p.get('conductivity', 50):<9}"
                                f"{p.get('conductivity_slope', 10):<9}"
                                f"{p.get('suction_head', 100)}\n")
                    elif layer == "storage":
                        f.write(f"{name:<17}STORAGE    "
                                f"{p.get('thickness', 300):<9}"
                                f"{p.get('void_ratio', 0.75):<9}"
                                f"{p.get('conductivity', 100):<9}"
                                f"{p.get('clog_factor', 0)}\n")
                    elif layer == "drain":
                        f.write(f"{name:<17}DRAIN      "
                                f"{p.get('coefficient', 0):<9}"
                                f"{p.get('exponent', 0.5):<9}"
                                f"{p.get('offset', 0):<9}"
                                f"{p.get('delay', 6)}\n")
                    elif layer == "drainmat":
                        f.write(f"{name:<17}DRAINMAT   "
                                f"{p.get('thickness', 25):<9}"
                                f"{p.get('void_fraction', 0.5):<9}"
                                f"{p.get('roughness', 0.1)}\n")
                    elif layer == "pavement":
                        f.write(f"{name:<17}PAVEMENT   "
                                f"{p.get('thickness', 100):<9}"
                                f"{p.get('void_ratio', 0.15):<9}"
                                f"{p.get('impervious_fraction', 0):<9}"
                                f"{p.get('permeability', 100):<9}"
                                f"{p.get('clog_factor', 0)}\n")

        # LID_USAGE
        if lid_usage:
            usages = lid_usage.get("lid_usage", [])
            if usages:
                f.write("\n[LID_USAGE]\n")
                f.write(";;Subcatchment   LID Control      Number  Area       Width      InitSat    FromImp    ToPerv     RptFile\n")
                for u in usages:
                    f.write(f"{u.get('subcatchment', ''):<17}"
                            f"{u.get('lid_control', ''):<17}"
                            f"{u.get('number', 1):<8}"
                            f"{u.get('area_per_unit', 100):<11}"
                            f"{u.get('surface_width', 0):<11}"
                            f"{u.get('init_saturation', 0):<11}"
                            f"{u.get('from_impervious', 0):<11}"
                            f"{u.get('to_pervious', 0):<11}"
                            f"{u.get('report_file', '')}\n")

        # REPORT
        f.write("\n[REPORT]\n")
        f.write("SUBCATCHMENTS ALL\n")
        f.write("NODES ALL\n")
        f.write("LINKS ALL\n")

        # COORDINATES
        f.write("\n[COORDINATES]\n")
        f.write(";;Node           X-Coord            Y-Coord\n")
        for j in junctions:
            x = j.get("x", "0")
            y = j.get("y", "0")
            if x != "0" or y != "0":
                f.write(f"{j['id']:<17}{x:<19}{y}\n")
        for o in outfalls:
            x = o.get("x", "0")
            y = o.get("y", "0")
            if x != "0" or y != "0":
                f.write(f"{o['id']:<17}{x:<19}{y}\n")

        # MAP
        f.write("\n[MAP]\n")
        f.write("DIMENSIONS 0.0 0.0 10000.0 10000.0\n")
        f.write("Units None\n")

    # Summary
    print(f"SWMM .inp file assembled: {output_path}")
    print(f"  Subcatchments: {len(subcatchments)}")
    print(f"  Junctions: {len(junctions)}")
    print(f"  Conduits: {len(conduits)}")
    print(f"  Outfalls: {len(outfalls)}")
    if lid_controls:
        n_lids = len(lid_controls.get("lid_controls", [lid_controls]))
        print(f"  LID Controls: {n_lids}")


if __name__ == "__main__":
    main()
