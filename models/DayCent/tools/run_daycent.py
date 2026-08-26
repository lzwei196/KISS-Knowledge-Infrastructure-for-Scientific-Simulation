#!/usr/bin/env python3
"""
run_daycent.py — DayCent execution wrapper.

Implements the canonical 3-step DayCent run:
    1. equilibrium spin-up (uses ACEQ block in the schedule)
    2. base history extension (-e eq)
    3. treatment extension    (-e base)

Then optionally extracts a .lis text table via DDlist100.

This wrapper does NOT reimplement DayCent. It calls the actual
DDcentEVI_rev491 ELF binary, just like wooster_run_rev491_Linux.R does.

Usage:
    python run_daycent.py \
        --run-dir /path/to/Wooster \
        --eq-sched wooster_eq \
        --base-sched wooster_base \
        --treat-sched wooster_cb_nt_blk1 \
        --extract treat:few_outvars.txt
"""
import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_BIN_DIR = Path(
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect_multi_agent/"
    "_work_v2/DayCent/source/repo/Linux_Version_491"
)
DDCENT = "DDcentEVI_rev491"
DDLIST = "DDlist100_rev491"


def validate_run_dir(run_dir: Path, eq_sched: str):
    if not run_dir.is_dir():
        raise FileNotFoundError(f"run dir not found: {run_dir}")
    sch_file = run_dir / f"{eq_sched}.sch"
    if not sch_file.is_file():
        raise FileNotFoundError(f"schedule file missing: {sch_file}")
    with open(sch_file) as f:
        for i, line in enumerate(f):
            if i == 2:
                site_name = line.strip().split()[0]
                site_file = run_dir / site_name
                if not site_file.is_file():
                    raise FileNotFoundError(
                        f"schedule references {site_name} but it does not exist in {run_dir}"
                    )
                break
    if not (run_dir / "outfiles.in").is_file():
        raise FileNotFoundError(f"outfiles.in missing in {run_dir} (DayCent will refuse to start)")
    if not (run_dir / "sitepar.in").is_file():
        raise FileNotFoundError(f"sitepar.in missing in {run_dir}")
    if not (run_dir / "soils.in").is_file():
        raise FileNotFoundError(f"soils.in missing in {run_dir}")


def stage_binaries(run_dir: Path, bin_dir: Path):
    """Copy / symlink the DayCent binaries into the run dir if not present."""
    for name in (DDCENT, DDLIST):
        src = bin_dir / name
        dst = run_dir / name
        if not src.is_file():
            raise FileNotFoundError(f"DayCent binary missing: {src}")
        if not os.access(src, os.X_OK):
            try:
                os.chmod(src, 0o755)
            except PermissionError:
                raise PermissionError(f"DayCent binary not executable: {src}")
        if not dst.exists():
            try:
                os.symlink(src, dst)
            except OSError:
                shutil.copy2(src, dst)
        if not os.access(dst, os.X_OK):
            os.chmod(dst, 0o755)


def run_step(run_dir: Path, args, label: str, timeout=1800):
    """Execute one DDcentEVI invocation and capture output."""
    cmd = [f"./{DDCENT}"] + args
    t0 = time.time()
    print(f"\n=== {label} ===")
    print(f"  cmd: {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(run_dir),
                          capture_output=True, text=True, timeout=timeout)
    dt = time.time() - t0
    tail = (proc.stdout or "")[-500:]
    print(f"  rc={proc.returncode}  wall={dt:.1f}s")
    if proc.stderr:
        print(f"  stderr (last 200): {proc.stderr[-200:]}")
    print(f"  stdout (tail):\n{tail}")
    if proc.returncode != 0:
        raise RuntimeError(
            f"{label} failed (rc={proc.returncode}). "
            f"See diagnostics/triplets.yaml — common causes: missing schedule, "
            f"sitepar.in/soils.in path, or .wth precip in mm/day."
        )
    return proc


