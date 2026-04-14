#!/usr/bin/env python3
"""
EPIC0810 workspace setup, execution, and output collection.

Pattern: validate inputs -> copy template workspace -> sanitize SOL
         -> update EPICCONT/EPICRUN -> run binary -> validate outputs.

Critical fixes the EPIC0810 binary requires (vs. the EPIC1102 example bundle):
  1. The binary opens SOIL38K.DAT, not SOIL35K.DAT  -> we copy/alias 35K -> 38K
  2. SOL files contain alphabetic structure codes (A/B/C/D) that crash the
     stricter EPIC0810 Fortran reader -> we replace each alpha token with 0.00
     while preserving column widths
  3. EPICRUN.DAT must be plain "<site_id> NSIT NWP1 NWND NWP5 NSOL NOPS NDLY/"
"""

import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

EPIC_BINARY = "/home/server/knowledge-dissection-toolkit/auto_dissect_multi_agent/_work_v2/EPIC/source/repo/epic0810.x"
EXAMPLE_DIR = "/home/server/knowledge-dissection-toolkit/auto_dissect_multi_agent/_work_v2/EPIC/source/repo/epic1102_example_files_20221002"

REQUIRED_TEMPLATE_FILES = [
    "EPICCONT.DAT", "EPICFILE.DAT", "EPICRUN.DAT", "EPICERR.DAT", "AYEAR.DAT",
    "PARM1102.DAT", "MLRN1102.DAT", "PRNT1102.DAT", "CMOD1102.DAT",
    "CROPCOM.DAT", "TILLCOM.DAT", "PESTCOM.DAT", "FERT2012.DAT", "TR55COM.DAT",
    "SOIL35K.DAT", "WORKSPACE.DAT",
    "SITECOM.DAT", "SOILCOM.DAT", "OPSCCOM.DAT", "WDLSTCOM.DAT",
    "WPM1USEL.DAT", "WPM5US.DAT", "WINDUSEL.DAT", "WIDXCOM.DAT",
    "umstead.SIT", "umstead.SOL", "umstead.OPC",
    "NCRDU.DLY", "NCCLAYTO.WP1", "NCCLAYTO.WND",
]


def validate_template_dir(template_dir: str = EXAMPLE_DIR) -> list:
    """Confirm all template files exist before we try to copy them."""
    missing = []
    for f in REQUIRED_TEMPLATE_FILES:
        if not os.path.exists(os.path.join(template_dir, f)):
            missing.append(f)
    return missing


def sanitize_sol(sol_path: str) -> int:
    """
    Replace alphabetic structure tokens (e.g. 'A','B','C','D') in SOL data
    rows with numeric '0.00', preserving column width.

    Returns the number of lines that were modified.
    Skips the first non-numeric header line which is free text.
    """
    with open(sol_path, "r") as f:
        lines = f.readlines()

    n_changed = 0
    for i, line in enumerate(lines):
        if i == 0:
            continue  # header line is free text
        # Only act on lines that look like fixed-width numeric data with stray alpha tokens.
        # An alpha token = a run of letters surrounded by spaces.
        if re.search(r"(^|\s)[A-Za-z]+(\s|$)", line):
            new = re.sub(
                r"(^|\s)([A-Za-z]+)(?=\s|$)",
                lambda m: m.group(1) + ("0.00".rjust(len(m.group(2)))),
                line,
            )
            lines[i] = new
            n_changed += 1

    with open(sol_path, "w") as f:
        f.writelines(lines)
    return n_changed


def setup_workspace(workspace_dir: str, template_dir: str = EXAMPLE_DIR,
                    binary: str = EPIC_BINARY) -> str:
    """
    Build a clean EPIC workspace under workspace_dir.

    Steps:
      1. Validate template directory
      2. mkdir -p workspace_dir
      3. Copy every template file
      4. Copy the binary in
      5. Create SOIL38K.DAT alias of SOIL35K.DAT
      6. Sanitize every .SOL file in the workspace
    """
    missing = validate_template_dir(template_dir)
    if missing:
        raise FileNotFoundError(f"Template files missing in {template_dir}: {missing}")
    if not os.path.exists(binary):
        raise FileNotFoundError(f"EPIC binary not found at {binary}")

    os.makedirs(workspace_dir, exist_ok=True)

    for f in REQUIRED_TEMPLATE_FILES:
        shutil.copy2(os.path.join(template_dir, f), os.path.join(workspace_dir, f))

    bin_target = os.path.join(workspace_dir, "epic0810.x")
    shutil.copy2(binary, bin_target)
    os.chmod(bin_target, 0o755)

    # Create the SOIL38K.DAT alias the EPIC0810 binary expects
    src_35k = os.path.join(workspace_dir, "SOIL35K.DAT")
    dst_38k = os.path.join(workspace_dir, "SOIL38K.DAT")
    if os.path.exists(src_35k) and not os.path.exists(dst_38k):
        shutil.copy2(src_35k, dst_38k)

    # Sanitize every SOL file
    for sol in Path(workspace_dir).glob("*.SOL"):
        sanitize_sol(str(sol))

    return workspace_dir


