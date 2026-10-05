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
# Engine python: pyBadlands lives in its own venv (numpy<2, badlands from source), not in the HydroCraft python_env that
# SKILL.md uses to start the KI tools. Lookup (same as preflight_check.py): --pybadlands-python ->
# $PYBADLANDS_PYTHON -> server default -> this python (only if it imports badlands). An explicit value is
# used as given (no fallback). If the chosen python is not the one running this tool, the tool
# re-launches itself with it (os.execv, same arguments).
# ---------------------------------------------------------------------------
ENGINE_PYTHON_ENV = "PYBADLANDS_PYTHON"
ENGINE_PYTHON_DEFAULT = "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/pyBadlands/venv/bin/python"
_REEXEC_GUARD = "KI_PYBADLANDS_REEXEC"


def resolve_engine_python(cli_value=None):
    """Return (python, source) for the pyBadlands interpreter, or (None, reason)."""
    if cli_value is not None:
        return cli_value, "--pybadlands-python"
    env_value = os.environ.get(ENGINE_PYTHON_ENV)
    if env_value is not None:
        return env_value, "$" + ENGINE_PYTHON_ENV
    if os.path.isfile(ENGINE_PYTHON_DEFAULT):
        return ENGINE_PYTHON_DEFAULT, "server default"
    try:
        from badlands.model import Model  # noqa: F401
        return sys.executable, "running python (imports badlands)"
    except ImportError:
        return None, (f"no python with badlands: --pybadlands-python and ${ENGINE_PYTHON_ENV} not set, "
                      f"server default {ENGINE_PYTHON_DEFAULT} not found, and {sys.executable} "
                      "cannot import badlands")


def ensure_engine_python(cli_value=None):
    """Re-launch this tool with the pyBadlands python when another python is running it."""
    python, source = resolve_engine_python(cli_value)
    if python is None:
        print(json.dumps({"status": "error", "errors": [source]}), file=sys.stderr)
        sys.exit(1)
    if os.path.abspath(python) == os.path.abspath(sys.executable):
        return
    if os.environ.get(_REEXEC_GUARD):
        print(json.dumps({"status": "error", "errors": [
            f"re-launch loop: running {sys.executable}, expected {python} ({source})"]}),
            file=sys.stderr)
        sys.exit(1)
    if not (os.path.isfile(python) and os.access(python, os.X_OK)):
        print(json.dumps({"status": "error", "errors": [
            f"pyBadlands python not found or not executable: {python!r} ({source})"]}),
            file=sys.stderr)
        sys.exit(1)
    python = os.path.abspath(python)  # not realpath: a venv python must keep its own path
    print(f"[{os.path.basename(__file__)}] re-launching with {python} ({source})",
          file=sys.stderr, flush=True)
    env = dict(os.environ, **{_REEXEC_GUARD: "1"})
    try:
        os.execve(python, [python, os.path.abspath(__file__)] + sys.argv[1:], env)
    except OSError as e:
        print(json.dumps({"status": "error", "errors": [
            f"could not start pyBadlands python {python!r} ({source}): {e}"]}), file=sys.stderr)
        sys.exit(1)


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
        # Badlands opens the files named in the XML relative to the CURRENT folder
        # (forcing/xmlParser.py), not the XML's folder; check them the same way.
        dem_elem = root.find(".//demfile")
        if dem_elem is not None and dem_elem.text:
            dem_path = os.path.abspath(dem_elem.text.strip())
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
                map_path = os.path.abspath(rain_map.text.strip())
                if not os.path.isfile(map_path):
                    warnings.append(f"Rainfall map not found: {map_path}")

        # Check displacement files (<dfile>: vertical, <ufile>: 3D)
        for ufile in root.findall(".//disp/dfile") + root.findall(".//disp/ufile"):
            if ufile.text:
                u_path = os.path.abspath(ufile.text.strip())
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
        # Badlands picks its own output folder (relative to the current folder, with
        # "_N" added when the folder already exists); report the folder it really uses.
        result["output_dir"] = os.path.abspath(model.input.outDir)
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
    parser.add_argument("--pybadlands-python", dest="pybadlands_python", default=None,
                        help="Python of the pyBadlands venv (default: $PYBADLANDS_PYTHON, "
                             "else the server venv, else this python if it imports badlands). "
                             "The tool re-launches itself with it.")

    args = parser.parse_args()
    ensure_engine_python(args.pybadlands_python)
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
