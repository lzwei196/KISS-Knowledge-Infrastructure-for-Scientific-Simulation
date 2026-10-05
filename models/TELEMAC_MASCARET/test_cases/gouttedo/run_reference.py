#!/usr/bin/env python3
"""Run the official TELEMAC-MASCARET example telemac2d/gouttedo and check expected.json.

Foundation case for the TELEMAC_MASCARET KI. The run goes through the KI's own
tools/run_telemac.py (telemac2d, serial). The result is compared with the official
reference file reference/f2d_gouttedo.slf using the official vnv tolerance (1e-7).
Exit 0 PASS, 2 checks failed, 3 engine/dependency missing.

Run it with a Python that has numpy (the server python_env), because telemac2d.py
is started with the same interpreter.

TELEMAC lookup: --hometel -> $HOMETEL -> which telemac2d.py (../..) -> server default.
Build dir:      --build-dir -> $BUILD_DIR -> <hometel>/builds/main_gfortran_release.
"""
import argparse, glob, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parents[1] / "tools"
RUN_TOOL = TOOLS / "run_telemac.py"
sys.path.insert(0, str(TOOLS))
from parse_selafin import SelafinReader  # noqa: E402  (KI parse tool)

EXP = json.loads((HERE / "expected.json").read_text())
_DEF_HOME = "/home/server/knowledge-dissection-toolkit/auto_dissect/_work/TELEMAC_MASCARET/source/repo"
INPUTS = ["t2d_gouttedo.cas", "geo_gouttedo.slf", "geo_gouttedo.cli", "user_fortran"]
RESULT = "r2d_gouttedo_v1p0.slf"
VARS = {"VELOCITY_U": "VELOCITY U      M/S", "VELOCITY_V": "VELOCITY V      M/S",
        "WATER_DEPTH": "WATER DEPTH     M"}


def find_home(arg):
    w = shutil.which("telemac2d.py")
    for c in (arg, os.environ.get("HOMETEL"), str(Path(w).resolve().parents[2]) if w else None, _DEF_HOME):
        if c and (Path(c) / "scripts" / "python3" / "telemac2d.py").is_file():
            return Path(c)
    return None


def read_all(path):
    r = SelafinReader(str(path))
    r.open()
    recs = [r.read_timestep(i) for i in range(r.ntimes)]
    info = dict(n=r.ntimes, npoin=r.npoin, nelem=r.nelem)
    r.close()
    return info, recs


