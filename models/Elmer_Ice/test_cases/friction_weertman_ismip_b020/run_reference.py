#!/usr/bin/env python3
"""Run the official Elmer/Ice test Friction_Weertman in a clean dir and check expected.json.

Foundation case for the Elmer_Ice KI. Official test elmerice/Tests/Friction_Weertman
(ISMIP-HOM B020 set-up: 2D full-Stokes flow over a sine bed, Weertman sliding law).
Steps, as in the official runTest.cmake:
  1. ElmerGrid 1 2 rectangle.grd        (build the mesh; run directly, KI has no mesh tool)
  2. ElmerSolver ismip_weertman.sif     (run through the KI tool tools/run_elmerice.py)
The .sif carries the official "Solver 3 :: Reference Norm = 56.70374"; ElmerSolver
compares itself against it and writes TEST.PASSED.

Exit 0 PASS, 2 checks failed, 3 engine/dependency missing.

Binary lookup (each): --elmersolver-bin / --elmergrid-bin -> $ELMERSOLVER_BIN /
$ELMERGRID_BIN -> `which` -> server default (install_ice build, which has the
Elmer/Ice libraries ElmerIceSolvers.so and ElmerIceUSF.so).
"""
import argparse, json, os, re, shutil, struct, subprocess, sys, tempfile
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
RUN_TOOL = HERE.parents[1] / "tools" / "run_elmerice.py"
_DEF_DIR = "/home/server/knowledge-dissection-toolkit/auto_dissect/_work/Elmer_Ice/install_ice/bin"
INPUTS = ("ismip_weertman.sif", "rectangle.grd", "ELMERSOLVER_STARTINFO")
SIF = "ismip_weertman.sif"


