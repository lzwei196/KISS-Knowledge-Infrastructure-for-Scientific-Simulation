#!/usr/bin/env python3
"""Execute EPIC 1102 on a prepared workspace (copy-first wrapper).

Copies templates + user files into an isolated workspace, runs the Windows
PE32 binary via Wine from inside the workspace, collects outputs.
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import TEMPLATES_DIR, DEFAULT_BINARY


def _stage_templates(workspace):
    os.makedirs(workspace, exist_ok=True)
    for fn in os.listdir(TEMPLATES_DIR):
        src = os.path.join(TEMPLATES_DIR, fn)
        dst = os.path.join(workspace, fn)
        if os.path.isfile(src) and not os.path.isfile(dst):
            shutil.copy2(src, dst)


def _stage_user_files(workspace, input_dir):
    if not input_dir:
        return
    for pat in ("*.SIT", "*.SOL", "*.OPC", "*.DLY", "*.WP1", "*.WND",
                "EPICRUN.DAT", "EPICCONT.DAT",
                "SITECOM.DAT", "SOILCOM.DAT", "OPSCCOM.DAT",
                "WPM1USEL.DAT", "WINDUSEL.DAT", "WDLSTCOM.DAT"):
        for src in glob.glob(os.path.join(input_dir, pat)):
            dst = os.path.join(workspace, os.path.basename(src))
            shutil.copy2(src, dst)


def _stage_binary(workspace, binary_path):
    if not os.path.isfile(binary_path):
        raise FileNotFoundError(f"EPIC binary not found: {binary_path}")
    dst = os.path.join(workspace, os.path.basename(binary_path))
    if not os.path.isfile(dst):
        shutil.copy2(binary_path, dst)
    return dst


def run(workspace, run_name, output_dir, binary_path=None, input_dir=None,
        timeout=1800):
    binary_path = binary_path or DEFAULT_BINARY
    workspace = os.path.abspath(workspace)
    output_dir = os.path.abspath(output_dir)
    os.makedirs(workspace, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    _stage_templates(workspace)
    _stage_user_files(workspace, input_dir)
    exe_in_ws = _stage_binary(workspace, binary_path)

    cmd = ["wine", exe_in_ws]
    print(f"  running: cd {workspace} && wine {os.path.basename(exe_in_ws)}")
    proc = subprocess.run(
        cmd, cwd=workspace, timeout=timeout,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    stdout = proc.stdout.decode("ascii", errors="replace")
    stderr = proc.stderr.decode("ascii", errors="replace")
    # Wine wraps EPIC's Fortran exit code; 38 = normal EPIC completion on this host
    if proc.returncode not in (0, 38):
        print("  EPIC stdout (last 30 lines):", file=sys.stderr)
        for ln in stdout.splitlines()[-30:]:
            print("    " + ln, file=sys.stderr)
        print("  EPIC stderr (last 30 lines):", file=sys.stderr)
        for ln in stderr.splitlines()[-30:]:
            print("    " + ln, file=sys.stderr)
        raise RuntimeError(
            f"EPIC exited with status {proc.returncode}. See diagnostics/triplets.yaml."
        )

    collected = []
    for fn in os.listdir(workspace):
        if fn.startswith(run_name) and not fn.endswith(".DAT"):
            shutil.copy2(os.path.join(workspace, fn),
                         os.path.join(output_dir, fn))
            collected.append(fn)
    if not collected:
        for fn in os.listdir(workspace):
            ext = os.path.splitext(fn)[1].upper()
            if ext in (".OUT", ".ACY", ".ANN", ".DGN", ".DWC", ".DCN",
                       ".DSL", ".DNC", ".DHS", ".DGZ", ".DWT", ".ACN",
                       ".ACO", ".ASL", ".SCN", ".SOT", ".APS", ".ABR",
                       ".MFS"):
                shutil.copy2(os.path.join(workspace, fn),
                             os.path.join(output_dir, fn))
                collected.append(fn)
    print(f"  collected {len(collected)} output files into {output_dir}")
    return collected


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--run-name", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--binary", default=DEFAULT_BINARY)
    ap.add_argument("--input-dir")
    ap.add_argument("--timeout", type=int, default=1800)
    args = ap.parse_args()

    try:
        run(args.workspace, args.run_name, args.output_dir,
            binary_path=args.binary, input_dir=args.input_dir,
            timeout=args.timeout)
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