def run_extract(run_dir: Path, bin_root: str, out_prefix: str, var_file: str):
    """
    DDlist100 syntax (from `strings` on rev 491):
        list100 <.bin> <out.lis> [var|vfil] [date]
    DDlist100 uses out.lis verbatim, so we always pass {out_prefix}.lis.
    """
    out_name = f"{out_prefix}.lis"
    cmd = [f"./{DDLIST}", bin_root, out_name, var_file]
    print(f"\n=== extract: {' '.join(cmd)} ===")
    out_path = run_dir / out_name
    if out_path.exists():
        out_path.unlink()
    proc = subprocess.run(cmd, cwd=str(run_dir),
                          capture_output=True, text=True, timeout=300)
    print(f"  rc={proc.returncode}")
    if proc.returncode != 0:
        raise RuntimeError(f"DDlist100 failed: {proc.stderr[-300:]}")
    if not out_path.is_file():
        raise RuntimeError(f"expected {out_path} but it was not written")
    print(f"  wrote {out_path} ({out_path.stat().st_size} bytes)")
    return out_path


def validate_outputs(run_dir: Path, expected_bins):
    for b in expected_bins:
        p = run_dir / f"{b}.bin"
        if not p.is_file():
            raise RuntimeError(f"expected output binary {p} missing")
        if p.stat().st_size < 1000:
            raise RuntimeError(f"{p} is suspiciously small ({p.stat().st_size} bytes)")
        print(f"  OK  {p.name}  ({p.stat().st_size} bytes)")


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--run-dir", required=True, type=Path)
    p.add_argument("--bin-dir", default=DEFAULT_BIN_DIR, type=Path)
    p.add_argument("--eq-sched", required=True, help="root name (no .sch) of equilibrium schedule")
    p.add_argument("--base-sched", help="root name of base history schedule (optional)")
    p.add_argument("--treat-sched", help="root name of treatment schedule (optional)")
    p.add_argument("--no-outfiles-in", default="no_outfiles.in",
                   help="outfiles.in preset to use during equilibrium")
    p.add_argument("--full-outfiles-in", default="few_outfiles.in",
                   help="outfiles.in preset to use during the treatment run")
    p.add_argument("--extract", action="append", default=[],
                   help="EXTRACT specs of the form bin_root:varfile (eg treat:few_outvars.txt)")
    p.add_argument("--extract-prefix", default="run",
                   help="output .lis file prefix")
    args = p.parse_args(argv)

    run_dir = args.run_dir.resolve()
    validate_run_dir(run_dir, args.eq_sched)
    stage_binaries(run_dir, args.bin_dir.resolve())

    produced = []

    # Equilibrium
    if (run_dir / args.no_outfiles_in).is_file():
        shutil.copy2(run_dir / args.no_outfiles_in, run_dir / "outfiles.in")
    run_step(run_dir, ["-s", args.eq_sched, "-N", "eq"], label="equilibrium")
    produced.append("eq")

    # Base history
    if args.base_sched:
        run_step(run_dir,
                 ["-s", args.base_sched, "-e", "eq", "-N", "base"],
                 label="base_history")
        produced.append("base")

    # Treatment
    if args.treat_sched:
        if (run_dir / args.full_outfiles_in).is_file():
            shutil.copy2(run_dir / args.full_outfiles_in, run_dir / "outfiles.in")
        prev = "base" if args.base_sched else "eq"
        run_step(run_dir,
                 ["-s", args.treat_sched, "-e", prev, "-N", "treat"],
                 label="treatment")
        produced.append("treat")

    validate_outputs(run_dir, produced)

    # Extraction
    for spec in args.extract:
        if ":" not in spec:
            print(f"WARN: skipping malformed --extract '{spec}' (need bin_root:varfile)")
            continue
        bin_root, var_file = spec.split(":", 1)
        run_extract(run_dir, bin_root, args.extract_prefix, var_file)

    print("\nDayCent run completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
