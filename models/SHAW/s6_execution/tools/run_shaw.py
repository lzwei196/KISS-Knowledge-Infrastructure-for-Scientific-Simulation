#!/usr/bin/env python3
"""
run_shaw.py — Execute SHAW model with progress monitoring and input validation.

Generates the .inp (input/output list) file, validates all input files exist,
runs SHAW, and checks for successful completion.

Usage:
    python run_shaw.py \
        --workdir /path/to/shaw/run \
        --sit_file site.sit --wea_file weather.wea \
        --moi_file init.moi --tem_file init.tem \
        [--mtstep 1] [--iflagsi 1] \
        [--shaw_exe /mnt/disk1/Hydrocraft_server/model/shaw/Code/shaw303]
"""

import argparse
import subprocess
import os
import sys
import time
from pathlib import Path

SHAW_EXE = os.path.join(os.environ.get("HYDROCRAFT_ROOT", "/mnt/disk1/Hydrocraft_server"), "model/shaw/Code/shaw303")


def create_inp_file(args, workdir):
    """
    Create the SHAW .inp (input/output list) file.

    Structure:
        Line A: IVERSION
        Line B: MTSTEP IFLAGSI INPH2O MWATRXT
        Line B-1: site file
        Line B-2: weather file
        Line B-3: moisture file
        Line B-4: temperature file
        Line B-5: soil sink file (if MWATRXT=1)
        Line C: LVLOUT(1..20) — 20 output frequency flags
        Lines C-1..C-19: output file names
    """
    inp_path = workdir / "shaw.inp"

    # Output frequencies: daily for key outputs
    # LVLOUT indices:
    # 1=general, 2=side-by-side, 3=temp, 4=moisture, 5=liquid, 6=matric
    # 7=canopy_temp, 8=canopy_hum, 9=snow_temp, 10=energy, 11=water
    # 12=wflow, 13=rootxt, 14=lateral, 15=frost, 16=salts, 17=solute
    # 18=future, 19=future, 20=screen_update
    lvlout = [
        24,  # 1: general output (24=daily)
        24,  # 2: temp profile
        24,  # 3: moisture profile
        24,  # 4: liquid water
        0,   # 5: matric potential (off)
        0,   # 6: canopy temp (off)
        0,   # 7: canopy humidity (off)
        0,   # 8: snow temp (off)
        24,  # 9: energy balance
        24,  # 10: water balance
        0,   # 11: wflow (off)
        0,   # 12: root extraction (off)
        0,   # 13: lateral flow (off)
        24,  # 14: frost depth
        0,   # 15: salts (off)
        0,   # 16: solute (off)
        0,   # 17: side-by-side comparison
        0,   # 18: future
        0,   # 19: future
        0,   # 20: screen update freq (0=no screen output)
    ]

    # Override with user preferences
    if args.output_hourly:
        lvlout[0] = 1  # hourly output
        lvlout[1] = 1
        lvlout[2] = 1
        lvlout[8] = 1
        lvlout[9] = 1
        lvlout[13] = 1

    if args.output_frost:
        lvlout[13] = max(lvlout[13], 24)

    # Output file names (must be <80 chars, relative to workdir)
    output_files = [
        "out.out",       # C-1: general
        "temp.out",      # C-2: temperature
        "moist.out",     # C-3: moisture
        "liquid.out",    # C-4: liquid water
        "matric.out",    # C-5: matric potential
        "cantmp.out",    # C-6: canopy temp
        "canhum.out",    # C-7: canopy humidity
        "snowtmp.out",   # C-8: snow temp
        "energy.out",    # C-9: energy balance
        "water.out",     # C-10: water balance
        "wflow.out",     # C-11: water flow
        "rootxt.out",    # C-12: root extraction
        "lateral.out",   # C-13: lateral flow
        "frost.out",     # C-14: frost depth
        "salts.out",     # C-15: salt concentration
        "solute.out",    # C-16: solute concentration
        "compare.out",   # C-17: side-by-side comparison
        "future1.out",   # C-18: reserved
        "future2.out",   # C-19: reserved
    ]

    lines = []

    # Line A: IVERSION
    lines.append("Shaw 3.0")

    # Line B: MTSTEP IFLAGSI INPH2O MWATRXT
    lines.append(f" {args.mtstep} {args.iflagsi} 0 0")

    # Line B-1 through B-4: input file names
    lines.append(str(args.sit_file))
    lines.append(str(args.wea_file))
    lines.append(str(args.moi_file))
    lines.append(str(args.tem_file))

    # Line C: LVLOUT(1..20)
    lvlout_str = '  '.join(str(v) for v in lvlout)
    lines.append(f" {lvlout_str}")

    # Lines C-1 through C-19: output file names
    for fname in output_files:
        lines.append(fname)

    with open(inp_path, 'w') as f:
        f.write('\n'.join(lines) + '\n')

    print(f"Input control file written: {inp_path}")
    return inp_path


