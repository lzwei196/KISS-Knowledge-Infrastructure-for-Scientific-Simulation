#!/usr/bin/env python3
"""
preprocess_geometry.py -- Run the real RasGeomPreprocess.exe under WINE to build
the geometry hydraulic-property tables a project needs before the solver runs.

The geometry preprocessor turns the surveyed cross sections (.gNN) into the
conveyance / area-vs-elevation tables stored in the geometry HDF (.gNN.hdf) and
the binary geometry file (.cNN). RasSteady then reads those tables.

In this headless environment most shipped steady examples ALREADY include a
.gNN.hdf (saved by the GUI), so run_hecras.py can seed the results skeleton
directly and you do NOT need this step. Use this tool when a project's geometry
has changed and the HDF must be rebuilt.

Caveat: RasGeomPreprocess is normally invoked by Ras.exe with extra run-control
files; standalone invocation may require those. The tool reports the solver's
stdout so you can see how far it progressed (see triplets.yaml
'geom_preprocess_incomplete').

Usage:
  python3 preprocess_geometry.py --project <dir> --prj MIXED --plan 01
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _hecras_env import run_solver, check_binary, TEMPLATE_PRJ


def preprocess(project, prj=TEMPLATE_PRJ, plan="01", timeout=300):
    check_binary("geom_preprocess")
    # the preprocessor typically takes the geometry/run base; try the run file
    arg = None
    for cand in (f"{prj}.c{plan}", f"{prj}.g{plan}", f"{prj}.r{plan}"):
        if os.path.isfile(os.path.join(project, cand)):
            arg = cand
            break
    if arg is None:
        raise FileNotFoundError(
            f"no .c{plan}/.g{plan}/.r{plan} in {project} to hand the preprocessor")
    before = set(glob.glob(os.path.join(project, "*.hdf")))
    result = run_solver("geom_preprocess", arg, project, timeout=timeout)
    after = set(glob.glob(os.path.join(project, "*.hdf")))
    new_hdf = sorted(after - before)
    return {"arg": arg, "returncode": result["returncode"],
            "new_hdf": new_hdf,
            "geom_hdf_present": os.path.isfile(os.path.join(project, f"{prj}.g{plan}.hdf")),
            "stdout_tail": result["stdout"][-600:]}


def validate_outputs(result, project, prj, plan):
    if result["geom_hdf_present"]:
        return True, f"geometry HDF present: {prj}.g{plan}.hdf"
    if result["new_hdf"]:
        return True, f"preprocessor produced: {result['new_hdf']}"
    return False, ("no geometry HDF produced; standalone preprocessing likely "
                   "needs Ras.exe orchestration -- use a project that ships a "
                   ".gNN.hdf (see triplets.yaml 'geom_preprocess_incomplete')")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--prj", default=TEMPLATE_PRJ)
    ap.add_argument("--plan", default="01")
    ap.add_argument("--timeout", type=int, default=300)
    a = ap.parse_args()
    res = preprocess(a.project, prj=a.prj, plan=a.plan, timeout=a.timeout)
    ok, msg = validate_outputs(res, a.project, a.prj, a.plan)
    res["validation"] = {"ok": ok, "detail": msg}
    print(json.dumps(res, indent=2))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
