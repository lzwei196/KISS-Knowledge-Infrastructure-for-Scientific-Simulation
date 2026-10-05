#!/usr/bin/env python3
"""Run ISSM's official NightlyRun test101 in a clean temp dir and check expected.json.

Foundation case for the ISSM KI. Two runs, both in a fresh temp dir:
  A) the unmodified official test101.py (square ice shelf, SSA stress balance, 2 MPI ranks),
     compared field by field against the official Archive101.arch with the official
     tolerances and the same error formula as ISSM's test/NightlyRun/runme.py;
  B) the same case driven by the KI's own tools/run_issm.py (custom mode: domain .exp +
     par file + SSA + Stressbalance), its velocity max/mean checked against Archive101 Vel.
Exit 0 PASS, 2 checks failed, 3 engine/dependency missing.

Engine lookup: --issm-bin -> $ISSM_BIN -> `which issm.exe` -> server default.
ISSM_DIR is taken as the parent of the bin/ folder that holds issm.exe; the ISSM Python
API (bin/*.py, lib/*_python.so) must be built there. mpiexec is taken from
$ISSM_DIR/externalpackages/petsc/install/bin (the MPI issm.exe is linked against) when
present, else from PATH.
"""
import argparse, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
RUN_TOOL = HERE.parents[1] / "tools" / "run_issm.py"
_DEF_BIN = "/home/server/knowledge-dissection-toolkit/auto_dissect/_work/ISSM/source/repo/bin/issm.exe"
_DEF_PY = "/mnt/disk1/Hydrocraft_server/python_env/bin/python"

# Runs test101.py the way runme.py does, then applies runme.py's archive check.
DRIVER = r'''
import json, sys
from sys import float_info
import numpy as np
from arch import archread
ns = {"__name__": "__main__"}
exec(compile(open("test101.py").read(), "test101.py", "exec"), ns)
md = ns["md"]
assert hasattr(md.results, "StressbalanceSolution"), "no StressbalanceSolution in md.results"
out = {"nvert": int(md.mesh.numberofvertices), "nelem": int(md.mesh.numberofelements),
       "name": md.miscellaneous.name, "fields": {}}
arch = "../Archives/Archive101.arch"
for k, (fname, tol, val) in enumerate(zip(ns["field_names"], ns["field_tolerances"], ns["field_values"])):
    field = np.array(val)
    if field.ndim == 1:
        field = field.reshape(np.size(field), 1) if np.size(field) else field.reshape(0, 0)
    archive = np.array(archread(arch, "Archive101_field" + str(k + 1)))
    if np.shape(field) != np.shape(archive) and np.shape(field) not in [(1, 1), (0, 0), (1, 0), (0, 1)]:
        field = field.T
    err = np.amax(np.abs(archive - field), axis=0) / (np.amax(np.abs(archive), axis=0) + float_info.epsilon)
    if not np.isscalar(err):
        err = err[0]
    out["fields"][fname] = {"rel_diff": float(err), "official_tol": float(tol),
                            "max": float(np.max(field)), "min": float(np.min(field)),
                            "mean": float(np.mean(field))}
json.dump(out, open("driver_result.json", "w"), indent=2)
print("DRIVER_DONE")
'''


def find_bin(arg):
    for c in (arg, os.environ.get("ISSM_BIN"), shutil.which("issm.exe"), _DEF_BIN):
        if c and Path(c).is_file():
            return Path(c).resolve()
    return None


def issm_env(issm_dir):
    env = os.environ.copy()
    env["ISSM_DIR"] = str(issm_dir)
    env["OMP_NUM_THREADS"] = "4"
    petsc = issm_dir / "externalpackages" / "petsc" / "install"
    env["PATH"] = ":".join([str(petsc / "bin"), str(issm_dir / "bin"), env.get("PATH", "")])
    env["PYTHONPATH"] = ":".join([str(issm_dir / "bin"), str(issm_dir / "lib"), env.get("PYTHONPATH", "")])
    env["LD_LIBRARY_PATH"] = ":".join([str(issm_dir / "lib"), str(petsc / "lib"),
                                       str(issm_dir / "externalpackages" / "triangle" / "install" / "lib"),
                                       env.get("LD_LIBRARY_PATH", "")])
    return env


