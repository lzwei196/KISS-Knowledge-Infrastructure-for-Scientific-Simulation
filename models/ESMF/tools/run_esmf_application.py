#!/usr/bin/env python3
"""
run_esmf_application.py — Build and execute an ESMF-based application.

Handles:
  - Environment variable setup (ESMF_DIR, ESMF_COMPILER, ESMF_COMM, etc.)
  - Building ESMF library from source
  - Compiling user ESMF applications against the library
  - Running with MPI launcher
  - Capturing and parsing log output

Pipeline stage: s6_run
Pattern: validate → process → validate

Usage:
    python run_esmf_application.py \
        --esmf-dir /path/to/esmf \
        --compiler gfortran \
        --comm openmpi \
        --app-source my_coupled_model.F90 \
        --np 4
"""

import argparse
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ESMF environment configuration
# ---------------------------------------------------------------------------
ESMF_ENV_VARS = {
    "ESMF_DIR": "Top-level ESMF directory (required)",
    "ESMF_COMPILER": "Compiler family: gfortran, intel, pgi, nag, llvm",
    "ESMF_COMM": "MPI library: openmpi, mpich, mvapich2, mpiuni (serial)",
    "ESMF_BOPT": "Build optimization: O (optimized), g (debug)",
    "ESMF_NETCDF": "NetCDF mode: split (separate C/Fortran), standard",
    "ESMF_NETCDF_INCLUDE": "Path to NetCDF include files",
    "ESMF_NETCDF_LIBPATH": "Path to NetCDF libraries",
    "ESMF_INSTALL_PREFIX": "Installation prefix (default: ESMF_DIR/install)",
    "ESMF_PTHREADS": "Thread support: ON, OFF",
    "ESMF_OPENMP": "OpenMP support: ON, OFF",
    "ESMF_OPENACC": "OpenACC support: ON, OFF",
}

SUPPORTED_COMPILERS = ["gfortran", "intel", "pgi", "nag", "llvm", "absoft"]
SUPPORTED_COMM = ["openmpi", "mpich", "mvapich2", "mpiuni", "intelmpi"]


def validate_environment(esmf_dir: str, compiler: str, comm: str) -> dict:
    """Validate ESMF build environment.

    TRAP: ESMF_DIR must point to the source root, not an install prefix.
    The directory must contain 'makefile' and 'src/' subdirectory.

    TRAP: ESMF_COMM=mpiuni builds serial-only ESMF. Running with mpirun
    will cause double-initialization of MPI → segfault.
    """
    errors = []

    # Check ESMF source directory
    if not os.path.isdir(esmf_dir):
        errors.append(f"ESMF_DIR not found: {esmf_dir}")
    else:
        makefile = os.path.join(esmf_dir, "makefile")
        src_dir = os.path.join(esmf_dir, "src")
        if not os.path.isfile(makefile):
            errors.append(f"No makefile in ESMF_DIR: {makefile}")
        if not os.path.isdir(src_dir):
            errors.append(f"No src/ in ESMF_DIR: {src_dir}")

    # Check compiler
    if compiler not in SUPPORTED_COMPILERS:
        errors.append(f"Unsupported compiler: {compiler}. Use one of: {SUPPORTED_COMPILERS}")

    # Check compiler is available
    compiler_cmds = {
        "gfortran": "gfortran", "intel": "ifort", "pgi": "pgfortran",
        "nag": "nagfor", "llvm": "flang", "absoft": "af90",
    }
    cmd = compiler_cmds.get(compiler, compiler)
    if not shutil.which(cmd):
        errors.append(f"Compiler '{cmd}' not found in PATH")

    # Check MPI
    if comm not in SUPPORTED_COMM:
        errors.append(f"Unsupported ESMF_COMM: {comm}. Use one of: {SUPPORTED_COMM}")
    if comm != "mpiuni" and not shutil.which("mpirun") and not shutil.which("mpiexec"):
        errors.append("MPI launcher (mpirun/mpiexec) not found but ESMF_COMM != mpiuni")

    # Check NetCDF (optional but recommended)
    nc_config = shutil.which("nc-config")
    nf_config = shutil.which("nf-config")
    netcdf_info = {"nc-config": nc_config is not None, "nf-config": nf_config is not None}

    if errors:
        for e in errors:
            logger.error(e)
        raise RuntimeError(f"Environment validation failed with {len(errors)} error(s)")

    info = {
        "esmf_dir": esmf_dir,
        "compiler": compiler,
        "comm": comm,
        "platform": platform.system(),
        "netcdf": netcdf_info,
    }
    logger.info("Environment validated: compiler=%s, comm=%s", compiler, comm)
    return info


