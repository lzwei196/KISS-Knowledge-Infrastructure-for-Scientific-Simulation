#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
============================================
Tool ID:      run_crhm
Stage:        s5_execution
Description:  Execute CRHM CLI with progress reporting and error capture.

CRHM CLI invocation:
  crhm [options] PROJECT_FILE

Options:
  -h, --help             Show help
  -t TIME_FORMAT         Date format: MS, ISO, YYYYMMDD
  -f OUTPUT_FORMAT       Output format: STD (tab-delimited), OBS
  -o PATH                Output file path (default: CRHM_output_1.txt)
  -d DELIMITER           Column delimiter
  --obs_file_directory   Directory for observation files
  -p UPDATE_FREQUENCY    Print progress every N simulation days

CRITICAL:
  - CRHM reads .obs file paths from the .prj file. If the path is
    relative, it is relative to the WORKING DIRECTORY, not the .prj location.
    Use --obs_file_directory to override, or use absolute paths in .prj.
  - Exit code 0 = success, non-zero = error. But some errors produce
    exit code 0 with error messages on stderr. Always check stderr.
  - CRHM output STD format has 2 header rows: variable names, then units.
    Skip both when parsing data.

Inputs:
  --crhm_exe:      Path to CRHM executable
  --prj_path:      Path to .prj project file
  --output_path:   Output file path
  --obs_dir:       Observation file directory (optional)
  --run_dir:       Stage original .prj/.obs here and run in this directory (optional)
  --progress:      Progress update interval in days (default: 100)
  --time_format:   Output time format: ISO, MS, YYYYMMDD (default: YYYYMMDD)

Exit codes:
  0 -- success
  1 -- input error
  2 -- CRHM execution failed
  3 -- output validation failed