def find_bin(arg, env, name):
    for c in (arg, os.environ.get(env), shutil.which(name), os.path.join(_DEF_DIR, name)):
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def read_vtu(fp):
    """Read Elmer's default VTU (appended raw, 4-byte block headers) -> (npts, ncells, arrays)."""
    raw = Path(fp).read_bytes()
    head, _, rest = raw.partition(b"<AppendedData encoding=\"raw\">")
    data = rest[rest.index(b"_") + 1:]
    txt = head.decode("latin-1")
    npts = int(re.search(r'NumberOfPoints="(\d+)"', txt).group(1))
    ncel = int(re.search(r'NumberOfCells="(\d+)"', txt).group(1))
    arrs = {}
    pd = txt[txt.index("<PointData>"):txt.index("</PointData>")]
    for m in re.finditer(r'type="Float64" Name="([^"]+)" NumberOfComponents="(\d+)"'
                         r' format="appended" offset="(\d+)"', pd):
        name, nc, off = m.group(1), int(m.group(2)), int(m.group(3))
        nbytes = struct.unpack("<I", data[off:off + 4])[0]
        a = np.frombuffer(data[off + 4:off + 4 + nbytes], dtype="<f8")
        arrs[name] = a.reshape(npts, nc) if nc > 1 else a
    pts = re.search(r'<Points>\s*<DataArray type="Float64" NumberOfComponents="3"'
                    r' format="appended" offset="(\d+)"', txt)
    off = int(pts.group(1))
    nbytes = struct.unpack("<I", data[off:off + 4])[0]
    arrs["_points"] = np.frombuffer(data[off + 4:off + 4 + nbytes], dtype="<f8").reshape(npts, 3)
    return npts, ncel, arrs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--elmersolver-bin")
    ap.add_argument("--elmergrid-bin")
    ap.add_argument("--keep", action="store_true", help="keep the temp run dir")
    a = ap.parse_args()
    solver = find_bin(a.elmersolver_bin, "ELMERSOLVER_BIN", "ElmerSolver")
    grid = find_bin(a.elmergrid_bin, "ELMERGRID_BIN", "ElmerGrid")
    if not solver or not grid:
        print("MISSING DEPENDENCY: ElmerSolver/ElmerGrid (built with Elmer/Ice) not found "
              "(set ELMERSOLVER_BIN / ELMERGRID_BIN). NOT run.", file=sys.stderr)
        return 3

    env = dict(os.environ, OMP_NUM_THREADS="4")
    run = Path(tempfile.mkdtemp(prefix="elmerice_weertman_"))
    for f in INPUTS:
        shutil.copy(HERE / "inputs" / f, run / f)
    fails, got = [], {}
    try:
        cp = subprocess.run([grid, "1", "2", "rectangle.grd"], cwd=run, env=env,
                            capture_output=True, text=True, timeout=300)
        if cp.returncode != 0 or not (run / "rectangle" / "mesh.header").is_file():
            fails.append(f"ElmerGrid failed (rc={cp.returncode}): {cp.stdout[-300:]}")
            raise RuntimeError
        print("  ran ElmerGrid 1 2 rectangle.grd")
        cp = subprocess.run([sys.executable, str(RUN_TOOL), "--sif", SIF, "--run_dir", str(run),
                             "--solver_binary", solver, "--timeout", "900"],
                            env=env, capture_output=True, text=True, timeout=1000)
        lines = cp.stderr.splitlines()
        status = json.loads("\n".join(lines[lines.index("{"):]))
        out = status["stdout_last_20"]
        if "ElmerIce" in status["stderr_last_10"] and "cannot open shared object" in status["stderr_last_10"]:
            print(f"MISSING DEPENDENCY: {solver} cannot load the Elmer/Ice libraries "
                  "(ElmerIceSolvers/ElmerIceUSF); use an ElmerSolver built with Elmer/Ice. NOT run.",
                  file=sys.stderr)
            return 3
        print(f"  ran ElmerSolver {SIF} via tools/run_elmerice.py (rc={cp.returncode})")

        tp = run / "TEST.PASSED"
        got["solver_returncode"] = status["returncode"]
        got["all_done_line"] = int("*** Elmer Solver: ALL DONE ***" in out)
        got["reference_compare_passed"] = int(
            "PASSED all 1 tests" in out and tp.is_file() and tp.read_text().strip() == "1")
        m = re.search(r"CompareToReferenceSolution: Solver 3 PASSED:\s+Norm =\s*(\S+)", out) or \
            re.search(r"CompareToReferenceSolution: Solver 3 FAILED:\s+Norm =\s*(\S+)", out)
        got["ns_final_norm"] = float(m.group(1)) if m else float("nan")
        its = re.findall(r"ComputeChange: NS \(ITER=(\d+)\)", out)
        got["ns_nonlinear_iterations"] = int(its[-1]) if its else -1

        npts, ncel, A = read_vtu(run / "rectangle" / "ismip_weertman_t0001.vtu")
        vel, p, xy = A["velocity"], A["pressure"], A["_points"]
        speed = np.hypot(vel[:, 0], vel[:, 1])
        x = xy[:, 0]
        top = np.isclose(xy[:, 1], -x * np.tan(0.5 * np.pi / 180.0), atol=1e-3)
        bed = np.isclose(xy[:, 1], -x * np.tan(0.5 * np.pi / 180.0) - 1000.0
                         + 500.0 * np.sin(2 * np.pi * x / 20.0e3), atol=1e-3)
        got.update({
            "n_nodes": npts, "n_cells": ncel,
            "n_surface_nodes": int(top.sum()), "n_bed_nodes": int(bed.sum()),
            "max_speed": float(speed.max()),
            "mean_surface_vx": float(vel[top, 0].mean()),
            "max_surface_vx": float(vel[top, 0].max()),
            "mean_bed_speed": float(speed[bed].mean()),
            "max_pressure": float(p.max()),
            "mean_pressure": float(p.mean()),
        })
        for c in EXP["numeric_checks"]:
            v = got[c["name"]]
            if not abs(v - c["expected"]) <= c["tol"]:
                fails.append(f"{c['name']}: {v:.9g} vs {c['expected']} +/- {c['tol']}")
            else:
                print(f"  OK {c['name']}: {v:.9g}")
    except RuntimeError:
        pass
    finally:
        if a.keep:
            print(f"  run dir kept: {run}")
        else:
            shutil.rmtree(run, ignore_errors=True)

    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: Elmer/Ice Friction_Weertman (ISMIP-HOM B020) matched the official reference norm "
          "and the expected results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