def setup_environment(esmf_dir: str, compiler: str, comm: str,
                      bopt: str = "O", netcdf: str = "split") -> dict:
    """Set up ESMF environment variables for build.

    Returns the environment dict to pass to subprocess.
    """
    env = os.environ.copy()
    env["ESMF_DIR"] = esmf_dir
    env["ESMF_COMPILER"] = compiler
    env["ESMF_COMM"] = comm
    env["ESMF_BOPT"] = bopt

    # Auto-detect NetCDF paths
    nc_config = shutil.which("nc-config")
    if nc_config:
        try:
            inc = subprocess.check_output([nc_config, "--includedir"], text=True).strip()
            lib = subprocess.check_output([nc_config, "--libdir"], text=True).strip()
            env["ESMF_NETCDF"] = netcdf
            env["ESMF_NETCDF_INCLUDE"] = inc
            env["ESMF_NETCDF_LIBPATH"] = lib
            logger.info("NetCDF detected: include=%s, lib=%s", inc, lib)
        except subprocess.CalledProcessError:
            logger.warning("nc-config found but failed to query paths")

    return env


def build_esmf_library(esmf_dir: str, env: dict, jobs: int = 4) -> str:
    """Build the ESMF library from source.

    TRAP: Must use GNU make, not standard Unix make.
    TRAP: Build can take 10-30 minutes depending on system.

    Returns path to built library.
    """
    logger.info("Building ESMF library (this may take 10-30 minutes)...")
    start = time.time()

    make_cmd = shutil.which("gmake") or shutil.which("make")
    if not make_cmd:
        raise RuntimeError("GNU make not found (tried gmake, make)")

    # Clean first if requested
    cmd = [make_cmd, "-j", str(jobs), "lib"]
    logger.info("Running: %s (in %s)", " ".join(cmd), esmf_dir)

    result = subprocess.run(
        cmd, cwd=esmf_dir, env=env,
        capture_output=True, text=True, timeout=3600
    )

    elapsed = time.time() - start

    if result.returncode != 0:
        logger.error("ESMF build failed (%.0fs):\n%s", elapsed, result.stderr[-2000:])
        return None

    logger.info("ESMF library built successfully (%.0fs)", elapsed)

    # Find the library
    lib_dir = os.path.join(esmf_dir, "lib")
    if os.path.isdir(lib_dir):
        return lib_dir
    return esmf_dir


def compile_application(source_file: str, output_binary: str,
                        esmf_dir: str, env: dict) -> str:
    """Compile a user ESMF application against the ESMF library.

    TRAP: Link order matters. ESMF libraries must come AFTER user objects.
    TRAP: Fortran applications need both esmf and esmf_fullylinked libraries.
    """
    if not os.path.isfile(source_file):
        raise FileNotFoundError(f"Application source not found: {source_file}")

    ext = os.path.splitext(source_file)[1].lower()
    is_fortran = ext in (".f90", ".f", ".f03", ".f08")

    # Use ESMF's esmf.mk for compiler/linker flags
    esmf_mk = None
    for root, dirs, files in os.walk(os.path.join(esmf_dir, "lib")):
        if "esmf.mk" in files:
            esmf_mk = os.path.join(root, "esmf.mk")
            break

    if esmf_mk:
        env["ESMFMKFILE"] = esmf_mk
        logger.info("Using ESMF makefile fragment: %s", esmf_mk)

    if is_fortran:
        compiler = env.get("ESMF_F90COMPILER", "mpif90")
        cmd = [compiler, "-o", output_binary, source_file, "-lesmf"]
    else:
        compiler = env.get("ESMF_CXXCOMPILER", "mpicxx")
        cmd = [compiler, "-o", output_binary, source_file, "-lesmf", "-lesmf_fullylinked"]

    logger.info("Compiling: %s", " ".join(cmd))
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)

    if result.returncode != 0:
        logger.error("Compilation failed:\n%s", result.stderr[-2000:])
        return None

    logger.info("Application compiled: %s", output_binary)
    return output_binary


def run_application(binary: str, np_procs: int, comm: str,
                    env: dict, timeout: int = 3600) -> dict:
    """Run the ESMF application with MPI launcher.

    TRAP: If ESMF was built with ESMF_COMM=mpiuni, do NOT use mpirun.
    This causes double MPI_Init → segfault.

    TRAP: The number of MPI processes must match the DELayout decomposition
    in the application. Mismatch → "DELayout: PET count" error.
    """
    if not os.path.isfile(binary):
        raise FileNotFoundError(f"Binary not found: {binary}")

    if comm == "mpiuni":
        if np_procs > 1:
            logger.warning(
                "TRAP: ESMF_COMM=mpiuni but np=%d. "
                "Serial ESMF cannot run with MPI. Forcing np=1.",
                np_procs
            )
            np_procs = 1
        cmd = [binary]
    else:
        launcher = shutil.which("mpirun") or shutil.which("mpiexec")
        if not launcher:
            raise RuntimeError("MPI launcher not found")
        cmd = [launcher, "-np", str(np_procs), binary]

    logger.info("Running: %s", " ".join(cmd))
    start = time.time()

    result = subprocess.run(
        cmd, env=env, capture_output=True, text=True, timeout=timeout
    )

    elapsed = time.time() - start
    output = {
        "command": " ".join(cmd),
        "returncode": result.returncode,
        "stdout": result.stdout[:5000],
        "stderr": result.stderr[:5000],
        "elapsed_s": elapsed,
    }

    if result.returncode != 0:
        logger.error("Application failed (%.1fs, rc=%d)", elapsed, result.returncode)
        _diagnose_runtime_error(result.stderr)
    else:
        logger.info("Application completed successfully (%.1fs)", elapsed)

    return output