def summarise(run, listing):
    o = {}
    info, recs = read_all(run / RESULT)
    _, ref = read_all(HERE / "reference" / "f2d_gouttedo.slf")
    if len(recs) != len(ref):
        raise ValueError(f"record count {len(recs)} vs reference {len(ref)}")
    for short, v in VARS.items():
        o[f"linf_diff_last_record_{short}"] = np.abs(recs[-1][1][v] - ref[-1][1][v]).max()
    o["linf_diff_all_records_all_vars"] = max(
        max(abs(a[0] - b[0]), np.abs(a[1][v] - b[1][v]).max()) for a, b in zip(recs, ref) for v in VARS.values())
    H, U, V = VARS["WATER_DEPTH"], VARS["VELOCITY_U"], VARS["VELOCITY_V"]
    o.update(ref_n_records=info["n"], ref_t_end_s=recs[-1][0], ref_npoin=info["npoin"],
             ref_nelem=info["nelem"], ref_H_initial_max_m=recs[0][1][H].max(),
             ref_H_record10_max_m=recs[10][1][H].max(), ref_H_final_max_m=recs[-1][1][H].max(),
             ref_H_final_min_m=recs[-1][1][H].min(), ref_H_final_mean_m=recs[-1][1][H].mean(),
             ref_U_final_max_ms=recs[-1][1][U].max(), ref_V_final_min_ms=recs[-1][1][V].min())
    num = r"([-+]?\d+\.\d+(?:E[-+]\d+)?)"
    for key, pat in (("run_initial_volume_m3", r"INITIAL VOLUME\s*:\s*" + num),
                     ("run_final_volume_m3", r"FINAL VOLUME\s*:\s*" + num),
                     ("run_volume_rel_error_cumulated", r"RELATIVE ERROR CUMULATED ON VOLUME:\s*" + num)):
        m = re.search(pat, listing)
        if m:
            o[key] = float(m.group(1))
    return {k: float(v) for k, v in o.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hometel")
    ap.add_argument("--build-dir")
    a = ap.parse_args()
    home = find_home(a.hometel)
    if not home:
        print("MISSING DEPENDENCY: TELEMAC tree with scripts/python3/telemac2d.py not found "
              "(set HOMETEL). NOT run.", file=sys.stderr)
        return 3
    build = Path(a.build_dir or os.environ.get("BUILD_DIR") or home / "builds" / "main_gfortran_release")
    missing = [str(p) for p in (build / "bin" / "telemac2d", build / "lib" / "libtelemac2d.so",
                                build / "systel.cfg", build / "build_commands.json") if not p.is_file()]
    if not shutil.which("f95"):
        missing.append("f95 (gfortran) for the case's user_fortran")
    if missing:
        print("MISSING DEPENDENCY: " + ", ".join(missing) + ". NOT run.", file=sys.stderr)
        return 3

    run = Path(tempfile.mkdtemp(prefix="telemac_gouttedo_"))
    for f in INPUTS:
        src = HERE / "inputs" / f
        (shutil.copytree if src.is_dir() else shutil.copy)(src, run / f)
    # TELEMAC's temp work folder is kept inside the temp run dir (-w). This build's user
    # Fortran link line writes CMakeFiles/user_fortran.dir/link.d relative to that folder,
    # so the empty folder is made first. Inputs and settings are not changed.
    wd = run / "wd"
    (wd / "user_fortran" / "CMakeFiles" / "user_fortran.dir").mkdir(parents=True)
    env = os.environ.copy()
    env.update(HOMETEL=str(home), BUILD_DIR=str(build), SYSTELCFG=str(build / "systel.cfg"),
               PYTHONPATH=str(home / "scripts" / "python3"),
               LD_LIBRARY_PATH=str(build / "lib") + os.pathsep + env.get("LD_LIBRARY_PATH", ""))
    cp = subprocess.run([sys.executable, str(RUN_TOOL), "--cas", str(run / "t2d_gouttedo.cas"),
                         "--module", "telemac2d", "--hometel", str(home), "--nproc", "1",
                         "--options", f"-w {wd} -s"],
                        capture_output=True, text=True, timeout=1200, env=env, cwd=str(run))
    fails = []
    sorties = glob.glob(str(run / "t2d_gouttedo.cas_*.sortie"))
    listing = Path(sorties[0]).read_text(errors="replace") if sorties else ""
    try:
        status = json.loads(cp.stdout.strip().splitlines()[-1]).get("status")
    except Exception:
        status = None
    ok = cp.returncode == 0 and status == "success" and "CORRECT END OF RUN" in listing
    if not ok:
        fails.append(f"run_telemac.py failed (rc={cp.returncode}, status={status}): "
                     f"{(cp.stdout + cp.stderr)[-600:]}")
    else:
        print("  ran telemac2d through KI tools/run_telemac.py (serial); listing says CORRECT END OF RUN")
        try:
            got = summarise(run, listing)
        except Exception as ex:
            got = {}
            fails.append(f"could not read outputs: {ex}")
        got["finished_normally"] = 1.0
        for c in EXP["numeric_checks"]:
            v = got.get(c["name"])
            if v is None:
                fails.append(f"{c['name']}: not computed")
            elif abs(v - c["expected"]) > c["tol"]:
                fails.append(f"{c['name']}: {v:.10g} vs {c['expected']}+-{c['tol']}")
            else:
                print(f"  OK {c['name']}: {v:.10g}")
    shutil.rmtree(run, ignore_errors=True)
    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: TELEMAC-2D gouttedo matches the official reference f2d_gouttedo.slf (eps 1e-7).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