"""

import sys
import os
import json
import logging
import argparse
import subprocess
import time
import math
import shutil
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="Run CRHM simulation")
    parser.add_argument("--crhm_exe", type=str, required=True, help="Path to CRHM executable")
    parser.add_argument("--prj_path", type=str, required=True, help="Path to .prj file")
    parser.add_argument("--output_path", type=str, required=True, help="Output file path")
    parser.add_argument("--obs_dir", type=str, default="", help="Observation file directory")
    parser.add_argument("--run_dir", type=str, default="",
                        help="Stage the project and its observations here, changing only observation paths; "
                             "run here with output_path inside this directory. With staging, obs_dir "
                             "resolves each observation by basename, including obsolete absolute paths.")
    parser.add_argument("--progress", type=int, default=100, help="Progress interval (days)")
    parser.add_argument("--time_format", type=str, default="YYYYMMDD",
                        choices=["ISO", "MS", "YYYYMMDD"], help="Output time format")
    return parser.parse_args()


def validate_inputs(crhm_exe, prj_path, output_path):
    errors = []
    if not Path(crhm_exe).exists():
        errors.append(f"CRHM executable not found: {crhm_exe}")
    elif not os.access(crhm_exe, os.X_OK):
        errors.append(f"CRHM executable not executable: {crhm_exe}. Run: chmod +x {crhm_exe}")
    if not Path(prj_path).exists():
        errors.append(f"Project file not found: {prj_path}")
    if not output_path:
        errors.append("Output path not set")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def read_prj_obs_paths(prj_path):
    """Return the obs file paths listed in the .prj Observations block."""
    paths = []
    in_block = False
    try:
        for line in Path(prj_path).read_text(errors="ignore").splitlines():
            s = line.strip()
            if s.startswith("Observations"):
                in_block = True
                continue
            if in_block:
                if s.startswith("#") or not s:
                    if paths:
                        break
                    continue
                paths.append(s)
    except OSError:
        pass
    return paths


def _observation_lines(data):
    """Locate path lines without decoding/reformatting the scientific project."""
    lines = data.splitlines(keepends=True)
    headers = [i for i, line in enumerate(lines) if line.strip() == b"Observations:"]
    if len(headers) != 1:
        raise ValueError("Staging requires exactly one Observations section in the project")
    indices = []
    for i in range(headers[0] + 1, len(lines)):
        value = lines[i].strip()
        if not value or value.startswith(b"#"):
            if indices:
                break
            continue
        if value.endswith(b":"):
            break
        indices.append(i)
    if not indices:
        raise ValueError("The project's Observations section contains no files to stage")
    return lines, indices


def stage_inputs(prj_path, run_dir, obs_dir=""):
    """Copy authentic inputs; change only Observations path bytes in the copy.

    An explicit obs_dir selects same-named genuine source files even when an
    upstream example contains its author's obsolete absolute Windows paths.
    Resolve every source and destination before writing anything.
    """
    source_prj, run_dir = Path(prj_path).resolve(), Path(run_dir).resolve()
    source_data = source_prj.read_bytes()
    lines, indices = _observation_lines(source_data)
    staged_prj = run_dir / source_prj.name
    if source_prj == run_dir or run_dir in source_prj.parents:
        raise ValueError("run_dir must not contain the original project")
    observations = []
    destinations = {}
    for i in indices:
        raw = os.fsdecode(lines[i].strip()).strip('"')
        basename = raw.replace("\\", "/").rsplit("/", 1)[-1]
        if not basename or basename in (".", ".."):
            raise ValueError(f"Invalid observation path: {raw!r}")
        source = Path(obs_dir).resolve() / basename if obs_dir else Path(raw)
        if not source.is_absolute():
            source = source_prj.parent / source
        source = source.resolve()
        if not source.is_file():
            raise ValueError(f"Observation file not found: {source}; supply --obs_dir with the genuine upstream files")
        target = run_dir / "obs" / basename
        target.resolve().relative_to(run_dir)
        if target.is_symlink() or (target.exists() and target.stat().st_nlink > 1):
            raise ValueError("A staged observation path must not be a symbolic link or hard link")
        key = str(target).casefold()
        if key in destinations and destinations[key] != source:
            raise ValueError(f"Different observation files have the same staging filename: {basename}")
        if run_dir in source.parents:
            raise ValueError("run_dir must not contain an original observation file")
        destinations[key] = source
        observations.append((i, source, target))
    staged_prj.resolve().relative_to(run_dir)
    if staged_prj.is_symlink() or (staged_prj.exists() and staged_prj.stat().st_nlink > 1):
        raise ValueError("The staged project path must not be a symbolic link or hard link")
    run_dir.mkdir(parents=True, exist_ok=True)
    for i, source, target in observations:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        line = lines[i]
        ending = b"\r\n" if line.endswith(b"\r\n") else b"\n" if line.endswith(b"\n") else b""
        prefix = line[:len(line) - len(line.lstrip(b" \t"))]
        lines[i] = prefix + os.fsencode(str(target)) + ending
    staged_prj.write_bytes(b"".join(lines))
    logger.info("Staged original project and %d observation file(s) in %s", len(observations), run_dir)
    return staged_prj


def process(crhm_exe, prj_path, output_path, obs_dir, progress, time_format, run_dir=""):
    """Run CRHM and capture output."""
    crhm_exe, prj_path, output_path = (Path(p).resolve() for p in (crhm_exe, prj_path, output_path))
    cwd = None
    if run_dir:
        cwd = Path(run_dir).resolve()
        output_path.relative_to(cwd)
        prj_path = stage_inputs(prj_path, cwd, obs_dir)
        if output_path == prj_path or (cwd / "obs") in output_path.parents:
            raise ValueError("output_path must not overwrite the staged project or observations")
        obs_dir = ""       # staged observation paths are absolute; CRHM must not prefix them
    before = output_path.stat() if output_path.exists() else None
    # Build command
    cmd = [
        str(crhm_exe),
        "-f", "STD",
        "-t", time_format,
        "-o", str(output_path),
        "-p", str(progress),
    ]

    if obs_dir:
        # CRHM (CRHMmain.cpp:445) prepends obs_file_directory to EVERY obs
        # path in the .prj by raw string concatenation, including absolute
        # paths -> "<obs_dir>/mnt/.../basin.obs" -> "Cannot find observation
        # file. Exiting." Only pass the flag when the .prj actually uses
        # relative obs paths.
        obs_paths = read_prj_obs_paths(prj_path)
        rel_paths = [pp for pp in obs_paths if not os.path.isabs(pp)]
        if rel_paths:
            cmd.extend(["--obs_file_directory", str(obs_dir)])
        else:
            logger.warning(
                "Ignoring --obs_dir=%s: no relative obs path found in %s "
                "(parsed obs paths: %s); CRHM prepends the directory to "
                "every obs path, which breaks absolute paths.",
                obs_dir, prj_path, obs_paths if obs_paths else "none")

    cmd.append(str(prj_path))

    logger.info(f"Running: {' '.join(cmd)}")

    # Ensure output directory exists
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Execute
    # Upstream uses both mktime and gmtime for model civil dates. Inheriting
    # the host timezone changes timestep/solar calculations as well as labels.
    # UTC0 makes that arithmetic consistent; it does not convert forcing from
    # a station's geographical timezone. Restrict the override to this child.
    model_env = os.environ.copy()
    model_env["TZ"] = "UTC0"
    start_time = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd is not None else None,
            env=model_env,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=3600,  # 1 hour max
        )
    except subprocess.TimeoutExpired:
        logger.error("CRHM timed out after 1 hour")
        sys.exit(2)
    except FileNotFoundError:
        logger.error(f"CRHM executable not found at runtime: {crhm_exe}")
        sys.exit(2)

    elapsed = time.time() - start_time

    # Log output
    if result.stdout:
        logger.info(f"STDOUT:\n{result.stdout[:2000]}")
    if result.stderr:
        # Check for actual errors vs progress messages
        stderr_lines = result.stderr.strip().split("\n")
        error_lines = [l for l in stderr_lines if "error" in l.lower() or "fatal" in l.lower()]
        if error_lines:
            logger.error(f"STDERR errors:\n" + "\n".join(error_lines))
        else:
            logger.info(f"STDERR (progress/info):\n{result.stderr[:1000]}")

    if result.returncode != 0:
        logger.error(f"CRHM exited with code {result.returncode}")
        logger.error(f"Full stderr: {result.stderr}")
        sys.exit(2)

    if before and output_path.exists():
        after = output_path.stat()
        if (after.st_size, after.st_mtime_ns, after.st_ctime_ns) == (
                before.st_size, before.st_mtime_ns, before.st_ctime_ns):
            logger.error("CRHM did not replace the previous output file: %s", output_path)
            sys.exit(3)

    logger.info(f"CRHM completed in {elapsed:.1f} seconds")

    return str(output_path)


def validate_outputs(output_path):
    errors = []
    p = Path(output_path)
    if not p.exists():
        errors.append(f"Output file not created: {output_path}")
    elif p.stat().st_size == 0:
        errors.append("Output file is empty -- CRHM may have run but produced no output")
    else:
        # Check first few lines for STD format header.
        # errors="replace": CRHM writes Latin-1 degree signs in the units row
        # (e.g. hru_t "(ºC)" = byte 0xBA), which crashes a strict-UTF-8 read.
        with open(p, encoding="utf-8", errors="replace") as f:
            first_lines = [f.readline() for _ in range(3)]
        if any(not line.strip() for line in first_lines):
            errors.append("Output file must contain variable and units headers plus a data row")
        else:
            header = first_lines[0].strip().split("\t")
            row = first_lines[2].strip().split("\t")
            try:
                numeric = len(header) > 1 and len(row) == len(header) and all(
                    math.isfinite(float(value)) for value in row[1:])
            except ValueError:
                numeric = False
            if not numeric:
                errors.append("Output has no complete, finite numeric data row after its two STD headers")
        # STD format: line 1 = variable names, line 2 = units
        logger.info(f"Output header: {first_lines[0].strip()[:100]}...")

    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)
    logger.info("Output validation passed.")


if __name__ == "__main__":
    args = parse_args()
    logger.info(f"Running tool: {os.path.basename(__file__)}")

    validate_inputs(args.crhm_exe, args.prj_path, args.output_path)

    try:
        output_path = process(
            args.crhm_exe, args.prj_path, args.output_path,
            args.obs_dir, args.progress, args.time_format, args.run_dir
        )
    except SystemExit:
        raise
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)

    validate_outputs(output_path)

    print(json.dumps({
        "status": "success",
        "output": output_path,
        "size_bytes": Path(output_path).stat().st_size,
    }))
    sys.exit(0)