def _diagnose_runtime_error(stderr: str):
    """Diagnose common ESMF runtime errors from stderr."""
    diagnostics = [
        ("PET count", "DELayout PET count mismatch. Adjust -np or regDecomp."),
        ("MPI_Init", "Double MPI initialization. Check ESMF_COMM vs launcher."),
        ("NETCDF", "NetCDF I/O error. Check file paths and NetCDF installation."),
        ("ESMF_LogErr", "ESMF logged error. Check PET*.ESMF_LogFile for details."),
        ("Segmentation fault", "Segfault. Check stagger locations, halo widths, array bounds."),
        ("Calendar", "Calendar error. Set calendar type before creating Clock."),
    ]
    for pattern, msg in diagnostics:
        if pattern.lower() in stderr.lower():
            logger.error("DIAGNOSIS: %s", msg)


def run_regrid_weight_gen(source_grid: str, dest_grid: str, weight_file: str,
                          method: str = "bilinear", env: dict = None) -> dict:
    """Run ESMF_RegridWeightGen command-line tool.

    TRAP: For conservative regridding, both source and destination grids
    MUST have corner coordinates AND cell areas defined.
    """
    tool = shutil.which("ESMF_RegridWeightGen")
    if not tool:
        logger.warning("ESMF_RegridWeightGen not found in PATH")
        return {"status": "not_found"}

    cmd = [
        tool,
        "--source", source_grid,
        "--destination", dest_grid,
        "--weight", weight_file,
        "--method", method,
        "--ignore_unmapped",
    ]

    logger.info("Running: %s", " ".join(cmd))
    result = subprocess.run(cmd, env=env or os.environ, capture_output=True, text=True)

    return {
        "command": " ".join(cmd),
        "returncode": result.returncode,
        "stdout": result.stdout[:2000],
        "stderr": result.stderr[:2000],
    }


def validate_output(run_result: dict, work_dir: str = ".") -> dict:
    """Validate execution results.

    Checks for:
    - Non-zero return code
    - ESMF log files (PET*.ESMF_LogFile)
    - Output data files
    """
    status = "success" if run_result.get("returncode") == 0 else "failed"

    # Check for ESMF log files
    log_files = list(Path(work_dir).glob("PET*.ESMF_LogFile"))
    errors_in_logs = 0
    for lf in log_files[:4]:  # check first 4 PET logs
        try:
            content = lf.read_text()
            errors_in_logs += content.lower().count("error")
        except Exception:
            pass

    validation = {
        "status": status,
        "returncode": run_result.get("returncode"),
        "elapsed_s": run_result.get("elapsed_s"),
        "log_files_found": len(log_files),
        "errors_in_logs": errors_in_logs,
    }

    if errors_in_logs > 0:
        logger.warning("Found %d error(s) in ESMF log files", errors_in_logs)

    logger.info("Validation: status=%s, logs=%d, errors=%d",
                status, len(log_files), errors_in_logs)
    return validation


def main():
    parser = argparse.ArgumentParser(description="Build and run ESMF application")
    parser.add_argument("--esmf-dir", required=True, help="ESMF source directory")
    parser.add_argument("--compiler", default="gfortran", choices=SUPPORTED_COMPILERS)
    parser.add_argument("--comm", default="openmpi", choices=SUPPORTED_COMM)
    parser.add_argument("--bopt", default="O", choices=["O", "g"])
    parser.add_argument("--np", type=int, default=1, help="Number of MPI processes")
    parser.add_argument("--app-source", help="Application source file to compile")
    parser.add_argument("--app-binary", help="Pre-built binary to run")
    parser.add_argument("--build-only", action="store_true", help="Only build, don't run")
    parser.add_argument("--regrid", nargs=3, metavar=("SRC", "DST", "WGT"),
                        help="Run RegridWeightGen: source dest weight")
    args = parser.parse_args()

    # Validate environment
    validate_environment(args.esmf_dir, args.compiler, args.comm)
    env = setup_environment(args.esmf_dir, args.compiler, args.comm, args.bopt)

    # Build ESMF library
    lib_path = build_esmf_library(args.esmf_dir, env)
    if not lib_path:
        logger.error("ESMF library build failed. Cannot continue.")
        sys.exit(1)

    if args.build_only:
        logger.info("Build-only mode. Done.")
        return

    # Compile and run application
    binary = args.app_binary
    if args.app_source:
        out_name = os.path.splitext(os.path.basename(args.app_source))[0]
        binary = compile_application(args.app_source, out_name, args.esmf_dir, env)

    if binary:
        result = run_application(binary, args.np, args.comm, env)
        validation = validate_output(result)
        print(json.dumps(validation, indent=2))

    # Regridding
    if args.regrid:
        src, dst, wgt = args.regrid
        rg_result = run_regrid_weight_gen(src, dst, wgt, env=env)
        print(json.dumps(rg_result, indent=2))


if __name__ == "__main__":
    main()
