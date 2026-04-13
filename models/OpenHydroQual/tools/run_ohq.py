#!/usr/bin/env python3
"""
run_ohq.py - Execution wrapper for OpenHydroQual model.

Performs pre-flight checks, runs the OHQLibTest binary, captures output,
and validates results.

CRITICAL: The binary resolves template paths relative to its own location
  at ../../../resources/. If templates are not found, it silently fails.
CRITICAL: The .ohq input file may contain hardcoded absolute paths from the
  developer's machine. These MUST be replaced before running.
CRITICAL: Working folder is derived from the input file's directory.
  All relative paths in the .ohq file resolve from there.

Usage:
  python run_ohq.py --binary ./build/OHQLibTest --input model.ohq

  python run_ohq.py --binary ./build/OHQLibTest --input model.ohq \\
    --resources /path/to/resources/ --timeout 3600

  python run_ohq.py --binary ./build/OHQLibTest --input model.ohq \\
    --fix-paths --resources /path/to/resources/
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time


def validate_inputs(args):
    """Pre-flight validation of binary, input file, and resources."""
    errors = []
    warnings = []

    # Check binary exists and is executable
    if not os.path.isfile(args.binary):
        errors.append(f"Binary not found: {args.binary}")
    elif not os.access(args.binary, os.X_OK):
        errors.append(f"Binary not executable: {args.binary}. Run: chmod +x {args.binary}")

    # Check input file
    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")
    else:
        # Scan for hardcoded paths
        with open(args.input, "r") as f:
            content = f.read()

        # Check for common hardcoded path patterns
        hardcoded = re.findall(r'/home/\w+/[^\s,;]+', content)
        if hardcoded:
            warnings.append(
                f"Input file contains {len(hardcoded)} hardcoded absolute paths. "
                f"Example: {hardcoded[0][:60]}... Use --fix-paths to auto-fix."
            )

        # Check for template references
        template_refs = re.findall(r'filename\s*=\s*([^\n;]+)', content)
        for ref in template_refs:
            ref = ref.strip()
            if ref and not os.path.isfile(ref):
                if not args.fix_paths:
                    warnings.append(f"Template file not found: {ref}")

    # Check resources directory
    if args.resources:
        if not os.path.isdir(args.resources):
            errors.append(f"Resources directory not found: {args.resources}")
        else:
            main_template = os.path.join(args.resources, "main_components.json")
            if not os.path.isfile(main_template):
                errors.append(
                    f"main_components.json not found in resources: {args.resources}"
                )
            settings = os.path.join(args.resources, "settings.json")
            if not os.path.isfile(settings):
                warnings.append(f"settings.json not found in resources: {args.resources}")

    # Check shared library dependencies
    binary_dir = os.path.dirname(os.path.abspath(args.binary))
    lib_check = shutil.which("ldd")
    if lib_check and os.path.isfile(args.binary):
        try:
            ldd_out = subprocess.run(
                ["ldd", args.binary], capture_output=True, text=True, timeout=10
            )
            missing = [
                line.strip() for line in ldd_out.stdout.splitlines()
                if "not found" in line
            ]
            if missing:
                errors.append(f"Missing shared libraries: {'; '.join(missing)}")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    if errors:
        print(json.dumps({"status": "error", "errors": errors, "warnings": warnings}))
        sys.exit(1)

    if warnings:
        for w in warnings:
            print(f"WARNING: {w}", file=sys.stderr)

    return True


def fix_template_paths(input_file, resources_dir):
    """Replace hardcoded template paths in .ohq file with local resources path.

    Returns path to the fixed file (written alongside original with _fixed suffix).
    """
    with open(input_file, "r") as f:
        content = f.read()

    # Replace loadtemplate and addtemplate filename paths
    def replace_path(match):
        keyword = match.group(1)
        old_path = match.group(2).strip()
        basename = os.path.basename(old_path)
        new_path = os.path.join(resources_dir, basename)
        return f"{keyword}; filename = {new_path}"

    content = re.sub(
        r'(loadtemplate|addtemplate)\s*;\s*filename\s*=\s*([^\n]+)',
        replace_path,
        content
    )

    # Write fixed file
    base, ext = os.path.splitext(input_file)
    fixed_file = f"{base}_fixed{ext}"
    with open(fixed_file, "w") as f:
        f.write(content)

    return fixed_file


def run_model(binary, input_file, timeout, env=None):
    """Execute the OHQ binary and capture output."""
    cmd = [os.path.abspath(binary), os.path.abspath(input_file)]

    start_time = time.time()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=os.path.dirname(os.path.abspath(input_file)),
            env=env,
        )
        elapsed = time.time() - start_time

        return {
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "elapsed_s": round(elapsed, 2),
            "command": " ".join(cmd),
        }

    except subprocess.TimeoutExpired:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"TIMEOUT after {timeout} seconds",
            "elapsed_s": timeout,
            "command": " ".join(cmd),
        }
    except FileNotFoundError as e:
        return {
            "returncode": -2,
            "stdout": "",
            "stderr": str(e),
            "elapsed_s": 0,
            "command": " ".join(cmd),
        }


def check_output_files(input_file):
    """Check if model produced expected output files."""
    work_dir = os.path.dirname(os.path.abspath(input_file))
    outputs = {}

    for name in ["output.txt", "observedoutput.txt", "GA_output.txt", "mcmc.txt"]:
        fpath = os.path.join(work_dir, name)
        if os.path.isfile(fpath):
            size = os.path.getsize(fpath)
            outputs[name] = {"exists": True, "size_bytes": size}
        else:
            outputs[name] = {"exists": False}

    return outputs


def process(args):
    """Run the model with all checks."""
    result = {"status": "success", "warnings": []}

    input_file = args.input

    # Fix paths if requested
    if args.fix_paths and args.resources:
        input_file = fix_template_paths(args.input, args.resources)
        result["fixed_input"] = input_file
        result["warnings"].append(f"Template paths fixed. Using: {input_file}")

    # Set up environment
    env = os.environ.copy()
    if args.resources:
        env["OHQ_RESOURCES"] = os.path.abspath(args.resources)

    # Run the model
    run_result = run_model(args.binary, input_file, args.timeout, env)
    result["run"] = run_result

    if run_result["returncode"] != 0:
        result["status"] = "error"
        result["errors"] = [
            f"Model exited with code {run_result['returncode']}",
            run_result["stderr"][:500] if run_result["stderr"] else "No stderr",
        ]
    else:
        # Check output files
        result["outputs"] = check_output_files(input_file)
        has_output = any(v["exists"] for v in result["outputs"].values())
        if not has_output:
            result["warnings"].append("No output files found after model run")

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Run OpenHydroQual model with pre-flight checks"
    )
    parser.add_argument("--binary", required=True,
                        help="Path to OHQLibTest binary")
    parser.add_argument("--input", required=True,
                        help="Path to .ohq input file")
    parser.add_argument("--resources", default=None,
                        help="Path to resources/ directory with JSON templates")
    parser.add_argument("--timeout", type=int, default=3600,
                        help="Maximum runtime in seconds (default: 3600)")
    parser.add_argument("--fix-paths", action="store_true",
                        help="Auto-fix hardcoded template paths in .ohq file")

    args = parser.parse_args()
    validate_inputs(args)
    result = process(args)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
