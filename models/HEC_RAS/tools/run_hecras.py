#!/usr/bin/env python3
"""
run_hecras.py -- Execution wrapper for the REAL HEC-RAS steady-flow solver.

Drives the actual Intel-Fortran ``RasSteady.exe`` (HEC-RAS 6.7 Beta 5) under
WINE. NO physics is approximated here -- this calls the binary.

Architecture (copy-first; see docs/input_preparation.md):
  1. COPY a working project (template or user-supplied) into a temp workspace.
  2. (optional) swap in user-edited geometry / flow / run files.
  3. SEED the plan results skeleton  <prj>.pNN.tmp.hdf  from  <prj>.gNN.hdf
     (the step Ras.exe/Wine-Mono would normally do).
  4. RUN  wine RasSteady.exe <prj>.rNN   from the workspace.
  5. COLLECT the populated <prj>.pNN.tmp.hdf + <prj>.ONN into output_dir.

Usage:
  python3 run_hecras.py --project <dir> --prj MIXED --plan 01 --out <dir>
  python3 run_hecras.py --out <dir>          # runs the bundled template

Returns (and prints) a JSON status dict.
"""
import argparse
import glob
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _hecras_env import (TEMPLATE_DIR, TEMPLATE_PRJ, run_solver, seed_plan_hdf)


def _find_run_file(workspace, prj, plan):
    cand = os.path.join(workspace, f"{prj}.r{plan}")
    if os.path.isfile(cand):
        return f"{prj}.r{plan}"
    runs = sorted(glob.glob(os.path.join(workspace, f"{prj}.r[0-9][0-9]")))
    if runs:
        return os.path.basename(runs[0])
    raise FileNotFoundError(
        f"No steady run file {prj}.r{plan} in {workspace}. A steady run file is "
        "required (it is the flattened input the Fortran solver reads). It ships "
        "with every example project; for a brand-new project it must be written "
        "by the HEC-RAS GUI / ras-commander. See triplets.yaml 'missing_run_file'.")


def run(project=None, prj=TEMPLATE_PRJ, plan="01", output_dir=".",
        forcing_files=None, timeout=600):
    """Run the real HEC-RAS steady solver and collect results.

    Parameters
    ----------
    project : str or None   path to a HEC-RAS project dir; None -> bundled template
    prj : str               project base name (e.g. "MIXED")
    plan : str              two-digit plan number (e.g. "01")
    output_dir : str        where to copy results
    forcing_files : dict    optional {basename: src_path} files to swap into the
                            workspace before running (e.g. an edited .r01/.g01/.f01)
    """
    src = project or TEMPLATE_DIR
    if not os.path.isdir(src):
        raise FileNotFoundError(f"project dir not found: {src}")
    os.makedirs(output_dir, exist_ok=True)

    workspace = tempfile.mkdtemp(prefix="hecras_")
    try:
        # 1. copy the whole project
        for f in os.listdir(src):
            s = os.path.join(src, f)
            if os.path.isfile(s):
                shutil.copy2(s, os.path.join(workspace, f))

        # 2. swap in user files (copy-first: replace, never regenerate)
        for name, path in (forcing_files or {}).items():
            shutil.copy2(path, os.path.join(workspace, name))

        # remove any stale results so we never report a previous run's output
        for stale in glob.glob(os.path.join(workspace, f"{prj}.p*.tmp.hdf")):
            os.remove(stale)
        for stale in glob.glob(os.path.join(workspace, f"{prj}.O[0-9][0-9]")):
            try:
                os.remove(stale)
            except OSError:
                pass

        run_file = _find_run_file(workspace, prj, plan)

        # 3. seed the plan results skeleton
        seed_plan_hdf(workspace, prj=prj, plan=plan)

        # 4. run the real solver
        result = run_solver("steady", run_file, workspace, timeout=timeout)

        # 5. collect outputs
        produced = []
        result_hdf = os.path.join(workspace, f"{prj}.p{plan}.tmp.hdf")
        for pattern in (f"{prj}.p{plan}.tmp.hdf", f"{prj}.O{plan}", f"{prj}.r{plan}"):
            p = os.path.join(workspace, pattern)
            if os.path.isfile(p):
                dest = os.path.join(output_dir, os.path.basename(p))
                shutil.copy2(p, dest)
                produced.append(dest)

        ok = result["finished"] and os.path.isfile(result_hdf) and \
            os.path.getsize(result_hdf) > 60000  # populated, not just the seed
        status = {
            "ok": bool(ok),
            "finished": result["finished"],
            "returncode": result["returncode"],
            "cmd": result["cmd"],
            "run_file": run_file,
            "result_hdf": os.path.join(output_dir, f"{prj}.p{plan}.tmp.hdf"),
            "outputs": produced,
            "stdout_tail": result["stdout"][-800:],
        }
        return status
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def validate_outputs(status):
    """Physical-plausibility gate on the produced results HDF."""
    if not status.get("ok"):
        return False, "solver did not finish or produced an empty results HDF"
    try:
        import h5py
        import numpy as np
        from _hecras_env import STEADY_XS
        with h5py.File(status["result_hdf"], "r") as f:
            ws = f[STEADY_XS + "Water Surface"][:]
            q = f[STEADY_XS + "Flow"][:]
        if not np.all(np.isfinite(ws)):
            return False, "non-finite water surface values"
        if np.any(q < 0):
            return False, "negative discharge"
        return True, f"WS range {ws.min():.2f}..{ws.max():.2f}, {ws.shape[0]} profiles x {ws.shape[1]} XS"
    except Exception as e:  # noqa
        return False, f"could not read results HDF: {e}"


def main():
    ap = argparse.ArgumentParser(description="Run the real HEC-RAS steady solver under WINE.")
    ap.add_argument("--project", default=None, help="HEC-RAS project dir (default: bundled template)")
    ap.add_argument("--prj", default=TEMPLATE_PRJ, help="project base name (e.g. MIXED)")
    ap.add_argument("--plan", default="01")
    ap.add_argument("--out", default="./hecras_out")
    ap.add_argument("--timeout", type=int, default=600)
    a = ap.parse_args()
    status = run(project=a.project, prj=a.prj, plan=a.plan,
                 output_dir=a.out, timeout=a.timeout)
    ok, msg = validate_outputs(status)
    status["validation"] = {"physical_plausibility": ok, "detail": msg}
    print(json.dumps(status, indent=2))
    sys.exit(0 if status["ok"] else 1)


if __name__ == "__main__":
    main()
