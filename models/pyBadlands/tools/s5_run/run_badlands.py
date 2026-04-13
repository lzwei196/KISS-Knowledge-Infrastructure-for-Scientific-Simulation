#!/usr/bin/env python3
"""
run_badlands.py — Execute pyBadlands model with XML configuration.

Wraps the badlands.model.Model class to provide:
- Pre-flight validation of XML config and required files
- Output directory creation
- Progress monitoring and timing
- Structured JSON status output

Usage:
    python run_badlands.py --xml input.xml --end 1000000
    python run_badlands.py --xml input.xml --end 1000000 --verbose
    python run_badlands.py --xml input.xml --end 1000000 --restart output --rstep 5

CRITICAL:
    - Ensure output folder exists before running (dt_009)
    - Check DEM file path is accessible from XML location
    - numpy < 2 required (dt_018)
"""

import argparse
import json
import os
import sys
import time
import xml.etree.ElementTree as ET


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inputs(args):
    """Pre-flight validation of XML config and dependencies."""
    errors = []
    warnings = []

    # Check XML exists
    if not os.path.isfile(args.xml):
        errors.append(f"XML config not found: {args.xml}")
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)

    # Parse XML to validate referenced files
    try:
        tree = ET.parse(args.xml)
        root = tree.getroot()
        xml_dir = os.path.dirname(os.path.abspath(args.xml))

        # Check DEM file
        dem_elem = root.find(".//demfile")
        if dem_elem is not None and dem_elem.text:
            dem_path = os.path.join(xml_dir, dem_elem.text.strip())
            if not os.path.isfile(dem_path):
                errors.append(f"DEM file not found: {dem_path}")

        # Check output folder
        out_elem = root.find(".//outfolder")
        if out_elem is not None and out_elem.text:
            out_path = os.path.join(xml_dir, out_elem.text.strip())
        else:
            out_path = os.path.join(xml_dir, "out")

        # Check rainfall maps
        for rain_map in root.findall(".//rain/map"):
            if rain_map.text:
                map_path = os.path.join(xml_dir, rain_map.text.strip())
                if not os.path.isfile(map_path):
                    warnings.append(f"Rainfall map not found: {map_path}")

        # Check displacement files
        for ufile in root.findall(".//disp/ufile"):
            if ufile.text:
                u_path = os.path.join(xml_dir, ufile.text.strip())
                if not os.path.isfile(u_path):
                    warnings.append(f"Displacement file not found: {u_path}")

        # Check time parameters
        start_elem = root.find(".//time/start")
        end_elem = root.find(".//time/end")
        if start_elem is not None and end_elem is not None:
            t_start = float(start_elem.text)
            t_end = float(end_elem.text)
            if t_end <= t_start:
                errors.append(f"End time ({t_end}) must be > start time ({t_start})")

        # Validate rainfall units (heuristic check)
        for rval_elem in root.findall(".//rain/rval"):
            if rval_elem.text:
                rval = float(rval_elem.text)
                if rval > 50:
                    warnings.append(
                        f"Rainfall rval={rval} m/year seems very high. "
                        "Verify units are m/year, NOT mm/year (dt_001)."
                    )

    except ET.ParseError as e:
        errors.append(f"XML parse error: {e}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors, "warnings": warnings}))
        sys.exit(1)

    if warnings:
        for w in warnings:
            print(f"WARNING: {w}", file=sys.stderr)

    return out_path, warnings


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def run_model(args, out_path):
    """Execute pyBadlands model."""
    result = {
        "xml": os.path.abspath(args.xml),
        "output_dir": out_path,
        "verbose": args.verbose,
    }

    # Create output directory
    os.makedirs(out_path, exist_ok=True)

    try:
        from badlands.model import Model
    except ImportError as e:
        result["status"] = "error"
        result["message"] = (
            f"Failed to import badlands: {e}. "
            "Ensure badlands is installed: pip install -e . (dt_018)"
        )
        return result

    # Initialize model
    t0 = time.time()

    try:
        model = Model()
        model.load_xml(args.xml, verbose=args.verbose)
        result["load_time_s"] = round(time.time() - t0, 2)
        result["start_time"] = model.tNow
    except Exception as e:
        result["status"] = "error"
        result["message"] = f"Failed to load XML: {e}"
        return result

    # Determine end time
    if args.end is not None:
        t_end = args.end
    else:
        t_end = model.input.tEnd

    result["target_end_time"] = t_end

    # Run simulation
    t_run_start = time.time()

    try:
        model.run_to_time(t_end, verbose=args.verbose)
        run_time = time.time() - t_run_start
        total_time = time.time() - t0

        result["status"] = "completed"
        result["run_time_s"] = round(run_time, 2)
        result["total_time_s"] = round(total_time, 2)
        result["final_time"] = float(model.tNow)
        result["output_steps"] = model.outputStep

    except Exception as e:
        run_time = time.time() - t_run_start
        result["status"] = "failed"
        result["message"] = str(e)
        result["run_time_before_failure_s"] = round(run_time, 2)
        result["final_time"] = float(model.tNow) if hasattr(model, "tNow") else None

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--xml", required=True,
                        help="Path to pyBadlands XML configuration file")
    parser.add_argument("--end", type=float, default=None,
                        help="Override end time (years). Default: from XML.")
    parser.add_argument("--verbose", action="store_true",
                        help="Enable verbose output during simulation")
    parser.add_argument("--output-json", dest="output_json", default=None,
                        help="Write result to JSON file")

    args = parser.parse_args()
    out_path, warnings = validate_inputs(args)

    result = run_model(args, out_path)
    result["warnings"] = warnings

    output_str = json.dumps(result, indent=2)

    if args.output_json:
        with open(args.output_json, "w") as f:
            f.write(output_str)

    print(output_str)

    if result.get("status") == "completed":
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
