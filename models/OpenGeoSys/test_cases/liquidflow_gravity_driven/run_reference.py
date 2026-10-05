#!/usr/bin/env python3
"""Run the official OpenGeoSys benchmark LiquidFlow/GravityDriven and check expected.json.

Foundation case for the OpenGeoSys KI. The run goes through the KI's own tools/run_ogs.py,
the output is read with the KI's tools/parse_ogs_output.py (pressure stats) and with meshio
(point-by-point error). The pass test is the OFFICIAL one from the OGS ctest suite
(ProcessLib/LiquidFlow/Tests.cmake, test LiquidFlow_GravityDriven): vtkdiff of the output
against the analytic fields stored in mesh2D.vtu, abs and rel tolerance 1e-8.
Exit 0 PASS, 2 checks failed, 3 engine/dependency missing.

ogs lookup:     --ogs-bin     -> $OGS_BIN     -> which ogs     -> server default.
vtkdiff lookup: --vtkdiff-bin -> $VTKDIFF_BIN -> which vtkdiff -> next to ogs -> server default.
"""
import argparse, csv, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
TOOLS = HERE.parents[1] / "tools"
RUN_TOOL = TOOLS / "run_ogs.py"
PARSE_TOOL = TOOLS / "parse_ogs_output.py"
_VENV = "/home/server/knowledge-dissection-toolkit/auto_dissect/_work/OpenGeoSys/venv/bin"
INPUTS = ("gravity_driven.prj", "gravity_driven.gml", "mesh2D.vtu")
OUT_VTU = "gravity_driven_ts_1_t_1.000000.vtu"
# official DIFF_DATA lines: reference file, output file, field a, field b, abs tol, rel tol
DIFF_DATA = [("mesh2D.vtu", OUT_VTU, "AnalyticPressure", "pressure", "1e-8", "1e-8"),
             ("mesh2D.vtu", OUT_VTU, "v_ref", "v", "1e-8", "1e-8")]


def find_bin(arg, env, name, extra=()):
    for c in (arg, os.environ.get(env), shutil.which(name), *extra):
        if c and Path(c).is_file() and os.access(c, os.X_OK):
            return c
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ogs-bin")
    ap.add_argument("--vtkdiff-bin")
    a = ap.parse_args()
    ogs = find_bin(a.ogs_bin, "OGS_BIN", "ogs", (f"{_VENV}/ogs",))
    if not ogs:
        print("MISSING DEPENDENCY: ogs binary not found (set OGS_BIN). NOT run.", file=sys.stderr)
        return 3
    vtkdiff = find_bin(a.vtkdiff_bin, "VTKDIFF_BIN", "vtkdiff",
                       (str(Path(ogs).parent / "vtkdiff"), f"{_VENV}/vtkdiff"))
    if not vtkdiff:
        print("MISSING DEPENDENCY: vtkdiff not found (set VTKDIFF_BIN). NOT run.", file=sys.stderr)
        return 3
    try:
        import numpy as np
        import meshio
    except ImportError as ex:
        print(f"MISSING DEPENDENCY: python package {ex.name}. NOT run.", file=sys.stderr)
        return 3

    run = Path(tempfile.mkdtemp(prefix="ogs_gravity_driven_"))
    for f in INPUTS:
        shutil.copy(HERE / "inputs" / f, run / f)
    out = run / "out"
    env = dict(os.environ, OMP_NUM_THREADS=os.environ.get("OMP_NUM_THREADS", "1"))
    fails, got = [], {}
    try:
        cp = subprocess.run([sys.executable, str(RUN_TOOL), "--prj", str(run / "gravity_driven.prj"),
                             "--ogs_binary", ogs, "--output_dir", str(out), "--timeout", "600"],
                            capture_output=True, text=True, timeout=900, cwd=run, env=env)
        try:
            summ = json.loads(cp.stdout)
        except ValueError:
            summ = {}
        print(f"  ran {ogs} through KI tools/run_ogs.py: status={summ.get('status')} "
              f"rc={summ.get('return_code')}")
        if summ.get("status") != "success":
            fails.append(f"run_ogs.py did not report success (rc={cp.returncode}): "
                         f"{cp.stdout[-400:]} {cp.stderr[-400:]}")
        got["ogs_return_code"] = summ.get("return_code")
        got["n_output_vtu"] = summ.get("n_vtu_files")
        ts = summ.get("timesteps") or []
        got["final_time_s"] = max((t["time_s"] for t in ts), default=None)

        # official ctest check: vtkdiff with the official tolerances
        for ref, res, fa, fb, at, rt in DIFF_DATA:
            v = subprocess.run([vtkdiff, str(run / ref), str(out / res), "-a", fa, "-b", fb,
                                "--abs", at, "--rel", rt], capture_output=True, text=True,
                               timeout=120, cwd=run)
            got[f"vtkdiff_{fb}_vs_{fa}_rc"] = v.returncode

        # KI parse tool: spatial stats of pressure (last row = t_end)
        csv_path = run / "stats.csv"
        subprocess.run([sys.executable, str(PARSE_TOOL), "--pvd_file", str(out / "gravity_driven.pvd"),
                        "--variables", "pressure", "--stats", "--output", str(csv_path)],
                       capture_output=True, text=True, timeout=300, cwd=run)
        rows = list(csv.DictReader(open(csv_path)))
        last = rows[-1]
        got.update(pressure_min=float(last["pressure_min"]), pressure_max=float(last["pressure_max"]),
                   pressure_mean=float(last["pressure_mean"]))

        # point-by-point max error against the official analytic fields
        refm, resm = meshio.read(run / "mesh2D.vtu"), meshio.read(out / OUT_VTU)
        got["n_points"] = len(resm.points)
        got["pressure_max_abs_error_vs_analytic"] = float(np.abs(
            resm.point_data["pressure"] - refm.point_data["AnalyticPressure"]).max())
        got["v_max_abs_error_vs_v_ref"] = float(np.abs(
            resm.point_data["v"] - refm.point_data["v_ref"]).max())
    except Exception as ex:
        fails.append(f"could not run or read outputs: {ex!r}")
    finally:
        shutil.rmtree(run, ignore_errors=True)

    for c in EXP["numeric_checks"]:
        v = got.get(c["name"])
        if v is None:
            fails.append(f"{c['name']}: not computed")
        elif abs(v - c["expected"]) > c["tol"]:
            fails.append(f"{c['name']}: {v:.12g} vs {c['expected']}+-{c['tol']}")
        else:
            print(f"  OK {c['name']}: {v:.12g}")
    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: OpenGeoSys LiquidFlow GravityDriven matches the official analytic solution "
          "(vtkdiff, abs/rel tol 1e-8).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
