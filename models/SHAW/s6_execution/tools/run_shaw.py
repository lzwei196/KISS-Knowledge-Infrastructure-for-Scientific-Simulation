#!/usr/bin/env python3
"""
run_shaw.py — Execute SHAW model with progress monitoring and input validation.

Preserves an existing .inp (input/output list), or generates one for four input
files, validates inputs, and checks fresh output through the requested end date.

Usage:
    python run_shaw.py \
        --workdir /path/to/shaw/run \
        --sit_file site.sit --wea_file weather.wea \
        --moi_file init.moi --tem_file init.tem \
        [--mtstep 1] [--iflagsi 1] \
        [--shaw_exe KISSPATH_BINARIES/shaw/shaw303]

    # Preserve the official hourly Trial control and PEST comparison settings:
    python run_shaw.py --workdir /path/to/Trial --inp_file Trial.303.inp
"""

import argparse
import subprocess
import os
import sys
import time
import shutil
from pathlib import Path, PureWindowsPath
from datetime import datetime, timedelta

from parse_shaw_output import _date_fields, parse_profile_file

# Canonical compiled binary: model/shaw/shaw303 (symlink -> model/shaw/Shaw303/shaw303,
# produced by model/shaw/compile.sh). The old "model/shaw/Code/shaw303" path never
# existed (there is no Code/ directory) — fixed 2026-06-28 RISMA run.
SHAW_EXE = os.path.join(os.environ.get("HYDROCRAFT_ROOT", "KISSPATH_ROOT"), "model/shaw/shaw303")
BINARY_DIR = Path("KISSPATH_BINARIES") / "shaw"


def resolve_executable(value):
    """Prefer native Windows PE over a case-insensitive Shaw303 source directory."""
    path = Path(value)
    if sys.platform == "win32" and path.suffix.lower() != ".exe":
        native = path.with_name(path.name + ".exe")
        if native.is_file():
            return native
    return path


def default_executable():
    """Keep Windows software outside scenario data, using the configured role."""
    legacy = resolve_executable(SHAW_EXE)
    if sys.platform != "win32":
        return str(legacy)
    managed = BINARY_DIR / "shaw303.exe"
    return str(managed if managed.is_file() or not legacy.is_file() else legacy)


def control_lines(inp_file):
    """Read an existing control file without replacing its scientific/output settings."""
    lines = Path(inp_file).read_text(encoding="utf-8").splitlines()
    if len(lines) < 26 or "shaw" not in lines[0].lower():
        raise ValueError("existing .inp must contain the SHAW input and output filename lists")
    return lines


def control_layout(lines):
    """Locate optional soil-sink input and output flags in a 3.03 control file."""
    flags = [int(value) for value in lines[1].split()]
    if len(flags) != 4:
        raise ValueError("control file must specify MTSTEP IFLAGSI INPH2O MWATRXT")
    level_index = 7 if flags[3] == 1 else 6
    levels = [int(value) for value in lines[level_index].split()]
    if len(levels) != 20 or len(lines) < level_index + 20:
        raise ValueError("control file must specify 20 output-frequency flags and 19 filenames")
    return level_index, levels


def _input_names(lines, level_index, levels):
    names = [line.strip() for line in lines[2:level_index]]
    if levels[16] > 0:
        for line in lines[level_index + 20:]:
            fields = line.split()
            if fields:
                try:
                    float(fields[0])
                except ValueError:
                    names.append(line.strip())
    return names


def _staged_path(base, filename):
    """Resolve a short relative Fortran filename without escaping its directory."""
    filename = filename.strip().replace("\\", "/")
    relative = Path(filename)
    if (not filename or len(filename) > 80 or relative.is_absolute()
            or PureWindowsPath(filename).drive or ".." in relative.parts):
        raise ValueError(f"staged control requires a relative filename within 80 characters: {filename}")
    path = (base / relative).resolve()
    if not path.is_relative_to(base.resolve()):
        raise ValueError(f"staged filename escapes its directory: {filename}")
    return path


