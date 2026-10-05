#!/usr/bin/env python3
"""Run the official Delft3D-FLOW example 01_standard (F34) in a clean dir and check expected.json.

Foundation case for the Delft3D KI. Engine: d_hydro + libflow2d3d.so (Delft3D-FLOW 6.04),
the engine the KI preflight resolves. Exit 0 PASS, 2 checks failed, 3 engine missing.

inputs/ are the unmodified files. In the run copy only, one output keyword is appended to
f34.mdf: `FlNcdf = #maphis#`, so FLOW writes trih-f34.nc (NetCDF) instead of NEFIS only.
It changes the output file format, not the computation (tri-diag was compared: same run).
The history file is then read with the KI's own tools/parse_delft3d_output.py, and the
water levels (ZWL) are checked here directly.

d_hydro lookup: --d-hydro arg -> $D_HYDRO -> which d_hydro -> server default.
libflow2d3d.so is searched next to it (../flow2d3d) or via $FLOW2D3D_LIB_DIR.
"""
import argparse, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
PARSE_TOOL = HERE.parents[1] / "tools" / "parse_delft3d_output.py"
_DEF = "/home/server/knowledge-dissection-toolkit/auto_dissect/_work/Delft3D/build_flow2d3d/d_hydro/d_hydro"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--d-hydro")
    a = ap.parse_args()
    b = next((c for c in (a.d_hydro, os.environ.get("D_HYDRO"), shutil.which("d_hydro"), _DEF)
              if c and Path(c).is_file()), None)
    if not b:
        print("MISSING DEPENDENCY: d_hydro not found (set D_HYDRO). NOT run.", file=sys.stderr)
        return 3
    libdir = os.environ.get("FLOW2D3D_LIB_DIR") or str(Path(b).parent.parent / "flow2d3d")
    if not (Path(libdir) / "libflow2d3d.so").is_file():
        print(f"MISSING DEPENDENCY: libflow2d3d.so not in {libdir} (set FLOW2D3D_LIB_DIR). NOT run.",
              file=sys.stderr)
        return 3
    import netCDF4

    run = Path(tempfile.mkdtemp(prefix="d3d_f34_"))
    for f in (HERE / "inputs").iterdir():
        shutil.copy(f, run / f.name)
    with open(run / "f34.mdf", "a") as fh:
        fh.write("FlNcdf = #maphis#\n")
    env = dict(os.environ, LD_LIBRARY_PATH=libdir + ":" + os.environ.get("LD_LIBRARY_PATH", ""))
    cp = subprocess.run([b, "config_d_hydro.xml"], cwd=run, env=env,
                        capture_output=True, text=True, timeout=1800)
    fails = []
    diag = (run / "tri-diag.f34").read_text(errors="replace") if (run / "tri-diag.f34").is_file() else ""
    if cp.returncode != 0:
        fails.append(f"d_hydro exit code {cp.returncode}")
    if EXP["diag_contains"] not in diag:
        fails.append(f"'{EXP['diag_contains']}' not in tri-diag.f34")
    his = run / "trih-f34.nc"
    if not his.is_file():
        fails.append("trih-f34.nc not written")
    else:
        pt = subprocess.run([sys.executable, str(PARSE_TOOL), "--his_file", str(his),
                             "--output_csv", str(run / "his.csv")], capture_output=True, text=True)
        if pt.returncode != 0:
            fails.append(f"KI parse_delft3d_output.py failed: {pt.stderr[-300:]}")
        else:
            print("  KI parse_delft3d_output.py read the history file")
        d = netCDF4.Dataset(his)
        names = [b"".join(x).decode().strip() for x in d["NAMST"][:]]
        zwl = np.asarray(d["ZWL"][:])
        t_end = float(d["time"][-1])
        d.close()
        got = {"n_times": zwl.shape[0], "n_stations": zwl.shape[1], "t_end_s": t_end}
        for i, n in enumerate(names):
            got[f"{n}_max_wl"] = float(zwl[:, i].max())
            got[f"{n}_min_wl"] = float(zwl[:, i].min())
            got[f"{n}_last_wl"] = float(zwl[-1, i])
        for c in EXP["numeric_checks"]:
            v = got.get(c["name"])
            if v is None:
                fails.append(f"{c['name']}: not found")
            elif abs(v - c["expected"]) > c["tol"]:
                fails.append(f"{c['name']}: {v:.6g} vs {c['expected']}±{c['tol']}")
            else:
                print(f"  OK {c['name']}: {v:.6g}")
    shutil.rmtree(run, ignore_errors=True)
    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: Delft3D-FLOW F34 reproduced the expected results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
