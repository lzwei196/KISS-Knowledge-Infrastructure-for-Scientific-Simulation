#!/usr/bin/env python3
"""Run the official OpenFOAM cavity tutorial in a clean dir and check expected.json.

Foundation case for the OpenFOAM KI. Steps are what OpenFOAM's own
bin/foamRunTutorials does for a tutorial without an Allrun script:
`blockMesh`, then the application named in controlDict (`foamRun`,
solver module incompressibleFluid). foamRun is run through the KI's own
tools/run_openfoam.py; the fields are read with the KI's own
tools/parse_openfoam_output.py. Exit 0 PASS, 2 checks failed, 3 engine missing.

OpenFOAM lookup (the engine needs its etc/bashrc environment):
--foam-bashrc -> $OPENFOAM_BASHRC -> $WM_PROJECT_DIR/etc/bashrc (env already
sourced) -> dir of `which foamRun` (../../../etc/bashrc) -> server default.
"""
import argparse, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = json.loads((HERE / "expected.json").read_text())
TOOLS = HERE.parents[1] / "tools"
RUN_TOOL = TOOLS / "run_openfoam.py"
PARSE_TOOL = TOOLS / "parse_openfoam_output.py"
_DEF = "/home/server/knowledge-dissection-toolkit/auto_dissect/_work/OpenFOAM/source/repo/etc/bashrc"


def find_bashrc(arg):
    cands = [arg, os.environ.get("OPENFOAM_BASHRC")]
    if os.environ.get("WM_PROJECT_DIR"):
        cands.append(os.path.join(os.environ["WM_PROJECT_DIR"], "etc", "bashrc"))
    fr = shutil.which("foamRun")
    if fr:  # <root>/platforms/<arch>/bin/foamRun
        cands.append(str(Path(fr).resolve().parents[3] / "etc" / "bashrc"))
    cands.append(_DEF)
    for c in cands:
        if not c or not Path(c).is_file():
            continue
        cp = subprocess.run(["bash", "-c", f'source "{c}" >/dev/null 2>&1; '
                             "command -v foamRun && command -v blockMesh"],
                            capture_output=True, text=True, timeout=60)
        if cp.returncode == 0 and cp.stdout.count("\n") >= 2:
            return c
    return None


def count_cells(field_file):
    """Own check of the cell count: the number after 'internalField nonuniform'."""
    lines = Path(field_file).read_text().splitlines()
    for i, l in enumerate(lines):
        if l.startswith("internalField") and "nonuniform" in l:
            return int(lines[i + 1].strip())
    return -1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--foam-bashrc")
    a = ap.parse_args()
    bashrc = find_bashrc(a.foam_bashrc)
    if not bashrc:
        print("MISSING DEPENDENCY: OpenFOAM etc/bashrc giving foamRun + blockMesh not found "
              "(set OPENFOAM_BASHRC or --foam-bashrc). NOT run.", file=sys.stderr)
        return 3
    print(f"  OpenFOAM env: {bashrc}")

    tmp = Path(tempfile.mkdtemp(prefix="of_cavity_"))
    case = tmp / "cavity"
    shutil.copytree(HERE / "inputs", case)
    fails, got = [], {}
    try:
        # 1) blockMesh (no KI tool can run blockMesh on an existing blockMeshDict; see README)
        cp = subprocess.run(["bash", "-c", f'source "{bashrc}" && blockMesh > log.blockMesh 2>&1'],
                            cwd=case, timeout=300)
        bm_log = (case / "log.blockMesh").read_text()
        if cp.returncode != 0 or not bm_log.rstrip().endswith("End"):
            fails.append(f"blockMesh failed (rc={cp.returncode}): {bm_log[-400:]}")
        else:
            print("  ran blockMesh")

        # 2) foamRun through the KI run tool
        if not fails:
            res_json = tmp / "run_result.json"
            cp = subprocess.run([sys.executable, str(RUN_TOOL), "--case-dir", str(case),
                                 "--solver", "incompressibleFluid", "--np", "1",
                                 "--foam-bashrc", bashrc, "--output", str(res_json)],
                                cwd=tmp, capture_output=True, text=True, timeout=1200)
            if cp.returncode != 0 or not res_json.is_file():
                fails.append(f"run_openfoam.py failed (rc={cp.returncode}): {cp.stdout[-400:]}{cp.stderr[-400:]}")
            else:
                run = json.loads(res_json.read_text())
                ex = run.get("execution", {})
                if run.get("status") != "success" or ex.get("returncode") != 0:
                    fails.append(f"foamRun failed: {run.get('errors')}")
                elif not ex.get("stdout_tail", "").rstrip().endswith("End"):
                    fails.append("foamRun log does not end with 'End'")
                else:
                    print("  ran foamRun (KI tools/run_openfoam.py): rc=0, log ends with 'End'")
                    got["courant_max"] = run["courant"]["max"]
                    bad = {v: r["final"] for v, r in run["residuals"].items() if r["final"] > 1e-3}
                    if bad or not run["residuals"]:
                        fails.append(f"final residuals not converged: {bad}")
                    else:
                        print(f"  OK final residuals all < 1e-3 ({', '.join(sorted(run['residuals']))})")

        # 3) read fields with the KI parse tool
        if not fails:
            cp = subprocess.run([sys.executable, str(PARSE_TOOL), "--case-dir", str(case),
                                 "--extract-fields", "U,p,k,epsilon,nut"],
                                cwd=tmp, capture_output=True, text=True, timeout=300)
            par = json.loads(cp.stdout)
            fs = par["field_statistics"]
            last = {f: s[-1] for f, s in fs.items()}
            if any(v["time"] != 10.0 for v in last.values()):
                fails.append(f"last output time is not 10: {[v['time'] for v in last.values()]}")
            got.update({
                "n_output_times": par["n_output_times"],
                "n_cells": count_cells(case / "10" / "U"),
                "U_mag_mean": last["U"]["magnitude_mean"],
                "U_mag_max": last["U"]["magnitude_max"],
                "p_mean": last["p"]["mean"], "p_min": last["p"]["min"], "p_max": last["p"]["max"],
                "k_mean": last["k"]["mean"], "k_max": last["k"]["max"],
                "epsilon_mean": last["epsilon"]["mean"],
                "nut_mean": last["nut"]["mean"],
            })
            for c in EXP["numeric_checks"]:
                v = got.get(c["name"])
                if v is None or abs(v - c["expected"]) > c["tol"]:
                    fails.append(f"{c['name']}: {v} vs {c['expected']}+-{c['tol']}")
                else:
                    print(f"  OK {c['name']}: {v:.6g}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if fails:
        print("FAIL:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 2
    print("PASS: OpenFOAM cavity reproduced the expected results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