def update_epiccont(workspace_dir: str, start_year: int = 1930,
                    start_month: int = 1, start_day: int = 1,
                    nbyr: int = 15) -> None:
    """
    Patch the first 16 columns of EPICCONT.DAT to set NBYR / IYR / IMO / IDA.
    Format: I4 I4 I4 I4 (4-wide right-aligned integers).
    Other fields on line 1 are left untouched.
    """
    path = os.path.join(workspace_dir, "EPICCONT.DAT")
    with open(path, "r") as f:
        lines = f.readlines()
    new_prefix = f"{nbyr:4d}{start_year:4d}{start_month:4d}{start_day:4d}"
    lines[0] = new_prefix + lines[0][16:]
    with open(path, "w") as f:
        f.writelines(lines)


def update_epicrun(workspace_dir: str, site_id: str = "umstead_0",
                   nsit: int = 2, nwp1: int = 0, nwnd: int = 0,
                   nwp5: int = 0, nsol: int = 3, nops: int = 3,
                   ndly: int = 2) -> None:
    """
    Write a single-run EPICRUN.DAT line.

    The 7 integers index the corresponding *COM.DAT / *USEL.DAT files:
      nsit -> SITECOM.DAT row
      nwp1 -> WPM1USEL.DAT row (0 = use default WXGEN station)
      nwnd -> WINDUSEL.DAT row
      nwp5 -> WPM5US.DAT row
      nsol -> SOILCOM.DAT row
      nops -> OPSCCOM.DAT row
      ndly -> WDLSTCOM.DAT row (which .DLY to use)
    """
    path = os.path.join(workspace_dir, "EPICRUN.DAT")
    line = (
        f"{site_id:>9s} "
        f"{nsit:3d} {nwp1:3d} {nwnd:3d} {nwp5:3d} "
        f"{nsol:3d} {nops:3d} {ndly:3d}/\n"
    )
    with open(path, "w") as f:
        f.write(line)


def run(workspace_dir: str, site_id: str = "umstead_0",
        timeout: int = 600) -> dict:
    """
    Execute epic0810.x in the workspace directory.

    Returns dict {status, return_code, stdout, stderr, outputs}.
    Status is one of: completed | timeout | error.
    """
    bin_path = os.path.join(workspace_dir, "epic0810.x")
    if not os.path.exists(bin_path):
        return {"status": "error", "message": f"Binary not found at {bin_path}"}
    os.chmod(bin_path, 0o755)

    try:
        proc = subprocess.run(
            [bin_path],
            cwd=workspace_dir,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        return {
            "status": "timeout",
            "message": f"epic0810 timed out after {timeout}s",
            "stdout": (e.stdout or b"").decode("utf-8", "replace")[-2000:],
            "stderr": (e.stderr or b"").decode("utf-8", "replace")[-2000:],
        }

    outputs = sorted([
        p.name for p in Path(workspace_dir).glob(f"{site_id}.*")
        if p.is_file() and p.stat().st_size > 0
    ])

    return {
        "status": "completed" if proc.returncode == 0 else "error",
        "return_code": proc.returncode,
        "stdout": proc.stdout.decode("utf-8", "replace")[-2000:],
        "stderr": proc.stderr.decode("utf-8", "replace")[-2000:],
        "outputs": outputs,
    }


def collect_outputs(workspace_dir: str, output_dir: str,
                    site_id: str = "umstead_0") -> list:
    """Copy non-empty <site_id>.* output files into output_dir."""
    os.makedirs(output_dir, exist_ok=True)
    collected = []
    for p in Path(workspace_dir).glob(f"{site_id}.*"):
        if p.is_file() and p.stat().st_size > 0:
            dst = os.path.join(output_dir, p.name)
            shutil.copy2(p, dst)
            collected.append(dst)
    return collected


def validate_outputs(workspace_dir: str, site_id: str = "umstead_0") -> list:
    """Sanity-check the OUT file is non-trivial."""
    errors = []
    out_path = os.path.join(workspace_dir, f"{site_id}.OUT")
    if not os.path.exists(out_path):
        errors.append(f"ERROR: {site_id}.OUT not produced")
        return errors
    if os.path.getsize(out_path) < 1000:
        errors.append(f"WARNING: {site_id}.OUT only {os.path.getsize(out_path)} bytes")
    with open(out_path) as f:
        content = f.read(8192)
    if "EPIC0810" not in content:
        errors.append("WARNING: OUT file header does not contain EPIC0810")
    return errors


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--workspace", default="/tmp/epic_run")
    p.add_argument("--site-id", default="umstead_0")
    p.add_argument("--start-year", type=int, default=1930)
    p.add_argument("--nbyr", type=int, default=15)
    p.add_argument("--timeout", type=int, default=600)
    args = p.parse_args()

    setup_workspace(args.workspace)
    update_epiccont(args.workspace, start_year=args.start_year, nbyr=args.nbyr)
    update_epicrun(args.workspace, site_id=args.site_id)

    result = run(args.workspace, site_id=args.site_id, timeout=args.timeout)
    print(f"status: {result['status']}  rc: {result.get('return_code')}")
    print(f"outputs: {result.get('outputs', [])[:10]}")
    for e in validate_outputs(args.workspace, args.site_id):
        print(e)


if __name__ == "__main__":
    main()
