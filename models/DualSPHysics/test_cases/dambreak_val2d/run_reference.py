#!/usr/bin/env python3
"""Run the official DualSPHysics 2D dam-break validation case and check expected.json.

Foundation case for the DualSPHysics KI: examples/main/01_DamBreak/CaseDambreakVal2D
from the official DualSPHysics git (v5.4). Steps follow the official script
xCaseDambreakVal2D_linux64_CPU.sh: GenCase -> DualSPHysics (CPU), both run through
the KI's own tools/run_dualsphysics.py, then the official MeasureTool elevation step.
The dam-break front (gauge Swl_z003, written by the solver) is also compared with the
official experiment file shipped with the case (Koshizuka & Oka 1996).

Exit 0 PASS, 2 checks failed, 3 engine missing ("MISSING DEPENDENCY: ... NOT run.").
Binary dir lookup: --dsph-bin-dir -> $DSPH_BIN_DIR -> dir of `which DualSPHysics5.4CPU_linux64`
-> server default. The dir must hold GenCase_linux64, DualSPHysics5.4CPU_linux64 and
MeasureTool_linux64. Uses at most 8 OpenMP threads (--threads to change).
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
RUN_TOOL = HERE.parents[1] / "tools" / "run_dualsphysics.py"
_DEF = "/home/server/knowledge-dissection-toolkit/auto_dissect/_work/DualSPHysics/source/repo/bin/linux"
NAME = "CaseDambreakVal2D"
EXPFILE = "EXP_X-DamTipPosition_Koshizula&Oka1996.txt"
BINS = ("GenCase_linux64", "DualSPHysics5.4CPU_linux64", "MeasureTool_linux64")


def find_bin_dir(arg):
    w = shutil.which("DualSPHysics5.4CPU_linux64")
    for c in (arg, os.environ.get("DSPH_BIN_DIR"), str(Path(w).parent) if w else None, _DEF):
        if c and all((Path(c) / b).is_file() for b in BINS):
            return c
    return None


def num(s):
    return int(s.replace(",", ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsph-bin-dir")
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--keep", action="store_true", help="keep the temp run dir")
    a = ap.parse_args()
    bd = find_bin_dir(a.dsph_bin_dir)
    if not bd:
        print("MISSING DEPENDENCY: DualSPHysics bin dir with " + ", ".join(BINS) +
              " not found (set DSPH_BIN_DIR or --dsph-bin-dir). NOT run.", file=sys.stderr)
        return 3

    run = Path(tempfile.mkdtemp(prefix="dsph_dambreak2d_"))
    for f in (f"{NAME}_Def.xml", EXPFILE):
        shutil.copy(HERE / "inputs" / f, run / f)
    out = run / f"{NAME}_out"
    fails, got = [], {}

    cmd = [sys.executable, str(RUN_TOOL), "--case_def", f"{NAME}_Def.xml",
           "--run_dir", str(run), "--dirout", str(out), "--bin_dir", bd,
           "--cpu", "--ompthreads", str(a.threads), "--solver_timeout", "1500"]
    print("  running GenCase + DualSPHysics through KI tools/run_dualsphysics.py ...")
    cp = subprocess.run(cmd, capture_output=True, text=True, cwd=run, timeout=1800)
    runout = out / "Run.out"
    txt = runout.read_text(errors="replace") if runout.is_file() else ""
    if cp.returncode != 0 or not txt:
        fails.append(f"run tool failed (rc={cp.returncode}): {(cp.stdout + cp.stderr)[-600:]}")
    else:
        # official post-processing step (MeasureTool elevation at x=0.2), as in the official script
        env = dict(os.environ, LD_LIBRARY_PATH=os.environ.get("LD_LIBRARY_PATH", "") + ":" + bd)
        mt = subprocess.run([str(Path(bd) / "MeasureTool_linux64"), "-dirdata", f"{NAME}_out/data",
                             "-pointsdef:ptels[x=0.2:0:0.2,y=0:0:0,z=0:0.02:2.1]",
                             "-onlytype:-all,+fluid", "-elevation",
                             "-savevtk", f"{NAME}_out/measuretool/EtaPoints",
                             "-savecsv", f"{NAME}_out/MeasuredA", f"-threads:{a.threads}"],
                            capture_output=True, text=True, cwd=run, env=env, timeout=600)
        if mt.returncode != 0:
            fails.append(f"MeasureTool failed (rc={mt.returncode}): {mt.stdout[-400:]}")

    if not fails:
        got["finished_code0"] = 1 if "Finished execution (code=0)." in txt else 0
        m = re.search(r"Total particles: ([\d,]+) \(bound=([\d,]+).*fluid=([\d,]+)\)", txt)
        got["total_particles"], got["fluid_particles"] = num(m.group(1)), num(m.group(3))
        got["n_part_files"] = len(list((out / "data").glob("Part_*.bi4")))
        last = re.findall(r"^(\d{5})\s+([\d.]+)\s+([\d,]+)\s", txt, re.M)[-1]
        got["final_time_s"], got["total_steps"] = float(last[1]), num(last[2])
        outs = re.findall(r"total out: (\d+)", txt)
        got["particles_out_total"] = int(outs[-1]) if outs else 0

        z = np.genfromtxt(out / "GaugesSWL_Swl_z003.csv", delimiter=";", skip_header=1)
        x = np.genfromtxt(out / "GaugesSWL_Swl_x02.csv", delimiter=";", skip_header=1)
        ex = np.loadtxt(run / EXPFILE, skiprows=2, encoding="latin-1")
        ex = ex[ex[:, 1] < 3.9]          # experiment points before the front hits the end wall (x=4)
        e = np.interp(ex[:, 0], z[:, 0], z[:, 1]) - ex[:, 1]
        got["front_x_t0"] = float(z[0, 1])
        got["front_max_x"] = float(z[:, 1].max())
        got["front_time_reach_3p9m"] = float(z[np.argmax(z[:, 1] >= 3.9), 0])
        got["front_rmse_vs_experiment"] = float(np.sqrt((e ** 2).mean()))
        got["front_maxabs_vs_experiment"] = float(np.abs(e).max())
        got["swl_x02_at_t1"] = float(np.interp(1.0, x[:, 0], x[:, 3]))

        el = np.genfromtxt(out / "MeasuredA_Elevation.csv", delimiter=";", skip_header=4)
        got["elev_x02_t0"], got["elev_x02_final"] = float(el[0, 2]), float(el[-1, 2])
        got["n_elev_rows"] = len(el)

        for c in EXP["numeric_checks"]:
            v = got[c["name"]]
            if abs(v - c["expected"]) > c["tol"]:
                fails.append(f"{c['name']}: {v:.6g} vs {c['expected']}+-{c['tol']}")
            else:
                print(f"  OK {c['name']}: {v:.6g}")

    if a.keep:
        print("  run dir kept:", run)
    else:
        shutil.rmtree(run, ignore_errors=True)
    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: DualSPHysics CaseDambreakVal2D reproduced the expected results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