def stage_inputs(source_dir, inp_name, workdir):
    """Copy a control and its referenced inputs byte for byte into a separate run directory."""
    source_dir, workdir = Path(source_dir).resolve(), Path(workdir).resolve()
    if source_dir == workdir or Path(inp_name).name != inp_name:
        raise ValueError("staging requires separate source/run directories and a control basename")
    source_control = _staged_path(source_dir, inp_name)
    lines = control_lines(source_control)
    level_index, levels = control_layout(lines)
    names = [inp_name] + [line.strip() for line in lines[2:level_index]]
    # The optional PEST block includes observation filenames interleaved with
    # numeric configuration rows. Preserve those input bytes as well.
    if levels[16] > 0:
        for line in lines[level_index + 20:]:
            fields = line.split()
            if not fields:
                continue
            try:
                float(fields[0])
            except ValueError:
                names.append(line.strip())
    pairs = []
    for name in dict.fromkeys(names):
        source, target = _staged_path(source_dir, name), _staged_path(workdir, name)
        if not source.is_file() or source.stat().st_size == 0:
            raise ValueError(f"staging input is missing or empty: {source}")
        if source == target:
            raise ValueError(f"staging would overwrite source input: {source}")
        if target.exists() and (not target.is_file() or target.read_bytes() != source.read_bytes()):
            raise ValueError(f"staging would overwrite a different existing file: {target}")
        if not any(existing_target == target for _, existing_target in pairs):
            pairs.append((source, target))
    targets = {target for _, target in pairs}
    outputs = [_staged_path(workdir, name) for name, frequency in
               zip(lines[level_index + 1:level_index + 20], levels[:19]) if frequency > 0]
    if any(path in targets for path in outputs):
        raise ValueError("control output would overwrite a staged input")
    for source, target in pairs:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copyfile(source, target)
    for path in outputs:
        path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Staged {len(pairs)} unchanged input files from {source_dir}")


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
    # LVLOUT(1..19) correspond to output_files below; flag 20 controls screen updates.
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
    """Check each selected input in the project; examples are not software prerequisites."""
    errors = []
    files = [("Site file", args.sit_file), ("Weather file", args.wea_file),
             ("Moisture file", args.moi_file), ("Temperature file", args.tem_file)]
    if getattr(args, "inp_file", None):
        inp = workdir / args.inp_file
        if inp.resolve().parent != workdir.resolve() or len(inp.name) > 80:
            errors.append("existing .inp must be in workdir with a filename of at most 80 characters")
        try:
            lines = control_lines(inp)
            level_index, _ = control_layout(lines)
            files = list(zip(("Site file", "Weather file", "Moisture file", "Temperature file"),
                             [line.strip() for line in lines[2:6]]))
            if level_index == 7:
                files.append(("Soil sink file", lines[6].strip()))
        except (OSError, ValueError) as error:
            errors.append(str(error))
            files = []
    for label, filepath in files:
        if not filepath:
            errors.append(f"{label} is required")
            continue
        path = workdir / filepath
        if not path.is_file():
            errors.append(f"{label} not found: {path}")
        elif path.stat().st_size == 0:
            errors.append(f"{label} is empty: {path}")
        if len(str(filepath)) > 80:
            errors.append(f"Path too long (>80 chars, Fortran limit): {filepath}")
    exe = resolve_executable(args.shaw_exe)
    if not exe.is_file():
        errors.append(f"SHAW executable not found: {exe}")
    elif not os.access(str(exe), os.X_OK):
        errors.append(f"SHAW executable not executable: {exe}")
    if errors:
        print("VALIDATION ERRORS:")
        for error in errors:
            print(f"  - {error}")
        return False
    print("All input files validated successfully.")
    return True