def settings_file(folder, execpath):
    # ISSM's own user hook for the generic cluster: only moves the run files to the temp dir.
    (folder / "generic_settings.py").write_text(
        "def generic_settings(c):\n    c.executionpath = %r\n    return c\n" % str(execpath))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--issm-bin")
    ap.add_argument("--python", default=None, help="python with numpy/scipy (default HydroCraft python_env)")
    a = ap.parse_args()
    exe = find_bin(a.issm_bin)
    if not exe:
        print("MISSING DEPENDENCY: issm.exe not found (use --issm-bin or $ISSM_BIN). NOT run.", file=sys.stderr)
        return 3
    issm_dir = exe.parent.parent
    for need in ("bin/model.py", "bin/triangle.py", "bin/arch.py"):
        if not (issm_dir / need).is_file():
            print(f"MISSING DEPENDENCY: ISSM Python API file {issm_dir / need}. NOT run.", file=sys.stderr)
            return 3
    py = a.python or (_DEF_PY if Path(_DEF_PY).is_file() else sys.executable)
    env = issm_env(issm_dir)
    if not shutil.which("mpiexec", path=env["PATH"]):
        print("MISSING DEPENDENCY: mpiexec not found. NOT run.", file=sys.stderr)
        return 3
    chk = subprocess.run([py, "-c", "import numpy, scipy; from model import model; from triangle import triangle"],
                         env=env, capture_output=True, text=True)
    if chk.returncode != 0:
        print("MISSING DEPENDENCY: ISSM Python API does not import: " + chk.stderr[-400:] + " NOT run.", file=sys.stderr)
        return 3

    run = Path(tempfile.mkdtemp(prefix="issm_test101_"))
    fails, got = [], {}
    try:
        shutil.copytree(HERE / "inputs", run, dirs_exist_ok=True)
        (run / "execution").mkdir()
        nr = run / "NightlyRun"
        settings_file(nr, run / "execution")
        (nr / "_driver.py").write_text(DRIVER)

        # ---- A) official test101.py
        cp = subprocess.run([py, "_driver.py"], cwd=nr, env=env, capture_output=True, text=True, timeout=1200)
        if cp.returncode != 0 or "DRIVER_DONE" not in cp.stdout:
            fails.append(f"test101 run failed (rc={cp.returncode}): {(cp.stdout + cp.stderr)[-800:]}")
        else:
            res = json.loads((nr / "driver_result.json").read_text())
            outbins = list((run / "execution").rglob("*.outbin"))
            errlogs = list((run / "execution").rglob("*.errlog"))
            if not outbins or outbins[0].stat().st_size == 0:
                fails.append("issm.exe wrote no .outbin")
            if any(e.stat().st_size for e in errlogs):
                fails.append("issm.exe .errlog not empty: " + errlogs[0].read_text()[-400:])
            print(f"  ran test101 (official): {res['nvert']} vertices, {res['nelem']} elements, "
                  f"outbin {outbins[0].stat().st_size if outbins else 0} bytes")
            for f, v in res["fields"].items():
                got[f] = v["rel_diff"]

        # ---- B) same case through the KI tool run_issm.py
        ki = run / "ki_run"
        ki.mkdir()
        settings_file(ki, run / "execution")
        cp = subprocess.run([py, str(RUN_TOOL), "--issm_dir", str(issm_dir),
                             "--domain", str(run / "Exp" / "Square.exp"), "--resolution", "50000",
                             "--ocean_mask", "all", "--grounded_mask", "",
                             "--par_file", str(run / "Par" / "SquareShelfConstrained.py"),
                             "--flow_equation", "SSA", "--solution", "Stressbalance",
                             "--nprocs", "2", "--timeout", "1200", "--output_dir", str(ki)],
                            env=env, capture_output=True, text=True, timeout=1300)
        rj = ki / "results.json"
        kres = json.loads(rj.read_text()) if rj.is_file() else {}
        if cp.returncode != 0 or kres.get("status") != "success":
            fails.append(f"KI tool run_issm.py failed (rc={cp.returncode}): {(cp.stdout + cp.stderr)[-800:]}")
        else:
            print(f"  ran KI tool run_issm.py: status={kres['status']}, elapsed {kres.get('elapsed_s')} s")
            got["ki_tool_vel_max"] = kres["velocity"]["max"]
            got["ki_tool_vel_mean"] = kres["velocity"]["mean"]
    finally:
        shutil.rmtree(run, ignore_errors=True)

    for c in EXP["numeric_checks"]:
        key = c.get("field", c["name"])
        if key not in got:
            fails.append(f"{c['name']}: no value")
            continue
        v = got[key]
        ok = abs(v - c["expected"]) <= c["tol"]
        print(f"  {'ok  ' if ok else 'FAIL'} {c['name']}: got {v:.6g} expected {c['expected']:.6g} tol {c['tol']:.3g}")
        if not ok:
            fails.append(f"{c['name']}: {v} vs {c['expected']} (tol {c['tol']})")

    if fails:
        print("FAIL:\n  " + "\n  ".join(fails))
        return 2
    print(f"PASS: ISSM test101 matches official Archive101 on all 13 fields; KI tool run matches "
          f"({len(EXP['numeric_checks'])} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
