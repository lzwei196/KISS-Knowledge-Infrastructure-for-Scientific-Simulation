#!/usr/bin/env python3
"""Run the official WRF idealized case em_quarter_ss (supercell, quarter-circle shear) and check expected.json.

Foundation case for the WRF KI. WRF builds one case per build, so this needs ideal + wrf built with
WRF_CASE=EM_QUARTER_SS. Both programs are taken from ONE install folder, so an em_real wrf can never be
paired with this ideal. The run is direct (ideal, then wrf, serial): the KI tool tools/run_wrf.py has no
ideal stage (see README). WRF ships no reference output for this case, so expected.json holds values from
our own runs (two runs were bit-identical). Exit 0 PASS, 2 checks failed, 3 engine/dependency missing.

Install folder lookup: --wrf-install -> $WRF_QUARTER_SS_INSTALL -> server default; it must hold bin/ideal
and bin/wrf.
"""
import argparse, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
_DEF = "/home/server/engine_builds_20261006/wrf/install_quarter_ss"
WRFOUT = "wrfout_d01_0001-01-01_00:00:00"


def summarise(run):
    import netCDF4
    o = {}
    with netCDF4.Dataset(run / WRFOUT) as d:
        o["n_times"] = len(d.dimensions["Time"])
        o["xtime_last_min"] = float(d["XTIME"][-1])
        o["n_mass_points"] = (len(d.dimensions["west_east"]) * len(d.dimensions["south_north"])
                              * len(d.dimensions["bottom_top"]))
        g = {v: np.asarray(d[v][:], dtype=float) for v in ("W", "T", "QRAIN", "QCLOUD", "RAINNC", "U")}
    o["nonfinite_values"] = sum(int(np.sum(~np.isfinite(a))) for a in g.values())
    o["w_max_30min"] = g["W"][1].max()
    o["w_max_60min"] = g["W"][2].max()
    o["w_min_60min"] = g["W"][2].min()
    o["t_pert_min_60min"] = g["T"][2].min()
    o["t_pert_max_60min"] = g["T"][2].max()
    o["qrain_max_60min"] = g["QRAIN"][2].max()
    o["qcloud_max_60min"] = g["QCLOUD"][2].max()
    o["rainnc_max_60min"] = g["RAINNC"][2].max()
    o["rainnc_mean_60min"] = g["RAINNC"][2].mean()
    o["u_absmax_60min"] = np.abs(g["U"][2]).max()
    return {k: float(v) for k, v in o.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wrf-install", help="install folder with bin/ideal and bin/wrf built for EM_QUARTER_SS")
    ap.add_argument("--keep", action="store_true", help="keep the temp run dir")
    a = ap.parse_args()
    if a.wrf_install:
        inst, src = a.wrf_install, "--wrf-install"
    elif os.environ.get("WRF_QUARTER_SS_INSTALL"):
        inst, src = os.environ["WRF_QUARTER_SS_INSTALL"], "$WRF_QUARTER_SS_INSTALL"
    else:
        inst, src = _DEF, "server default"
    inst = Path(os.path.abspath(inst))
    ideal, wrf = inst / "bin" / "ideal", inst / "bin" / "wrf"
    for p in (ideal, wrf):
        if not (p.is_file() and os.access(p, os.X_OK)):
            print(f"MISSING DEPENDENCY: {p} ({src}) is not an executable file. NOT run.", file=sys.stderr)
            return 3
    try:
        import netCDF4  # noqa: F401
    except ImportError:
        print("MISSING DEPENDENCY: python netCDF4. NOT run.", file=sys.stderr)
        return 3
    print(f"  ideal ({src}): {ideal}\n  wrf   ({src}): {wrf}")
    run = Path(tempfile.mkdtemp(prefix="wrf_qss_"))
    for f in ("namelist.input", "input_sounding"):
        shutil.copy(HERE / "inputs" / f, run / f)
    env = dict(os.environ, OMP_NUM_THREADS="1")
    fails = []
    for exe, line in ((ideal, "SUCCESS COMPLETE IDEAL INIT"), (wrf, "SUCCESS COMPLETE WRF")):
        try:
            cp = subprocess.run([str(exe)], cwd=run, env=env, capture_output=True, text=True, timeout=1100)
            out, rc = cp.stdout + cp.stderr, cp.returncode
        except subprocess.TimeoutExpired:
            out, rc = "timed out", -1
        (run / f"{exe.name}.log").write_text(out)
        if rc != 0 or line not in out:
            fails.append(f"{exe.name} failed (rc={rc}, '{line}' {'found' if line in out else 'missing'}): {out[-400:]}")
            break
        print(f"  OK finished: {exe.name} rc=0 and '{line}'")
    if not fails:
        try:
            got = summarise(run)
        except Exception as ex:
            got = {}
            fails.append(f"could not read outputs: {ex}")
        for c in EXP["numeric_checks"]:
            v = got.get(c["name"])
            if v is None:
                fails.append(f"{c['name']}: not computed")
            elif not abs(v - c["expected"]) <= c["tol"]:
                fails.append(f"{c['name']}: {v:.10g} vs {c['expected']}+-{c['tol']}")
            else:
                print(f"  OK {c['name']}: {v:.10g}")
    if a.keep:
        print(f"  kept run dir {run}")
    else:
        shutil.rmtree(run, ignore_errors=True)
    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: WRF em_quarter_ss matches expected.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
