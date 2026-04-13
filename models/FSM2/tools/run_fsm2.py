#!/usr/bin/env python3
"""
FSM2 execution wrapper: compile (if needed) and run the model.

Steps:
  1. Validate that source directory and namelist exist
  2. Optionally compile FSM2 with specified physics options
  3. Run FSM2 with the namelist piped to stdin
  4. Validate that output files were created
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Default compile-time options
# ---------------------------------------------------------------------------

DEFAULT_OPTIONS = {
    "ALBEDO": 2,
    "CANINT": 1,
    "CANMOD": 1,
    "CANRAD": 1,
    "CANUNL": 1,
    "CONDCT": 1,
    "DENSTY": 1,
    "EXCHNG": 1,
    "HYDROL": 1,
    "SGRAIN": 1,
    "SNFRAC": 1,
    "DRIV1D": 1,
    "SWPART": 0,
    "ZOFFST": 0,
    "PROFNC": 0,
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_prerequisites(source_dir: str, namelist_file: str) -> list[str]:
    """Check that source directory and namelist exist."""
    issues = []
    src = Path(source_dir) / "src"
    if not src.is_dir():
        issues.append(f"Source directory not found: {src}")
    if not Path(namelist_file).is_file():
        issues.append(f"Namelist file not found: {namelist_file}")
    # Check for gfortran
    if shutil.which("gfortran") is None:
        issues.append("gfortran compiler not found in PATH")
    return issues


def validate_output_files(run_dir: str, runid: str) -> list[str]:
    """Check that expected output files were created."""
    issues = []
    expected = [f"{runid}flux.txt", f"{runid}stat.txt", f"{runid}subc.txt"]
    for fname in expected:
        fpath = Path(run_dir) / fname
        if not fpath.is_file():
            issues.append(f"Expected output file not found: {fpath}")
        elif fpath.stat().st_size == 0:
            issues.append(f"Output file is empty: {fpath}")
    return issues


# ---------------------------------------------------------------------------
# Compile
# ---------------------------------------------------------------------------

def generate_opts_h(options: dict) -> str:
    """Generate the OPTS.h preprocessor file content."""
    lines = []
    for key, val in options.items():
        lines.append(f"#define {key} {val}")
    return "\n".join(lines) + "\n"


def compile_fsm2(
    source_dir: str,
    options: dict | None = None,
    compiler: str = "gfortran",
    output_binary: str | None = None,
) -> str:
    """
    Compile FSM2 from source.

    Parameters
    ----------
    source_dir : str
        Path to FSM2 repository root (contains src/).
    options : dict, optional
        Physics options. Defaults to DEFAULT_OPTIONS.
    compiler : str
        Fortran compiler command.
    output_binary : str, optional
        Where to place the binary. Default: source_dir/FSM2.

    Returns
    -------
    str : path to compiled binary
    """
    if options is None:
        options = DEFAULT_OPTIONS.copy()

    src_dir = Path(source_dir) / "src"
    opts_file = src_dir / "OPTS.h"

    # Write OPTS.h
    opts_content = generate_opts_h(options)
    opts_file.write_text(opts_content)
    print(f"Wrote OPTS.h with options: {options}")

    # Source files in compilation order
    sources = [
        "FSM2_MODULES.F90", "FSM2_PARAMS.F90", "FSM2.F90",
        "FSM2_DRIVE.F90", "FSM2_OUTPUT.F90", "FSM2_VEG.F90",
        "FSM2_TIMESTEP.F90", "CANOPY.F90", "INTERCEPT.F90",
        "LUDCMP.F90", "PSIMH.F90", "QSAT.F90", "SNOW.F90",
        "SOIL.F90", "SOLARPOS.F90", "SRFEBAL.F90", "SWRAD.F90",
        "THERMAL.F90", "TRIDIAG.F90", "TWOSTREAM.F90",
    ]

    # Add NetCDF sources if needed
    if options.get("PROFNC", 0) == 1:
        sources.insert(4, "FSM2_PREPNC.F90")
        sources.insert(6, "FSM2_WRITENC.F90")

    binary_name = "FSM2"
    if output_binary is None:
        output_binary = str(Path(source_dir) / binary_name)

    # Build compile command
    cmd = [compiler, "-cpp", "-O3", "-o", binary_name]

    if options.get("PROFNC", 0) == 1:
        cmd.extend(["-I/usr/include/", "-lnetcdff", "-lnetcdf"])

    cmd.extend(sources)

    print(f"Compiling FSM2: {' '.join(cmd[:5])} ...")
    result = subprocess.run(
        cmd,
        cwd=str(src_dir),
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        print(f"Compilation FAILED:\n{result.stderr}")
        raise RuntimeError(f"FSM2 compilation failed: {result.stderr}")

    # Move binary to target location
    built = src_dir / binary_name
    if built.exists():
        shutil.move(str(built), output_binary)
        # Clean up .mod files
        for mod in src_dir.glob("*.mod"):
            mod.unlink()
        print(f"Binary compiled: {output_binary}")
    else:
        raise RuntimeError("Binary not found after compilation")

    return output_binary


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def run_fsm2(
    binary: str,
    namelist_file: str,
    run_dir: str | None = None,
    timeout: int = 600,
) -> dict:
    """
    Execute FSM2 with given namelist.

    Parameters
    ----------
    binary : str
        Path to FSM2 executable.
    namelist_file : str
        Path to namelist file (piped to stdin).
    run_dir : str, optional
        Working directory for execution. Default: directory of namelist.
    timeout : int
        Maximum runtime in seconds.

    Returns
    -------
    dict with status, output, errors
    """
    if run_dir is None:
        run_dir = str(Path(namelist_file).parent)

    binary = str(Path(binary).resolve())
    namelist_file = str(Path(namelist_file).resolve())

    if not os.access(binary, os.X_OK):
        os.chmod(binary, 0o755)

    # Read namelist content
    namelist_content = Path(namelist_file).read_text()

    print(f"Running: {binary} < {namelist_file}")
    print(f"Working directory: {run_dir}")

    result = subprocess.run(
        [binary],
        input=namelist_content,
        capture_output=True,
        text=True,
        cwd=run_dir,
        timeout=timeout,
    )

    status = "success" if result.returncode == 0 else "failed"
    output = result.stdout[:2000] if result.stdout else ""
    errors = result.stderr[:2000] if result.stderr else ""

    if result.returncode != 0:
        print(f"FSM2 run FAILED (return code {result.returncode}):")
        print(f"  stderr: {errors}")
    else:
        print(f"FSM2 run completed successfully")

    return {
        "status": status,
        "return_code": result.returncode,
        "stdout": output,
        "stderr": errors,
        "binary": binary,
        "namelist": namelist_file,
        "run_dir": run_dir,
    }


# ---------------------------------------------------------------------------
# Combined compile + run
# ---------------------------------------------------------------------------

def compile_and_run(
    source_dir: str,
    namelist_file: str,
    options: dict | None = None,
    run_dir: str | None = None,
) -> dict:
    """Compile FSM2 and run it in one step."""
    # Validate
    issues = validate_prerequisites(source_dir, namelist_file)
    if issues:
        for iss in issues:
            print(f"ERROR: {iss}")
        return {"status": "failed", "issues": issues}

    # Compile
    binary = compile_fsm2(source_dir, options)

    # Run
    result = run_fsm2(binary, namelist_file, run_dir)

    # Parse runid from namelist for output validation
    runid = ""
    nml = Path(namelist_file).read_text()
    for line in nml.split("\n"):
        if "runid" in line and "=" in line:
            runid = line.split("=")[1].strip().strip("'\"")
            break

    if result["status"] == "success":
        rdir = run_dir or str(Path(namelist_file).parent)
        out_issues = validate_output_files(rdir, runid)
        result["output_issues"] = out_issues
        if out_issues:
            print("Output validation issues:")
            for iss in out_issues:
                print(f"  - {iss}")

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Compile and run FSM2")
    parser.add_argument("source_dir", help="FSM2 source repository directory")
    parser.add_argument("namelist", help="Namelist file path")
    parser.add_argument("--run-dir", help="Working directory for execution")
    parser.add_argument("--compile-only", action="store_true", help="Only compile, don't run")
    parser.add_argument("--run-only", action="store_true", help="Only run (binary must exist)")
    parser.add_argument("--binary", help="Path to existing binary (for --run-only)")
    args = parser.parse_args()

    if args.compile_only:
        compile_fsm2(args.source_dir)
    elif args.run_only:
        binary = args.binary or str(Path(args.source_dir) / "FSM2")
        run_fsm2(binary, args.namelist, args.run_dir)
    else:
        compile_and_run(args.source_dir, args.namelist, run_dir=args.run_dir)


if __name__ == "__main__":
    main()
