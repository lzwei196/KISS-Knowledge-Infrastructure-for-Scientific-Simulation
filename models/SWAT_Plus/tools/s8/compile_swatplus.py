#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      compile_swatplus
Stage:        s8_model_execution
Description:  Compile SWAT+ Fortran source code using CMake + gfortran on Linux.

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys, os, logging, json, subprocess
from pathlib import Path

SOURCE_DIR = ""
BUILD_DIR = ""
COMPILER = "gfortran"
BUILD_TYPE = "Release"  # Release or Debug

if len(sys.argv) >= 3:
    SOURCE_DIR = sys.argv[1]
    BUILD_DIR = sys.argv[2]
if len(sys.argv) >= 4:
    COMPILER = sys.argv[3]
if len(sys.argv) >= 5:
    BUILD_TYPE = sys.argv[4]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def validate_inputs():
    errors = []
    if not SOURCE_DIR or not Path(SOURCE_DIR).is_dir():
        errors.append(f"Source directory not found: {SOURCE_DIR}")
    elif not (Path(SOURCE_DIR) / "CMakeLists.txt").exists():
        errors.append(f"CMakeLists.txt not found in {SOURCE_DIR}")
    if not BUILD_DIR:
        errors.append("BUILD_DIR is not set")

    # Check compiler
    try:
        result = subprocess.run([COMPILER, "--version"], capture_output=True, text=True)
        if result.returncode != 0:
            errors.append(f"Compiler {COMPILER} not working")
        else:
            version_line = result.stdout.split('\n')[0]
            logger.info(f"Compiler: {version_line}")
    except FileNotFoundError:
        errors.append(f"Compiler not found: {COMPILER}")

    # Check cmake
    try:
        result = subprocess.run(["cmake", "--version"], capture_output=True, text=True)
        if result.returncode != 0:
            errors.append("cmake not working")
    except FileNotFoundError:
        errors.append("cmake not found")

    if errors:
        for e in errors: logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")

def process():
    build_dir = Path(BUILD_DIR)
    build_dir.mkdir(parents=True, exist_ok=True)

    # CMake configure
    logger.info("Running CMake configure...")
    cmake_cmd = [
        "cmake", str(Path(SOURCE_DIR).resolve()),
        f"-DCMAKE_Fortran_COMPILER={COMPILER}",
        f"-DCMAKE_BUILD_TYPE={BUILD_TYPE}"
    ]
    result = subprocess.run(cmake_cmd, cwd=str(build_dir), capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"CMake configure failed:\n{result.stderr}")
        raise RuntimeError("CMake configure failed")

    # Make
    logger.info("Running make...")
    n_cores = os.cpu_count() or 4
    make_result = subprocess.run(["make", f"-j{n_cores}"], cwd=str(build_dir),
                                  capture_output=True, text=True)
    if make_result.returncode != 0:
        logger.error(f"Compilation failed:\n{make_result.stderr}")
        raise RuntimeError("Compilation failed")

    # Find the binary
    possible_names = ["swatplus", "swat_plus", "SWAT+"]
    binary_path = None
    for name in possible_names:
        candidate = build_dir / name
        if candidate.exists():
            binary_path = str(candidate)
            break
    if not binary_path:
        # Search recursively
        for f in build_dir.rglob("swat*"):
            if f.is_file() and os.access(str(f), os.X_OK):
                binary_path = str(f)
                break

    if not binary_path:
        raise RuntimeError("Binary not found after compilation")

    logger.info(f"Compilation successful: {binary_path}")
    return {
        "status": "success",
        "executable": binary_path,
        "build_type": BUILD_TYPE,
        "compiler": COMPILER
    }

def validate_outputs(result):
    if not Path(result["executable"]).exists():
        logger.error(f"Binary not found: {result['executable']}"); sys.exit(3)
    if not os.access(result["executable"], os.X_OK):
        logger.error(f"Binary not executable: {result['executable']}"); sys.exit(3)
    logger.info("Output validation passed.")

if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try: result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}"); sys.exit(2)
    validate_outputs(result)
    print(json.dumps(result, indent=2)); sys.exit(0)