def _stamp(path):
    if not path.is_file():
        return None
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def run_shaw(inp_file, shaw_exe, workdir, timeout=3600):
    """Run a control file intact; require fresh output through its requested period."""
    workdir = Path(workdir).resolve()
    inp_file = Path(inp_file).resolve()
    shaw_exe = resolve_executable(shaw_exe).resolve()
    try:
        if inp_file.parent != workdir or len(inp_file.name) > 80:
            raise ValueError("selected control must be inside workdir with a filename of at most 80 characters")
        for implicit in ("ShawPEST.fof", "ShawMod.fof"):
            if (workdir / implicit).exists():
                raise ValueError(f"implicit SHAW control would bypass the selected input: {implicit}")
        lines = control_lines(inp_file)
        level_index, levels = control_layout(lines)
        declared = [(_staged_path(workdir, name), frequency) for name, frequency in
                    zip(lines[level_index + 1:level_index + 20], levels[:19])]
        # The Fortran program opens the general output even when LVLOUT(1)=0.
        enabled = [path for index, (path, frequency) in enumerate(declared)
                   if index == 0 or frequency > 0]
        protected = [inp_file, shaw_exe] + [(workdir / name).resolve() for name in
                                          _input_names(lines, level_index, levels)]
        targets = enabled + [_staged_path(workdir, name) for name in
                             ("shaw.stdout.log", "shaw.stderr.log")]
        for target in targets:
            if target.is_file() and target.stat().st_nlink > 1:
                raise ValueError(f"output has another hardlink and cannot be replaced: {target}")
            if any(target == source or (target.is_file() and source.is_file()
                   and target.samefile(source)) for source in protected):
                raise ValueError(f"output would overwrite an input or executable: {target}")
        profiles = [(path, frequency) for path, frequency in declared[1:4] if frequency > 0]
        site = (workdir / lines[2].strip()).read_text(encoding="utf-8").splitlines()
        period = site[1].split()
        start = _date_fields(int(period[0]), int(period[1]), int(period[2]))["datetime"]
        end = _date_fields(int(period[3]), 24, int(period[4]))["datetime"]
        node_count = int(site[3].split()[3])
        hours_per_step = int(site[3].split()[6])
        if (start >= end or node_count < 1 or not enabled or hours_per_step < 1
                or 24 % hours_per_step or int(period[1]) % hours_per_step):
            raise ValueError("site period, soil-node count or enabled outputs are invalid")
    except (OSError, ValueError, IndexError) as error:
        print(f"Invalid SHAW control/site input: {error}")
        return False
    before = {path: _stamp(path) for path in enabled}
    # SHAW's NEWFIL branch asks once before replacing existing declared outputs.
    # A requested rerun authorizes these outputs; leave all file writes to SHAW
    # and still require each one to be fresh and complete afterward.
    stdin = inp_file.name + ("\nY\n\n" if any(value is not None for value in before.values()) else "\n\n")
    print(f"Running SHAW: {shaw_exe} in {workdir} with {inp_file.name}")
    started = time.monotonic()
    try:
        result = subprocess.run(
            [str(shaw_exe)], input=stdin, capture_output=True,
            text=True, cwd=str(workdir), timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
        )
    except subprocess.TimeoutExpired:
        print(f"SHAW TIMED OUT after {timeout}s")
        return False
    except OSError as error:
        print(f"Cannot execute SHAW: {error}")
        return False
    (workdir / "shaw.stdout.log").write_text(result.stdout, encoding="utf-8")
    (workdir / "shaw.stderr.log").write_text(result.stderr, encoding="utf-8")
    fresh = all(path.is_file() and path.stat().st_size > 0 and _stamp(path) != before[path]
                for path in enabled)
    complete_profile = bool(profiles and fresh)
    for profile, frequency in profiles:
        try:
            rows = parse_profile_file(profile)
            expected = [start]
            cursor = datetime.fromisoformat(start) + timedelta(hours=hours_per_step)
            end_time = datetime.fromisoformat(end)
            while cursor <= end_time:
                if (cursor.hour or 24) % frequency == 0:
                    expected.append(cursor.isoformat())
                cursor += timedelta(hours=hours_per_step)
            complete_profile = complete_profile and (
                [row["datetime"] for row in rows] == expected and expected[-1] == end
                and all(len(row) - 4 == node_count for row in rows)
            )
        except (OSError, ValueError):
            complete_profile = False
    output = (result.stdout + result.stderr).lower()
    # A final stdin EOF can follow a completed Fortran run, but the mere presence
    # of old output files never establishes success or makes another error benign.
    final_input_eof = "end of file" in output or "end-of-file" in output
    completion_marker = "run complete" in output or "normal completion" in output
    acceptable_exit = result.returncode == 0 or (
        result.returncode in (2, 24) and complete_profile
        and completion_marker and final_input_eof
    )
    complete = complete_profile if profiles else bool(fresh and completion_marker)
    if not acceptable_exit or not complete:
        print(f"SHAW FAILED (return code {result.returncode}); no fresh complete result through {end}.")
        print((result.stderr or result.stdout)[-1200:])
        return False
    print(f"SHAW completed in {time.monotonic() - started:.1f}s; output reaches {end}")
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
    parser.add_argument("--sit_file", type=str, help="Site file (.sit)")
    parser.add_argument("--wea_file", type=str, help="Weather file (.wea)")
    parser.add_argument("--moi_file", type=str, help="Moisture profile (.moi)")
    parser.add_argument("--tem_file", type=str, help="Temperature profile (.tem)")
    parser.add_argument("--inp_file", help="Existing control file in workdir; preserves all model/output settings")
    parser.add_argument("--stage_from", help="Copy --inp_file and its referenced inputs unchanged from this directory into workdir")
    parser.add_argument("--shaw_exe", type=str, default=default_executable(),
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

    if args.stage_from and not args.inp_file:
        parser.error("--stage_from requires --inp_file")
    if args.inp_file and any((args.sit_file, args.wea_file, args.moi_file, args.tem_file)):
        parser.error("use --inp_file or the four input-file arguments, not both")
    if not args.inp_file and not all((args.sit_file, args.wea_file, args.moi_file, args.tem_file)):
        parser.error("provide --inp_file or all four of --sit_file, --wea_file, --moi_file and --tem_file")
    args.shaw_exe = str(resolve_executable(args.shaw_exe))
    workdir = Path(args.workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    if args.stage_from:
        try:
            stage_inputs(args.stage_from, args.inp_file, workdir)
        except (OSError, ValueError) as error:
            print(f"Cannot stage SHAW inputs: {error}")
            sys.exit(1)

    # Validate inputs
    if not validate_inputs(args, workdir):
        sys.exit(1)

    # Create .inp file
    inp_file = workdir / args.inp_file if args.inp_file else create_inp_file(args, workdir)

    # Run SHAW
    success = run_shaw(inp_file, args.shaw_exe, workdir, args.timeout)

    if success:
        check_outputs(workdir)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
