#!/usr/bin/env python3
"""
run_dualsphysics.py — Execute DualSPHysics with preflight checks and output validation.

Runs the complete DualSPHysics pipeline: GenCase -> DualSPHysics -> basic validation.
Captures stdout/stderr, checks for common failure modes, validates outputs.

Typical runtimes:
  - Small case (100k particles, 1s): 1-5 minutes (CPU)
  - Medium case (1M particles, 2s): 10-60 minutes (CPU), 1-5 minutes (GPU)
  - Large case (10M particles, 5s): hours (CPU), 30-60 minutes (GPU)

Usage:
    python run_dualsphysics.py --case_def CaseDef.xml --dirout output/ --cpu
    python run_dualsphysics.py --case_name CaseName --dirout output/ --gpu 0 --tmax 5.0
    python run_dualsphysics.py --run_dir /path/to/case --skip_gencase --cpu
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time


# Default binary paths
DEFAULT_BIN_DIR = None  # Auto-detect from repo structure
GENCASE_NAME = "GenCase_linux64"
DSPH_CPU_NAME = "DualSPHysics5.4CPU_linux64"
DSPH_GPU_NAME = "DualSPHysics5.4_linux64"


def find_bin_dir(start_path=None):
    """Auto-detect bin/linux directory from repo structure."""
    if start_path is None:
        start_path = os.path.dirname(os.path.abspath(__file__))

    # Walk up to find bin/linux
    path = start_path
    for _ in range(6):
        candidate = os.path.join(path, "bin", "linux")
        if os.path.isdir(candidate):
            return candidate
        path = os.path.dirname(path)

    return None


def validate_inputs(args):
    """Preflight checks before running DualSPHysics."""
    errors = []
    warnings = []

    # Find binary directory
    bin_dir = args.bin_dir or find_bin_dir(args.run_dir)
    if bin_dir is None:
        errors.append("Cannot find bin/linux directory. "
                      "Use --bin_dir to specify.")
    else:
        # Check GenCase exists
        gencase = os.path.join(bin_dir, GENCASE_NAME)
        if not args.skip_gencase and not os.path.exists(gencase):
            errors.append(f"GenCase not found: {gencase}")
        elif not args.skip_gencase and not os.access(gencase, os.X_OK):
            errors.append(f"GenCase not executable: {gencase}")

        # Check DualSPHysics binary
        if args.gpu is not None:
            dsph = os.path.join(bin_dir, DSPH_GPU_NAME)
            if not os.path.exists(dsph):
                warnings.append(f"GPU binary not found: {dsph}. "
                                "Falling back to CPU.")
                dsph = os.path.join(bin_dir, DSPH_CPU_NAME)
        else:
            dsph = os.path.join(bin_dir, DSPH_CPU_NAME)

        if not os.path.exists(dsph):
            errors.append(f"DualSPHysics binary not found: {dsph}")
        elif not os.access(dsph, os.X_OK):
            errors.append(f"DualSPHysics binary not executable: {dsph}")

    # Check case definition XML (if not skipping GenCase)
    if not args.skip_gencase:
        if args.case_def:
            case_xml = os.path.join(args.run_dir or ".", args.case_def)
            if not os.path.exists(case_xml):
                errors.append(f"Case definition XML not found: {case_xml}")
        elif args.case_name:
            case_xml = os.path.join(args.run_dir or ".",
                                    f"{args.case_name}_Def.xml")
            if not os.path.exists(case_xml):
                errors.append(f"Case XML not found: {case_xml}")

    # Check dirout
    if args.dirout:
        os.makedirs(args.dirout, exist_ok=True)

    # Check for existing output that would be overwritten
    if args.dirout and os.path.exists(args.dirout):
        existing_bi4 = glob.glob(os.path.join(args.dirout, "data",
                                               "Part_*.bi4"))
        if existing_bi4 and not args.overwrite:
            warnings.append(f"Output directory contains {len(existing_bi4)} "
                            "existing bi4 files. Use --overwrite to replace.")

    result = {"status": "error" if errors else "ok", "errors": errors,
              "warnings": warnings}
    if errors:
        print(json.dumps(result, indent=2), file=sys.stderr)
    return result


def run_gencase(args, bin_dir):
    """Run GenCase to generate initial particle distribution."""
    gencase = os.path.join(bin_dir, GENCASE_NAME)
    case_name = args.case_name or os.path.splitext(
        os.path.basename(args.case_def))[0].replace("_Def", "")

    case_def = args.case_def or f"{case_name}_Def"
    if case_def.endswith(".xml"):
        case_def = case_def[:-4]

    dirout = args.dirout or f"{case_name}_out"
    output_prefix = os.path.join(dirout, case_name)

    cmd = [gencase, case_def, output_prefix, "-save:all"]

    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = env.get("LD_LIBRARY_PATH", "") + ":" + bin_dir

    print(f"Running GenCase: {' '.join(cmd)}")
    t0 = time.time()

    proc = subprocess.run(cmd, capture_output=True, text=True,
                          cwd=args.run_dir or ".", env=env,
                          timeout=args.timeout)

    elapsed = time.time() - t0
    print(f"GenCase completed in {elapsed:.1f}s (returncode={proc.returncode})")

    if proc.returncode != 0:
        return {
            "status": "error",
            "stage": "gencase",
            "returncode": proc.returncode,
            "stdout": proc.stdout[:2000],
            "stderr": proc.stderr[:2000],
            "elapsed_s": elapsed,
        }

    # Extract particle counts from stdout
    np_match = re.search(r"Total particles:\s*(\d+)", proc.stdout)
    nb_match = re.search(r"Boundary particles:\s*(\d+)", proc.stdout)
    nf_match = re.search(r"Fluid particles:\s*(\d+)", proc.stdout)

    return {
        "status": "ok",
        "stage": "gencase",
        "case_name": case_name,
        "output_prefix": output_prefix,
        "total_particles": int(np_match.group(1)) if np_match else None,
        "boundary_particles": int(nb_match.group(1)) if nb_match else None,
        "fluid_particles": int(nf_match.group(1)) if nf_match else None,
        "elapsed_s": elapsed,
        "stdout": proc.stdout[:2000],
    }


def run_solver(args, bin_dir, case_prefix):
    """Run DualSPHysics solver."""
    if args.gpu is not None:
        dsph_binary = os.path.join(bin_dir, DSPH_GPU_NAME)
        if not os.path.exists(dsph_binary):
            dsph_binary = os.path.join(bin_dir, DSPH_CPU_NAME)
    else:
        dsph_binary = os.path.join(bin_dir, DSPH_CPU_NAME)

    dirout = args.dirout or os.path.dirname(case_prefix)
    cmd = [dsph_binary, case_prefix, dirout]

    # Add options
    if args.gpu is not None:
        cmd.append(f"-gpu:{args.gpu}" if args.gpu > 0 else "-gpu")
    else:
        cmd.append("-cpu")

    if args.ompthreads:
        cmd.append(f"-ompthreads:{args.ompthreads}")
    if args.tmax:
        cmd.append(f"-tmax:{args.tmax}")
    if args.tout:
        cmd.append(f"-tout:{args.tout}")
    if args.nsteps:
        cmd.append(f"-nsteps:{args.nsteps}")
    if args.stable:
        cmd.append("-stable")

    # Extra options
    if args.extra_opts:
        cmd.extend(args.extra_opts.split())

    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = env.get("LD_LIBRARY_PATH", "") + ":" + bin_dir

    print(f"Running DualSPHysics: {' '.join(cmd)}")
    t0 = time.time()

    proc = subprocess.run(cmd, capture_output=True, text=True,
                          cwd=args.run_dir or ".", env=env,
                          timeout=args.solver_timeout or 3600)

    elapsed = time.time() - t0
    print(f"DualSPHysics completed in {elapsed:.1f}s "
          f"(returncode={proc.returncode})")

    if proc.returncode != 0:
        # Try to identify the failure reason
        stderr = proc.stderr
        stdout = proc.stdout
        diagnosis = diagnose_failure(stdout + stderr)

        return {
            "status": "error",
            "stage": "solver",
            "returncode": proc.returncode,
            "stdout": stdout[:3000],
            "stderr": stderr[:3000],
            "elapsed_s": elapsed,
            "diagnosis": diagnosis,
        }

    # Parse output summary
    nparts = len(glob.glob(
        os.path.join(args.run_dir or ".", dirout, "data", "Part_*.bi4")))

    return {
        "status": "ok",
        "stage": "solver",
        "binary": dsph_binary,
        "output_parts": nparts,
        "elapsed_s": elapsed,
        "stdout_tail": proc.stdout[-2000:],
    }


def diagnose_failure(output):
    """Diagnose common DualSPHysics failure modes from output text."""
    patterns = [
        (r"CUDA error", "GPU/CUDA error. Try -cpu mode or check CUDA installation."),
        (r"out of memory", "Insufficient memory. Reduce particle count (increase dp)."),
        (r"(?i)exception.*particles", "Too many particles excluded. "
         "Check RhopOutMin/Max or reduce dp."),
        (r"Finished.*code=[1-9]", "Simulation failed. Check parameters."),
        (r"NaN|nan|inf", "Numerical instability. Reduce CFL, increase coefsound, "
         "or enable DDT."),
        (r"file.*not found", "Input file missing. Check case generation."),
        (r"No.+particles", "No particles found. GenCase may have failed."),
    ]

    for pattern, diagnosis in patterns:
        if re.search(pattern, output):
            return diagnosis

    return "Unknown failure. Check stdout/stderr for details."


def validate_outputs(args, dirout):
    """Validate simulation outputs."""
    warnings = []

    data_dir = os.path.join(args.run_dir or ".", dirout, "data")
    if not os.path.isdir(data_dir):
        return {"status": "error",
                "errors": [f"Data directory not found: {data_dir}"]}

    # Check bi4 files
    bi4_files = sorted(glob.glob(os.path.join(data_dir, "Part_*.bi4")))
    if not bi4_files:
        return {"status": "error",
                "errors": ["No Part_*.bi4 output files found"]}

    # Check for excluded particles
    out_files = glob.glob(os.path.join(data_dir, "PartOut_*.bi4"))

    # Check RUN.out
    run_out = os.path.join(args.run_dir or ".", dirout, "RUN.out")
    run_info = {}
    if os.path.exists(run_out):
        with open(run_out) as f:
            content = f.read()
        # Extract key info
        time_match = re.search(r"Time:\s+([\d.]+)", content)
        if time_match:
            run_info["final_time"] = float(time_match.group(1))
    else:
        warnings.append("RUN.out not found")

    return {
        "status": "ok",
        "n_output_files": len(bi4_files),
        "n_excluded_files": len(out_files),
        "last_output": os.path.basename(bi4_files[-1]) if bi4_files else None,
        "run_info": run_info,
        "warnings": warnings,
    }


def process(args):
    """Main execution pipeline: validate -> gencase -> solve -> validate."""
    # 1. Validate inputs
    result = validate_inputs(args)
    if result["status"] == "error":
        return result

    bin_dir = args.bin_dir or find_bin_dir(args.run_dir)
    dirout = args.dirout or "output"

    # 2. Run GenCase
    if not args.skip_gencase:
        gc_result = run_gencase(args, bin_dir)
        if gc_result["status"] == "error":
            return gc_result
        case_prefix = gc_result["output_prefix"]
    else:
        case_name = args.case_name
        case_prefix = os.path.join(dirout, case_name)

    # 3. Run solver
    solver_result = run_solver(args, bin_dir, case_prefix)
    if solver_result["status"] == "error":
        return solver_result

    # 4. Validate outputs
    val_result = validate_outputs(args, dirout)

    return {
        "status": "ok",
        "gencase": gc_result if not args.skip_gencase else "skipped",
        "solver": solver_result,
        "validation": val_result,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Run DualSPHysics with preflight checks")
    parser.add_argument("--case_def", help="Case definition XML file")
    parser.add_argument("--case_name", help="Case name (without _Def.xml)")
    parser.add_argument("--dirout", help="Output directory")
    parser.add_argument("--run_dir", help="Working directory for execution")
    parser.add_argument("--bin_dir", help="Binary directory path")
    parser.add_argument("--cpu", action="store_true", help="Use CPU")
    parser.add_argument("--gpu", type=int, nargs="?", const=0,
                        help="Use GPU (optional device ID)")
    parser.add_argument("--ompthreads", type=int,
                        help="OpenMP threads for CPU")
    parser.add_argument("--tmax", type=float,
                        help="Override max simulation time")
    parser.add_argument("--tout", type=float,
                        help="Override output interval")
    parser.add_argument("--nsteps", type=int,
                        help="Max number of steps (debug)")
    parser.add_argument("--stable", action="store_true",
                        help="Stable/reproducible mode")
    parser.add_argument("--skip_gencase", action="store_true",
                        help="Skip GenCase step")
    parser.add_argument("--overwrite", action="store_true",
                        help="Overwrite existing output")
    parser.add_argument("--timeout", type=int, default=300,
                        help="GenCase timeout in seconds")
    parser.add_argument("--solver_timeout", type=int, default=3600,
                        help="Solver timeout in seconds")
    parser.add_argument("--extra_opts", help="Extra CLI options for solver")

    args = parser.parse_args()

    if args.cpu:
        args.gpu = None

    result = process(args)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