def validate_inputs(args, workdir):
    """Check that all required input files exist and are non-empty."""
    errors = []

    for label, filepath in [
        ("Site file", args.sit_file),
        ("Weather file", args.wea_file),
        ("Moisture file", args.moi_file),
        ("Temperature file", args.tem_file),
    ]:
        p = workdir / filepath if not Path(filepath).is_absolute() else Path(filepath)
        if not p.exists():
            errors.append(f"{label} not found: {p}")
        elif p.stat().st_size == 0:
            errors.append(f"{label} is empty: {p}")

    # Check SHAW executable
    exe = Path(args.shaw_exe)
    if not exe.exists():
        errors.append(f"SHAW executable not found: {exe}")
    elif not os.access(str(exe), os.X_OK):
        errors.append(f"SHAW executable not executable: {exe}")

    # Check path lengths (Fortran 77: max 80 chars)
    for filepath in [args.sit_file, args.wea_file, args.moi_file, args.tem_file]:
        if len(str(filepath)) > 80:
            errors.append(f"Path too long (>80 chars, Fortran limit): {filepath}")

    if errors:
        print("VALIDATION ERRORS:")
        for e in errors:
            print(f"  - {e}")
        return False

    print("All input files validated successfully.")
    return True


def run_shaw(inp_file, shaw_exe, workdir, timeout=3600):
    """
    Execute SHAW model.

    SHAW reads from stdin — it prompts for the .inp file path.
    We pipe the filename to stdin.
    """
    inp_name = Path(inp_file).name

    print(f"\nRunning SHAW model...")
    print(f"  Executable: {shaw_exe}")
    print(f"  Working dir: {workdir}")
    print(f"  Input file: {inp_name}")
    print(f"  Timeout: {timeout}s")

    start_time = time.time()

    try:
        result = subprocess.run(
            [str(shaw_exe)],
            input=inp_name + '\n',
            capture_output=True,
            text=True,
            cwd=str(workdir),
            timeout=timeout,
        )

        elapsed = time.time() - start_time

        if result.returncode == 0:
            print(f"\nSHAW completed successfully in {elapsed:.1f}s")
            if result.stdout:
                # Print last few lines of stdout
                stdout_lines = result.stdout.strip().split('\n')
                for line in stdout_lines[-5:]:
                    print(f"  {line}")
        else:
            print(f"\nSHAW FAILED with return code {result.returncode}")
            print(f"  Elapsed: {elapsed:.1f}s")
            if result.stderr:
                print(f"  STDERR: {result.stderr[:500]}")
            if result.stdout:
                print(f"  STDOUT (last 10 lines):")
                for line in result.stdout.strip().split('\n')[-10:]:
                    print(f"    {line}")
            return False

    except subprocess.TimeoutExpired:
        print(f"\nSHAW TIMED OUT after {timeout}s")
        return False
    except FileNotFoundError:
        print(f"\nSHAW executable not found: {shaw_exe}")
        return False

    return True


def check_outputs(workdir):
    """Check which output files were produced and their sizes."""
    output_files = {
        'out.out': 'General output',
        'temp.out': 'Soil temperature profiles',
        'moist.out': 'Soil moisture profiles',
        'energy.out': 'Surface energy balance',
        'water.out': 'Water balance',
        'frost.out': 'Frost/thaw/snow depth',
    }

    print("\nOutput files:")
    found = 0
    for fname, desc in output_files.items():
        fpath = workdir / fname
        if fpath.exists() and fpath.stat().st_size > 0:
            size = fpath.stat().st_size
            print(f"  {fname:15s} ({size:>8d} bytes) — {desc}")
            found += 1
        elif fpath.exists():
            print(f"  {fname:15s} (EMPTY) — {desc}")
        else:
            print(f"  {fname:15s} (missing)")

    print(f"\n{found}/{len(output_files)} key output files produced.")
    return found > 0


def main():
    parser = argparse.ArgumentParser(description="Run SHAW model")
    parser.add_argument("--workdir", type=str, required=True, help="Working directory")
    parser.add_argument("--sit_file", type=str, required=True, help="Site file (.sit)")
    parser.add_argument("--wea_file", type=str, required=True, help="Weather file (.wea)")
    parser.add_argument("--moi_file", type=str, required=True, help="Moisture profile (.moi)")
    parser.add_argument("--tem_file", type=str, required=True, help="Temperature profile (.tem)")
    parser.add_argument("--shaw_exe", type=str, default=SHAW_EXE,
                        help="Path to SHAW executable")
    parser.add_argument("--mtstep", type=int, default=1, choices=[0, 1, 2],
                        help="Weather timestep: 0=hourly, 1=daily, 2=custom")
    parser.add_argument("--iflagsi", type=int, default=1, choices=[0, 1],
                        help="Units: 0=mixed English/SI, 1=all SI (metric)")
    parser.add_argument("--timeout", type=int, default=3600, help="Max runtime (seconds)")
    parser.add_argument("--output_hourly", action="store_true",
                        help="Enable hourly output (default: daily)")
    parser.add_argument("--output_frost", action="store_true",
                        help="Enable frost depth output")

    args = parser.parse_args()

    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    # Validate inputs
    if not validate_inputs(args, workdir):
        sys.exit(1)

    # Create .inp file
    inp_file = create_inp_file(args, workdir)

    # Run SHAW
    success = run_shaw(inp_file, args.shaw_exe, workdir, args.timeout)

    if success:
        check_outputs(workdir)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
